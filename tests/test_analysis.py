import json
import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.models.entities import Company, Source, Document, Signal
from app.services import analysis
from app.services.analysis import (
    validate_evidence_snippet,
    analyze_document_and_create_signal,
    process_all_unprocessed_documents,
    SignalExtractionSchema,
)
from app.services.ranking import compute_final_rank_score

client = TestClient(app)


def test_validate_evidence_snippet_logic():
    """Verify exact and normalized verbatim substring detection."""
    doc_text = "GlobalAdmissions announced a 50% discount on undergraduate study abroad counseling services."
    
    # Valid verbatim substrings
    assert validate_evidence_snippet("50% discount on undergraduate study abroad", doc_text) is True
    assert validate_evidence_snippet("GlobalAdmissions announced a 50% discount", doc_text) is True
    
    # Hallucinated or modified snippets must be rejected
    assert validate_evidence_snippet("GlobalAdmissions gave away free counseling", doc_text) is False
    assert validate_evidence_snippet("50 percent discount for undergrads", doc_text) is False


def test_rejects_hallucinated_snippets_acceptance(session: Session, monkeypatch):
    """
    Acceptance Test: A unit test that strictly rejects hallucinated snippets.
    If the LLM outputs an evidence_snippet that does not exist verbatim in the document,
    the pipeline MUST reject it and refuse to store it.
    """
    company = Company(name="Target Edu Co", url="https://targetedu.com", industry="EdTech")
    session.add(company)
    session.commit()
    session.refresh(company)

    doc = Document(
        url="https://rival.com/news/article-1",
        content_hash="hash_art_1",
        title="Rival Launch",
        text="Rival Corp has introduced automated visa guidance modules for graduate applications.",
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)

    # Simulated LLM hallucination: returns fabricated wording NOT in doc.text
    hallucinated_extraction = SignalExtractionSchema(
        is_meaningful_development=True,
        category="product_launch",
        what_happened="Rival Corp launched new visa module",
        evidence_snippet="Rival Corp gives 100% guaranteed visa approvals to all international students.",  # Hallucinated!
        affected_business_area="product_core",
        type="threat",
        urgency="high",
        why_it_matters="Significant threat to visa advisory",
        suggested_action="Review feature parity",
        interpretation="Aggressive market push to capture undergraduate share.",
        relevance_score=0.9,
        impact_score=0.85,
    )

    monkeypatch.setattr(analysis, "extract_signal_from_document", MagicMock(return_value=hallucinated_extraction))

    # Must raise ValueError and reject the signal!
    with pytest.raises(ValueError, match="is not a verbatim substring of document text"):
        analyze_document_and_create_signal(document_id=doc.id, company_id=company.id)

    # Verify nothing was saved to DB
    signals_in_db = session.exec(select(Signal).where(Signal.document_id == doc.id)).all()
    assert len(signals_in_db) == 0, "Hallucinated signal was saved to database!"


def test_accepts_verbatim_evidence_snippet_with_ai_inference_label(session: Session, monkeypatch):
    """
    Test that a valid verbatim snippet is accepted and interpretation is clearly labelled as AI inference.
    """
    company = Company(name="Target Edu Co", url="https://targetedu.com", industry="EdTech")
    session.add(company)
    session.commit()
    session.refresh(company)

    doc = Document(
        url="https://rival.com/news/article-2",
        content_hash="hash_art_2",
        title="Rival Launch",
        text="Rival Corp has introduced automated visa guidance modules for graduate applications across North America.",
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)

    verbatim_text = "automated visa guidance modules for graduate applications"
    valid_extraction = SignalExtractionSchema(
        is_meaningful_development=True,
        category="product_launch",
        what_happened="Rival Corp introduced automated visa guidance modules",
        evidence_snippet=verbatim_text,
        affected_business_area="product_core",
        type="threat",
        urgency="high",
        why_it_matters="Competitor matching our core digital feature",
        suggested_action="Accelerate Q1 visa automation milestone",
        interpretation="Aggressive expansion to capture graduate visa market.",
        relevance_score=0.9,
        impact_score=0.85,
    )

    monkeypatch.setattr(analysis, "extract_signal_from_document", MagicMock(return_value=valid_extraction))

    signal = analyze_document_and_create_signal(document_id=doc.id, company_id=company.id)
    assert signal is not None
    assert signal.evidence_snippet == verbatim_text
    assert signal.interpretation.startswith("[AI Inference]:")
    assert signal.final_rank_score > 0.0
    assert signal.rank_explanation is not None

    # Check score breakdown
    breakdown = json.loads(signal.score_breakdown)
    assert "relevance" in breakdown
    assert "impact" in breakdown
    assert "recency_decay" in breakdown
    assert "final_rank_score" in breakdown


