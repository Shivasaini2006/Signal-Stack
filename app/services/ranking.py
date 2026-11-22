import math
import re
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

from app.models.entities import utcnow


URGENCY_WEIGHTS = {
    "critical": 1.0,
    "high": 0.8,
    "medium": 0.5,
    "low": 0.2,
}


def calculate_urgency_score(urgency: str) -> float:
    """Normalize urgency label to 0.0 - 1.0 scalar."""
    return URGENCY_WEIGHTS.get((urgency or "").lower().strip(), 0.5)


def calculate_recency_decay(
    published_at: Optional[datetime],
    fetched_at: Optional[datetime] = None,
    half_life_days: float = 14.0,
) -> float:
    """
    Exponential recency decay with a 14-day half-life.
    Fresh items (0-2 days) score 0.90 - 1.0; 30+ day old items decay smoothly.
    """
    event_time = published_at or fetched_at or utcnow()
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=timezone.utc)

    delta_seconds = (utcnow() - event_time).total_seconds()
    delta_days = max(0.0, delta_seconds / 86400.0)

    # Exponential decay: e^(-ln(2) * delta_days / half_life)
    decay = math.exp(-math.log(2) * (delta_days / max(1.0, half_life_days)))
    # Bound between 0.20 and 1.0
    return round(max(0.20, min(1.0, decay)), 3)


def calculate_novelty_score(
    what_happened: str,
    affected_area: Optional[str],
    historical_signals: List[Any],
) -> float:
    """
    Compute novelty score against existing signals:
    - 1.0 if completely novel topic
    - Decays if previous signals describe overlapping developments in the same area.
    """
    if not historical_signals or not what_happened:
        return 1.0

    tokens1 = set(re.findall(r"\w+", what_happened.lower()))
    if not tokens1:
        return 1.0

    max_overlap = 0.0
    for prev in historical_signals:
        prev_text = getattr(prev, "what_happened", "") or ""
        tokens2 = set(re.findall(r"\w+", prev_text.lower()))
        if tokens2:
            jaccard = len(tokens1.intersection(tokens2)) / len(tokens1.union(tokens2))
            if jaccard > max_overlap:
                max_overlap = jaccard

    # If high overlap with a past signal, novelty decreases
    novelty = 1.0 - (max_overlap * 0.75)
    return round(max(0.25, min(1.0, novelty)), 3)


def compute_final_rank_score(
    relevance: float,
    impact: float,
    urgency: str,
    source_credibility: float,
    published_at: Optional[datetime] = None,
    fetched_at: Optional[datetime] = None,
    what_happened: str = "",
    affected_area: Optional[str] = None,
    historical_signals: Optional[List[Any]] = None,
) -> Tuple[float, Dict[str, float], str]:
    """
    Deterministic mathematical ranking engine computed in code (never by LLM):
    1. Relevance (30%)
    2. Impact (25%)
    3. Urgency (20%)
    4. Source Credibility (25%)
    Modulated by:
    - Recency decay multiplier (up to 30% modulation)
    - Novelty multiplier (up to 30% modulation)
    
    Returns:
    (final_rank_score, score_breakdown, rank_explanation)
    """
    # 1. Component normalization
    rel = max(0.0, min(1.0, float(relevance)))
    imp = max(0.0, min(1.0, float(impact)))
    urg_score = calculate_urgency_score(urgency)
    cred = max(0.0, min(1.0, float(source_credibility)))

    rec_decay = calculate_recency_decay(published_at, fetched_at)
    nov_score = calculate_novelty_score(what_happened, affected_area, historical_signals or [])

    # 2. Base weighted sum
    w_rel = 0.30
    w_imp = 0.25
    w_urg = 0.20
    w_cred = 0.25
    base_score = (w_rel * rel) + (w_imp * imp) + (w_urg * urg_score) + (w_cred * cred)

    # 3. Dynamic Modulation (Recency + Novelty)
    time_factor = 0.70 + (0.30 * rec_decay)
    novelty_factor = 0.70 + (0.30 * nov_score)
    final_score = round(max(0.0, min(1.0, base_score * time_factor * novelty_factor)), 3)

    # 4. Score Breakdown
    breakdown = {
        "relevance": round(rel, 3),
        "impact": round(imp, 3),
        "urgency_score": round(urg_score, 3),
        "source_credibility": round(cred, 3),
        "base_score": round(base_score, 3),
        "recency_decay": round(rec_decay, 3),
        "novelty": round(nov_score, 3),
        "final_rank_score": final_score,
    }

    # 5. Human-readable explanation
    tier = "Critical" if final_score >= 0.85 else ("High" if final_score >= 0.70 else ("Medium" if final_score >= 0.50 else "Low"))
    explanation = (
        f"Rank {final_score:.2f} ({tier} Priority) — "
        f"Relevance: {rel:.2f}, Impact: {imp:.2f}, Urgency: {urgency.capitalize()} ({urg_score:.2f}), "
        f"Source Credibility: {cred:.2f}. "
        f"Recency factor: {rec_decay:.2f}, Novelty: {nov_score:.2f}."
    )

    return final_score, breakdown, explanation
