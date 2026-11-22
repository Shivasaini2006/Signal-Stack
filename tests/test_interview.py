import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.models.entities import Company, ProfileField, InterviewTurn
from app.services.interview import (
    generate_next_question,
    answer_or_skip_question,
    edit_interview_answer,
    get_interview_history,
    calculate_semantic_overlap,
)

client = TestClient(app)


def test_two_different_companies_differing_question_sets(session: Session):
    """
    Acceptance Test 1: Run for 2 different companies and show the question sets differ.
    """
    # Company 1: EdTech
    c1 = Company(
        name="EduGlobal Advisory",
        url="https://eduglobal.com",
        domain="eduglobal.com",
        industry="EdTech & Study Abroad",
        description="Global university placement and counseling platform",
    )
    session.add(c1)

    # Company 2: Fintech Payments
    c2 = Company(
        name="PaySwift Rails",
        url="https://payswift.io",
        domain="payswift.io",
        industry="Fintech & Merchant Payments",
        description="Developer-first cross-border payment processing gateway",
    )
    session.add(c2)
    session.commit()
    session.refresh(c1)
    session.refresh(c2)

    # Generate question 1 for each company
    q1_c1 = generate_next_question(c1.id)
    q1_c2 = generate_next_question(c2.id)

    assert q1_c1["question"] != q1_c2["question"]
    # Check that questions are tailored to respective industries
    assert "study abroad" in q1_c1["question"].lower() or "education" in q1_c1["question"].lower() or "consultanc" in q1_c1["question"].lower()
    assert "merchant" in q1_c2["question"].lower() or "payment" in q1_c2["question"].lower() or "gateway" in q1_c2["question"].lower()

    # Answer question 1 with detailed operational context to advance to main question 2
    ans1_c1 = (
        "We provide comprehensive end-to-end overseas university admissions counseling, "
        "including Ivy League test prep, visa assistance, and personalized college essay reviews for students."
    )
    ans1_c2 = (
        "We provide developer-first payment infrastructure with a unified API, offering 1.2% flat processing fees, "
        "multi-currency settlement, and automated chargeback protection for enterprise merchants."
    )
    answer_or_skip_question(c1.id, q1_c1["turn_id"], answer=ans1_c1)
    answer_or_skip_question(c2.id, q1_c2["turn_id"], answer=ans1_c2)

    q2_c1 = generate_next_question(c1.id)
    q2_c2 = generate_next_question(c2.id)

    assert q2_c1["question"] != q2_c2["question"]
    assert q2_c1["turn_index"] == 2
    assert q2_c2["turn_index"] == 2
    assert "student" in q2_c1["question"].lower() or "university" in q2_c1["question"].lower()
    assert "merchant" in q2_c2["question"].lower() or "developer" in q2_c2["question"].lower() or "cohort" in q2_c2["question"].lower()


def test_skip_handling_and_no_repeat(session: Session):
    """
    Acceptance Test 2: Test skip handling (never re-ask) and no-repeat semantic overlap.
    """
    company = Company(
        name="CloudScale AI",
        url="https://cloudscale.ai",
        domain="cloudscale.ai",
        industry="Cloud Infrastructure",
    )
    session.add(company)
    session.commit()
    session.refresh(company)

    # 1. Ask Q1
    q1 = generate_next_question(company.id)
    assert q1["status"] == "pending"
    assert q1["turn_index"] == 1
    theme_1 = q1["theme"]

    # 2. Skip Q1
    skip_res = answer_or_skip_question(company.id, q1["turn_id"], is_skip=True)
    assert skip_res["status"] == "skipped"
    assert skip_res["extracted_fields"] == []

    # 3. Ask Q2 - Must NOT re-ask theme_1 and must NOT repeat question
    q2 = generate_next_question(company.id)
    assert q2["turn_index"] == 2
    assert q2["theme"] != theme_1
    assert q2["question"] != q1["question"]
    assert calculate_semantic_overlap(q2["question"], q1["question"]) < 0.65


