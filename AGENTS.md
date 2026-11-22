# Signal Stack — AGENTS.md (Project Rules & Guidelines)

This document defines the architectural laws, constraints, data integrity standards, and operational guidelines for the **Signal Stack** project. All autonomous agents and developers working on this repository **MUST** strictly adhere to these rules in every task.

---

## 1. Project Mission

**Signal Stack** is an autonomous strategic intelligence and competitive monitoring engine designed for executive leadership, product strategists, and investors. It monitors dynamic industry landscapes, tracks strategic movements, extracts verified signals from public web assets, scores their reliability and impact, and synthesizes executive briefings—without relying on static, hard-coded industry assumptions.

---

## 2. HARD RULES (Non-Negotiable)

1. **Zero Company-Specific Hardcoding**:
   - Never hardcode competitor lists, target source URLs, discovery search queries, interview questions, or company categories.
   - All company profiling, competitor identification, source discovery, and contextual categorization must be dynamically generated via LLM inference combined with real-time web search (`ddgs`).

2. **Zero Fabrication Policy (Truth Over Hallucination)**:
   - Never fabricate, guess, or extrapolate developments, news, or signals.
   - If a search or crawl yields no relevant information, the system must state this explicitly (e.g., `"No recent developments detected in the specified observation window."`).

3. **Verifiable Signal Attribution Schema**:
   - Every recorded signal must capture the following fields:
     - `source_url`: The verified URL where the signal was obtained.
     - `evidence_snippet`: A verbatim text excerpt extracted directly from the crawled source document. No paraphrasing in the evidence field.
     - `published_at`: Original publication timestamp (nullable if not detectable).
     - `discovered_at`: System timestamp when the signal was extracted.
     - `interpretation`: A distinct, clearly separated analytical layer detailing strategic implications, potential impact, and hypotheses.

4. **Tri-Factor Scoring System**:
   - Every signal must evaluate three independent, decoupled scores:
     1. `source_reliability`: Credibility and historical trustworthiness of the source domain/platform (e.g., official SEC filing / press release vs. anonymous blog post).
     2. `evidence_strength`: Directness, clarity, and factual precision of the evidence snippet.
     3. `strategic_relevance`: Business impact and relevance to the target company's market position.
   - *LLM confidence is never treated as proof.* High LLM confidence cannot compensate for a weak or unverified source.

5. **Ethical & Compliant Web Crawling**:
   - Always check and respect `robots.txt` before fetching any URL.
   - Enforce per-domain rate limiting and exponential backoff (minimum 1.5–2.0 second delays per domain).
   - Identify requests using an honest, transparent `User-Agent` (e.g., `SignalStackBot/1.0 (+https://github.com/Shivasaini2006/Signal-Stack)`).
   - Never attempt to bypass authentication walls, CAPTCHAs, or paywalls. If a resource is gated, skip it or record it as restricted.

6. **100% Free & Open-Source Stack**:
   - Core LLM: Google Gemini Free Tier via the official `google-genai` SDK.
   - LLM Fallback: Groq Free Tier (Llama-3 models) for failover upon 429/rate-limit triggers.
   - Web Search: `duckduckgo_search` (`ddgs`) package.
   - All rate limits, tier constraints, and mitigation strategies must be tracked in `docs/COSTS.md`.

7. **Deterministic & Resilient LLM Layer**:
   - All LLM outputs must use structured output enforcing strict JSON schemas (Pydantic / SQLModel).
   - All LLM interactions must implement exponential backoff retry logic.
   - Persistent response caching keyed by SHA-256 prompt hash in SQLite to minimize redundant API calls and prevent token waste.

---

## 3. Technology Stack & Directory Conventions

- **Language**: Python 3.11+
- **Backend API**: FastAPI + Uvicorn
- **Data Layer**: SQLModel + SQLite (`sqlite:///./data/signal_stack.db`)
- **Web Crawling & Parsing**: HTTPX, Trafilatura, Feedparser, PyPDF
- **Web Search**: `duckduckgo_search` (`ddgs`)
- **LLM SDKs**: `google-genai` (Primary), `groq` (Secondary/Fallback)
- **User Interface**: Streamlit
- **Job Orchestration**: APScheduler (local execution), GitHub Actions (automated cron)
- **Testing**: PyTest with mock LLM and network fixtures

### Standard Directory Structure

```
Signal-Stack/
├── .github/
│   └── workflows/          # GitHub Actions cron & CI pipelines
├── app/
│   ├── __init__.py
│   ├── api/                # FastAPI routers & endpoints
│   ├── core/               # DB engine, LLM client, config, rate limiter, cache
│   ├── models/             # SQLModel table & schema definitions
│   └── services/           # Research, crawler, extractor, ranking, briefing
├── data/                   # SQLite database & crawl caches (git-ignored)
├── docs/                   # Architectural docs, COSTS.md, specs
├── scripts/                # CLI runners, seeding, and maintenance scripts
├── tests/                  # Pytest unit and integration test suite
├── ui/                     # Streamlit dashboard pages & components
├── .env.example            # Sample configuration file
├── AGENTS.md               # Project laws and developer instructions
├── requirements.txt        # Pinned Python package dependencies
└── README.md               # Project documentation & onboarding
```

---

## 4. Coding & Architecture Standards

1. **Separation of Concerns**:
   - Database models live in `app/models/`.
   - External API/LLM wrappers live in `app/core/`.
   - Business logic (crawling, scoring, briefing, interviews) lives in `app/services/`.
   - UI code in `ui/` should consume backend services or API endpoints, never embedding direct raw SQL or crawler code.

2. **Testing Protocols**:
   - All features must include comprehensive unit tests in `tests/`.
   - Unit tests must never make live external network calls or burn live LLM tokens. Always use mock fixtures for `google-genai`, `groq`, and `ddgs`.
   - Test suites must pass cleanly before any code is merged or shipped.
