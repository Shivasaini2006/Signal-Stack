import os
import re
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from sqlmodel import Session, select

from app.main import app
from app.models.entities import Company, ProfileField, Source
from app.services import discovery
from app.services.discovery import (
    discover_sources_for_company,
    CompetitorProfile,
    is_valid_url,
)

client = TestClient(app)


def test_no_hardcoded_domains_grep():
    """
    Acceptance Rule: No hard-coded company domains exist in the code (grep test).
    Ensures that discovery logic dynamically resolves domains via search and inference.
    """
    service_path = os.path.join("app", "services", "discovery.py")
    with open(service_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Prohibited specific company domain literals
    prohibited_domains = [
        "meetuniversity.com",
        "idp.com",
        "shiksha.com",
        "topuniversities.com",
        "hotcoursesabroad.com",
        "leverageedu.com",
        "yocket.com",
        "upgrad.com",
        "coursera.org",
        "stripe.com",
        "adyen.com",
    ]

    for domain in prohibited_domains:
        pattern = rf'["\']https?://(?:www\.)?{re.escape(domain)}["\']'
        matches = re.findall(pattern, content, re.IGNORECASE)
        assert len(matches) == 0, f"Found hardcoded domain {domain} in {service_path}: {matches}"


def test_discovery_pipeline_and_scoring(session: Session, monkeypatch):
    """
    Acceptance: each source has category, reason, scores, and targets 20+ sources.
    """
    company = Company(
        name="StudySphere Global",
        url="https://studysphere.io",
        domain="studysphere.io",
        industry="EdTech & Higher Education Counseling",
        description="Comprehensive study abroad counseling platform",
    )
    session.add(company)
    session.commit()
    session.refresh(company)

    # Mock DDGS hits to return a rich dynamic set of candidate sites
    mock_hits = [
        {"title": f"Competitor Brand {i} Official Newsroom", "url": f"https://rivalbrand{i}.com/news", "snippet": "Global student placement updates"}
        for i in range(1, 9)
    ] + [
        {"title": f"International Student Community Forum {i}", "url": f"https://studentforum{i}.org/discussions", "snippet": "Discussions on visa acceptance rates"}
        for i in range(1, 8)
    ] + [
        {"title": f"Higher Ed Quality Assurance Agency {i}", "url": f"https://regulator{i}.gov/updates", "snippet": "Official university accreditation criteria"}
        for i in range(1, 8)
    ]

    monkeypatch.setattr(discovery, "_run_ddgs_safe", MagicMock(return_value=mock_hits))
    monkeypatch.setattr(discovery, "validate_and_probe_source", MagicMock(return_value=(True, True, True, "Verified Source Portal")))

    result = discover_sources_for_company(company.id)

    assert result["company_name"] == "StudySphere Global"
    assert result["total_sources_suggested"] >= 20, f"Expected 20+ sources, got {result['total_sources_suggested']}"
    assert result["competitor_profiles_count"] >= 5

    # Verify each source conforms to standards
    sources = result["sources"]
    for src in sources:
        assert src["category"] in ("competitors", "customers", "market", "internal")
        assert src["status"] == "suggested"
        assert len(src["reason"].strip()) > 10, f"Reason too short for {src['name']}"
        assert 0.0 <= src["specific_score"] <= 1.0
        assert 0.0 <= src["recent_score"] <= 1.0
        assert 0.0 <= src["credible_score"] <= 1.0

    # Verify competitor profiles
    competitors = result["competitor_profiles"]
    for cp in competitors:
        assert "name" in cp
        assert "positioning" in cp
        assert "pricing" in cp
        assert "why_they_matter" in cp


def test_source_approval_and_rejection_api(session: Session):
    """Test approval and rejection workflows via REST API."""
    company = Company(
        name="Nova Logistics",
        url="https://novalogistics.com",
        domain="novalogistics.com",
        industry="Freight & Supply Chain",
    )
    session.add(company)
    session.commit()
    session.refresh(company)

    # Create a source
    src = Source(
        company_id=company.id,
        category="competitors",
        name="Rival Freight Feed",
        url="https://rivalfreight.com/feed",
        reason="Monitored for lane pricing updates.",
        specific_score=0.9,
        recent_score=0.85,
        credible_score=0.88,
        status="suggested",
    )
    session.add(src)
    session.commit()
    session.refresh(src)

    # 1. Approve
    app_resp = client.put(f"/sources/{src.id}/approve")
    assert app_resp.status_code == 200
    assert app_resp.json()["status"] == "approved"

    # 2. Reject
    rej_resp = client.put(f"/sources/{src.id}/reject")
    assert rej_resp.status_code == 200
    assert rej_resp.json()["status"] == "rejected"

    # 3. List with filter
    list_resp = client.get(f"/companies/{company.id}/sources?category=competitors")
    assert list_resp.status_code == 200
    data = list_resp.json()
    assert len(data) == 1
    assert data[0]["id"] == src.id
