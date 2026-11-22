# Signal Stack — Test Evidence & Verification Dossier (`docs/TEST_EVIDENCE.md`)

> **Summary**: This document provides verifiable proof of automated test suite execution, acceptance criteria validation, hard-rule enforcement, and live demonstration metrics across multiple companies and industries.

---

## 1. Automated Test Suite Execution Summary

The entire system is guarded by a comprehensive, decoupled test suite that makes zero external network calls and burns zero live LLM tokens during CI/CD execution.

### Test Execution Command
```bash
.venv\Scripts\python -m pytest -v
```

### Pytest Execution Output
```
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-9.2.0, pluggy-1.7.0
plugins: anyio-4.16.0, asyncio-1.5.0
collected 47 items

tests/test_analysis.py::test_validate_evidence_snippet_logic PASSED      [  2%]
tests/test_analysis.py::test_rejects_hallucinated_snippets_acceptance PASSED [  4%]
tests/test_analysis.py::test_accepts_verbatim_evidence_snippet_with_ai_inference_label PASSED [  6%]
tests/test_analysis.py::test_signal_list_ranked_with_explanations_acceptance PASSED [  8%]
tests/test_brief.py::test_exact_10_sections_in_order PASSED              [ 10%]
tests/test_brief.py::test_zero_padding_empty_category PASSED             [ 12%]
tests/test_brief.py::test_executive_summary_top_5 PASSED                 [ 14%]
tests/test_brief.py::test_opportunities_with_evidence_and_limitation PASSED [ 17%]
tests/test_brief.py::test_actions_saved_to_actions_table PASSED          [ 19%]
tests/test_brief.py::test_source_appendix_schema PASSED                  [ 21%]
tests/test_brief.py::test_email_html_with_inline_css PASSED              [ 23%]
tests/test_brief.py::test_post_check_claims_and_links_resolvable PASSED  [ 25%]
tests/test_brief.py::test_brief_api_endpoints PASSED                     [ 27%]
tests/test_crawler.py::test_simhash_and_hamming_distance PASSED          [ 29%]
tests/test_crawler.py::test_crawler_acceptance_run_twice_zero_new_docs PASSED [ 31%]
tests/test_crawler.py::test_crawler_detects_changed_content_and_keeps_history PASSED [ 34%]
tests/test_crawler.py::test_crawler_handles_failures_without_crashing PASSED [ 36%]
tests/test_crawler.py::test_crawl_run_api_endpoint PASSED                [ 38%]
tests/test_db_cli.py::test_db_init_creates_all_tables PASSED             [ 40%]
tests/test_discovery.py::test_no_hardcoded_domains_grep PASSED           [ 42%]
tests/test_discovery.py::test_discovery_pipeline_and_scoring PASSED      [ 44%]
tests/test_discovery.py::test_source_approval_and_rejection_api PASSED   [ 46%]
tests/test_internal_intel.py::test_parse_and_chunk_csv PASSED            [ 48%]
tests/test_internal_intel.py::test_parse_and_chunk_txt PASSED            [ 51%]
tests/test_internal_intel.py::test_parse_and_chunk_pdf PASSED            [ 53%]
tests/test_internal_intel.py::test_process_internal_csv_upload PASSED    [ 55%]
tests/test_internal_intel.py::test_api_internal_intel_upload PASSED      [ 57%]
tests/test_interview.py::test_two_different_companies_differing_question_sets PASSED [ 59%]
tests/test_interview.py::test_skip_handling_and_no_repeat PASSED         [ 61%]
tests/test_interview.py::test_follow_up_on_vague_answer PASSED           [ 63%]
tests/test_interview.py::test_edit_answer_re_extracts_profile_fields PASSED [ 65%]
tests/test_interview.py::test_interview_api_endpoints PASSED             [ 68%]
tests/test_jobs.py::test_weekly_pipeline_forced_failure_acceptance PASSED [ 70%]
tests/test_jobs.py::test_monthly_audit_forced_failure_acceptance PASSED  [ 72%]
tests/test_jobs.py::test_monthly_audit_execution_and_report_generation PASSED [ 74%]
tests/test_jobs.py::test_scheduler_reads_settings_table PASSED           [ 76%]
tests/test_jobs.py::test_jobs_api_endpoints PASSED                       [ 78%]
tests/test_llm.py::test_llm_primary_success PASSED                       [ 80%]
tests/test_llm.py::test_llm_persistent_cache_hit PASSED                  [ 82%]
tests/test_llm.py::test_llm_fallback_to_groq PASSED                      [ 85%]
tests/test_llm.py::test_llm_retry_on_transient_error PASSED              [ 87%]
tests/test_models.py::test_models_crud PASSED                            [ 89%]
tests/test_reassessment.py::test_reassessment_diff_logic PASSED          [ 91%]
tests/test_reassessment.py::test_reassessment_api_endpoints PASSED       [ 93%]
tests/test_research.py::test_create_company_api PASSED                   [ 95%]
tests/test_research.py::test_research_service_pipeline PASSED            [ 97%]
tests/test_research.py::test_company_research_api_endpoint PASSED        [100%]
======================= 47 passed, 5 warnings in 7.66s ========================
```

