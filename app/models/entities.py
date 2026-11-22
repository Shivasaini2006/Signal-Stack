from datetime import datetime, timezone
from typing import Optional
from sqlmodel import SQLModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Company(SQLModel, table=True):
    __tablename__ = "companies"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    url: Optional[str] = None
    domain: Optional[str] = Field(default=None, index=True)
    industry: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ProfileField(SQLModel, table=True):
    __tablename__ = "profile_fields"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    key: str = Field(index=True)
    value: str
    source: str = Field(description="'research' | 'interview' | 'manual'")
    is_verified_fact: bool = Field(default=False)
    source_url: Optional[str] = None
    evidence_snippet: Optional[str] = None
    updated_at: datetime = Field(default_factory=utcnow)


class InterviewTurn(SQLModel, table=True):
    __tablename__ = "interview_turns"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    turn_index: int = Field(default=0)
    question: str
    answer: Optional[str] = None
    status: str = Field(default="pending", description="'pending' | 'answered' | 'skipped'")
    is_follow_up: bool = Field(default=False)
    parent_turn_id: Optional[int] = Field(default=None, foreign_key="interview_turns.id")
    theme: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Source(SQLModel, table=True):
    __tablename__ = "sources"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: Optional[int] = Field(default=None, foreign_key="companies.id", index=True)
    category: str = Field(description="'customers' | 'competitors' | 'market' | 'internal'", index=True)
    url: str = Field(index=True)
    name: str
    reason: Optional[str] = None
    specific_score: float = Field(default=0.0)
    recent_score: float = Field(default=0.0)
    credible_score: float = Field(default=0.0)
    status: str = Field(
        default="suggested",
        description="'suggested' | 'approved' | 'rejected' | 'dead'",
        index=True,
    )
    health: str = Field(default="ok", description="'ok' | 'warning' | 'failing' | 'unknown'")
    consecutive_failures: int = Field(default=0)
    last_success: Optional[datetime] = None
    last_error: Optional[str] = None
    last_checked: Optional[datetime] = None


class CrawlRun(SQLModel, table=True):
    __tablename__ = "crawl_runs"

    id: Optional[int] = Field(default=None, primary_key=True)
    status: str = Field(default="running", description="'running' | 'completed' | 'failed'")
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: Optional[datetime] = None
    sources_crawled: int = Field(default=0)
    documents_found: int = Field(default=0)
    documents_new: int = Field(default=0)
    documents_changed: int = Field(default=0)
    documents_unchanged: int = Field(default=0)
    error: Optional[str] = None


class Document(SQLModel, table=True):
    __tablename__ = "documents"

    id: Optional[int] = Field(default=None, primary_key=True)
    url: str = Field(index=True)
    content_hash: str = Field(index=True)
    title: Optional[str] = None
    text: str
    simhash: Optional[str] = Field(default=None, index=True)
    published_at: Optional[datetime] = None
    fetched_at: datetime = Field(default_factory=utcnow)
    source_id: Optional[int] = Field(default=None, foreign_key="sources.id", index=True)
    crawl_run_id: Optional[int] = Field(default=None, foreign_key="crawl_runs.id", index=True)


class Signal(SQLModel, table=True):
    __tablename__ = "signals"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: Optional[int] = Field(default=None, foreign_key="companies.id", index=True)
    document_id: Optional[int] = Field(default=None, foreign_key="documents.id", index=True)
    category: str = Field(index=True)
    what_happened: str
    evidence_snippet: str  # Verbatim from crawled page
    interpretation: str    # Analytical layer clearly labelled as AI inference
    affected_area: Optional[str] = None
    type: str = Field(default="neutral", description="'opportunity' | 'threat' | 'neutral'", index=True)
    urgency: str = Field(default="medium", description="'low' | 'medium' | 'high' | 'critical'")
    why_it_matters: Optional[str] = None
    suggested_action: Optional[str] = None
    source_reliability: float = Field(default=0.0)  # Tri-Factor decoupled score 1
    evidence_strength: float = Field(default=0.0)   # Tri-Factor decoupled score 2
    strategic_relevance: float = Field(default=0.0) # Tri-Factor decoupled score 3
    final_rank_score: float = Field(default=0.0, index=True)
    rank_explanation: Optional[str] = None
    score_breakdown: Optional[str] = None  # JSON serialization of ranking components
    verification_status: str = Field(
        default="unverified",
        description="'unverified' | 'reported' | 'verified'",
        index=True,
    )
    duplicate_of: Optional[int] = Field(default=None, foreign_key="signals.id")
    source_url: Optional[str] = None
    published_at: Optional[datetime] = None
    discovered_at: datetime = Field(default_factory=utcnow)


class Brief(SQLModel, table=True):
    __tablename__ = "briefs"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: Optional[int] = Field(default=None, foreign_key="companies.id", index=True)
    markdown: str
    html: str
    period: str = Field(index=True)
    created_at: datetime = Field(default_factory=utcnow)


class Action(SQLModel, table=True):
    __tablename__ = "actions"

    id: Optional[int] = Field(default=None, primary_key=True)
    brief_id: Optional[int] = Field(default=None, foreign_key="briefs.id", index=True)
    text: str
    reason: Optional[str] = Field(default=None)
    owner: Optional[str] = None
    priority: str = Field(default="medium", description="'low' | 'medium' | 'high'")
    status: str = Field(
        default="open",
        description="'open' | 'in_progress' | 'completed' | 'dismissed'",
        index=True,
    )


class AuditReport(SQLModel, table=True):
    __tablename__ = "audit_reports"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: Optional[int] = Field(default=None, foreign_key="companies.id", index=True)
    title: str
    content: str
    created_at: datetime = Field(default_factory=utcnow)


class JobLog(SQLModel, table=True):
    __tablename__ = "job_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    job_type: str = Field(index=True)
    status: str = Field(description="'started' | 'success' | 'failed'", index=True)
    error: Optional[str] = None
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: Optional[datetime] = None


class SystemSetting(SQLModel, table=True):
    __tablename__ = "system_settings"

    key: str = Field(primary_key=True)
    value: str
    description: Optional[str] = None
    updated_at: datetime = Field(default_factory=utcnow)


class LLMCache(SQLModel, table=True):
    __tablename__ = "llm_cache"

    id: Optional[int] = Field(default=None, primary_key=True)
    prompt_hash: str = Field(unique=True, index=True)
    provider: str
    model: str
    response_json: str
    created_at: datetime = Field(default_factory=utcnow)
