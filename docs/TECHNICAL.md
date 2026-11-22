# Signal Stack — Technical Architecture & Engineering Specification

> **System Overview**: An autonomous strategic intelligence and competitive signal engine designed for executive leadership, product strategists, and investment committees. It continuously monitors dynamic market environments, extracts verified signals from public web assets, scores their strategic impact, and synthesizes executive briefings without hardcoded company assumptions.

---

## 1. System Architecture

Signal Stack is built upon a **100% Free and Open-Source Software (FOSS)** stack engineered for zero operating expenditure, high resiliency, and strict compliance with ethical web standards.

```
+-------------------------------------------------------------------------------+
|                             Presentation Layer                                |
|  Streamlit Multi-Page Web UI (ui/app.py) & Executive Reports (HTML / Markdown) |
+---------------------------------------+---------------------------------------+
                                        | (REST / Internal Calls)
                                        v
+-------------------------------------------------------------------------------+
|                             Application & API Layer                           |
|       FastAPI Application (app/main.py) with Dedicated Domain Routers:        |
|   /companies  •  /interviews  •  /sources  •  /crawl  •  /signals  •  /briefs |
+---------------------------------------+---------------------------------------+
                                        |
       +--------------------------------+-------------------------------+
       |                                |                               |
       v                                v                               v
+---------------+             +-------------------+             +---------------+
| Autonomous    |             | Data Extraction   |             | Strategic     |
| Discovery     |             | & Crawling Engine |             | Intelligence  |
| (discovery.py)|             | (crawler.py)      |             | & Analysis    |
+-------+-------+             +---------+---------+             +-------+-------+
        |                               |                               |
        |      +------------------------+------------------------+      |
        |      |                                                 |      |
        v      v                                                 v      v
+----------------------------------+          +----------------------------------+
|      Zero-Cost LLM Layer         |          |       Local Storage Engine       |
|  • Primary: Google Gemini API    |          |  • SQLite (SQLModel / SQLAlchemy)|
|  • Fallback: Groq Cloud (Llama3) |          |  • SHA-256 Prompt-Hash Cache     |
|  • Rate Limiter & Backoff Engine |          |  • Transaction Isolation (WAL)   |
+----------------------------------+          +----------------------------------+
```

### 1.1 Architectural Principles
1. **Decoupled Business Logic**: Core capabilities reside in `app/services/`, cleanly separated from API transport (`app/api/`) and database schemas (`app/models/`).
2. **Deterministic Data Layer**: SQLModel wraps SQLAlchemy and Pydantic, enforcing database constraints and typed data models across SQLite.
3. **Zero-Lockin Autonomous Inference**: The LLM abstraction layer in `app/core/llm.py` dynamically routes queries, transparently caches responses, and fails over between Gemini and Groq without user intervention.

---

## 2. Autonomous Source Discovery

A core mandate of Signal Stack is **Zero Company-Specific Hardcoding** (verified via automated codebase grep tests). Competitors, industry portals, and customer forums are discovered dynamically.

```
   Target Company Profile + Interview Answers
                       │
                       ▼
       [LLM Proposes Category Queries]
       ├── Competitor Queries (5-10 direct/substitute rivals)
       ├── Customer Queries (reviews, forums, sentiment)
       └── Market Queries (regulators, policy bodies, news)
                       │
                       ▼
    [Real-Time Discovery Execution]
    ├── DuckDuckGo Web Search (ddgs) with Jitter
    └── Hacker News Algolia Search API
                       │
                       ▼
    [Heuristic & Accessibility Probing]
    ├── Strict robots.txt parser & compliance check
    ├── HTTP HEAD/GET reachability check (HTTP 200)
    ├── Feed / Listing Element Detection (RSS, Atom, <article>)
    └── Content Freshness Check (2024-2026 content timestamps)
                       │
                       ▼
    [Tri-Factor Source Scoring (LLM)]
    ├── Specificity Score (0.0 - 1.0)
    ├── Recency Score (0.0 - 1.0)
    └── Credibility Score (0.0 - 1.0)
                       │
                       ▼
    [Persistence & Deduplication]
    ├── Domain & Path normalizer
    └── Target: 20+ Suggested Sources across 4 Categories
```

