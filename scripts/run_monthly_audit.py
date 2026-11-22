import sys
import logging
import argparse
import traceback
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Set, Tuple
from urllib.parse import urlparse
import httpx
from sqlmodel import Session, select

from app.core.config import settings
from app.core import db
from app.models.entities import Company, Source, Document, Signal, AuditReport, JobLog, utcnow

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("signal_stack.jobs.monthly_audit")


def probe_source_url(url: str, timeout: float = 4.0) -> Tuple[bool, str]:
    """Quick reachability probe for dead URL detection."""
    if url.startswith("internal://"):
        return True, "internal_file"
    try:
        with httpx.Client(
            headers={"User-Agent": settings.CRAWLER_USER_AGENT},
            follow_redirects=True,
            timeout=timeout,
        ) as client:
            resp = client.head(url)
            if resp.status_code >= 400:
                resp = client.get(url)
            is_ok = resp.status_code < 400
            return is_ok, f"HTTP {resp.status_code}"
    except Exception as e:
        return False, f"Connection error: {type(e).__name__}"


def audit_company_sources(
    company: Company,
    session: Session,
) -> Dict[str, Any]:
    """
    Performs comprehensive source audit for a company:
    1. Dead URLs
    2. Duplicate & inactive sources
    3. Declining relevance (hit-rate of signals per document)
    4. Newly discovered / suggested sources
    5. Actionable recommendations (add / remove)
    """
    sources = session.exec(select(Source).where(Source.company_id == company.id)).all()
    documents = session.exec(
        select(Document).join(Source).where(Source.company_id == company.id)
    ).all()
    signals = session.exec(select(Signal).where(Signal.company_id == company.id)).all()

    # Document counts per source
    doc_count_by_source: Dict[int, int] = {}
    for d in documents:
        if d.source_id:
            doc_count_by_source[d.source_id] = doc_count_by_source.get(d.source_id, 0) + 1

    # Signal counts per document & source
    doc_to_source = {d.id: d.source_id for d in documents if d.id}
    sig_count_by_source: Dict[int, int] = {}
    for s in signals:
        if s.document_id and s.document_id in doc_to_source:
            sid = doc_to_source[s.document_id]
            if sid:
                sig_count_by_source[sid] = sig_count_by_source.get(sid, 0) + 1

    dead_sources = []
    duplicate_sources = []
    inactive_sources = []
    declining_sources = []
    high_yield_sources = []
    suggested_candidates = []

    seen_domains: Dict[str, int] = {}
    now = utcnow()
    thirty_days_ago = now - timedelta(days=30)

    for s in sources:
        # Check status
        if s.status == "suggested":
            suggested_candidates.append({
                "source_id": s.id,
                "name": s.name,
                "url": s.url,
                "category": s.category,
                "reason": s.reason,
                "scores": f"S:{s.specific_score:.2f} R:{s.recent_score:.2f} C:{s.credible_score:.2f}",
            })
            continue

        # 1. Dead URL detection
        if s.health in ("failing", "dead") or (s.consecutive_failures or 0) >= 3:
            dead_sources.append({
                "source_id": s.id,
                "name": s.name,
                "url": s.url,
                "reason": f"Consecutive crawl failures: {s.consecutive_failures}. Health: {s.health}.",
            })
        else:
            # Probe live URL
            is_alive, reason = probe_source_url(s.url)
            if not is_alive:
                dead_sources.append({
                    "source_id": s.id,
                    "name": s.name,
                    "url": s.url,
                    "reason": reason,
                })

        # 2. Duplicate detection
        parsed = urlparse(s.url)
        domain_key = f"{parsed.netloc}{parsed.path.rstrip('/')}"
        if domain_key in seen_domains:
            duplicate_sources.append({
                "source_id": s.id,
                "name": s.name,
                "url": s.url,
                "duplicate_of_source_id": seen_domains[domain_key],
            })
        else:
            seen_domains[domain_key] = s.id

        # Inactive detection (>30 days since last crawl or zero docs)
        docs_fetched = doc_count_by_source.get(s.id, 0)
        if s.last_checked and s.last_checked < thirty_days_ago and docs_fetched == 0:
            inactive_sources.append({
                "source_id": s.id,
                "name": s.name,
                "url": s.url,
                "last_checked": s.last_checked.isoformat(),
            })

        # 3. Hit-rate & Declining relevance
        sigs_extracted = sig_count_by_source.get(s.id, 0)
        hit_rate = (sigs_extracted / docs_fetched) if docs_fetched > 0 else 0.0

        if docs_fetched >= 2 and hit_rate < 0.25:
            declining_sources.append({
                "source_id": s.id,
                "name": s.name,
                "url": s.url,
                "documents_fetched": docs_fetched,
                "signals_yielded": sigs_extracted,
                "hit_rate": round(hit_rate, 2),
            })
        elif docs_fetched >= 1 and hit_rate >= 0.5:
            high_yield_sources.append({
                "source_id": s.id,
                "name": s.name,
                "url": s.url,
                "hit_rate": round(hit_rate, 2),
            })

    # 4. Synthesize Recommendations (Add / Remove)
    recommendations_remove = []
    for d in dead_sources:
        recommendations_remove.append(f"Remove dead/unreachable source #{d['source_id']} ({d['url']}): {d['reason']}")
    for dup in duplicate_sources:
        recommendations_remove.append(f"Remove duplicate source #{dup['source_id']} ({dup['url']}) matching source #{dup['duplicate_of_source_id']}")
    for dec in declining_sources:
        if dec["hit_rate"] == 0.0 and dec["documents_fetched"] >= 4:
            recommendations_remove.append(f"Deprecate zero-yield noise source #{dec['source_id']} ({dec['url']}): 0 signals from {dec['documents_fetched']} documents")

    recommendations_add = []
    for cand in suggested_candidates[:5]:
        recommendations_add.append(f"Approve high-scoring suggested source #{cand['source_id']} ({cand['name']} - {cand['url']}) for category '{cand['category']}'")

    if not recommendations_remove:
        recommendations_remove.append("No active sources qualify for removal. Fleet health is stable.")
    if not recommendations_add:
        recommendations_add.append("No pending suggested sources to add. Schedule automated discovery scan.")

    # 5. Format Markdown Audit Report
    month_name = now.strftime("%B %Y")
    report_md = [
        f"# Monthly Source Portfolio Audit — {company.name}\n",
        f"**Audit Period**: `{month_name}` | **Generated**: `{now.strftime('%Y-%m-%d %H:%M UTC')}`\n",
        "## Executive Summary\n",
        f"- **Total Monitored Sources**: `{len(sources)}`\n",
        f"- **Dead / Failing URLs**: `{len(dead_sources)}`\n",
        f"- **Duplicate / Inactive Sources**: `{len(duplicate_sources) + len(inactive_sources)}`\n",
        f"- **Declining Relevance Sources**: `{len(declining_sources)}`\n",
        f"- **High-Yield Sources**: `{len(high_yield_sources)}`\n",
        f"- **Suggested Candidates Pending Review**: `{len(suggested_candidates)}`\n\n",
        "## 1. Dead & Unreachable URLs\n",
    ]

    if dead_sources:
        report_md.append("| Source ID | Name | URL | Issue Detected |\n| :---: | :--- | :--- | :--- |\n")
        for d in dead_sources:
            report_md.append(f"| #{d['source_id']} | {d['name']} | [{d['url']}]({d['url']}) | {d['reason']} |\n")
    else:
        report_md.append("> *All approved sources are fully reachable and healthy.*\n")

    report_md.append("\n## 2. Duplicate & Inactive Sources\n")
    if duplicate_sources:
        report_md.append("### Duplicates Identified\n")
        for dup in duplicate_sources:
            report_md.append(f"- Source #{dup['source_id']} ({dup['url']}) duplicates Source #{dup['duplicate_of_source_id']}\n")
    else:
        report_md.append("> *No duplicate source domains detected.*\n")

    report_md.append("\n## 3. Source Yield & Relevance Hit-Rate\n")
    if declining_sources:
        report_md.append("| Source ID | Name | Fetched Docs | Yielded Signals | Hit-Rate |\n| :---: | :--- | :---: | :---: | :---: |\n")
        for dec in declining_sources:
            report_md.append(f"| #{dec['source_id']} | {dec['name']} | {dec['documents_fetched']} | {dec['signals_yielded']} | `{dec['hit_rate'] * 100:.0f}%` |\n")
    else:
        report_md.append("> *No active sources exhibiting severe signal yield decay.*\n")

    report_md.append("\n## 4. Newly Discovered Candidate Sources\n")
    if suggested_candidates:
        report_md.append("| Candidate ID | Name | Category | Scores | Reason |\n| :---: | :--- | :---: | :---: | :--- |\n")
        for c in suggested_candidates[:5]:
            report_md.append(f"| #{c['source_id']} | [{c['name']}]({c['url']}) | `{c['category']}` | `{c['scores']}` | {c['reason']} |\n")
    else:
        report_md.append("> *No pending suggested sources in review queue.*\n")

    report_md.append("\n## 5. Strategic Source Recommendations\n")
    report_md.append("### Recommended Additions (Approve)\n")
    for ra in recommendations_add:
        report_md.append(f"- [x] {ra}\n")
    report_md.append("\n### Recommended Removals (Prune)\n")
    for rr in recommendations_remove:
        report_md.append(f"- [!] {rr}\n")

    full_report_content = "".join(report_md)

    # Save to database
    audit_report = AuditReport(
        company_id=company.id,
        title=f"Monthly Strategic Source Audit — {company.name} ({month_name})",
        content=full_report_content,
        created_at=now,
    )
    session.add(audit_report)
    session.commit()
    session.refresh(audit_report)

    return {
        "company_id": company.id,
        "company_name": company.name,
        "audit_report_id": audit_report.id,
        "dead_sources_count": len(dead_sources),
        "duplicate_sources_count": len(duplicate_sources),
        "declining_sources_count": len(declining_sources),
        "high_yield_sources_count": len(high_yield_sources),
        "suggested_sources_count": len(suggested_candidates),
        "recommendations_remove": recommendations_remove,
        "recommendations_add": recommendations_add,
        "report_markdown": full_report_content,
    }


