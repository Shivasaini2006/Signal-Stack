from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlmodel import Session, select

from app.core import db
from app.models.entities import JobLog, AuditReport, Company
from scripts.run_weekly import execute_weekly_pipeline
from scripts.run_monthly_audit import execute_monthly_audit

router = APIRouter(prefix="/jobs", tags=["Job Orchestration & Logs"])


@router.post("/weekly/trigger")
def trigger_weekly_pipeline(
    company_id: Optional[int] = Query(None, description="Optional target company ID"),
    fail_for_test: bool = Query(False, description="Simulate forced failure for test acceptance"),
) -> Dict[str, Any]:
    """
    Manually trigger the Weekly Autonomous Pipeline:
    Crawl approved sources -> Analyse -> Rank -> Generate Brief -> Save.
    All execution metrics and errors are logged to job_logs.
    """
    result = execute_weekly_pipeline(
        company_id=company_id,
        fail_for_test=fail_for_test,
    )
    return result


@router.post("/monthly-audit/trigger")
def trigger_monthly_audit(
    company_id: Optional[int] = Query(None, description="Optional target company ID"),
    fail_for_test: bool = Query(False, description="Simulate forced failure for test acceptance"),
) -> Dict[str, Any]:
    """
    Manually trigger the Monthly Source Audit:
    Detect dead URLs, duplicate/inactive sources, declining relevance, newly discovered sources,
    recommend add/remove, and save AuditReport.
    All execution metrics and errors are logged to job_logs.
    """
    result = execute_monthly_audit(
        company_id=company_id,
        fail_for_test=fail_for_test,
    )
    return result


@router.get("/logs")
def list_job_logs(
    limit: int = Query(50, ge=1, le=200),
    job_type: Optional[str] = Query(None, description="'weekly_pipeline' | 'monthly_audit'"),
    session: Session = Depends(db.get_session),
) -> List[Dict[str, Any]]:
    """
    Retrieve audit history of background job executions.
    """
    stmt = select(JobLog).order_by(JobLog.started_at.desc()).limit(limit)
    if job_type:
        stmt = stmt.where(JobLog.job_type == job_type)

    logs = session.exec(stmt).all()
    return [
        {
            "id": j.id,
            "job_type": j.job_type,
            "status": j.status,
            "error": j.error,
            "started_at": j.started_at.isoformat() if j.started_at else None,
            "finished_at": j.finished_at.isoformat() if j.finished_at else None,
        }
        for j in logs
    ]


@router.get("/logs/{job_id}")
def get_job_log(
    job_id: int,
    session: Session = Depends(db.get_session),
) -> Dict[str, Any]:
    """
    Retrieve specific JobLog record.
    """
    log = session.get(JobLog, job_id)
    if not log:
        raise HTTPException(status_code=404, detail=f"JobLog #{job_id} not found")

    return {
        "id": log.id,
        "job_type": log.job_type,
        "status": log.status,
        "error": log.error,
        "started_at": log.started_at.isoformat() if log.started_at else None,
        "finished_at": log.finished_at.isoformat() if log.finished_at else None,
    }


@router.get("/audit-reports")
def list_audit_reports(
    company_id: Optional[int] = None,
    session: Session = Depends(db.get_session),
) -> List[Dict[str, Any]]:
    """
    List monthly source portfolio audit reports.
    """
    stmt = select(AuditReport).order_by(AuditReport.created_at.desc())
    if company_id:
        stmt = stmt.where(AuditReport.company_id == company_id)

    reports = session.exec(stmt).all()
    return [
        {
            "id": r.id,
            "company_id": r.company_id,
            "title": r.title,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "preview": r.content[:300] + "...",
        }
        for r in reports
    ]


@router.get("/audit-reports/{report_id}")
def get_audit_report(
    report_id: int,
    session: Session = Depends(db.get_session),
) -> Dict[str, Any]:
    """
    Retrieve full content of a monthly source portfolio audit report.
    """
    report = session.get(AuditReport, report_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"AuditReport #{report_id} not found")

    return {
        "id": report.id,
        "company_id": report.company_id,
        "title": report.title,
        "content": report.content,
        "created_at": report.created_at.isoformat() if report.created_at else None,
    }
