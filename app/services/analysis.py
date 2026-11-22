import json
import re
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field as PydanticField
from sqlmodel import Session, select

from app.core.config import settings
from app.core import db
from app.core.llm import generate_json
from app.models.entities import Company, ProfileField, Source, Document, Signal, utcnow
from app.services.ranking import compute_final_rank_score

logger = logging.getLogger("signal_stack.analysis")


class SignalExtractionSchema(BaseModel):
    is_meaningful_development: bool = PydanticField(
        default=True,
        description="True if this document contains an actual strategic or operational development for this company",
    )
    category: str = PydanticField(
        default="strategic_movement",
        description="Category e.g. product_launch, pricing_change, regulatory_shift, partnership, customer_feedback",
    )
    what_happened: Optional[str] = PydanticField(
        default=None,
        description="Concise factual summary of what actually occurred",
    )
    when_date: Optional[str] = PydanticField(
        default=None,
        description="Date or timeframe when this development occurred",
    )
    evidence_snippet: Optional[str] = PydanticField(
        default=None,
        description="EXACT, VERBATIM substring quote extracted directly from the document. Must match word-for-word.",
    )
    affected_business_area: Optional[str] = PydanticField(
        default="product_core",
        description="Area of company affected, e.g. pricing, product_core, gtm, compliance, partnerships",
    )
    type: str = PydanticField(
        default="neutral",
        description="'opportunity' | 'threat' | 'neutral'",
    )
    urgency: str = PydanticField(
        default="medium",
        description="'low' | 'medium' | 'high' | 'critical'",
    )
    why_it_matters: Optional[str] = PydanticField(
        default=None,
        description="Direct strategic impact on this company's market position",
    )
    suggested_action: Optional[str] = PydanticField(
        default=None,
        description="Actionable counter-measure or tactical response",
    )
    interpretation: Optional[str] = PydanticField(
        default=None,
        description="Distinct analytical inference detailing long-term strategic hypotheses and implications.",
    )
    relevance_score: float = PydanticField(
        default=0.8,
        description="Relevance to this specific company from 0.0 to 1.0",
    )
    impact_score: float = PydanticField(
        default=0.8,
        description="Potential business impact magnitude from 0.0 to 1.0",
    )


def validate_evidence_snippet(snippet: str, document_text: str) -> bool:
    """
    Validates that evidence_snippet is a true verbatim substring of document_text.
    Rejects any fabricated or hallucinated quotations.
    """
    if not snippet or not document_text:
        return False

    clean_snippet = snippet.strip()
    clean_doc = document_text.strip()

    # 1. Exact string match
    if clean_snippet in clean_doc:
        return True

    # 2. Match with normalized whitespace
    norm_doc = re.sub(r"\s+", " ", clean_doc).lower()
    norm_snippet = re.sub(r"\s+", " ", clean_snippet).lower()
    return norm_snippet in norm_doc


def determine_verification_status(
    source: Optional[Source],
    document: Document,
    session: Session,
) -> str:
    """
    Determine verification status:
    - 'verified': primary/official source (internal, company official, regulator) or corroborated by 2+ sources
    - 'reported': recognized industry news or publisher
    - 'unverified': user forums, anonymous blogs, or single uncorroborated mention
    """
    if not source:
        return "unverified"

    # Internal or official primary sources
    if source.category == "internal" or "official" in (source.name or "").lower():
        return "verified"

    # Government / regulatory domains
    if ".gov" in source.url or "regulator" in (source.name or "").lower():
        return "verified"

    # Corroboration check: check if 2+ documents in DB have similar content hash or keywords
    other_docs_count = session.exec(
        select(Document)
        .where(Document.id != document.id)
        .where(Document.title == document.title)
    ).all()
    if len(other_docs_count) >= 1:
        return "verified"

    if source.category in ("competitors", "market") and source.credible_score >= 0.85:
        return "reported"

    return "unverified"


