import pytest
from pydantic import BaseModel
from unittest.mock import MagicMock
from app.core import llm
from app.core.llm import generate_json, get_llm_metrics, reset_llm_metrics


class AnalysisSchema(BaseModel):
    summary: str
    impact_score: float
    is_urgent: bool


def test_llm_primary_success(monkeypatch):
    """Test successful primary (Gemini) JSON response generation."""
    reset_llm_metrics()

    # Mock _call_gemini to return valid structured data without external network calls
    mock_response = {
        "summary": "Competitor introduced new real-time pipeline",
        "impact_score": 0.85,
        "is_urgent": True,
    }
    monkeypatch.setattr(llm.llm_client, "_call_gemini", MagicMock(return_value=mock_response))

    result = generate_json(
        prompt="Analyze competitor press release",
        schema=AnalysisSchema,
        system_prompt="Extract competitive movement",
    )

    assert result["summary"] == "Competitor introduced new real-time pipeline"
    assert result["impact_score"] == 0.85
    assert result["is_urgent"] is True

    metrics = get_llm_metrics()
    assert metrics["total_calls"] == 1
    assert metrics["cache_hits"] == 0
    assert metrics["fallback_triggers"] == 0


def test_llm_persistent_cache_hit(monkeypatch):
    """Test that subsequent identical prompt calls return from SQLite cache with zero API calls."""
    reset_llm_metrics()

    mock_response = {
        "summary": "Cached result",
        "impact_score": 0.5,
        "is_urgent": False,
    }
    gemini_mock = MagicMock(return_value=mock_response)
    monkeypatch.setattr(llm.llm_client, "_call_gemini", gemini_mock)

    # First call - populates cache
    res1 = generate_json(
        prompt="Identical prompt test",
        schema=AnalysisSchema,
    )
    assert res1["summary"] == "Cached result"
    assert gemini_mock.call_count == 1

    # Second call - must hit cache
    res2 = generate_json(
        prompt="Identical prompt test",
        schema=AnalysisSchema,
    )
    assert res2["summary"] == "Cached result"
    assert gemini_mock.call_count == 1  # Not called again!

    metrics = get_llm_metrics()
    assert metrics["total_calls"] == 2
    assert metrics["cache_hits"] == 1


def test_llm_fallback_to_groq(monkeypatch):
    """Test automatic failover to Groq when Gemini throws an exception / rate limit."""
    reset_llm_metrics()

    # Gemini raises error
    gemini_mock = MagicMock(side_effect=RuntimeError("Gemini 429 Resource Exhausted"))
    monkeypatch.setattr(llm.llm_client, "_call_gemini", gemini_mock)

    # Groq returns successfully
    groq_response = {
        "summary": "Recovered via Groq fallback",
        "impact_score": 0.72,
        "is_urgent": False,
    }
    groq_mock = MagicMock(return_value=groq_response)
    monkeypatch.setattr(llm.llm_client, "_call_groq", groq_mock)

    result = generate_json(
        prompt="High priority signal extraction",
        schema=AnalysisSchema,
    )

    assert result["summary"] == "Recovered via Groq fallback"
    assert groq_mock.call_count == 1

    metrics = get_llm_metrics()
    assert metrics["fallback_triggers"] == 1


def test_llm_retry_on_transient_error(monkeypatch):
    """Test exponential backoff retry logic on transient errors."""
    reset_llm_metrics()

    # Fail once, then succeed
    success_response = {
        "summary": "Success after retry",
        "impact_score": 0.6,
        "is_urgent": False,
    }
    gemini_mock = MagicMock(
        side_effect=[
            ConnectionResetError("Transient network glitch"),
            success_response,
        ]
    )
    monkeypatch.setattr(llm.llm_client, "_call_gemini", gemini_mock)

    result = generate_json(
        prompt="Retry resilience verification",
        schema=AnalysisSchema,
    )

    assert result["summary"] == "Success after retry"
    assert gemini_mock.call_count == 2
