from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.db import get_session
from app.models.entities import CrawlRun
from app.services.crawler import run_crawler_pipeline

router = APIRouter(prefix="/crawl", tags=["crawler"])


class CrawlRunRequest(BaseModel):
    company_id: Optional[int] = None


class CrawlRunResponse(BaseModel):
    crawl_run_id: int
    status: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    sources_crawled: int
    documents_found: int
    documents_new: int
    documents_changed: int
    documents_unchanged: int
    per_source_report: List[Dict[str, Any]]


@router.post("/run", response_model=CrawlRunResponse)
def execute_crawl_run(payload: Optional[CrawlRunRequest] = None):
    """
    Execute autonomous web crawl across approved sources:
    - Checks cached robots.txt
    - Enforces per-domain rate limiting
    - Detects new vs changed vs unchanged documents via content_hash
    - Dedupes near-duplicates via SimHash
    - Records crawl runs with per-source status and error isolation
    - Updates source health (consecutive_failures, last_success)
    """
    company_id = payload.company_id if payload else None
    try:
        return run_crawler_pipeline(company_id=company_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/runs", response_model=List[CrawlRun])
def list_crawl_runs(session: Session = Depends(get_session)):
    """List recent crawl executions and metrics."""
    return session.exec(select(CrawlRun).order_by(CrawlRun.id.desc())).all()  # type: ignore


@router.get("/runs/{run_id}", response_model=CrawlRun)
def get_crawl_run(run_id: int, session: Session = Depends(get_session)):
    """Get details of a specific crawl run."""
    run = session.get(CrawlRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Crawl run not found")
    return run
