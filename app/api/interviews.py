from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlmodel import Session

from app.core.db import get_session
from app.models.entities import Company
from app.services.interview import (
    generate_next_question,
    answer_or_skip_question,
    edit_interview_answer,
    get_interview_history,
)

router = APIRouter(prefix="/companies/{company_id}/interview", tags=["interview"])


class AnswerRequest(BaseModel):
    turn_id: int
    answer: Optional[str] = None
    is_skip: bool = False


class EditAnswerRequest(BaseModel):
    answer: str


@router.post("/next")
def get_or_generate_next_question(company_id: int, session: Session = Depends(get_session)):
    """
    Fetch the next interview question:
    - Exactly 10 main questions, asked one at a time.
    - Deeply contextualized for the company's industry and research profile.
    - Automatically injects follow-ups for brief/vague answers (which don't count toward the 10).
    - Prevents question repetition.
    """
    company = session.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    try:
        return generate_next_question(company_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/answer")
def submit_answer_or_skip(
    company_id: int,
    payload: AnswerRequest,
    session: Session = Depends(get_session),
):
    """
    Submit an answer or skip for an interview turn:
    - If skipped: marked as 'skipped' and the theme is never re-asked.
    - If answered: automatically extracts structured intelligence into profile_fields.
    """
    company = session.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    try:
        return answer_or_skip_question(
            company_id=company_id,
            turn_id=payload.turn_id,
            answer=payload.answer,
            is_skip=payload.is_skip,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/turns/{turn_id}")
def edit_turn_answer(
    company_id: int,
    turn_id: int,
    payload: EditAnswerRequest,
    session: Session = Depends(get_session),
):
    """
    Edit an existing answer, which updates the turn and re-extracts profile_fields.
    """
    company = session.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    try:
        return edit_interview_answer(
            company_id=company_id,
            turn_id=turn_id,
            new_answer=payload.answer,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("")
def get_interview_progress(company_id: int, session: Session = Depends(get_session)):
    """
    Retrieve full interview memory, all turns, answers, and completion status.
    """
    company = session.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    return get_interview_history(company_id)
