from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlmodel import Session, select

from app.core import db
from app.models.entities import Company, Brief, Action
from app.services.brief import generate_weekly_brief, verify_brief_claims

router = APIRouter(tags=["Executive Briefing"])


@router.post("/companies/{company_id}/briefs/generate")
def create_brief_endpoint(
    company_id: int,
    period: str = Query("current_week", description="Observation period identifier e.g. current_week, 2026-W47"),
    session: Session = Depends(db.get_session),
) -> Dict[str, Any]:
    """
    Generates and persists an executive strategic briefing with the exact 10 sections in order.
    Saves generated actions to the actions table.
    Performs post-check verification that every claim has a signal_id and resolvable URL.
    """
    company = session.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail=f"Company with ID {company_id} not found")

    try:
        brief, actions, verification = generate_weekly_brief(
            company_id=company_id,
            period=period,
        )

        return {
            "brief_id": brief.id,
            "company_id": brief.company_id,
            "period": brief.period,
            "created_at": brief.created_at.isoformat(),
            "actions_count": len(actions),
            "actions": [
                {
                    "id": a.id,
                    "text": a.text,
                    "reason": a.reason,
                    "owner": a.owner,
                    "priority": a.priority,
                    "status": a.status,
                }
                for a in actions
            ],
            "verification": verification.model_dump(),
            "markdown": brief.markdown,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate executive brief: {e}")


@router.get("/companies/{company_id}/briefs")
def list_company_briefs(
    company_id: int,
    session: Session = Depends(db.get_session),
) -> List[Dict[str, Any]]:
    """
    List all generated briefings for a company.
    """
    company = session.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail=f"Company with ID {company_id} not found")

    stmt = select(Brief).where(Brief.company_id == company_id).order_by(Brief.created_at.desc())
    briefs = session.exec(stmt).all()

    return [
        {
            "id": b.id,
            "company_id": b.company_id,
            "period": b.period,
            "created_at": b.created_at.isoformat(),
            "preview": b.markdown[:200] + "...",
        }
        for b in briefs
    ]


@router.get("/briefs/{brief_id}")
def get_brief_details(
    brief_id: int,
    session: Session = Depends(db.get_session),
) -> Dict[str, Any]:
    """
    Retrieve full briefing content and associated actionable recommendations.
    """
    brief = session.get(Brief, brief_id)
    if not brief:
        raise HTTPException(status_code=404, detail=f"Brief with ID {brief_id} not found")

    actions = session.exec(select(Action).where(Action.brief_id == brief_id)).all()

    return {
        "id": brief.id,
        "company_id": brief.company_id,
        "period": brief.period,
        "created_at": brief.created_at.isoformat(),
        "markdown": brief.markdown,
        "actions": [
            {
                "id": a.id,
                "text": a.text,
                "reason": a.reason,
                "owner": a.owner,
                "priority": a.priority,
                "status": a.status,
            }
            for a in actions
        ],
    }


@router.get("/briefs/{brief_id}/html")
def get_brief_html_view(
    brief_id: int,
    session: Session = Depends(db.get_session),
):
    """
    Returns standalone, email-ready HTML representation of the executive brief with inline CSS.
    """
    brief = session.get(Brief, brief_id)
    if not brief:
        raise HTTPException(status_code=404, detail=f"Brief with ID {brief_id} not found")

    return Response(content=brief.html, media_type="text/html")
