from app.services.internal_intel import process_internal_file_upload
from app.core import db
from sqlmodel import Session, select
from app.models.entities import Company

with Session(db.engine) as session:
    c = session.exec(select(Company)).first()
    if not c:
        c = Company(
            name="MeetUniversity",
            domain="meetuniversity.com",
            url="https://www.meetuniversity.com",
            industry="EdTech",
        )
        session.add(c)
        session.commit()
        session.refresh(c)
    cid = c.id

with open("data/test_sales_objections_sample.csv", "rb") as f:
    content = f.read()

signals = process_internal_file_upload(cid, content, "test_sales_objections_sample.csv")
print(f"Extracted {len(signals)} internal signals from test_sales_objections_sample.csv for Company ID {cid}:")
for idx, s in enumerate(signals[:4], 1):
    print(f"\n[{idx}] Score: {s.final_rank_score:.3f} ({s.urgency.upper()}) | {s.what_happened}")
    print(f"    Source URL: {s.source_url}")
    print(f"    Verbatim Evidence: \"{s.evidence_snippet}\"")
    print(f"    Strategic Relevance: {s.strategic_relevance} | Source Reliability: {s.source_reliability}")
    print(f"    Interpretation: {s.interpretation}")
    print(f"    Rank Explanation: {s.rank_explanation}")
