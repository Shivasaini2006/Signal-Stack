import sys
import logging
import argparse
import traceback
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from sqlmodel import Session, select

from app.core import db
from app.models.entities import Company, JobLog, utcnow
from app.services.crawler import run_crawler_pipeline as crawl_approved_sources
from app.services.analysis import process_all_unprocessed_documents
from app.services.brief import generate_weekly_brief

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("signal_stack.jobs.weekly")


def execute_weekly_pipeline(
    company_id: Optional[int] = None,
    fail_for_test: bool = False,
) -> Dict[str, Any]:
    """
    Weekly autonomous pipeline execution:
    1. Crawl approved sources
    2. Analyze & extract signals
    3. Rank signals in code
    4. Generate weekly strategic brief
    5. Save brief and tactical actions to database

    All wrapped in job_logs with failures captured.
    """
    job_start = utcnow()
    job_log_id: Optional[int] = None

    # 1. Initialize JobLog
    with Session(db.engine, expire_on_commit=False) as session:
        job_log = JobLog(
            job_type="weekly_pipeline",
            status="started",
            started_at=job_start,
        )
        session.add(job_log)
        session.commit()
        session.refresh(job_log)
        job_log_id = job_log.id

    logger.info(f"Started weekly pipeline job #{job_log_id} at {job_start.isoformat()}")

    try:
        # Check for forced failure flag (acceptance testing)
        if fail_for_test:
            raise RuntimeError("Forced failure triggered for weekly pipeline acceptance testing.")

        # Identify target companies
        with Session(db.engine, expire_on_commit=False) as session:
            if company_id:
                target_companies = [session.get(Company, company_id)]
                if not target_companies[0]:
                    raise ValueError(f"Company ID {company_id} not found")
            else:
                target_companies = session.exec(select(Company)).all()

        if not target_companies:
            logger.warning("No companies registered in database. Nothing to crawl.")
            results = {"status": "success", "message": "No companies to monitor.", "companies_processed": 0}
            _finish_job_log(job_log_id, "success", None)
            return results

        company_reports = []
        current_period = utcnow().strftime("%Y-W%U")

        for comp in target_companies:
            logger.info(f"--- Processing weekly pipeline for '{comp.name}' (ID {comp.id}) ---")

            # Step 1: Crawl approved sources
            crawl_res = crawl_approved_sources(company_id=comp.id)
            logger.info(f"Crawl completed: {crawl_res.get('documents_new', 0)} new documents found.")

            # Step 2: Analyze unprocessed documents -> rank in code
            created_signals = process_all_unprocessed_documents(company_id=comp.id)
            logger.info(f"Analysis completed: {len(created_signals)} signals extracted and ranked.")

            # Step 3: Generate weekly brief -> save to DB with actions
            brief, actions, verification = generate_weekly_brief(
                company_id=comp.id,
                period=current_period,
            )
            logger.info(f"Brief #{brief.id} generated with {len(actions)} actions. Verification valid: {verification.is_valid}")

            company_reports.append({
                "company_id": comp.id,
                "company_name": comp.name,
                "documents_new": crawl_res.get("documents_new", 0),
                "signals_created": len(created_signals),
                "brief_id": brief.id,
                "actions_count": len(actions),
                "verification_valid": verification.is_valid,
            })

        summary = {
            "job_log_id": job_log_id,
            "status": "success",
            "period": current_period,
            "companies_processed": len(company_reports),
            "reports": company_reports,
            "finished_at": utcnow().isoformat(),
        }

        _finish_job_log(job_log_id, "success", None)
        logger.info(f"Weekly pipeline job #{job_log_id} completed successfully.")
        return summary

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        logger.error(f"Weekly pipeline job #{job_log_id} failed: {e}")
        _finish_job_log(job_log_id, "failed", str(e))
        return {
            "job_log_id": job_log_id,
            "status": "failed",
            "error": str(e),
            "traceback": error_msg,
            "finished_at": utcnow().isoformat(),
        }


def _finish_job_log(job_id: int, status: str, error: Optional[str]) -> None:
    """Updates JobLog record with termination state."""
    try:
        with Session(db.engine) as session:
            j = session.get(JobLog, job_id)
            if j:
                j.status = status
                j.error = error
                j.finished_at = utcnow()
                session.add(j)
                session.commit()
    except Exception as ex:
        logger.error(f"Failed to update JobLog #{job_id}: {ex}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Signal Stack Weekly Intelligence Pipeline")
    parser.add_argument("--company-id", type=int, default=None, help="Target specific company ID")
    parser.add_argument("--fail-for-test", action="store_true", help="Force failure to test job_logs error capturing")
    args = parser.parse_args()

    result = execute_weekly_pipeline(company_id=args.company_id, fail_for_test=args.fail_for_test)
    if result["status"] == "failed":
        print(f"[FAIL] Weekly pipeline failed: {result['error']}")
        sys.exit(1)
    else:
        print(f"[SUCCESS] Weekly pipeline succeeded: {result}")
        sys.exit(0)
