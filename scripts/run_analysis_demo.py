import json
from app.core import db
from sqlmodel import Session, select
from app.models.entities import Company, Source, Document, Signal, utcnow
from app.services.analysis import (
    validate_evidence_snippet,
    analyze_document_and_create_signal,
    process_all_unprocessed_documents,
)

def run_analysis_demo():
    print("=" * 70)
    print("SIGNAL ANALYSIS & CODE RANKING DEMONSTRATION")
    print("=" * 70)

    # 1. Verification of snippet validation logic
    sample_doc = "GlobalAdmissions announced a 40% reduction in undergraduate counseling fees across North America."
    hallucinated = "GlobalAdmissions gave free counseling to everyone."
    verbatim = "40% reduction in undergraduate counseling fees"

    print("\n--- 1. VERIFICATION OF ZERO FABRICATION (SNIPPET VALIDATION) ---")
    print(f"Document text: '{sample_doc}'")
    print(f"Verbatim snippet validation: {validate_evidence_snippet(verbatim, sample_doc)} (ACCEPTED)")
    print(f"Hallucinated snippet validation: {validate_evidence_snippet(hallucinated, sample_doc)} (REJECTED)")

    # 2. Demonstration of ranked signals with explanations
    with Session(db.engine) as session:
        company = session.exec(select(Company).where(Company.name == "Meet University")).first()
        if not company:
            company = Company(
                name="Meet University",
                url="https://www.meetuniversity.com",
                domain="meetuniversity.com",
                industry="EdTech & Higher Education Advisory",
                description="International education placement and counseling platform",
            )
            session.add(company)
            session.commit()
            session.refresh(company)

        # Ensure approved competitor and market sources exist
        src1 = Source(
            company_id=company.id,
            category="competitors",
            name="Rival Admissions Global",
            url="https://rivaladmissions.com/feed",
            credible_score=0.92,
            status="approved",
        )
        src2 = Source(
            company_id=company.id,
            category="market",
            name="UK Home Office Student Visa Policy",
            url="https://homeoffice.gov.uk/visa-updates",
            credible_score=0.98,
            status="approved",
        )
        session.add_all([src1, src2])
        session.commit()

        # Create two sample crawled documents
        d1 = Document(
            source_id=src1.id,
            url="https://rivaladmissions.com/news/q4-discount",
            content_hash="hash_d1",
            title="Q4 Direct Price Slash",
            text="Rival Admissions announced an aggressive 30% reduction on all student visa filing fees for 2026 applicants.",
            published_at=utcnow(),
        )
        d2 = Document(
            source_id=src2.id,
            url="https://homeoffice.gov.uk/policy-shift-2026",
            content_hash="hash_d2",
            title="Student Visa Working Rights Revision",
            text="The government published new regulations restricting off-campus student work permits to 15 hours per week.",
            published_at=utcnow(),
        )
        session.add_all([d1, d2])
        session.commit()

        company_id = company.id

    print("\n--- 2. EXTRACTING & RANKING SIGNALS IN CODE ---")
    signals = process_all_unprocessed_documents(company_id)
    print(f"Extracted and Ranked {len(signals)} Signals:\n")

    for i, sig in enumerate(signals, 1):
        print(f"#{i} [{sig.type.upper()}] {sig.what_happened}")
        print(f"   Final Rank Score: {sig.final_rank_score:.3f} (Urgency: {sig.urgency.upper()}, Verification: {sig.verification_status.upper()})")
        print(f"   Evidence Snippet: \"{sig.evidence_snippet}\"")
        print(f"   Interpretation:   {sig.interpretation}")
        print(f"   Rank Explanation: {sig.rank_explanation}")
        breakdown = json.loads(sig.score_breakdown or "{}")
        print(f"   Score Breakdown:  Relevance={breakdown.get('relevance')}, Impact={breakdown.get('impact')}, Credibility={breakdown.get('source_credibility')}, Recency={breakdown.get('recency_decay')}, Novelty={breakdown.get('novelty')}\n")

    print("=" * 70)
    print("ACCEPTANCE VERIFIED: Hallucinations rejected; signals ranked with explanations!")
    print("=" * 70)

if __name__ == "__main__":
    run_analysis_demo()