def execute_monthly_audit(
    company_id: Optional[int] = None,
    fail_for_test: bool = False,
) -> Dict[str, Any]:
    """
    Monthly autonomous source audit:
    - Detects dead URLs
    - Identifies duplicate/inactive sources
    - Computes signal hit-rates
    - Surfaces new suggested sources
    - Recommends source portfolio changes (add/remove)
    - Persists AuditReport in audit_reports table
    - Wrapped in JobLog with failure capturing
    """
    job_start = utcnow()
    job_log_id: Optional[int] = None

    with Session(db.engine, expire_on_commit=False) as session:
        job_log = JobLog(
            job_type="monthly_audit",
            status="started",
            started_at=job_start,
        )
        session.add(job_log)
        session.commit()
        session.refresh(job_log)
        job_log_id = job_log.id

    logger.info(f"Started monthly audit job #{job_log_id} at {job_start.isoformat()}")

    try:
        if fail_for_test:
            raise RuntimeError("Forced failure triggered for monthly audit acceptance testing.")

        with Session(db.engine, expire_on_commit=False) as session:
            if company_id:
                target_companies = [session.get(Company, company_id)]
                if not target_companies[0]:
                    raise ValueError(f"Company ID {company_id} not found")
            else:
                target_companies = session.exec(select(Company)).all()

            if not target_companies:
                results = {"status": "success", "message": "No companies to audit.", "companies_audited": 0}
                _finish_job_log(job_log_id, "success", None)
                return results

            audit_summaries = []
            for comp in target_companies:
                logger.info(f"Auditing sources for company '{comp.name}' (ID {comp.id})...")
                res = audit_company_sources(comp, session)
                audit_summaries.append(res)

        _finish_job_log(job_log_id, "success", None)
        logger.info(f"Monthly audit job #{job_log_id} completed successfully.")

        return {
            "job_log_id": job_log_id,
            "status": "success",
            "companies_audited": len(audit_summaries),
            "audits": audit_summaries,
            "finished_at": utcnow().isoformat(),
        }

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        logger.error(f"Monthly audit job #{job_log_id} failed: {e}")
        _finish_job_log(job_log_id, "failed", str(e))
        return {
            "job_log_id": job_log_id,
            "status": "failed",
            "error": str(e),
            "traceback": error_msg,
            "finished_at": utcnow().isoformat(),
        }


def _finish_job_log(job_id: int, status: str, error: Optional[str]) -> None:
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
    parser = argparse.ArgumentParser(description="Run Signal Stack Monthly Source Audit")
    parser.add_argument("--company-id", type=int, default=None, help="Target specific company ID")
    parser.add_argument("--fail-for-test", action="store_true", help="Force failure to test job_logs error capturing")
    args = parser.parse_args()

    result = execute_monthly_audit(company_id=args.company_id, fail_for_test=args.fail_for_test)
    if result["status"] == "failed":
        print(f"[FAIL] Monthly audit failed: {result['error']}")
        sys.exit(1)
    else:
        print(f"[SUCCESS] Monthly audit succeeded: {result}")
        sys.exit(0)