def _heuristic_signal_extractor(
    document: Document,
    company: Company,
) -> Optional[SignalExtractionSchema]:
    """
    Deterministic fallback extractor when LLM API keys are not provided.
    Extracts guaranteed verbatim substrings from document text.
    """
    text = document.text or ""
    if len(text.strip()) < 30:
        return None

    # Find sentences mentioning actionable developments
    sentences = re.split(r"(?<=[.!?])\s+", text)
    trigger_words = [
        "launched", "partnership", "announced", "pricing", "fees", "expanded",
        "visa", "policy", "regulations", "students", "admissions", "growth",
        "discounts", "features", "platform", "university", "merchants"
    ]

    selected_sentence = ""
    for s in sentences:
        s_clean = s.strip()
        if len(s_clean) > 30 and any(w in s_clean.lower() for w in trigger_words):
            selected_sentence = s_clean
            break

    if not selected_sentence and sentences:
        selected_sentence = sentences[0].strip()

    if not selected_sentence or len(selected_sentence) < 20:
        return None

    # Determine type
    stype = "neutral"
    if any(w in selected_sentence.lower() for w in ["launch", "partner", "expand", "growth"]):
        stype = "opportunity"
    elif any(w in selected_sentence.lower() for w in ["fee", "restrict", "delay", "decline", "cut"]):
        stype = "threat"

    return SignalExtractionSchema(
        is_meaningful_development=True,
        category="market_development",
        what_happened=f"Development reported in {document.title or 'source'}: {selected_sentence[:120]}",
        when_date=document.published_at.strftime("%Y-%m-%d") if document.published_at else "Recent",
        evidence_snippet=selected_sentence,
        affected_business_area="product_core",
        type=stype,
        urgency="high" if stype == "threat" else "medium",
        why_it_matters=f"Directly impacts {company.name}'s competitive positioning and strategic roadmap.",
        suggested_action=f"Review operational positioning for {company.name} against this development.",
        interpretation="Competitive movement indicating dynamic category expansion across regional channels.",
        relevance_score=0.85,
        impact_score=0.80,
    )


def extract_signal_from_document(
    document: Document,
    company: Company,
    profile_memory: str,
) -> Optional[SignalExtractionSchema]:
    """
    Invokes LLM structured extraction to classify and extract signal.
    Falls back to heuristic extractor if LLM is unavailable.
    """
    if settings.GEMINI_API_KEY or settings.GROQ_API_KEY:
        try:
            system_prompt = (
                "You are an executive strategic intelligence analyst for Signal Stack.\n"
                "Your objective is to determine whether the provided document contains a MEANINGFUL development "
                f"for the target company '{company.name}' ({company.industry}).\n\n"
                "CRITICAL NON-NEGOTIABLE LAWS:\n"
                "1. ZERO HALLUCINATION: The `evidence_snippet` field MUST be an EXACT, VERBATIM substring of the document text. "
                "Do NOT paraphrase, summarize, or alter a single word in `evidence_snippet`.\n"
                "2. SEPARATION OF INFERENCE: The `interpretation` field must be clearly distinct analytical hypothesis and implications.\n"
                "3. If the document is purely generic boilerplate, navigation text, or irrelevant to this company, "
                "set `is_meaningful_development = false`.\n"
                "4. Output strictly according to the JSON schema."
            )

            prompt = (
                f"=== TARGET COMPANY PROFILE ===\n"
                f"Name: {company.name}\n"
                f"Industry: {company.industry}\n"
                f"Description: {company.description}\n"
                f"Strategic Memory:\n{profile_memory}\n\n"
                f"=== DOCUMENT TO ANALYZE ===\n"
                f"URL: {document.url}\n"
                f"Title: {document.title}\n"
                f"Published At: {document.published_at}\n"
                f"Document Text:\n{document.text[:3000]}\n\n"
                "Analyze and extract structured signal if meaningful."
            )

            res = generate_json(
                prompt=prompt,
                schema=SignalExtractionSchema,
                system_prompt=system_prompt,
            )
            parsed = SignalExtractionSchema.model_validate(res)
            return parsed
        except Exception as e:
            logger.warning(f"LLM signal extraction failed, using heuristic fallback: {e}")

    return _heuristic_signal_extractor(document, company)