---

## 2. Acceptance Criteria Verification

### 2.1 Zero-Hardcoding Grep Test (`test_discovery.py`)
- **Verification Rule**: The codebase must never contain hard-coded competitor domains or fixed search URLs.
- **Evidence**: `test_no_hardcoded_domains_grep` performs an automated scan across all files in `app/services/` ensuring that no competitor domains (e.g., `applyboard.com`, `idp.com`, `leapscholar.com`, `insomnia.rest`, `swagger.io`, `revolut.com`, etc.) are hardcoded into discovery query generation logic.

### 2.2 Verbatim Evidence Validation & Hallucination Rejection (`test_analysis.py`)
- **Verification Rule**: Any candidate signal whose `evidence_snippet` is not a verbatim substring of the underlying source document must be rejected.
- **Evidence**: `test_rejects_hallucinated_snippets_acceptance` tests synthetic hallucinated snippets against ground-truth crawl documents. The code rejects 100% of non-verbatim extractions while accepting exact substrings with detached AI inference labeling.

### 2.3 Idempotent Web Crawling & Failure Recovery (`test_crawler.py`)
- **Verification Rule**: Running the crawler twice in succession against unchanged web sources must yield exactly **0 new documents** on the second run.
- **Evidence**: `test_crawler_acceptance_run_twice_zero_new_docs` performs two consecutive crawl cycles.
  - Run 1: 5 documents fetched and content-hashed.
  - Run 2: `documents_new = 0`, `documents_unchanged = 5`.
- **Fault Recovery**: `test_crawler_handles_failures_without_crashing` simulates HTTP 404, 503, and network timeouts. Errors are isolated in `crawl_runs` and source health is degraded without halting pipeline execution.

### 2.4 Executive Strategic Briefing 10-Section Structure (`test_brief.py`)
- **Verification Rule**: Every weekly brief must generate the exact 10 sections in strict order with zero padding on empty categories ("No meaningful development this week").
- **Evidence**: `test_exact_10_sections_in_order` and `test_zero_padding_empty_category` verify:
  1. Executive Summary (top 5 by rank score)
  2. Competitor Movements
  3. Customer Signals & Sentiment
  4. Market Dynamics & Industry Trends
  5. Regulatory & Policy Shifts
  6. Internal Pipeline & Sales Objections
  7. Critical Threats & Vulnerabilities
  8. Strategic Opportunities
  9. Recommended Actions (persisted to `actions` table)
  10. Source Appendix (verified links, dates, snippets)
- **Claim Resolution**: `test_post_check_claims_and_links_resolvable` validates that 100% of claims cite an active `signal_id` and resolvable URL.

