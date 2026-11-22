# Signal Stack 📡

> **Autonomous Strategic Intelligence & Competitive Signal Engine**  
> *Built for AI Engineer Intern Assignment*

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)
[![SQLModel](https://img.shields.io/badge/SQLModel-SQLite-orange.svg)](https://sqlmodel.tiangolo.com)
[![Streamlit](https://img.shields.io/badge/Streamlit-UI-FF4B4B.svg)](https://streamlit.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## 🎯 Overview

**Signal Stack** is an end-to-end autonomous competitive intelligence engine. It continuously tracks competitor actions, regulatory shifts, market disruptions, and product updates for any company without hard-coded assumptions or vendor lock-in.

### Non-Negotiable Core Tenets (from `AGENTS.md`)
- **Zero Hardcoding**: Dynamically discovers competitors, sources, queries, and interview turns per company via real-time web search and structured LLM queries.
- **Strict Evidence Attribution**: Every detected signal retains its raw `source_url`, verbatim `evidence_snippet`, verified dates, and decoupled `interpretation`.
- **Tri-Factor Scoring**: Decoupled scores for `source_reliability`, `evidence_strength`, and `strategic_relevance`. LLM confidence is never treated as proof.
- **Ethical Crawling**: Checks `robots.txt`, enforces rate limits, transmits an honest `User-Agent`, and never bypasses authentication/paywalls.
- **100% Free / Open-Source Tech**: Powered by Google Gemini Free Tier (`google-genai`), Groq fallback (`groq`), DuckDuckGo (`ddgs`), SQLite, and GitHub Actions cron.

---

## 🏗️ Architecture & Project Structure

```
Signal-Stack/
├── .github/
│   └── workflows/          # GitHub Actions cron schedules
├── app/
│   ├── api/                # FastAPI endpoints & REST routes
│   ├── core/               # DB engine, LLM abstraction, rate limiter, cache
│   ├── models/             # SQLModel database tables and schemas
│   └── services/           # Profiling, crawler, extractor, ranking, briefing
├── data/                   # SQLite database file & crawl store
├── docs/                   # Architectural guides, COSTS.md, specs
├── scripts/                # Standalone CLI tools & cron entrypoints
├── tests/                  # Pytest automated test suite
├── ui/                     # Streamlit web application
├── .env.example            # Environment configuration template
├── AGENTS.md               # Core project rules & agent commandments
├── requirements.txt        # Pinned dependencies
└── README.md               # This project documentation
```

---

## 🚀 Quickstart

### 1. Prerequisites
- Python 3.11+
- Free Google Gemini API Key
- (Optional) Free Groq API Key

### 2. Setup Virtual Environment
```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Configure Environment Variables
```bash
cp .env.example .env
# Edit .env and supply GEMINI_API_KEY
```

### 4. Initialize Database
```bash
python -m app.core.db init
```

### 5. Run API Backend
```bash
uvicorn app.main:app --reload --port 8000
```

### 6. Run Streamlit UI
```bash
streamlit run ui/app.py
```
The Streamlit UI provides 9 dedicated pages:
1. **Company Setup**: Register company & run autonomous initial web research.
2. **Profile (Editable)**: Inspect and edit facts vs assumptions across dimensions.
3. **Interview**: Adaptive 10-question executive interview with skip & thread follow-ups.
4. **Signal Stack**: 4-tab strategic landscape (`competitors`, `customers`, `market`, `internal`).
5. **Source Manager**: Health metrics, approval/rejection, duplicate detection, and manual add.
6. **Intelligence Feed**: Tri-factor ranked signals with dynamic multi-criteria filters.
7. **Monday Brief**: 10-section strategic intelligence brief with downloadable MD/HTML.
8. **Settings**: Timezone, briefing schedule, and autonomous job frequencies.
9. **Jobs**: Live job logs, failure inspection, and manual weekly/monthly triggers.

---

## 🧪 Multi-Company Demonstration Runner

To execute the entire autonomous strategic intelligence pipeline across three distinct companies and industries (MeetUniversity, Postman, Monzo) and verify acceptance targets:

```bash
python scripts/run_demo.py
```

### Custom Company Override
You can also specify your own target companies via command-line flags:
```bash
python scripts/run_demo.py --c2-name "Supabase" --c2-url "https://supabase.com" --c2-industry "Cloud Database Infrastructure" --c3-name "Snyk" --c3-url "https://snyk.io" --c3-industry "Developer Security & DevSecOps"
```

### Verified Targets Per Company:
- **$\ge 20$ Sources** discovered and categorized
- **5–10 Competitors** profiled with positioning and pricing
- **$\ge 30$ Intelligence Records** (crawled documents + extracted signals)
- **$\ge 1$ 10-Section Monday Brief** synthesized and verified

Generated deliverables are saved to `reports/`:
- `reports/meet_university_monday_brief.md` & `.html`
- `reports/postman_monday_brief.md` & `.html`
- `reports/monzo_monday_brief.md` & `.html`
- `reports/demo_execution_summary.json` & `.md`

---

## 🧪 CLI Automation & Maintenance Tools

### Run Weekly Autonomous Pipeline Locally
```bash
python scripts/run_weekly.py --company-id 1
```

### Run Monthly Strategic Source Audit
```bash
python scripts/run_monthly_audit.py --company-id 1
```

### Strategic Reassessment Demo (e.g. Germany Study-Abroad Pivot)
```bash
python scripts/demo_reassessment.py
```
*Outputs diff analysis (kept, demoted, and newly suggested sources with plain-language summaries) and saves evidence to `data/demo_evidence_meetuniversity_germany_pivot.json` and `data/demo_evidence_meetuniversity_germany_pivot.md`.*

### Run Automated Test Suite (Zero External Token Consumption)
```bash
python -m pytest -v
```
*All 47 unit and integration tests execute with zero network calls and zero token burn.*

---

## 📚 Technical Documentation & Specifications

- **[Technical Specification (`docs/TECHNICAL.md`)](docs/TECHNICAL.md)**: Deep-dive architectural specification covering system design, dynamic source discovery, crawler politeness, tri-factor algorithmic ranking, AI analysis & verbatim verification, job scheduling, and fault tolerance.
- **[Free-Tier Quotas & Costs (`docs/COSTS.md`)](docs/COSTS.md)**: Full accounting of free-tier quotas (Gemini, Groq, DuckDuckGo, SQLite, GitHub Actions), token economics, and defensive prompt-hash caching.
- **[Test Evidence Dossier (`docs/TEST_EVIDENCE.md`)](docs/TEST_EVIDENCE.md)**: Pytest execution logs, hard-rule grep test evidence, hallucination rejection tests, and multi-company demonstration scorecard.
- **[Project Rules & Constraints (`AGENTS.md`)](AGENTS.md)**: Non-negotiable architectural laws and engineering standards.
