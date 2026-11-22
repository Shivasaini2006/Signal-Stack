import re
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.core import db
from app.models.entities import Company, Signal, Source, Document, Brief, Action, utcnow
from app.services.brief import (
    EXACT_SECTION_TITLES,
    NO_MEANINGFUL_DEVELOPMENT_TEXT,
    generate_weekly_brief,
    verify_brief_claims,
)


@pytest.fixture
def mock_company_and_signals():
    with Session(db.engine, expire_on_commit=False) as session:
        # Create company
        company = Company(
            name="MeetUniversity Test",
            domain="meetuniversity.com",
            url="https://www.meetuniversity.com",
            industry="Higher Education & EdTech",
        )
        session.add(company)
        session.commit()
        session.refresh(company)

        # Create source & doc
        source = Source(
            company_id=company.id,
            category="competitors",
            name="Rival Admissions",
            url="https://rivaladmissions.example.com",
            reason="Direct competitor in study abroad counseling.",
            specific_score=0.9,
            recent_score=0.9,
            credible_score=0.9,
            status="approved",
        )
        session.add(source)
        session.commit()
        session.refresh(source)

        doc = Document(
            source_id=source.id,
            url="https://rivaladmissions.example.com/pricing-q4",
            content_hash="test_chash_123",
            title="Rival Pricing Q4",
            text="Competitor slashed international recruitment agency commission to 8% and added free visa filing.",
            simhash="123456",
            published_at=utcnow(),
            fetched_at=utcnow(),
        )
        session.add(doc)
        session.commit()
        session.refresh(doc)

        # Create distinct signals across categories
        signals_data = [
            Signal(
                company_id=company.id,
                document_id=doc.id,
                category="competitors",
                what_happened="Competitor cut commission rate to 8% with free visa support.",
                evidence_snippet="Competitor slashed international recruitment agency commission to 8% and added free visa filing.",
                interpretation="[AI Inference]: Competitor is attempting to squeeze broker margins.",
                affected_area="pricing",
                type="threat",
                urgency="high",
                why_it_matters="Threatens agency partnerships.",
                suggested_action="Review agency commission tiering and bundle visa tracking.",
                final_rank_score=0.92,
                source_url="https://rivaladmissions.example.com/pricing-q4",
                verification_status="verified",
                published_at=utcnow(),
            ),
            Signal(
                company_id=company.id,
                document_id=doc.id,
                category="customers",
                what_happened="Student community reports frustration with delayed counselor callbacks.",
                evidence_snippet="Over 40 students noted that response times exceeded 72 hours during peak intake.",
                interpretation="[AI Inference]: Operational bottleneck in student advising.",
                affected_area="gtm",
                type="opportunity",
                urgency="medium",
                why_it_matters="MeetUniversity can capture market share with instant WhatsApp routing.",
                suggested_action="Launch sub-5-minute WhatsApp response SLA.",
                final_rank_score=0.88,
                source_url="https://studentadmissionsforum.example.org/thread-449",
                verification_status="verified",
                published_at=utcnow(),
            ),
            Signal(
                company_id=company.id,
                document_id=doc.id,
                category="market",
                what_happened="Regulatory authority tightens student visa post-study work rules.",
                evidence_snippet="The Home Office published new limits on post-study work visas starting Q1.",
                interpretation="[AI Inference]: Shift in student destination preference towards Europe/Canada.",
                affected_area="compliance",
                type="threat",
                urgency="critical",
                why_it_matters="Shifts destination demand away from UK institutions.",
                suggested_action="Diversify destination university portfolios.",
                final_rank_score=0.95,
                source_url="https://homeoffice.example.gov/post-study-visa-2026",
                verification_status="verified",
                published_at=utcnow(),
            ),
            Signal(
                company_id=company.id,
                document_id=doc.id,
                category="internal",
                what_happened="[Lost Deal Reason] Missing automated WhatsApp counselor messaging.",
                evidence_snippet="The live WhatsApp counselor messaging was the decisive factor for our enrollment committee.",
                interpretation="[AI Inference]: WhatsApp integration is an urgent table-stakes feature.",
                affected_area="product_core",
                type="opportunity",
                urgency="high",
                why_it_matters="Directly unlocks 15+ stalled enterprise university deals.",
                suggested_action="Fast-track WhatsApp business API integration.",
                final_rank_score=0.89,
                source_url="internal://sales_retro.csv#row=2",
                verification_status="verified",
                published_at=utcnow(),
            ),
        ]

        for s in signals_data:
            session.add(s)
        session.commit()
        for s in signals_data:
            session.refresh(s)

        session.expunge_all()
        return company, signals_data


def test_exact_10_sections_in_order(mock_company_and_signals):
    company, signals = mock_company_and_signals
    brief, actions, verification = generate_weekly_brief(company.id, period="2026-W47")

    markdown = brief.markdown

    # Verify all 10 section headers are present in order
    last_pos = -1
    for title in EXACT_SECTION_TITLES:
        pos = markdown.find(title)
        assert pos != -1, f"Missing required section header: '{title}'"
        assert pos > last_pos, f"Section '{title}' appears out of order! pos={pos}, last_pos={last_pos}"
        last_pos = pos


