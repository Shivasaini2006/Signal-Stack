import os
import json
from sqlmodel import Session, select

from app.core import db
from app.models.entities import Company
from app.services.reassessment import reassess_company_sources


def run_demo():
    print("=" * 70)
    print("SIGNAL STACK — DEMO: STRATEGIC PORTFOLIO REASSESSMENT")
    print("Company: Meet University")
    print("Pivot Context: Pivot to focus on study-abroad in Germany")
    print("=" * 70)

    with Session(db.engine) as session:
        company = session.exec(select(Company).where(Company.name.like("%Meet%"))).first()
        if not company:
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

    pivot_context = "Pivot to focus on study-abroad in Germany"
    updated_fields = {
        "geography": "Germany & DACH Region",
        "primary_target_degrees": "English-taught Bachelors and Masters in German Public Universities",
        "strategic_priority": "DAAD scholarship guidance, Uni-Assist applications, and blocked account compliance",
    }

    report = reassess_company_sources(
        company_id=company_id,
        pivot_context=pivot_context,
        updated_fields=updated_fields,
    )

    print("\n--- 1. SUMMARY: WHAT CHANGED & WHY ---")
    print(report.summary)

    print("\n--- 2. KEPT SOURCES (" + str(report.kept_count) + ") ---")
    for k in report.kept:
        print(f"  [+] #{k['source_id']} {k['name']} ({k['url']})")
        print(f"      Status: {k['status'].upper()} | Category: {k['category']}")
        print(f"      Reason: {k['reason']}\n")

    print("--- 3. DEMOTED / REJECTED SOURCES (" + str(report.demoted_count) + ") ---")
    for d in report.demoted_or_rejected:
        print(f"  [-] #{d['source_id']} {d['name']} ({d['url']})")
        print(f"      Status: {d['status'].upper()} | Previous: {d['previous_status']}")
        print(f"      Demotion Rationale: {d['demotion_reason']}\n")

    print("--- 4. NEWLY SUGGESTED SOURCES (" + str(report.newly_suggested_count) + ") ---")
    for n in report.newly_suggested:
        print(f"  [*] #{n['source_id']} {n['name']} ({n['url']})")
        print(f"      Category: {n['category']} | Scores: {n['scores']}")
        print(f"      Proposed Role: {n['reason']}\n")

    # Persist evidence artifacts for demo
    os.makedirs("data", exist_ok=True)
    json_path = "data/demo_evidence_meetuniversity_germany_pivot.json"
    md_path = "data/demo_evidence_meetuniversity_germany_pivot.md"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report.model_dump(), f, indent=2)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# Strategic Intelligence Reassessment Demo — Meet University\n\n")
        f.write(f"**Trigger**: `{pivot_context}`\n\n")
        f.write(f"{report.summary}\n\n")
        f.write(f"## 1. Kept Sources ({report.kept_count})\n")
        for k in report.kept:
            f.write(f"- **{k['name']}** ([{k['url']}]({k['url']})) — *{k['reason']}*\n")
        f.write(f"\n## 2. Demoted / Rejected Sources ({report.demoted_count})\n")
        for d in report.demoted_or_rejected:
            f.write(f"- **{d['name']}** ([{d['url']}]({d['url']})) — **Demoted**: *{d['demotion_reason']}*\n")
        f.write(f"\n## 3. Newly Suggested Sources ({report.newly_suggested_count})\n")
        for n in report.newly_suggested:
            f.write(f"- **{n['name']}** ([{n['url']}]({n['url']})) — *{n['reason']}*\n")

    print("=" * 70)
    print(f"DEMO EVIDENCE PRESERVED:")
    print(f"  JSON: {json_path}")
    print(f"  Markdown: {md_path}")
    print(f"  AuditReport ID: #{report.audit_report_id}")
    print(f"  ReassessmentRecord ID: #{report.reassessment_id}")
    print("=" * 70)


if __name__ == "__main__":
    run_demo()
