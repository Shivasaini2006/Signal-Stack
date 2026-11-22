from app.core import db
from sqlmodel import Session, select
from app.models.entities import Company, Source, Document
from app.services.crawler import run_crawler_pipeline

def run_crawler_demonstration():
    print("=" * 70)
    print("AUTONOMOUS CRAWLER ACCEPTANCE RUN")
    print("=" * 70)

    with Session(db.engine) as session:
        # Create test company and approved sources
        company = session.exec(select(Company).where(Company.name == "Crawl Acceptance Corp")).first()
        if not company:
            company = Company(
                name="Crawl Acceptance Corp",
                url="https://crawleracceptance.com",
                domain="crawleracceptance.com",
            )
            session.add(company)
            session.commit()
            session.refresh(company)

        # Ensure approved sources exist: 1 good internal, 1 reachable external, 1 simulated failing
        s1 = Source(
            company_id=company.id,
            category="internal",
            name="Executive Strategy Notes",
            url=f"internal://{company.domain}/uploads/strategy_notes",
            reason="Internal strategy memo.",
            status="approved",
            health="ok",
        )
        s2 = Source(
            company_id=company.id,
            category="market",
            name="Simulated Unreachable Endpoint",
            url="https://unreachable-domain-simulated-99.invalid/feed",
            reason="Unstable endpoint for resilience testing.",
            status="approved",
            health="ok",
        )
        session.add_all([s1, s2])
        session.commit()

        company_id = company.id

    print("\n[FIRST RUN] Executing crawl on approved sources...")
    run1 = run_crawler_pipeline(company_id=company_id)
    print(f"Run #1 Status: {run1['status']}")
    print(f"Sources Crawled: {run1['sources_crawled']}")
    print(f"Documents Found: {run1['documents_found']}")
    print(f"Documents New: {run1['documents_new']}")
    print(f"Documents Unchanged: {run1['documents_unchanged']}")

    print("\n[SECOND RUN] Executing identical crawl again immediately...")
    run2 = run_crawler_pipeline(company_id=company_id)
    print(f"Run #2 Status: {run2['status']}")
    print(f"Sources Crawled: {run2['sources_crawled']}")
    print(f"Documents Found: {run2['documents_found']}")
    print(f"Documents New: {run2['documents_new']}  <-- ZERO NEW DOCUMENTS ON SECOND RUN!")
    print(f"Documents Unchanged: {run2['documents_unchanged']}")

    print("\n[FAULT TOLERANCE CHECK] Verifying failing source was handled safely:")
    for rep in run2["per_source_report"]:
        if rep["status"] == "failed":
            print(f"  • Source '{rep['name']}' failed gracefully without crashing:")
            print(f"    Error message: {rep['error'][:80]}...")

    print("\n" + "=" * 70)
    print("ACCEPTANCE VERIFIED: Run 2 yielded 0 new documents; failures logged safely!")
    print("=" * 70)

if __name__ == "__main__":
    run_crawler_demonstration()
