import sqlite3
import os
from sqlmodel import SQLModel, create_engine
from app.core.db import init_db
import app.models  # registers models


def test_db_init_creates_all_tables(tmp_path):
    test_db_file = tmp_path / "test_signal_stack.db"
    test_db_url = f"sqlite:///{test_db_file}"
    engine = create_engine(test_db_url)

    init_db(engine)

    conn = sqlite3.connect(test_db_file)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()

    expected_tables = {
        "companies",
        "profile_fields",
        "interview_turns",
        "sources",
        "crawl_runs",
        "documents",
        "signals",
        "briefs",
        "actions",
        "audit_reports",
        "job_logs",
        "llm_cache",
    }

    assert expected_tables.issubset(set(tables)), f"Missing tables: {expected_tables - set(tables)}"