### Discovery Categories
- **Competitors**: Identifies 5–10 direct, indirect, and emerging market alternatives with structured profiles detailing market positioning, pricing model, and competitive threat rationale.
- **Customers**: Uncovers organic customer discussions, product reviews, and pain points via Hacker News (Algolia API) and community forums, strictly avoiding unauthorized scraping of closed social APIs.
- **Market**: Indexes statutory regulators, accreditation bodies, trade associations, and regional economic updates.
- **Internal**: Registers placeholder hooks for enterprise pipeline uploads (lost-deal logs, sales call transcripts, win/loss CRM exports).

---

## 3. Politeness & Compliant Web Crawling

The web crawler (`app/services/crawler.py`) operates under strict ethical guidelines to ensure zero disruption to target servers.

```
                        Candidate URL
                              │
                              ▼
                [robots.txt Memory Cache]
                Disallowed? ──► [Skip URL & Log]
                              │ Allowed
                              ▼
            [Per-Domain Leaky-Bucket Rate Limiter]
            (Minimum 1.5s - 2.0s delay between requests)
                              │
                              ▼
                [HTTPX Resilient Fetcher]
          (Honest User-Agent: SignalStackBot/1.0)
                              │
               ┌──────────────┴──────────────┐
               │ Feed?                       │ Raw HTML?
               ▼                             ▼
       [feedparser (RSS/Atom)]      [Trafilatura Text Extractor]
               │                             │
               └──────────────┬──────────────┘
                              │
                              ▼
                    [Content Normalization]
                    ├── SHA-256 Content Hash
                    └── 64-bit SimHash (Cosine Distance)
                              │
          ┌───────────────────┼───────────────────┐
          │ Identical Hash    │ Near-Duplicate    │ Brand New
          ▼                   ▼ (Hamming Dist ≤ 3)▼
    [Skip Ingestion]    [Link Duplicate]    [Persist Document]
```

### Crawl Integrity Features
- **Robots.txt Protocol**: Cached per domain to prevent repetitive round-trips while honoring disallow directives and crawl-delay attributes.
- **Near-Duplicate Detection**: Implements a 64-bit SimHash algorithm on 3-gram word shingles. Documents with a Hamming distance $\le 3$ are clustered to prevent signal flooding.
- **Crash-Resilient Crawl Runs**: Individual URL failures (HTTP 404, 503, timeouts) are recorded in `crawl_runs` without interrupting the broader job batch. Consecutive failures trigger automatic health status downgrades (`ok` $\rightarrow$ `degraded` $\rightarrow$ `failing`).

---

## 4. Tri-Factor Scoring & Algorithmic Ranking

Signal Stack separates LLM confidence from factual credibility. LLMs are never allowed to assign the final strategic rank score; ranking is executed deterministically in Python code.

### 4.1 Tri-Factor Decoupled Scoring

$$\text{Factual Foundation} = f(\text{Source Reliability}, \text{Evidence Strength}, \text{Strategic Relevance})$$

1. **Source Reliability ($R \in [0.0, 1.0]$)**: Intrinsic credibility of the origin domain (e.g., official statutory government portal = 0.95, established trade journal = 0.85, anonymous personal blog = 0.40).
2. **Evidence Strength ($E \in [0.0, 1.0]$)**: Directness and precision of the verbatim excerpt. Quantified statements with empirical metrics score highest.
3. **Strategic Relevance ($S \in [0.0, 1.0]$)**: Business impact on the monitored company's core value proposition, ICP, and market positioning.

### 4.2 Deterministic Ranking Formula

The final rank score is computed in `app/services/ranking.py`:

$$\text{Final Rank Score} = \left[ 0.35 \cdot S + 0.30 \cdot I + 0.20 \cdot U + 0.15 \cdot R \right] \times \text{Decay}(t) \times \text{Novelty}$$

Where:
- **Relevance ($S$)**: Strategic relevance score ($0.0 - 1.0$).
- **Impact ($I$)**: Estimated organizational impact ($0.0 - 1.0$).
- **Urgency ($U$)**: Ordinal urgency weight:
  - Critical = $1.0$
  - High = $0.75$
  - Medium = $0.50$
  - Low = $0.25$
- **Reliability ($R$)**: Domain credibility score ($0.0 - 1.0$).
- **Recency Decay ($\text{Decay}(t)$)**: Half-life exponential decay function:
  $$\text{Decay}(t) = \exp\left(-\frac{\ln(2) \cdot \Delta t}{t_{1/2}}\right), \quad t_{1/2} = 14 \text{ days}$$
  *Signals older than 30 days are clamped to a minimum floor of $0.20$.*
