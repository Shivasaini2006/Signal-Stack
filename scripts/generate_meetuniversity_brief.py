import os
from sqlmodel import Session, select
from app.core import db
from app.models.entities import Company, Signal
from app.services.brief import generate_weekly_brief, verify_brief_claims

def run():
    with Session(db.engine) as session:
        company = session.exec(select(Company).where(Company.name.like("%Meet%"))).first()
        if not company:
            print("MeetUniversity not found, creating...")
            company = Company(
                name="Meet University",
                domain="meetuniversity.com",
                url="https://www.meetuniversity.com",
                industry="Higher Education & EdTech",
            )
            session.add(company)
            session.commit()
            session.refresh(company)

        company_id = company.id

    print(f"Generating Executive Strategic Brief for {company.name} (ID: {company_id})...")
    brief, actions, verification = generate_weekly_brief(company_id=company_id, period="2026-W47")

    print("\n" + "=" * 60)
    print("EXECUTIVE BRIEF GENERATION COMPLETED")
    print("=" * 60)
    print(f"Brief ID: {brief.id}")
    print(f"Period: {brief.period}")
    print(f"Actions Created: {len(actions)}")
    for a in actions:
        print(f"  * [{a.priority.upper()}] {a.text} (Owner: {a.owner})")
        print(f"    Reason: {a.reason}")

    print("\n" + "=" * 60)
    print("POST-CHECK VERIFICATION REPORT")
    print("=" * 60)
    print(f"Is Valid: {verification.is_valid}")
    print(f"Total Claims Checked: {verification.total_claims}")
    print(f"Verified Claims: {verification.verified_claims}")
    print(f"Unverified Claims: {verification.unverified_claims}")
    print(f"Broken Links: {verification.broken_links}")
    print(f"Sections Checked ({len(verification.sections_checked)}/10):")
    for sec in verification.sections_checked:
        print(f"  [x] {sec}")

    # Write preview files to data/
    os.makedirs("data", exist_ok=True)
    with open("data/sample_brief_meetuniversity.md", "w", encoding="utf-8") as f:
        f.write(brief.markdown)
    with open("data/sample_brief_meetuniversity.html", "w", encoding="utf-8") as f:
        f.write(brief.html)

    print("\nSaved markdown to: data/sample_brief_meetuniversity.md")
    print("Saved email-ready HTML to: data/sample_brief_meetuniversity.html")

    assert verification.is_valid is True, "Verification failed!"
    assert len(verification.broken_links) == 0, "Broken links detected!"
    print("\n>>> ACCEPTANCE CRITERIA MET: All links resolvable and verified against stored signals! <<<")

if __name__ == "__main__":
    run()
