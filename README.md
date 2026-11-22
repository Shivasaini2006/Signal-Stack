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

---

## 📊 Rate Limits & Free Tier Architecture
See [`docs/COSTS.md`](file:///c:/Users/SHIVA/OneDrive/Desktop/project1/Signal-Stack/docs/COSTS.md) for full accounting of free quotas, backoff intervals, and token caching strategies.
