from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlmodel import Session, select

from app.core.db import get_session
from app.models.entities import Company, Signal
from app.services.analysis import (
    analyze_document_and_create_signal,
    process_all_unprocessed_documents,
)

router = APIRouter(tags=["signals"])


@router.post("/companies/{company_id}/signals/analyze", response_model=List[Signal])
def analyze_company_documents(company_id: int, session: Session = Depends(get_session)):
    """
    Analyze newly crawled documents for a company:
    - Extracts strategic signals with verbatim evidence snippets (strictly validated in code)
    - Labels AI inference layer explicitly
    - Assigns verification status (verified, reported, unverified)
    - Computes mathematical final_rank_score in code (relevance, impact, urgency, credibility, recency, novelty)
    - Returns ranked signals with explanations
    """
    company = session.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    try:
        signals = process_all_unprocessed_documents(company_id)
        return signals
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/companies/{company_id}/signals", response_model=List[Signal])
def list_company_signals(
    company_id: int,
    category: Optional[str] = Query(None, description="Filter by category: competitors|customers|market|internal"),
    type: Optional[str] = Query(None, description="'opportunity' | 'threat' | 'neutral'"),
    urgency: Optional[str] = Query(None, description="'low' | 'medium' | 'high' | 'critical'"),
    verification_status: Optional[str] = Query(None, description="'verified' | 'reported' | 'unverified'"),
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    """
    List extracted strategic signals for a company, ranked by final_rank_score descending.
    """
    company = session.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    query = (
        select(Signal)
        .where(Signal.company_id == company_id)
        .order_by(Signal.final_rank_score.desc())  # type: ignore
        .limit(limit)
    )

    if category:
        query = query.where(Signal.category == category)
    if type:
        query = query.where(Signal.type == type)
    if urgency:
        query = query.where(Signal.urgency == urgency)
    if verification_status:
        query = query.where(Signal.verification_status == verification_status)

    return session.exec(query).all()


@router.get("/signals/{signal_id}", response_model=Signal)
def get_signal_details(signal_id: int, session: Session = Depends(get_session)):
    """Get full details of a specific signal including score breakdown and explanation."""
    signal = session.get(Signal, signal_id)
    if not signal:
        raise HTTPException(status_code=404, detail="Signal not found")
    return signal
