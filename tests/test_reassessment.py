import json
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.core import db
from app.models.entities import Company, Source, ProfileField, AuditReport, ReassessmentRecord, utcnow
from app.services.reassessment import reassess_company_sources


@pytest.fixture
def reassessment_test_company():
    with Session(db.engine, expire_on_commit=False) as session:
        comp = Company(
            name="Global Education Advisory",
            domain="globaledu.example.com",
            url="https://globaledu.example.com",
            industry="EdTech & Higher Ed Counseling",
        )
        session.add(comp)
        session.commit()
        session.refresh(comp)

        # 1. UK-specific source (should be demoted upon pivot to Germany)
        s_uk = Source(
            company_id=comp.id,
            category="market",
            name="UK Home Office Student Visa Policy",
            url="https://homeoffice.gov.uk/visa-updates",
            reason="UK government post-study visa updates.",
            specific_score=0.9,
            recent_score=0.9,
            credible_score=0.9,
            status="approved",
            health="ok",
        )
        # 2. General global platform (should be kept)
        s_global = Source(
            company_id=comp.id,
            category="competitors",
            name="Global Admissions Hub",
            url="https://globaladmissionshub.example.com/blog",
            reason="International cross-border counseling competitor.",
            specific_score=0.88,
            recent_score=0.85,
            credible_score=0.90,
            status="approved",
            health="ok",
        )
        # 3. Internal sales feedback (should be kept)
        s_internal = Source(
            company_id=comp.id,
            category="internal",
            name="Internal Sales Objections",
            url="internal://pipeline_lost_deals.csv",
            reason="Internal deal reviews.",
            specific_score=0.98,
            recent_score=0.95,
            credible_score=0.99,
            status="approved",
            health="ok",
        )

        session.add(s_uk)
        session.add(s_global)
        session.add(s_internal)
        session.commit()

        session.expunge_all()
        return comp, s_uk, s_global, s_internal


def test_reassessment_diff_logic(reassessment_test_company):
    comp, s_uk, s_global, s_internal = reassessment_test_company

    pivot = "pivot to focus on study-abroad in Germany"
    report = reassess_company_sources(
        company_id=comp.id,
        pivot_context=pivot,
        updated_fields={"geography": "Germany / DACH Region"},
    )

    # 1. Kept vs Demoted checks
    assert report.demoted_count >= 1
    demoted_ids = [d["source_id"] for d in report.demoted_or_rejected]
    assert s_uk.id in demoted_ids
    uk_demoted_entry = next(d for d in report.demoted_or_rejected if d["source_id"] == s_uk.id)
    assert "UK" in uk_demoted_entry["demotion_reason"]
    assert "Germany" in uk_demoted_entry["demotion_reason"]

    kept_ids = [k["source_id"] for k in report.kept]
    assert s_internal.id in kept_ids

    # 2. Newly suggested sources for Germany
    assert report.newly_suggested_count >= 1
    new_urls = [n["url"] for n in report.newly_suggested]
    assert any("germany" in u.lower() or "daad" in u.lower() or "uni-assist" in u.lower() for u in new_urls)

    # 3. Plain language summary
    assert "What Changed & Why" in report.summary
    assert "pivot to focus on study-abroad in Germany" in report.summary

    # 4. Check DB records
    with Session(db.engine) as session:
        # Check source statuses in DB
        uk_source = session.get(Source, s_uk.id)
        assert uk_source.status == "rejected"
        assert "Demoted" in uk_source.reason

        # Check AuditReport
        audit = session.get(AuditReport, report.audit_report_id)
        assert audit is not None
        assert "Strategic Reassessment Diff" in audit.title
        assert "Kept Sources Portfolio" in audit.content
        assert "Demoted & Pruned Sources" in audit.content

        # Check ReassessmentRecord
        reassess_rec = session.get(ReassessmentRecord, report.reassessment_id)
        assert reassess_rec is not None
        assert reassess_rec.pivot_context == pivot
        diff_obj = json.loads(reassess_rec.diff_json)
        assert len(diff_obj["demoted_or_rejected"]) >= 1

        # Check ProfileField updated
        pf_focus = session.exec(
            select(ProfileField)
            .where(ProfileField.company_id == comp.id)
            .where(ProfileField.key == "strategic_focus")
        ).first()
        assert pf_focus is not None
        assert pf_focus.value == pivot


def test_reassessment_api_endpoints(reassessment_test_company):
    comp, _, _, _ = reassessment_test_company
    client = TestClient(app)

    # 1. POST /companies/{id}/reassess
    payload = {
        "pivot_context": "Pivot to focus on study-abroad in Germany",
        "updated_fields": {
            "target_country": "Germany",
            "primary_language": "English & German",
        },
    }
    resp = client.post(f"/companies/{comp.id}/reassess", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["company_id"] == comp.id
    assert data["kept_count"] >= 1
    assert data["demoted_count"] >= 1
    assert data["newly_suggested_count"] >= 1
    assert "summary" in data

    # 2. GET /companies/{id}/reassess
    list_resp = client.get(f"/companies/{comp.id}/reassess")
    assert list_resp.status_code == 200
    reassessment_history = list_resp.json()
    assert len(reassessment_history) >= 1
    assert reassessment_history[0]["pivot_context"] == "Pivot to focus on study-abroad in Germany"
