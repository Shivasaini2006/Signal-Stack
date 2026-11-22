import os
import pytest
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.pool import StaticPool

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app.core import db
from app.core.config import settings
from app.core.llm import reset_llm_metrics
from app.main import app
from app.core.db import get_session

# Use in-memory SQLite engine with StaticPool so all connections share the same memory DB
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


def get_test_session():
    with Session(test_engine) as session:
        yield session


@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch):
    """Ensure in-memory database is initialized and clean for every test."""
    monkeypatch.setattr(db, "engine", test_engine)
    monkeypatch.setattr(settings, "APP_ENV", "test")
    monkeypatch.setattr(settings, "LLM_CACHE_ENABLED", True)

    import app.core.llm as llm_module
    monkeypatch.setattr(llm_module, "engine", test_engine)

    app.dependency_overrides[get_session] = get_test_session

    SQLModel.metadata.create_all(test_engine)
    reset_llm_metrics()
    yield
    SQLModel.metadata.drop_all(test_engine)
    app.dependency_overrides.clear()


@pytest.fixture
def session():
    with Session(test_engine) as session:
        yield session