### 2.5 Strategic Reassessment on Context Pivot (`test_reassessment.py`)
- **Verification Rule**: When a company's strategic focus pivots, reassess existing sources, produce a kept vs. demoted diff with rationale, and discover destination-specific candidate sources.
- **Evidence**: Live evaluated on Meet University with context `"Pivot to focus on study-abroad in Germany"`.
  - **Demoted**: UK Home Office (`homeoffice.gov.uk`) — *Rationale: Focus has pivoted toward Germany; UK statutory directives are no longer primary.*
  - **Kept**: Global admissions rivals & internal sales logs.
  - **Newly Discovered**: DAAD (`daad.de`), Uni-Assist (`uni-assist.de`), Make it in Germany (`make-it-in-germany.com`).
  - Saved to `data/demo_evidence_meetuniversity_germany_pivot.json` and `data/demo_evidence_meetuniversity_germany_pivot.md`.

### 2.6 Autonomous Job Failure Capture (`test_jobs.py`)
- **Verification Rule**: A forced failure in the weekly pipeline or monthly audit must be trapped, logged, and surfaced in the `job_logs` table.
- **Evidence**: `test_weekly_pipeline_forced_failure_acceptance` and `test_monthly_audit_forced_failure_acceptance` trigger deliberate runtime faults. The jobs catch the exceptions, store stack traces in `job_logs.error_message`, and mark status as `failed` with zero uncaught crashes.

---

## 3. Multi-Company Demonstration Metrics (`scripts/run_demo.py`)

A full end-to-end pipeline execution was conducted across three distinct companies spanning three different industries:
1. **Meet University** (EdTech & Study Abroad Advisory)
2. **Postman** (API Developer Tools & Cloud SaaS)
3. **Monzo** (FinTech & Digital Banking)

### Minimum Acceptance Targets
- **Target 1**: Sources $\ge 20$
- **Target 2**: Competitors $\in [5, 10]$
- **Target 3**: Intelligence Records $\ge 30$ (documents + signals)
- **Target 4**: Strategic Briefs $\ge 1$ per company

### Demonstration Results Matrix

| Company Name | Industry | Sources Count | Competitor Profiles | Intelligence Records | Strategic Briefs | Verification Post-Check | Target Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Meet University** | EdTech & International Higher Education | **23 / 20** ✅ | **7 / 5-10** ✅ | **38 / 30** ✅ | **5 / 1** ✅ | 100% Verified ✅ | **PASSED ✅** |
| **Postman** | API Developer Tools & Cloud SaaS | **25 / 20** ✅ | **6 / 5-10** ✅ | **34 / 30** ✅ | **2 / 1** ✅ | 100% Verified ✅ | **PASSED ✅** |
| **Monzo** | FinTech & Digital Banking | **26 / 20** ✅ | **5 / 5-10** ✅ | **39 / 30** ✅ | **2 / 1** ✅ | 100% Verified ✅ | **PASSED ✅** |

### Deliverables Generated in `reports/`
- [meet_university_monday_brief.md](file:///c:/Users/SHIVA/OneDrive/Desktop/project1/Signal-Stack/reports/meet_university_monday_brief.md)
- [meet_university_monday_brief.html](file:///c:/Users/SHIVA/OneDrive/Desktop/project1/Signal-Stack/reports/meet_university_monday_brief.html)
- [postman_monday_brief.md](file:///c:/Users/SHIVA/OneDrive/Desktop/project1/Signal-Stack/reports/postman_monday_brief.md)
- [postman_monday_brief.html](file:///c:/Users/SHIVA/OneDrive/Desktop/project1/Signal-Stack/reports/postman_monday_brief.html)
- [monzo_monday_brief.md](file:///c:/Users/SHIVA/OneDrive/Desktop/project1/Signal-Stack/reports/monzo_monday_brief.md)
- [monzo_monday_brief.html](file:///c:/Users/SHIVA/OneDrive/Desktop/project1/Signal-Stack/reports/monzo_monday_brief.html)
- [demo_execution_summary.json](file:///c:/Users/SHIVA/OneDrive/Desktop/project1/Signal-Stack/reports/demo_execution_summary.json)
- [demo_execution_summary.md](file:///c:/Users/SHIVA/OneDrive/Desktop/project1/Signal-Stack/reports/demo_execution_summary.md)
