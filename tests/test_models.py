from datetime import datetime
from sqlmodel import Session, select
from app.models.entities import (
    Company,
    ProfileField,
    InterviewTurn,
    Source,
    CrawlRun,
    Document,
    Signal,
    Brief,
    Action,
    AuditReport,
    JobLog,
    LLMCache,
)


def test_models_crud(session: Session):
    # 1. Company
    company = Company(
        name="Acme Corp",
        domain="acme.com",
        industry="Enterprise Software",
        description="Autonomous operations platform",
    )
    session.add(company)
    session.commit()
    session.refresh(company)
    assert company.id is not None
    assert company.name == "Acme Corp"

    # 2. ProfileField
    pf = ProfileField(
        company_id=company.id,
        key="pricing_model",
        value="Usage-based per API call",
        source="research",
        is_verified_fact=True,
    )
    session.add(pf)
    session.commit()
    session.refresh(pf)
    assert pf.source == "research"
    assert pf.is_verified_fact is True

    # 3. InterviewTurn
    turn = InterviewTurn(
        company_id=company.id,
        turn_index=1,
        question="What is the primary customer acquisition channel?",
        answer="Product-led growth with developer referrals.",
        status="answered",
    )
    session.add(turn)
    session.commit()
    session.refresh(turn)
    assert turn.turn_index == 1
    assert turn.status == "answered"

    # 4. Source
    source = Source(
        company_id=company.id,
        category="competitors",
        url="https://rival.com/news",
        name="Rival Newsroom",
        reason="Primary competitor blog",
        specific_score=0.9,
        recent_score=0.85,
        credible_score=0.95,
        status="approved",
        health="ok",
    )
    session.add(source)
    session.commit()
    session.refresh(source)
    assert source.category == "competitors"
    assert source.specific_score == 0.9

    # 5. CrawlRun & Document
    crawl = CrawlRun(status="completed", sources_crawled=1, documents_found=1)
    session.add(crawl)
    session.commit()
    session.refresh(crawl)

    doc = Document(
        url="https://rival.com/news/q3-release",
        content_hash="hash12345",
        title="Q3 Autonomous Engine Launch",
        text="Rival Corp launched autonomous agents with 30% faster indexing.",
        source_id=source.id,
        crawl_run_id=crawl.id,
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    assert doc.id is not None

    # 6. Signal (Verifiable Attribution Schema & Tri-Factor decoupled scores)
    signal = Signal(
        document_id=doc.id,
        category="product_launch",
        what_happened="Competitor announced v3 autonomous agent architecture",
        evidence_snippet="Rival Corp launched autonomous agents with 30% faster indexing.",
        interpretation="Threatens Acme's enterprise performance differentiation in real-time workloads.",
        affected_area="product_core",
        type="threat",
        urgency="high",
        source_reliability=0.9,
        evidence_strength=0.95,
        strategic_relevance=0.88,
        final_rank_score=0.91,
        rank_explanation="Verified launch from official press release impacting direct core feature.",
        verification_status="verified",
        source_url=doc.url,
    )
    session.add(signal)
    session.commit()
    session.refresh(signal)
    assert signal.id is not None
    assert signal.evidence_snippet == "Rival Corp launched autonomous agents with 30% faster indexing."
    assert signal.interpretation != signal.evidence_snippet
    assert signal.source_reliability == 0.9
    assert signal.evidence_strength == 0.95
    assert signal.strategic_relevance == 0.88

    # 7. Brief & Action
    brief = Brief(
        company_id=company.id,
        markdown="# Executive Brief\n\n- Key threat detected in competitor indexing.",
        html="<h1>Executive Brief</h1><p>Key threat detected in competitor indexing.</p>",
        period="2026-W47",
    )
    session.add(brief)
    session.commit()
    session.refresh(brief)

    action = Action(
        brief_id=brief.id,
        text="Benchmark Acme v2 against Rival v3 indexing latency.",
        owner="Engineering VP",
        priority="high",
        status="open",
    )
    session.add(action)
    session.commit()
    session.refresh(action)
    assert action.priority == "high"

    # 8. AuditReport & JobLog & LLMCache
    audit = AuditReport(
        company_id=company.id,
        title="Source Freshness Audit",
        content="All 1 sources active and verified.",
    )
    job = JobLog(job_type="nightly_crawl", status="success")
    cache = LLMCache(
        prompt_hash="abcde12345",
        provider="gemini",
        model="gemini-2.5-flash",
        response_json='{"analysis": "complete"}',
    )
    session.add_all([audit, job, cache])
    session.commit()

    all_signals = session.exec(select(Signal)).all()
    assert len(all_signals) == 1
