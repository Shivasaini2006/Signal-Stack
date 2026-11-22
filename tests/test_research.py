import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from sqlmodel import Session, select

from app.main import app
from app.models.entities import Company, ProfileField
from app.services import research
from app.services.research import (
    crawl_company_pages,
    run_ddgs_searches,
    extract_structured_profile,
    research_company,
    StructuredCompanyProfile,
    ProfileFieldItem,
)

client = TestClient(app)


def test_create_company_api():
    response = client.post(
        "/companies",
        json={"name": "Test University", "url": "https://testuniversity.edu"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test University"
    assert data["domain"] == "testuniversity.edu"
    assert "id" in data


def test_research_service_pipeline(monkeypatch, session: Session):
    """Test full research pipeline with mocked crawl and ddgs."""
    mock_crawled = [
        {
            "url": "https://example.org/",
            "title": "Example EdTech Homepage",
            "text": "Example EdTech provides international university admissions guidance and visa counseling.",
        },
        {
            "url": "https://example.org/study_in_usa",
            "title": "Study in USA",
            "text": "Comprehensive admissions advisory for universities across the USA.",
        },
    ]

    mock_search = [
        {
            "query": "Example EdTech news",
            "title": "Example EdTech Secures Partnership",
            "snippet": "EdTech platform partners with 50 global colleges.",
            "url": "https://news.example.com/edtech-partners",
        }
    ]

    monkeypatch.setattr(research, "crawl_company_pages", MagicMock(return_value=mock_crawled))
    monkeypatch.setattr(research, "run_ddgs_searches", MagicMock(return_value=mock_search))

    result = research_company(
        company_name="Example EdTech",
        url="https://example.org",
    )

    assert result["company"]["name"] == "Example EdTech"
    assert result["crawled_pages_count"] == 2
    assert result["search_results_count"] == 1

    pfs = result["profile_fields"]
    assert len(pfs) >= 6

    # Verify that every field has valid status, and verified facts must have source_url & evidence_snippet
    for field in pfs:
        if field["status"] == "verified":
            assert field["is_verified_fact"] is True
            assert field["source_url"] is not None
            assert field["evidence_snippet"] is not None
        else:
            assert field["status"] == "assumption"
            assert field["is_verified_fact"] is False


def test_company_research_api_endpoint(monkeypatch):
    """Test POST /companies/{id}/research API endpoint."""
    create_resp = client.post(
        "/companies",
        json={"name": "Api Target Co", "url": "https://apicompanysample.com"},
    )
    company_id = create_resp.json()["id"]

    mock_profile = StructuredCompanyProfile(
        industry=ProfileFieldItem(
            key="industry",
            value="EdTech",
            status="verified",
            is_verified_fact=True,
            source_url="https://apicompanysample.com",
            evidence_snippet="Global educational advising platform",
        ),
        business_lines=ProfileFieldItem(
            key="business_lines",
            value="Advisory",
            status="verified",
            is_verified_fact=True,
            source_url="https://apicompanysample.com",
            evidence_snippet="Student application advisory",
        ),
        products=ProfileFieldItem(
            key="products",
            value="University matching engine",
            status="verified",
            is_verified_fact=True,
            source_url="https://apicompanysample.com/products",
            evidence_snippet="Our automated matching engine",
        ),
        customer_segments=ProfileFieldItem(
            key="customer_segments",
            value="Undergraduate applicants",
            status="assumption",
            is_verified_fact=False,
            source_url=None,
            evidence_snippet=None,
        ),
        positioning=ProfileFieldItem(
            key="positioning",
            value="Premier overseas education partner",
            status="verified",
            is_verified_fact=True,
            source_url="https://apicompanysample.com",
            evidence_snippet="The premier overseas education partner",
        ),
        geography=ProfileFieldItem(
            key="geography",
            value="Global",
            status="assumption",
            is_verified_fact=False,
            source_url=None,
            evidence_snippet=None,
        ),
    )

    monkeypatch.setattr(research, "crawl_company_pages", MagicMock(return_value=[{"url": "https://apicompanysample.com", "title": "Home", "text": "Content"}]))
    monkeypatch.setattr(research, "run_ddgs_searches", MagicMock(return_value=[]))
    monkeypatch.setattr(research, "extract_structured_profile", MagicMock(return_value=mock_profile))

    research_resp = client.post(f"/companies/{company_id}/research")
    assert research_resp.status_code == 200
    data = research_resp.json()
    assert data["company"]["id"] == company_id
    assert len(data["profile_fields"]) == 6

    # Verify verified facts have source_url and assumptions have None
    for item in data["profile_fields"]:
        if item["status"] == "verified":
            assert item["is_verified_fact"] is True
            assert item["source_url"] is not None
            assert item["evidence_snippet"] is not None
        else:
            assert item["status"] == "assumption"
            assert item["is_verified_fact"] is False
            assert item["source_url"] is None
