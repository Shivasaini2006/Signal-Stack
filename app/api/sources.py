from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlmodel import Session, select

from app.core.db import get_session
from app.models.entities import Company, Source
from app.services.discovery import discover_sources_for_company

router = APIRouter(tags=["sources"])


@router.post("/companies/{company_id}/discovery")
def trigger_source_discovery(company_id: int, session: Session = Depends(get_session)):
    """
    Generate an autonomous Signal Stack across 4 categories (competitors, customers, market, internal):
    - Identifies 5-10 competitors with profiles (positioning, pricing, why they matter)
    - Finds customer discussion sources (forums, HN via Algolia, review feeds)
    - Finds market sources (regulators, industry bodies, policy watchdogs)
    - Establishes internal source placeholders
    - Validates reachability & robots.txt, scores Specific/Recent/Credible, and writes a reason tied to this company
    - Targets 20+ suggested sources
    """
    company = session.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    try:
        result = discover_sources_for_company(company_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/companies/{company_id}/sources", response_model=List[Source])
def list_company_sources(
    company_id: int,
    category: Optional[str] = Query(None, description="Filter by category: competitors|customers|market|internal"),
    status: Optional[str] = Query(None, description="Filter by status: suggested|approved|rejected|dead"),
    session: Session = Depends(get_session),
):
    """Retrieve all discovered sources for a company."""
    company = session.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    query = select(Source).where(Source.company_id == company_id)
    if category:
        query = query.where(Source.category == category)
    if status:
        query = query.where(Source.status == status)

    return session.exec(query).all()


@router.put("/sources/{source_id}/approve", response_model=Source)
def approve_source(source_id: int, session: Session = Depends(get_session)):
    """Approve a suggested source for inclusion in automated crawl monitoring."""
    source = session.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    source.status = "approved"
    session.add(source)
    session.commit()
    session.refresh(source)
    return source


@router.put("/sources/{source_id}/reject", response_model=Source)
def reject_source(source_id: int, session: Session = Depends(get_session)):
    """Reject a suggested source to exclude it from crawling."""
    source = session.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    source.status = "rejected"
    session.add(source)
    session.commit()
    session.refresh(source)
    return source
