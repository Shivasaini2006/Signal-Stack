import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.main import app
from app.core import db
from app.models.entities import Company, Source, Document, Signal, JobLog, AuditReport, SystemSetting, utcnow
from scripts.run_weekly import execute_weekly_pipeline
from scripts.run_monthly_audit import execute_monthly_audit
from scripts.run_scheduler import create_scheduler, parse_schedule_string


@pytest.fixture
def mock_job_company():
    with Session(db.engine, expire_on_commit=False) as session:
        comp = Company(
            name="Autonomous EdTech Inc",
            domain="autonedtech.example.com",
            url="https://autonedtech.example.com",
            industry="Education",
        )
        session.add(comp)
        session.commit()
        session.refresh(comp)

        source = Source(
            company_id=comp.id,
            category="competitors",
            name="EdCompetitor News",
            url="https://edcompetitor.example.com/rss",
            reason="Primary competitor news feed.",
            specific_score=0.9,
            recent_score=0.9,
            credible_score=0.9,
            status="approved",
            health="ok",
        )
        session.add(source)
        session.commit()
        session.refresh(source)

        session.expunge_all()
        return comp, source


def test_weekly_pipeline_forced_failure_acceptance():
    """
    Acceptance test requirement:
    A forced failure must show up in job_logs with status='failed' and captured error.
    """
    result = execute_weekly_pipeline(fail_for_test=True)
    assert result["status"] == "failed"
    assert "Forced failure" in result["error"]
    job_log_id = result["job_log_id"]

    # Verify directly from SQLite database
    with Session(db.engine) as session:
        log = session.get(JobLog, job_log_id)
        assert log is not None
        assert log.job_type == "weekly_pipeline"
        assert log.status == "failed"
        assert "Forced failure" in (log.error or "")
        assert log.finished_at is not None


def test_monthly_audit_forced_failure_acceptance():
    """
    Acceptance test requirement:
    A forced failure must show up in job_logs with status='failed' and captured error.
    """
    result = execute_monthly_audit(fail_for_test=True)
    assert result["status"] == "failed"
    assert "Forced failure" in result["error"]
    job_log_id = result["job_log_id"]

    with Session(db.engine) as session:
        log = session.get(JobLog, job_log_id)
        assert log is not None
        assert log.job_type == "monthly_audit"
        assert log.status == "failed"
        assert "Forced failure" in (log.error or "")
        assert log.finished_at is not None


def test_monthly_audit_execution_and_report_generation(mock_job_company):
    company, source = mock_job_company

    result = execute_monthly_audit(company_id=company.id, fail_for_test=False)
    assert result["status"] == "success"
    assert result["companies_audited"] == 1
    audit_data = result["audits"][0]
    assert audit_data["company_id"] == company.id
    assert "recommendations_remove" in audit_data
    assert "recommendations_add" in audit_data
    report_id = audit_data["audit_report_id"]

    # Verify audit_report persisted in database
    with Session(db.engine) as session:
        report = session.get(AuditReport, report_id)
        assert report is not None
        assert report.company_id == company.id
        assert "Monthly Strategic Source Audit" in report.title
        assert "Dead & Unreachable URLs" in report.content
        assert "Strategic Source Recommendations" in report.content

        # Verify job_log
        jlog = session.get(JobLog, result["job_log_id"])
        assert jlog.status == "success"
        assert jlog.error is None


def test_scheduler_reads_settings_table():
    # Update settings table
    db.set_setting("timezone", "UTC", "Global UTC scheduler timezone")
    db.set_setting("weekly_schedule", "mon 06:00", "Every Monday at 06:00")
    db.set_setting("monthly_schedule", "1 06:00", "Day 1 of month at 06:00")

    # Verify reading
    assert db.get_setting("timezone") == "UTC"
    assert db.get_setting("weekly_schedule") == "mon 06:00"

    # Instantiate scheduler
    scheduler = create_scheduler(is_background=True)
    job_ids = [j.id for j in scheduler.get_jobs()]
    assert "weekly_intelligence_pipeline" in job_ids
    assert "monthly_source_audit" in job_ids


def test_jobs_api_endpoints():
    client = TestClient(app)

    # 1. Trigger forced failure via API
    resp_weekly = client.post("/jobs/weekly/trigger?fail_for_test=true")
    assert resp_weekly.status_code == 200
    data_weekly = resp_weekly.json()
    assert data_weekly["status"] == "failed"
    assert "Forced failure" in data_weekly["error"]

    resp_monthly = client.post("/jobs/monthly-audit/trigger?fail_for_test=true")
    assert resp_monthly.status_code == 200
    data_monthly = resp_monthly.json()
    assert data_monthly["status"] == "failed"
    assert "Forced failure" in data_monthly["error"]

    # 2. Get Job Logs list
    logs_resp = client.get("/jobs/logs")
    assert logs_resp.status_code == 200
    logs = logs_resp.json()
    assert len(logs) >= 2
    # Ensure failure is recorded in API view
    failed_logs = [l for l in logs if l["status"] == "failed"]
    assert len(failed_logs) >= 2

    # 3. Get single Job Log
    first_id = logs[0]["id"]
    single_log = client.get(f"/jobs/logs/{first_id}").json()
    assert single_log["id"] == first_id

    # 4. Get Audit Reports list
    audits_resp = client.get("/jobs/audit-reports")
    assert audits_resp.status_code == 200
    assert isinstance(audits_resp.json(), list)
