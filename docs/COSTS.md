# API Quotas, Rate Limits & Zero-Cost Architecture (`docs/COSTS.md`)

This document logs all external service rate limits, free-tier quotas, and defensive engineering practices implemented in **Signal Stack** to ensure **100% free, zero-cost operation**.

---

## 1. Free-Tier Quota & Rate Limit Matrix

| Component | Provider / Tool | Tier / Pricing | Quotas & Rate Limits | Mitigation & Fallback Strategy |
| :--- | :--- | :--- | :--- | :--- |
| **Primary LLM** | **Google Gemini** (`google-genai`) | Free Tier | • **15 RPM** (Requests per minute)<br>• **1,000,000 TPM** (Tokens per minute)<br>• **1,500 RPD** (Requests per day) | • SQLite prompt-hash cache (`llm_cache`) avoids repeated calls.<br>• Leaky-bucket / sleep throttle between turns.<br>• Auto-failover to Groq on HTTP 429. |
| **Fallback LLM** | **Groq Cloud** (`groq`) | Free Tier | • **30 RPM** (Requests per minute)<br>• **6,000 TPM** (Tokens per minute)<br>• **14,400 RPD** | • Engaged only if Gemini is unavailable, throttled, or returns an error.<br>• Uses fast open models (e.g. Llama-3.3-70B-versatile / 8B-instant). |
| **Web Search** | **DuckDuckGo** (`duckduckgo_search` / `ddgs`) | Free / Public | • No official API quota<br>• IP rate-limiting on rapid bursts | • Minimum 1.5s–3.0s jittered delay between queries.<br>• Deduplication of query terms.<br>• HTML parsing fallback. |
| **Database** | **SQLite** (via `SQLModel`) | Local / OSS | • Unlimited local storage<br>• Single-writer concurrency | • Write-Ahead Logging (WAL) enabled.<br>• Zero cloud database cost. |
| **Web Crawler** | **Trafilatura & HTTPX** | Local / OSS | • Dependent on target host policies | • Strict `robots.txt` compliance.<br>• Per-domain concurrency limit (1 req/domain at a time).<br>• 1.5s delay per domain. Honest User-Agent. |
| **Automation** | **GitHub Actions** | Free Tier | • **2,000 minutes/month** for private repos<br>• Unlimited for public repos | • Scheduled cron runs once daily (estimated ~2-3 minutes per execution = ~90 mins/month). |

---

## 2. Defensive Cost-Saving Architectures

### 2.1 Prompt-Hash SQLite Cache
Before any payload is dispatched to Gemini or Groq:
1. Normalize system prompt and input variables.
2. Compute `hash = sha256(provider + model + json_schema + prompt)`.
3. Query `llm_cache` table in SQLite.
4. If a valid, non-expired response exists, return instantly with 0ms LLM latency and 0 token consumption.

### 2.2 Exponential Backoff & Circuit Breaking
- If an HTTP 429 (Resource Exhausted) or 503 (Service Unavailable) status is returned:
  - Back off with jitter: `delay = min(base * (2 ** attempt) + jitter, max_delay)`.
  - Max retries: 3 attempts before switching from primary to fallback provider.
- If primary provider fails 3 consecutive times, trip the circuit breaker and route all subsequent calls in that execution cycle to the fallback provider.

### 2.3 Crawler Politeness & Bandwidth Preservation
- HEAD requests or sitemap parsing are used when possible to verify `Last-Modified` timestamps before downloading heavy page payloads.
- HTML content extraction uses `trafilatura` to strip scripts, styles, advertisements, and navigation chrome, caching only the clean extracted article text.