def test_zero_padding_empty_category(mock_company_and_signals):
    company, _ = mock_company_and_signals

    # Create a fresh company with NO signals
    with Session(db.engine, expire_on_commit=False) as session:
        empty_comp = Company(
            name="Empty Signals Corp",
            domain="emptysignals.example.com",
            url="https://emptysignals.example.com",
            industry="Testing",
        )
        session.add(empty_comp)
        session.commit()
        session.refresh(empty_comp)
        session.expunge_all()

    brief, actions, verification = generate_weekly_brief(empty_comp.id, period="empty_period")
    
    # Must contain zero-padding disclaimer for empty categories
    assert NO_MEANINGFUL_DEVELOPMENT_TEXT in brief.markdown
    # All 10 sections must still be present
    for title in EXACT_SECTION_TITLES:
        assert title in brief.markdown


def test_executive_summary_top_5(mock_company_and_signals):
    company, signals = mock_company_and_signals
    brief, actions, verification = generate_weekly_brief(company.id, period="2026-W47")

    # Executive summary section should feature the top signal by score (0.95)
    exec_summary_chunk = brief.markdown.split("## 2. Competitor Movements")[0]
    assert "0.95" in exec_summary_chunk
    assert "Regulatory authority tightens student visa post-study work rules." in exec_summary_chunk


def test_opportunities_with_evidence_and_limitation(mock_company_and_signals):
    company, signals = mock_company_and_signals
    brief, actions, verification = generate_weekly_brief(company.id, period="2026-W47")

    # Section 8 Strategic Opportunities
    opp_chunk = brief.markdown.split("## 8. Strategic Opportunities")[1].split("## 9. Recommended Actions")[0]
    assert "Opportunity 1" in opp_chunk
    assert "Verified Evidence" in opp_chunk
    assert "Strategic Impact" in opp_chunk
    assert "Recommended Next Step" in opp_chunk
    assert "Priority" in opp_chunk


def test_actions_saved_to_actions_table(mock_company_and_signals):
    company, signals = mock_company_and_signals
    brief, actions, verification = generate_weekly_brief(company.id, period="2026-W47")

    assert len(actions) >= 1
    with Session(db.engine) as session:
        stored_actions = session.exec(select(Action).where(Action.brief_id == brief.id)).all()
        assert len(stored_actions) == len(actions)
        for act in stored_actions:
            assert act.brief_id == brief.id
            assert act.status == "open"
            assert act.priority in ("high", "medium", "low")
            assert act.owner is not None
            assert act.reason is not None
            assert len(act.text) > 10


def test_source_appendix_schema(mock_company_and_signals):
    company, signals = mock_company_and_signals
    brief, actions, verification = generate_weekly_brief(company.id, period="2026-W47")

    appendix_chunk = brief.markdown.split("## 10. Source Appendix")[1]
    assert "| Signal ID | Source URL | Published Date | Discovered Date | Verification Status | Verbatim Evidence Snippet |" in appendix_chunk
    for s in signals:
        assert f"#{s.id}" in appendix_chunk
        assert s.source_url in appendix_chunk
        assert s.verification_status.title() in appendix_chunk


def test_email_html_with_inline_css(mock_company_and_signals):
    company, signals = mock_company_and_signals
    brief, actions, verification = generate_weekly_brief(company.id, period="2026-W47")

    html = brief.html
    assert "<!DOCTYPE html>" in html
    assert "style=" in html
    assert "font-family:" in html
    assert "background-color:" in html
    assert company.name in html
    # Check all 10 section headers in HTML
    for title in EXACT_SECTION_TITLES:
        assert title in html


def test_post_check_claims_and_links_resolvable(mock_company_and_signals):
    company, signals = mock_company_and_signals
    brief, actions, verification = generate_weekly_brief(company.id, period="2026-W47")

    # Post-check validation
    assert verification.is_valid is True
    assert len(verification.unverified_claims) == 0
    assert len(verification.broken_links) == 0
    assert len(verification.sections_checked) == len(EXACT_SECTION_TITLES)


def test_brief_api_endpoints(mock_company_and_signals):
    company, signals = mock_company_and_signals
    client = TestClient(app)

    # 1. Generate Brief via API
    resp = client.post(f"/companies/{company.id}/briefs/generate?period=2026-W47")
    assert resp.status_code == 200
    data = resp.json()
    assert data["company_id"] == company.id
    assert data["period"] == "2026-W47"
    assert data["actions_count"] >= 1
    assert data["verification"]["is_valid"] is True
    brief_id = data["brief_id"]

    # 2. List Briefs
    list_resp = client.get(f"/companies/{company.id}/briefs")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) >= 1

    # 3. Get Brief Details
    detail_resp = client.get(f"/briefs/{brief_id}")
    assert detail_resp.status_code == 200
    detail_data = detail_resp.json()
    assert detail_data["id"] == brief_id
    assert len(detail_data["actions"]) >= 1

    # 4. View HTML representation
    html_resp = client.get(f"/briefs/{brief_id}/html")
    assert html_resp.status_code == 200
    assert "text/html" in html_resp.headers["content-type"]
    assert "<!DOCTYPE html>" in html_resp.text
