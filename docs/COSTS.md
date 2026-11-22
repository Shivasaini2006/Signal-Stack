# Free-Tier Quotas, Rate Limits & Zero-Cost Architecture (`docs/COSTS.md`)

This document provides a comprehensive accounting of all external service rate limits, free-tier quotas, and defensive architectural mechanisms implemented in **Signal Stack** to guarantee **100% free, zero-cost operation**.

---

## 1. Zero-Cost Infrastructure Matrix

| Service / Tool | Provider / Library | Tier / Pricing | Official Quotas & Rate Limits | Mitigation & Failover Architecture |
| :--- | :--- | :--- | :--- | :--- |
| **Primary LLM** | **Google Gemini** (`google-genai`) | Free Tier ($0.00) | • **15 RPM** (Requests per minute)<br>• **1,000,000 TPM** (Tokens per minute)<br>• **1,500 RPD** (Requests per day) | • Automated leaky-bucket throttle enforces $\ge 4.0\text{s}$ interval between calls.<br>• SQLite prompt-hash cache (`llm_cache`) eliminates repeated requests.<br>• Automatic failover to Groq on HTTP 429. |
| **Fallback LLM** | **Groq Cloud** (`groq`) | Free Tier ($0.00) | • **30 RPM** (Requests per minute)<br>• **6,000 TPM** (Tokens per minute)<br>• **14,400 RPD** (Requests per day) | • Engaged automatically when Gemini encounters rate limits or errors.<br>• Powered by open-weights models (`llama-3.3-70b-versatile` / `llama-3.1-8b-instant`). |
| **Web Search** | **DuckDuckGo Search** (`ddgs`) | Free / Public | • No hard numerical API cap<br>• IP rate-limiting on burst traffic | • Jittered delays ($1.5\text{s} - 3.0\text{s}$) between queries.<br>• Strict deduplication of query terms.<br>• Algolia Hacker News API as secondary community source. |
| **Relational DB** | **SQLite** (`SQLModel`) | Local / FOSS | • Unlimited local storage<br>• Zero compute cost | • Local single-file storage with Write-Ahead Logging (WAL).<br>• Zero cloud database hosting fees. |
| **Web Crawler** | **Trafilatura & HTTPX** | Local / FOSS | • Host-dependent | • Strict `robots.txt` compliance checking with in-memory cache.<br>• Per-domain rate limiting ($\ge 1.5\text{s}$ per domain).<br>• Honest User-Agent: `SignalStackBot/1.0`. |
| **Automation** | **GitHub Actions** | Free Tier ($0.00) | • **2,000 minutes/month** (private repos)<br>• Unlimited minutes (public repos) | • Weekly cron execution requires $\approx 3$ minutes/run ($\approx 12$ mins/month).<br>• Consumes $< 1\%$ of monthly free allocation. |

---

## 2. Defensive Cost-Saving Architectures

### 2.1 SHA-256 Prompt-Hash Persistent Caching
To prevent token waste and API billing exposure, all LLM invocations pass through an SQLite caching layer:

1. System instructions, user prompts, provider parameters, and output JSON schemas are normalized.
2. A cryptographic SHA-256 digest is generated:
   $$\text{hash} = \text{SHA256}(\text{provider} \mathbin{\Vert} \text{model} \mathbin{\Vert} \text{schema\_json} \mathbin{\Vert} \text{system\_prompt} \mathbin{\Vert} \text{prompt})$$
3. The cache table `llm_cache` is queried in SQLite.
4. **Cache Hit**: Returns the parsed JSON response in $0\text{ms}$ with zero network overhead and zero token consumption.
5. **Cache Miss**: Executes the external API call, stores the structured output in `llm_cache`, and returns the result.

### 2.2 Rate-Limiting Leaky Bucket & Exponential Backoff
To stay strictly within the **15 RPM** limit of the Gemini free tier:
- The internal `LLMClient` calculates elapsed time since the previous Gemini dispatch. If elapsed time is $< 4.0\text{s}$, execution sleeps for the remaining difference.
- If an HTTP 429 (`RESOURCE_EXHAUSTED`) or 503 error is received, the client executes exponential backoff with jitter:
  $$\Delta t = \min(2.0 \cdot 2^{\text{attempt}} + \text{jitter}, 16.0\text{s})$$
- After 3 unsuccessful retries on the primary provider, the client triggers the circuit breaker and transparently fails over to Groq.

### 2.3 Bandwidth & Network Politeness
- The crawler inspects `robots.txt` before fetching any web asset. If disallowed, the request is immediately aborted before downloading bytes.
- Document extraction uses `trafilatura` to extract clean article text, stripping heavy media files, scripts, and stylesheets, which minimizes memory footprint and database storage size.

---

## 3. Operational Token Economics (Weekly Run Estimate)

For a portfolio of 3 monitored companies running the full weekly pipeline:

| Pipeline Step | Invocations / Company | Total Invocations (3 Cos) | Estimated Input Tokens | Estimated Output Tokens | Total Tokens | Free Tier Utilization |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Initial Research** | 1 (Cached) | 3 | 3,000 | 900 | 3,900 | $0.26\%$ of daily cap |
| **10-Turn Interview** | 10 (Cached) | 30 | 15,000 | 4,500 | 19,500 | $1.30\%$ of daily cap |
| **Source Discovery** | 3 (Cached) | 9 | 4,500 | 2,700 | 7,200 | $0.48\%$ of daily cap |
| **Signal Extraction** | $\approx 10$ docs | 30 | 20,000 | 6,000 | 26,000 | $1.73\%$ of daily cap |
| **Weekly Brief Synthesis** | 1 | 3 | 8,000 | 3,500 | 11,500 | $0.77\%$ of daily cap |
| **Total Pipeline Cycle** | — | **75 calls** | **50,500** | **17,600** | **68,100** | **$4.54\%$ of Daily Limit** |

*Conclusion*: A complete 3-company weekly strategic monitoring run consumes less than **5% of the daily free tier token allowance** and zero dollars in infrastructure cost.