def analyze_document_and_create_signal(
    document_id: int,
    company_id: int,
) -> Optional[Signal]:
    """
    Process a single document:
    1. LLM classification & extraction
    2. Code validation of verbatim evidence_snippet (REJECTS otherwise)
    3. AI inference labeling
    4. Verification status determination
    5. Code calculation of final_rank_score via ranking.py
    6. Persist Signal to DB
    """
    with Session(db.engine) as session:
        document = session.get(Document, document_id)
        if not document:
            raise ValueError(f"Document #{document_id} not found")

        company = session.get(Company, company_id)
        if not company:
            raise ValueError(f"Company #{company_id} not found")

        source = session.get(Source, document.source_id) if document.source_id else None

        # Build profile memory
        pfs = session.exec(select(ProfileField).where(ProfileField.company_id == company_id)).all()
        memory_lines = [f"- [{pf.key}]: {pf.value}" for pf in pfs]
        profile_memory = "\n".join(memory_lines)

        # 1. Extraction step
        extracted = extract_signal_from_document(document, company, profile_memory)
        if not extracted or not extracted.is_meaningful_development or not extracted.what_happened:
            logger.info(f"Document #{document_id} contains no meaningful development for {company.name}.")
            return None

        # 2. Strict Code Validation of Evidence Snippet
        snippet = extracted.evidence_snippet or ""
        if not validate_evidence_snippet(snippet, document.text):
            logger.error(
                f"REJECTED SIGNAL: evidence_snippet is not a verbatim substring of Document #{document_id}!\n"
                f"Snippet attempted: '{snippet}'"
            )
            raise ValueError(
                f"Signal validation failed: evidence_snippet '{snippet}' is not a verbatim substring of document text."
            )

        # 3. Clearly separate and label AI inference layer
        raw_interp = extracted.interpretation or extracted.why_it_matters or "No specific strategic inference."
        if not raw_interp.startswith("[AI Inference]:"):
            labeled_interpretation = f"[AI Inference]: {raw_interp}"
        else:
            labeled_interpretation = raw_interp

        # 4. Verification Status
        v_status = determine_verification_status(source, document, session)

        # 5. Tri-Factor decoupled scores
        src_reliability = source.credible_score if source else 0.75
        ev_strength = 0.95 if len(snippet.strip()) >= 35 else 0.80
        strat_relevance = extracted.relevance_score

        # 6. Fetch historical signals for novelty computation
        historical_signals = session.exec(
            select(Signal).where(Signal.company_id == company_id)
        ).all()

        # 7. Compute final_rank_score in code via ranking.py
        final_score, breakdown, explanation = compute_final_rank_score(
            relevance=strat_relevance,
            impact=extracted.impact_score,
            urgency=extracted.urgency,
            source_credibility=src_reliability,
            published_at=document.published_at,
            fetched_at=document.fetched_at,
            what_happened=extracted.what_happened,
            affected_area=extracted.affected_business_area,
            historical_signals=historical_signals,
        )

        # 8. Create and Persist Signal
        signal = Signal(
            company_id=company.id,
            document_id=document.id,
            category=extracted.category,
            what_happened=extracted.what_happened,
            evidence_snippet=snippet,
            interpretation=labeled_interpretation,
            affected_area=extracted.affected_business_area,
            type=extracted.type,
            urgency=extracted.urgency,
            why_it_matters=extracted.why_it_matters,
            suggested_action=extracted.suggested_action,
            source_reliability=src_reliability,
            evidence_strength=ev_strength,
            strategic_relevance=strat_relevance,
            final_rank_score=final_score,
            rank_explanation=explanation,
            score_breakdown=json.dumps(breakdown),
            verification_status=v_status,
            source_url=document.url,
            published_at=document.published_at,
            discovered_at=utcnow(),
        )

        session.add(signal)
        session.commit()
        session.refresh(signal)

        logger.info(f"Signal #{signal.id} created with Rank {final_score:.2f} ({v_status}).")
        return signal


def process_all_unprocessed_documents(company_id: int) -> List[Signal]:
    """
    Process all un-analyzed documents for a company, extracting and ranking signals.
    """
    created_signals: List[Signal] = []
    with Session(db.engine) as session:
        # Get source IDs belonging to this company
        source_ids = [s.id for s in session.exec(select(Source).where(Source.company_id == company_id)).all()]

        # Query documents from these sources without an existing signal
        existing_doc_ids_with_signal = set(
            session.exec(select(Signal.document_id).where(Signal.company_id == company_id)).all()
        )

        query = select(Document)
        if source_ids:
            query = query.where(Document.source_id.in_(source_ids))  # type: ignore

        all_docs = session.exec(query).all()
        unprocessed_docs = [d for d in all_docs if d.id not in existing_doc_ids_with_signal]

    for doc in unprocessed_docs:
        try:
            sig = analyze_document_and_create_signal(doc.id, company_id)
            if sig:
                created_signals.append(sig)
        except Exception as e:
            logger.error(f"Error processing document #{doc.id}: {e}")

    # Return ranked by final_rank_score descending
    created_signals.sort(key=lambda s: s.final_rank_score, reverse=True)
    return created_signals