def test_follow_up_on_vague_answer(session: Session):
    """
    Test that vague/brief answers trigger an automatic follow-up that does NOT count toward the 10 main questions.
    """
    company = Company(
        name="LogiTrack",
        url="https://logitrack.com",
        domain="logitrack.com",
        industry="Supply Chain Logistics",
    )
    session.add(company)
    session.commit()
    session.refresh(company)

    # Main Question 1
    q1 = generate_next_question(company.id)
    assert q1["is_follow_up"] is False
    assert q1["turn_index"] == 1

    # Answer vaguely with 2 words
    ans_res = answer_or_skip_question(company.id, q1["turn_id"], answer="mostly online")
    assert ans_res["status"] == "answered"

    # Next call should generate a follow-up probing deeper
    q_next = generate_next_question(company.id)
    assert q_next["is_follow_up"] is True
    assert q_next["turn_index"] == 1  # Does NOT increment main question count!
    assert "mostly online" in q_next["question"]


def test_edit_answer_re_extracts_profile_fields(session: Session):
    """
    Test editing an answer updates the turn and re-extracts the profile_fields.
    """
    company = Company(
        name="FinCorp",
        url="https://fincorp.com",
        domain="fincorp.com",
        industry="Fintech",
    )
    session.add(company)
    session.commit()
    session.refresh(company)

    q = generate_next_question(company.id)
    initial_answer = "Our take rate is 2.5% per domestic transaction."
    ans_res = answer_or_skip_question(company.id, q["turn_id"], answer=initial_answer)
    assert ans_res["status"] == "answered"

    # Verify profile field created
    pf = session.exec(select(ProfileField).where(ProfileField.company_id == company.id)).first()
    assert pf is not None
    assert pf.value == initial_answer
    assert pf.source == "interview"

    # Now edit the answer
    updated_answer = "Revised: Our take rate is 1.8% plus 15 cents per transaction."
    edit_res = edit_interview_answer(company.id, q["turn_id"], new_answer=updated_answer)
    assert edit_res["status"] == "answered"

    # Verify profile field was updated
    session.refresh(pf)
    assert pf.value == updated_answer
    assert pf.evidence_snippet == updated_answer[:300]


def test_interview_api_endpoints(session: Session):
    """Test REST API endpoints for interview service."""
    create_resp = client.post(
        "/companies",
        json={"name": "API Enterprise Co", "url": "https://apienterprise.com"},
    )
    company_id = create_resp.json()["id"]

    # 1. POST /companies/{id}/interview/next
    next_resp = client.post(f"/companies/{company_id}/interview/next")
    assert next_resp.status_code == 200
    data = next_resp.json()
    assert "turn_id" in data
    assert data["turn_index"] == 1
    turn_id = data["turn_id"]

    # 2. POST /companies/{id}/interview/answer
    answer_resp = client.post(
        f"/companies/{company_id}/interview/answer",
        json={"turn_id": turn_id, "answer": "We differentiate through our enterprise graph analytics engine."},
    )
    assert answer_resp.status_code == 200
    assert answer_resp.json()["status"] == "answered"

    # 3. PUT /companies/{id}/interview/turns/{turn_id}
    edit_resp = client.put(
        f"/companies/{company_id}/interview/turns/{turn_id}",
        json={"answer": "We differentiate through real-time stream processing with sub-millisecond latencies."},
    )
    assert edit_resp.status_code == 200
    assert edit_resp.json()["status"] == "answered"

    # 4. GET /companies/{id}/interview
    hist_resp = client.get(f"/companies/{company_id}/interview")
    assert hist_resp.status_code == 200
    history = hist_resp.json()
    assert history["company_id"] == company_id
    assert history["main_questions_total"] == 1
    assert history["main_questions_answered"] == 1
    assert len(history["turns"]) == 1
