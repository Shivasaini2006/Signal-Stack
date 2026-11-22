import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.models.entities import Company, Source, Document, CrawlRun
from app.services import crawler
from app.services.crawler import (
    run_crawler_pipeline,
    compute_content_hash,
    compute_simhash,
    hamming_distance,
)

client = TestClient(app)


def test_simhash_and_hamming_distance():
    """Test 64-bit SimHash and near-duplicate detection."""
    text1 = "Meet University announced new international advisory partnerships with 10 UK institutions today."
    text2 = "Meet University announced new international advisory partnerships with 10 UK institutions today!"
    text3 = "Completely unrelated article on semiconductor quantum computing and photonic lasers."

    h1 = compute_simhash(text1)
    h2 = compute_simhash(text2)
    h3 = compute_simhash(text3)

    assert hamming_distance(h1, h2) <= 3  # Near-duplicate!
    assert hamming_distance(h1, h3) > 10  # Very different!


def test_crawler_acceptance_run_twice_zero_new_docs(session: Session, monkeypatch):
    """
    Acceptance Test: Running twice yields 0 new documents on the second run,
    and changed content preserves history.
    """
    company = Company(name="Test University Co", url="https://testuniv.edu")
    session.add(company)
    session.commit()
    session.refresh(company)

    # Approved source
    src = Source(
        company_id=company.id,
        category="competitors",
        name="Competitor News Feed",
        url="https://rivaled.org/feed",
        status="approved",
        health="ok",
    )
    session.add(src)
    session.commit()
    session.refresh(src)

    # Mock content for source
    mock_items_run1 = [
        {
            "url": "https://rivaled.org/news/post-1",
            "title": "Admissions Platform Launch",
            "text": "RivalEd launched their automated student visa tracking platform for international scholars.",
            "published_at": None,
        },
        {
            "url": "https://rivaled.org/news/post-2",
            "title": "Scholarship Fund Update",
            "text": "Over 500 university grants announced for engineering and science applicants.",
            "published_at": None,
        },
    ]

    monkeypatch.setattr(crawler, "is_robots_allowed_cached", MagicMock(return_value=True))
    monkeypatch.setattr(crawler, "enforce_domain_rate_limit", MagicMock())
    monkeypatch.setattr(crawler, "fetch_and_extract_content", MagicMock(return_value=mock_items_run1))

    # --- RUN 1 ---
    run1 = run_crawler_pipeline(company_id=company.id)
    assert run1["status"] == "completed"
    assert run1["sources_crawled"] == 1
    assert run1["documents_new"] == 2
    assert run1["documents_unchanged"] == 0

    docs_after_run1 = session.exec(select(Document).where(Document.source_id == src.id)).all()
    assert len(docs_after_run1) == 2

    # --- RUN 2 (Identical Content) ---
    # Acceptance criteria: running twice yields 0 new documents on the second run!
    run2 = run_crawler_pipeline(company_id=company.id)
    assert run2["status"] == "completed"
    assert run2["documents_new"] == 0
    assert run2["documents_unchanged"] == 2

    docs_after_run2 = session.exec(select(Document).where(Document.source_id == src.id)).all()
    assert len(docs_after_run2) == 2  # No duplicate rows created!


def test_crawler_detects_changed_content_and_keeps_history(session: Session, monkeypatch):
    """
    Test that when an article is modified, the crawler detects 'changed' and
    inserts a new version to keep full historical audit trail.
    """
    company = Company(name="FinTech Target", url="https://fintechtarget.io")
    session.add(company)
    session.commit()
    session.refresh(company)

    src = Source(
        company_id=company.id,
        category="competitors",
        name="Rival API Updates",
        url="https://rivalpay.com/updates",
        status="approved",
    )
    session.add(src)
    session.commit()
    session.refresh(src)

    monkeypatch.setattr(crawler, "is_robots_allowed_cached", MagicMock(return_value=True))
    monkeypatch.setattr(crawler, "enforce_domain_rate_limit", MagicMock())

    # Version 1
    v1_items = [{
        "url": "https://rivalpay.com/pricing",
        "title": "Pricing Schedule",
        "text": "Standard rate is 2.9% plus 30 cents per card transaction.",
        "published_at": None,
    }]
    monkeypatch.setattr(crawler, "fetch_and_extract_content", MagicMock(return_value=v1_items))

    run1 = run_crawler_pipeline(company_id=company.id)
    assert run1["documents_new"] == 1

    # Version 2 (Content updated)
    v2_items = [{
        "url": "https://rivalpay.com/pricing",
        "title": "Pricing Schedule",
        "text": "Price reduction: Standard rate is now 2.1% plus 20 cents per card transaction.",
        "published_at": None,
    }]
    monkeypatch.setattr(crawler, "fetch_and_extract_content", MagicMock(return_value=v2_items))

    run2 = run_crawler_pipeline(company_id=company.id)
    assert run2["documents_new"] == 0
    assert run2["documents_changed"] == 1

    # Full history: both versions stored!
    all_versions = session.exec(select(Document).where(Document.url == "https://rivalpay.com/pricing")).all()
    assert len(all_versions) == 2


def test_crawler_handles_failures_without_crashing(session: Session, monkeypatch):
    """
    Acceptance Test: Failures are logged without crashing and source health updates.
    """
    company = Company(name="Failing Source Co", url="https://failco.com")
    session.add(company)
    session.commit()
    session.refresh(company)

    src = Source(
        company_id=company.id,
        category="market",
        name="Unstable Regulatory Feed",
        url="https://flaky-server.gov/feed",
        status="approved",
        health="ok",
    )
    session.add(src)
    session.commit()
    session.refresh(src)

    monkeypatch.setattr(crawler, "is_robots_allowed_cached", MagicMock(return_value=True))
    monkeypatch.setattr(crawler, "enforce_domain_rate_limit", MagicMock())
    # Simulate HTTP 503 Service Unavailable
    monkeypatch.setattr(crawler, "fetch_and_extract_content", MagicMock(side_effect=RuntimeError("503 Service Unavailable")))

    # Crawl pipeline should NOT crash!
    run_res = run_crawler_pipeline(company_id=company.id)
    assert run_res["status"] == "completed"
    assert run_res["sources_crawled"] == 1

    # Check source health updated
    session.refresh(src)
    assert src.consecutive_failures == 1
    assert src.health == "warning"
    assert "503 Service Unavailable" in src.last_error


def test_crawl_run_api_endpoint(session: Session, monkeypatch):
    """Test POST /crawl/run REST API endpoint."""
    company = Company(name="API Crawl Co", url="https://apicrawl.com")
    session.add(company)
    session.commit()
    session.refresh(company)

    src = Source(
        company_id=company.id,
        category="customers",
        name="Customer Discussion Portal",
        url="https://community.apicrawl.com",
        status="approved",
    )
    session.add(src)
    session.commit()
    session.refresh(src)

    monkeypatch.setattr(crawler, "is_robots_allowed_cached", MagicMock(return_value=True))
    monkeypatch.setattr(crawler, "enforce_domain_rate_limit", MagicMock())
    monkeypatch.setattr(crawler, "fetch_and_extract_content", MagicMock(return_value=[{
        "url": "https://community.apicrawl.com/topic-1",
        "title": "Feedback on API Latency",
        "text": "Great platform but webhooks experience occasional 500ms jitter.",
        "published_at": None,
    }]))

    resp = client.post("/crawl/run", json={"company_id": company.id})
    assert resp.status_code == 200
    data = resp.json()
    assert "crawl_run_id" in data
    assert data["status"] == "completed"
    assert data["documents_new"] == 1