- **Novelty ($\text{Novelty}$)**: Jaccard similarity comparison against historical signals in the database. Near-duplicate developments receive a discount penalty ($0.50 - 0.75$).

Each signal persists a human-readable **Rank Explanation** detailing the exact contribution of each factor.

---

## 5. AI Analysis & Truth-Over-Fabrication Verification

To prevent AI hallucinations, Signal Stack enforces strict evidentiary guarantees.

```
       Crawled Source Document Text
                   │
                   ▼
     [Structured LLM Extraction]
     ├── What Happened & When
     ├── Affected Business Area
     ├── Strategic Opportunity vs Threat
     └── Suggested Tactical Action
                   │
                   ▼
     [Verbatim Substring Code Validator]
     Is `evidence_snippet` a verbatim substring
     of the raw document text?
           │               │
           │ No            │ Yes
           ▼               ▼
     [REJECT SIGNAL]  [Separate AI Interpretation]
     (Prevents AI     (Explicitly tagged:
     Hallucinations)   "AI Inference Layer")
                           │
                           ▼
                      [Persist Signal]
```

### Verification Classifications
- **Verified**: Confirmed by primary/official sources (SEC filings, regulatory registries, press rooms) or cross-verified across two independent crawled sources.
- **Reported**: Documented by third-party industry publications or media coverage.
- **Unverified**: Community discussions, social commentary, or unsourced forum claims.

---

## 6. Job Scheduling & Orchestration

Signal Stack supports autonomous, hands-off operation via dual orchestration architectures:

### 6.1 Local APScheduler Daemon (`scripts/run_scheduler.py`)
- Background scheduler reading dynamic execution frequencies and timezone settings directly from the `system_settings` SQLite table.
- Supports runtime schedule updates without restarting the application process.

### 6.2 GitHub Actions Workflows (`.github/workflows/`)
- **`weekly.yml`**: Scheduled cron trigger (`cron: '0 6 * * 1'`) executing `scripts/run_weekly.py`. Crawls approved sources, analyzes documents, ranks signals, synthesizes Monday strategic briefs, and commits the updated SQLite database to an isolated `data` repository branch.
- **`monthly.yml`**: Scheduled monthly audit (`cron: '0 0 1 * *'`) executing `scripts/run_monthly_audit.py`. Probes source health, detects dead links, evaluates signal hit-rates, flags decaying sources, and logs an `AuditReport`.
- Both workflows support manual execution via `workflow_dispatch`.

---

## 7. Production Reliability & Fault Tolerance

```
+-------------------------------------------------------------------------------+
|                            LLM Resilience Architecture                        |
+-------------------------------------------------------------------------------+
|                                                                               |
|   Prompt Payload ──► [SHA-256 Prompt Hash] ──► [SQLite Cache (llm_cache)]    |
|                                                       │ Hit                   |
|                                                       ▼                       |
|                                                Return 0ms Cached Result       |
|                                                       │ Miss                  |
|                                                       ▼                       |
|                              [Primary: Google Gemini Free Tier]               |
|                                  ├── Rate Throttle (15 RPM)                   |
|                                  ├── Exponential Backoff (3 Retries)          |
|                                  └── Success? ──► Save Cache & Return         |
|                                           │ Failure / HTTP 429                |
|                                           ▼                                   |
|                              [Circuit Breaker / Failover]                     |
|                                           │                                   |
|                                           ▼                                   |
|                              [Fallback: Groq Llama-3 Free Tier]               |
|                                  ├── Exponential Backoff (3 Retries)          |
|                                  └── Success? ──► Save Cache & Return         |
|                                                                               |
+-------------------------------------------------------------------------------+
```

### 7.1 Database Session Isolation
- Database sessions use `expire_on_commit=False` and explicit object expunging (`session.expunge_all()`), eliminating SQLAlchemy `DetachedInstanceError` issues across asynchronous thread boundaries.
- SQLite Write-Ahead Logging (WAL) mode enables concurrent readers while background crawlers write new documents.

### 7.2 Zero-Cost Free Tier Guardrails
- **Prompt Caching**: Persists structured outputs by input hash, preventing redundant LLM calls for unchanged company profiles or static documents.
- **Rate Throttling**: Enforces an automated leaky-bucket delay (4.0s minimum interval) on Gemini calls, guaranteeing 100% adherence to the 15 RPM free-tier quota.