def test_signal_list_ranked_with_explanations_acceptance(session: Session, monkeypatch):
    """
    Acceptance Test: A signal list ranked with human-readable explanations.
    """
    company = Company(name="Edu Ranking Co", url="https://eduranking.com", industry="EdTech")
    session.add(company)
    session.commit()
    session.refresh(company)

    src = Source(
        company_id=company.id,
        category="competitors",
        name="Rival Portal",
        url="https://rivalportal.com",
        credible_score=0.90,
        status="approved",
    )
    session.add(src)
    session.commit()
    session.refresh(src)

    # Create 3 documents with varying urgency & relevance
    doc_high = Document(
        source_id=src.id,
        url="https://rivalportal.com/doc-high",
        content_hash="h1",
        title="Major Price Slash",
        text="Rival slashed student placement fees by 40% nationwide.",
    )
    doc_low = Document(
        source_id=src.id,
        url="https://rivalportal.com/doc-low",
        content_hash="h2",
        title="Minor UI Update",
        text="Rival refreshed their logo color palette to modern navy.",
    )
    session.add_all([doc_high, doc_low])
    session.commit()

    # High signal extraction
    extract_high = SignalExtractionSchema(
        is_meaningful_development=True,
        category="pricing_change",
        what_happened="Rival slashed student placement fees by 40%",
        evidence_snippet="Rival slashed student placement fees by 40% nationwide.",
        type="threat",
        urgency="critical",
        relevance_score=0.95,
        impact_score=0.90,
        why_it_matters="Price disruption",
        interpretation="Direct price war initiated.",
    )

    # Low signal extraction
    extract_low = SignalExtractionSchema(
        is_meaningful_development=True,
        category="brand_update",
        what_happened="Rival updated brand logo palette",
        evidence_snippet="Rival refreshed their logo color palette to modern navy.",
        type="neutral",
        urgency="low",
        relevance_score=0.30,
        impact_score=0.20,
        why_it_matters="Cosmetic change",
        interpretation="Minor brand refresh.",
    )

    def mock_extract(doc, comp, mem):
        if doc.id == doc_high.id:
            return extract_high
        return extract_low

    monkeypatch.setattr(analysis, "extract_signal_from_document", mock_extract)

    signals = process_all_unprocessed_documents(company.id)
    assert len(signals) == 2

    # Verification: High priority signal ranked first!
    assert signals[0].final_rank_score > signals[1].final_rank_score
    assert signals[0].urgency == "critical"
    assert "Rank" in signals[0].rank_explanation
    assert "Relevance" in signals[0].rank_explanation

    # API test: GET /companies/{id}/signals
    resp = client.get(f"/companies/{company.id}/signals")
    assert resp.status_code == 200
    api_signals = resp.json()
    assert len(api_signals) == 2
    assert api_signals[0]["final_rank_score"] >= api_signals[1]["final_rank_score"]
    assert api_signals[0]["rank_explanation"] is not None
    assert api_signals[0]["interpretation"].startswith("[AI Inference]:")
