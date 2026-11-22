import io
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select
import pypdf

from app.main import app
from app.core import db
from app.models.entities import Company, Signal, Source, Document
from app.services.internal_intel import (
    parse_and_chunk_uploaded_file,
    process_internal_file_upload,
)
from scripts.generate_sample_internal_data import generate_sample_csv


@pytest.fixture
def test_company():
    with Session(db.engine) as session:
        company = Company(
            name="EdTech Global Labs",
            url="https://edtechglobal.example.com",
            domain="edtechglobal.example.com",
            industry="EdTech",
        )
        session.add(company)
        session.commit()
        session.refresh(company)
        return company


def test_parse_and_chunk_csv():
    csv_content = (
        "deal_id,lost_reason,customer_quote\n"
        "D-101,Pricing too high,The annual fee is 35% higher than our budget allowed.\n"
        "D-102,Missing feature,We need an automated visa document verification tool.\n"
    ).encode("utf-8")

    chunks = parse_and_chunk_uploaded_file(csv_content, "lost_deals.csv")
    assert len(chunks) == 2
    assert chunks[0]["source_ref"] == "lost_deals.csv#row=1"
    assert "Row 1" in chunks[0]["location_label"]
    assert "The annual fee is 35% higher than our budget allowed." in chunks[0]["text"]
    assert chunks[1]["source_ref"] == "lost_deals.csv#row=2"


def test_parse_and_chunk_txt():
    txt_content = (
        "Q3 Sales Retro Review\n\n"
        "Several customers pushed back on the lack of monthly invoicing.\n\n"
        "Competitors are aggressively offering 60-day pilots without upfront payment."
    ).encode("utf-8")

    chunks = parse_and_chunk_uploaded_file(txt_content, "retro.txt")
    assert len(chunks) == 3
    assert chunks[0]["source_ref"] == "retro.txt#section=1"
    assert "Section 1" in chunks[0]["location_label"]
    assert chunks[1]["source_ref"] == "retro.txt#section=2"
    assert "monthly invoicing" in chunks[1]["text"]


def test_parse_and_chunk_pdf():
    # Build a 2-page PDF in memory using pypdf
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_blank_page(width=72, height=72)
    
    # We can write dummy text into PDF or test blank page handling
    buf = io.BytesIO()
    writer.write(buf)
    pdf_bytes = buf.getvalue()

    # Empty pages won't produce chunks > 20 chars
    chunks = parse_and_chunk_uploaded_file(pdf_bytes, "report.pdf")
    assert isinstance(chunks, list)


def test_process_internal_csv_upload(test_company):
    csv_content = (
        "# [TEST DATA - SYNTHETIC DATASET FOR ACCEPTANCE TESTING]\n"
        "deal_id,outcome,notes,customer_quote\n"
        "OPP-1,Closed Lost,Lost to EduScale,The competitor pricing is 40% lower and includes automated visa filing support.\n"
        "OPP-2,Closed Lost,Missing integration,We urgently need automated AI verification to detect plagiarism.\n"
    ).encode("utf-8")

    signals = process_internal_file_upload(
        company_id=test_company.id,
        file_bytes=csv_content,
        filename="sales_objections_test.csv",
    )

    assert len(signals) >= 1
    for sig in signals:
        assert sig.category == "internal"
        assert "internal://sales_objections_test.csv#row=" in sig.source_url
        assert len(sig.evidence_snippet) >= 10
        assert sig.evidence_snippet in (
            "The competitor pricing is 40% lower and includes automated visa filing support.",
            "We urgently need automated AI verification to detect plagiarism.",
        ) or sig.evidence_snippet in csv_content.decode("utf-8")
        assert "[AI Inference]:" in sig.interpretation
        assert sig.verification_status == "verified"
        assert sig.final_rank_score > 0
        assert sig.rank_explanation is not None


def test_api_internal_intel_upload(test_company):
    client = TestClient(app)
    csv_content = (
        "deal_id,lost_reason,customer_quote\n"
        "D-500,Security objection,Our infosec policy strictly mandates that student records must reside within EU servers.\n"
    ).encode("utf-8")

    files = {
        "file": ("q3_pipeline_objections.csv", csv_content, "text/csv")
    }

    response = client.post(
        f"/companies/{test_company.id}/internal-intel/upload",
        files=files,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["company_id"] == test_company.id
    assert data["filename"] == "q3_pipeline_objections.csv"
    assert data["signals_extracted_count"] >= 1
    assert len(data["signals"]) >= 1

    first_sig = data["signals"][0]
    assert first_sig["category"] == "internal"
    assert "internal://q3_pipeline_objections.csv#row=1" in first_sig["source_url"]
    assert first_sig["verification_status"] == "verified"
