import os
import json
import requests
import streamlit as st
from datetime import datetime, timezone

# API Configuration
API_BASE_URL = os.environ.get("API_URL", "http://127.0.0.1:8000")

st.set_page_config(
    page_title="Signal Stack — Strategic Intelligence Engine",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling
st.markdown("""
<style>
    .brand-title { font-size: 24px; font-weight: 800; color: #0f172a; margin-bottom: 2px; }
    .page-desc { font-size: 13px; color: #64748b; margin-bottom: 20px; }
    .card-box { background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px; margin-bottom: 12px; }
    .tag-critical { background-color: #fee2e2; color: #991b1b; padding: 2px 8px; border-radius: 12px; font-weight: 700; font-size: 11px; }
    .tag-high { background-color: #ffedd5; color: #9a3412; padding: 2px 8px; border-radius: 12px; font-weight: 700; font-size: 11px; }
    .tag-med { background-color: #fef9c3; color: #854d0e; padding: 2px 8px; border-radius: 12px; font-weight: 700; font-size: 11px; }
    .tag-verified { background-color: #dcfce7; color: #166534; padding: 2px 8px; border-radius: 12px; font-weight: 700; font-size: 11px; }
    .inference-callout { background-color: #f8fafc; border-left: 3px solid #64748b; padding: 8px 12px; margin-top: 8px; font-size: 12px; color: #334155; }
</style>
""", unsafe_allow_html=True)


def api_get(endpoint: str, default=None):
    try:
        r = requests.get(f"{API_BASE_URL}{endpoint}", timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return default


def api_post(endpoint: str, json_data=None, params=None):
    return requests.post(f"{API_BASE_URL}{endpoint}", json=json_data, params=params, timeout=45)


def api_put(endpoint: str, json_data=None):
    return requests.put(f"{API_BASE_URL}{endpoint}", json=json_data, timeout=15)


def api_patch(endpoint: str, json_data=None):
    return requests.patch(f"{API_BASE_URL}{endpoint}", json=json_data, timeout=15)


def api_delete(endpoint: str):
    return requests.delete(f"{API_BASE_URL}{endpoint}", timeout=15)


# -----------------------------------------------------------------------------
# SIDEBAR NAVIGATION & COMPANY SELECTOR
# -----------------------------------------------------------------------------
st.sidebar.markdown('<div class="brand-title">📡 Signal Stack</div>', unsafe_allow_html=True)
st.sidebar.caption("Autonomous Strategic Intelligence Engine")

companies_list = api_get("/companies", default=[])

active_company_id = None
active_company_name = None

if companies_list:
    comp_map = {f"{c['name']} (ID: {c['id']})": c for c in companies_list}
    chosen_label = st.sidebar.selectbox("Active Company", list(comp_map.keys()))
    active_company = comp_map[chosen_label]
    active_company_id = active_company["id"]
    active_company_name = active_company["name"]
else:
    st.sidebar.warning("No companies registered yet. Go to 'Company Setup'.")

page = st.sidebar.radio(
    "Navigation Menu",
    [
        "Company Setup",
        "Profile",
        "Interview",
        "Signal Stack",
        "Source Manager",
        "Intelligence Feed",
        "Monday Brief",
        "Settings",
        "Jobs",
    ],
)

# -----------------------------------------------------------------------------
# PAGE 1: COMPANY SETUP
# -----------------------------------------------------------------------------
if page == "Company Setup":
    st.subheader("🏢 Company Setup & Research Onboarding")
    st.markdown('<div class="page-desc">Register a target company by URL. The engine crawls key internal pages and searches the web to extract an initial verifiable intelligence profile.</div>', unsafe_allow_html=True)

    with st.form("create_company_form"):
        col1, col2 = st.columns(2)
        with col1:
            comp_name = st.text_input("Company Name", value="Meet University")
        with col2:
            comp_url = st.text_input("Company Website URL", value="https://www.meetuniversity.com")

        submit_btn = st.form_submit_button("Register Company", type="primary")

    if submit_btn and comp_name and comp_url:
        with st.spinner("Registering company..."):
            res = api_post("/companies", json_data={"name": comp_name, "url": comp_url})
            if res.status_code in (200, 201):
                st.success(f"Company '{comp_name}' registered successfully!")
                st.rerun()
            else:
                st.error(f"Failed to register company: {res.text}")

    st.markdown("---")
    st.markdown("### Registered Companies")
    if companies_list:
        for c in companies_list:
            c1, c2, c3 = st.columns([2, 3, 2])
            with c1:
                st.markdown(f"**{c['name']}** (ID: {c['id']})")
            with c2:
                st.markdown(f"[{c['url']}]({c['url']})")
            with c3:
                if st.button(f"Run Web Research", key=f"res_{c['id']}"):
                    with st.spinner(f"Crawling {c['url']} and running web searches..."):
                        r_resp = api_post(f"/companies/{c['id']}/research")
                        if r_resp.status_code == 200:
                            st.success(f"Research completed! Extracted profile fields.")
                            st.rerun()
                        else:
                            st.error(f"Research failed: {r_resp.text}")
    else:
        st.info("No companies registered in the database.")


# -----------------------------------------------------------------------------
# PAGE 2: PROFILE (EDITABLE)
# -----------------------------------------------------------------------------
elif page == "Profile":
    st.subheader(f"📑 Company Intelligence Profile — {active_company_name or 'No Company Selected'}")
    st.markdown('<div class="page-desc">Structured company intelligence profile. Distinguishes verified facts (with exact source URLs and quotes) from assumptions. You can edit any field or add new strategic dimensions.</div>', unsafe_allow_html=True)

    if not active_company_id:
        st.warning("Please select a company in the sidebar.")
    else:
        company_data = api_get(f"/companies/{active_company_id}")
        profile_fields = company_data.get("profile_fields", []) if company_data else []

        st.markdown("### Stored Profile Dimensions")
        if profile_fields:
            for pf in profile_fields:
                with st.expander(f"Key: {pf['key'].upper()} — {'✅ Verified Fact' if pf.get('is_verified_fact') else '⚠️ Strategic Assumption'}"):
                    val_edit = st.text_area(f"Value ({pf['key']})", value=pf["value"], key=f"pf_val_{pf['id']}")
                    is_ver = st.checkbox("Is Verified Fact?", value=bool(pf.get("is_verified_fact")), key=f"pf_ver_{pf['id']}")
                    if st.button("Save Dimension", key=f"save_pf_{pf['id']}"):
                        u_res = api_put(f"/companies/{active_company_id}/profile-fields", json_data={"key": pf["key"], "value": val_edit, "is_verified_fact": is_ver})
                        if u_res.status_code == 200:
                            st.success(f"Updated '{pf['key']}' successfully!")
                            st.rerun()
                        else:
                            st.error(f"Failed to update: {u_res.text}")
        else:
            st.info("No profile fields stored yet. Run 'Research' in Company Setup or complete the Interview.")

        st.markdown("---")
        st.markdown("### Add / Override Strategic Dimension")
        with st.form("add_dimension_form"):
            new_key = st.text_input("Dimension Key (e.g. geography, pricing_model, ideal_customer_profile)")
            new_val = st.text_area("Dimension Value")
            new_is_ver = st.checkbox("Mark as Verified Fact", value=True)
            if st.form_submit_button("Add Dimension"):
                if new_key and new_val:
                    a_res = api_put(f"/companies/{active_company_id}/profile-fields", json_data={"key": new_key, "value": new_val, "is_verified_fact": new_is_ver})
                    if a_res.status_code == 200:
                        st.success(f"Added dimension '{new_key}'!")
                        st.rerun()


# -----------------------------------------------------------------------------
# PAGE 3: INTERVIEW (CHAT, ONE QUESTION AT A TIME, SKIP BUTTON)
# -----------------------------------------------------------------------------
elif page == "Interview":
    st.subheader(f"🎙️ Strategic Executive Interview — {active_company_name or 'No Company'}")
    st.markdown('<div class="page-desc">Dynamic 10-turn strategic intelligence interview. Questions are asked one at a time, contextualized for this company\'s industry, with adaptive follow-ups and zero repetition.</div>', unsafe_allow_html=True)

    if not active_company_id:
        st.warning("Please select a company in the sidebar.")
    else:
        # Fetch next question
        next_q_data = api_get(f"/companies/{active_company_id}/interview/next")

        if next_q_data:
            if next_q_data.get("interview_complete"):
                st.success("🎉 Strategic Interview Complete! All 10 strategic dimensions have been recorded.")
            else:
                q_text = next_q_data.get("question")
                theme = next_q_data.get("theme", "strategic_alignment")
                turn_num = next_q_data.get("turn_number", 1)
                is_follow_up = next_q_data.get("is_follow_up", False)

                tag_label = "Adaptive Follow-Up" if is_follow_up else f"Question {turn_num} of 10"
                st.markdown(f"#### ❓ {tag_label}: Theme `{theme.replace('_', ' ').title()}`")
                st.info(f"**{q_text}**")

                with st.form("interview_answer_form"):
                    user_answer = st.text_area("Your Executive Response", placeholder="Provide strategic details, key competitors, or operational realities...")
                    c1, c2 = st.columns([1, 1])
                    with c1:
                        submit_ans = st.form_submit_button("Submit Response", type="primary")
                    with c2:
                        skip_btn = st.form_submit_button("Skip Question")

                if submit_ans and user_answer:
                    with st.spinner("Recording response and updating intelligence profile..."):
                        a_res = api_post(f"/companies/{active_company_id}/interview/answer", json_data={"action": "answer", "answer": user_answer})
                        if a_res.status_code == 200:
                            st.success("Response recorded!")
                            st.rerun()
                        else:
                            st.error(f"Error submitting answer: {a_res.text}")

                if skip_btn:
                    with st.spinner("Skipping question..."):
                        s_res = api_post(f"/companies/{active_company_id}/interview/answer", json_data={"action": "skip"})
                        if s_res.status_code == 200:
                            st.warning("Question skipped.")
                            st.rerun()

        # Interview Turn History
        st.markdown("---")
        st.markdown("### Interview Transcript & History")
        turns = api_get(f"/companies/{active_company_id}/interview/turns", default=[])
        if turns:
            for t in turns:
                status_icon = "⏭️ Skipped" if t["status"] == "skipped" else "💬 Answered"
                with st.expander(f"{status_icon} Turn #{t['turn_number']} ({t['theme'].title()}): {t['question'][:80]}..."):
                    st.markdown(f"**Question**: {t['question']}")
                    st.markdown(f"**Answer**: {t.get('answer') or '*(Skipped)*'}")
                    if t.get("extracted_profile_facts"):
                        st.caption(f"Profile Extraction: {t['extracted_profile_facts']}")
        else:
            st.write("No interview questions answered yet.")


# -----------------------------------------------------------------------------
# PAGE 4: SIGNAL STACK (4 TABS WITH REASONS)
# -----------------------------------------------------------------------------
elif page == "Signal Stack":
    st.subheader(f"📡 Signal Stack Portfolio — {active_company_name or 'No Company'}")
    st.markdown('<div class="page-desc">Autonomous Signal Stack across 4 core intelligence categories. Evaluates Specificity, Recency, and Credibility with an explicit reason for inclusion.</div>', unsafe_allow_html=True)

    if not active_company_id:
        st.warning("Please select a company in the sidebar.")
    else:
        if st.button("🔍 Run Autonomous Signal Stack Discovery", type="primary"):
            with st.spinner("Discovering competitors, customer forums, and regulatory feeds..."):
                d_res = api_post(f"/companies/{active_company_id}/discovery")
                if d_res.status_code == 200:
                    st.success("Discovery completed! Discovered fresh candidate sources.")
                    st.rerun()
                else:
                    st.error(f"Discovery error: {d_res.text}")

        # 4 Category Tabs
        tab_comp, tab_cust, tab_mkt, tab_int = st.tabs(["Competitors", "Customers", "Market & Regulators", "Internal Intel"])

        all_sources = api_get(f"/companies/{active_company_id}/sources", default=[])

        def render_sources_for_cat(cat_name):
            cat_sources = [s for s in all_sources if s["category"] == cat_name]
            if cat_sources:
                st.write(f"Sources in this category: **{len(cat_sources)}**")
                for s in cat_sources:
                    with st.container():
                        st.markdown(f"**#{s['id']} [{s['name']}]({s['url']})** — Status: `{s['status'].upper()}`")
                        st.markdown(f"*Reason for inclusion*: {s['reason']}")
                        st.caption(f"Scores: Specific: `{s['specific_score']:.2f}` | Recent: `{s['recent_score']:.2f}` | Credible: `{s['credible_score']:.2f}`")
                        st.markdown("---")
            else:
                st.info(f"No sources categorized under '{cat_name}'. Click discovery above.")

        with tab_comp:
            render_sources_for_cat("competitors")
        with tab_cust:
            render_sources_for_cat("customers")
        with tab_mkt:
            render_sources_for_cat("market")
        with tab_int:
            render_sources_for_cat("internal")


# -----------------------------------------------------------------------------
# PAGE 5: SOURCE MANAGER (APPROVE / REJECT / ADD / REMOVE, HEALTH, DUPLICATES)
# -----------------------------------------------------------------------------
elif page == "Source Manager":
    st.subheader(f"🛠️ Source Portfolio Manager — {active_company_name or 'No Company'}")
    st.markdown('<div class="page-desc">Approve, reject, or remove sources, monitor crawl health, and detect duplicate domains.</div>', unsafe_allow_html=True)

    if not active_company_id:
        st.warning("Please select a company in the sidebar.")
    else:
        sources = api_get(f"/companies/{active_company_id}/sources", default=[])

        # Duplicate Source Detection
        st.markdown("### Duplicate Detection")
        domain_map = {}
        duplicates = []
        for s in sources:
            url = s["url"] or ""
            domain = url.split("//")[-1].split("/")[0].lower()
            if domain in domain_map:
                duplicates.append((s, domain_map[domain]))
            else:
                domain_map[domain] = s

        if duplicates:
            st.warning(f"Detected {len(duplicates)} duplicate source domain registrations:")
            for dup, orig in duplicates:
                st.write(f"- Source #{dup['id']} (`{dup['url']}`) duplicates Source #{orig['id']} (`{orig['url']}`)")
        else:
            st.success("Zero duplicate source domains detected in portfolio.")

        st.markdown("---")
        # Add Custom Source Form
        with st.expander("➕ Add Custom Strategic Source"):
            with st.form("add_source_form"):
                ns_name = st.text_input("Source Name (e.g. DAAD Policy News)")
                ns_url = st.text_input("Source URL (e.g. https://www.daad.de/en/)")
                ns_cat = st.selectbox("Category", ["competitors", "customers", "market", "internal"])
                ns_reason = st.text_area("Reason for Monitoring", value="Manual executive addition.")
                if st.form_submit_button("Add Source"):
                    if ns_name and ns_url:
                        a_res = api_post(f"/companies/{active_company_id}/sources", json_data={"name": ns_name, "url": ns_url, "category": ns_cat, "reason": ns_reason})
                        if a_res.status_code == 200:
                            st.success(f"Added source '{ns_name}'!")
                            st.rerun()

        # Source Table & Actions
        st.markdown("### Source Portfolio Table")
        status_filter = st.selectbox("Filter by Status", ["All", "approved", "suggested", "rejected", "dead"])

        filtered_sources = sources if status_filter == "All" else [s for s in sources if s["status"] == status_filter]
        st.write(f"Showing **{len(filtered_sources)}** sources:")

        for s in filtered_sources:
            colA, colB, colC, colD, colE = st.columns([3, 1, 1, 1, 1])
            with colA:
                st.markdown(f"**#{s['id']} [{s['name']}]({s['url']})** (`{s['category']}`)")
                st.caption(f"Health: `{s.get('health', 'ok')}` | Failures: `{s.get('consecutive_failures', 0)}` | {s['reason']}")
            with colB:
                st.caption(f"Status: **{s['status'].upper()}**")
            with colC:
                if s["status"] != "approved":
                    if st.button("Approve", key=f"app_{s['id']}"):
                        api_put(f"/sources/{s['id']}/approve")
                        st.rerun()
            with colD:
                if s["status"] != "rejected":
                    if st.button("Reject", key=f"rej_{s['id']}"):
                        api_put(f"/sources/{s['id']}/reject")
                        st.rerun()
            with colE:
                if st.button("Remove", key=f"del_{s['id']}"):
                    api_delete(f"/sources/{s['id']}")
                    st.rerun()


# -------------------------------------------------------------
# PAGE 6: INTELLIGENCE FEED (FILTERS: CATEGORY, DATE, RELEVANCE, IMPACT, VERIFICATION)
# -------------------------------------------------------------
elif page == "Intelligence Feed":
    st.subheader(f"⚡ Live Strategic Intelligence Feed — {active_company_name or 'No Company'}")
    st.markdown('<div class="page-desc">Algorithmic intelligence stream. Filter by category, domain, relevance score, impact, and verification status. Every signal contains a verbatim quoted excerpt from the live crawl.</div>', unsafe_allow_html=True)

    if not active_company_id:
        st.warning("Please select a company in the sidebar.")
    else:
        # Filter Bar
        f_col1, f_col2, f_col3 = st.columns(3)
        with f_col1:
            sel_cat = st.selectbox("Category", ["All", "competitors", "customers", "market", "internal"])
        with f_col2:
            sel_ver = st.selectbox("Verification Status", ["All", "verified", "reported", "unverified"])
        with f_col3:
            sel_urgency = st.selectbox("Urgency", ["All", "critical", "high", "medium", "low"])

        s_col1, s_col2 = st.columns(2)
        with s_col1:
            min_rank = st.slider("Minimum Final Rank Score", 0.0, 1.0, 0.0, 0.05)
        with s_col2:
            search_query = st.text_input("Filter by Keyword or Competitor Domain", placeholder="e.g. visa, WhatsApp, pricing, DAAD")

        # Fetch signals
        all_signals = api_get(f"/companies/{active_company_id}/signals?limit=150", default=[])

        # Apply in-memory filters
        filtered_signals = []
        for s in all_signals:
            if sel_cat != "All" and s["category"] != sel_cat:
                continue
            if sel_ver != "All" and s["verification_status"] != sel_ver:
                continue
            if sel_urgency != "All" and s["urgency"] != sel_urgency:
                continue
            if s["final_rank_score"] < min_rank:
                continue
            if search_query:
                q = search_query.lower()
                blob = f"{s['what_happened']} {s['evidence_snippet']} {s.get('source_url', '')}".lower()
                if q not in blob:
                    continue
            filtered_signals.append(s)

        st.markdown(f"**Found {len(filtered_signals)} Signals matching criteria:**")
        for sig in filtered_signals:
            urgency_class = f"tag-{sig['urgency']}" if sig['urgency'] in ("critical", "high", "med") else "tag-med"
            with st.container():
                st.markdown(f"""
                <div class="card-box">
                    <div style="display:flex; justify-content:space-between; margin-bottom:6px;">
                        <span style="font-weight:700; font-size:15px; color:#0f172a;">[Signal #{sig['id']}] {sig['what_happened']}</span>
                        <span>
                            <span class="{urgency_class}">{sig['urgency'].upper()}</span>
                            <span class="tag-verified">{sig['verification_status'].upper()}</span>
                            <span style="font-weight:800; color:#2563eb; font-size:12px; margin-left:8px;">Score: {sig['final_rank_score']:.2f}</span>
                        </span>
                    </div>
                    <div style="font-size:13px; color:#334155; margin:4px 0;">
                        <strong>Verbatim Evidence:</strong> <em>"{sig['evidence_snippet']}"</em> — Source: <a href="{sig['source_url']}" target="_blank">{sig['source_url']}</a>
                    </div>
                    <div style="font-size:13px; color:#334155; margin:4px 0;">
                        <strong>Why It Matters:</strong> {sig.get('why_it_matters') or 'Direct strategic impact.'}
                    </div>
                    <div class="inference-callout">
                        <strong>Strategic Interpretation:</strong> <code>{sig['interpretation']}</code>
                    </div>
                    <div style="font-size:11px; color:#64748b; margin-top:6px;">
                        {sig.get('rank_explanation')}
                    </div>
                </div>
                """, unsafe_allow_html=True)


# -------------------------------------------------------------
# PAGE 7: MONDAY BRIEF (HISTORY, EVIDENCE LINKS, ACTION TRACKER, DOWNLOAD MD/HTML)
# -------------------------------------------------------------
elif page == "Monday Brief":
    st.subheader(f"📋 Executive Strategic Briefing Room — {active_company_name or 'No Company'}")
    st.markdown('<div class="page-desc">Synthesized 10-section executive intelligence briefings. Track actionable recommendations, verify verbatim evidence links, and export markdown or HTML briefings.</div>', unsafe_allow_html=True)

    if not active_company_id:
        st.warning("Please select a company in the sidebar.")
    else:
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("Generate Current Brief Now", type="primary"):
                with st.spinner("Generating 10-section executive brief and validating all claims..."):
                    b_gen_res = api_post(f"/companies/{active_company_id}/briefs/generate")
                    if b_gen_res.status_code == 200:
                        st.success("New Executive Briefing generated!")
                        st.rerun()
                    else:
                        st.error(f"Failed to generate brief: {b_gen_res.text}")

        # Brief Selector
        briefs = api_get(f"/companies/{active_company_id}/briefs", default=[])
        if briefs:
            brief_dict = {f"Brief #{b['id']} — Period {b['period']} ({b['created_at'][:10]})": b["id"] for b in briefs}
            sel_brief_title = st.selectbox("Select Briefing", list(brief_dict.keys()))
            chosen_brief_id = brief_dict[sel_brief_title]

            brief_detail = api_get(f"/briefs/{chosen_brief_id}")

            tab_md, tab_html, tab_actions = st.tabs(["Markdown Brief", "Email HTML View", "Action Item Tracker"])

            with tab_md:
                # Downloads
                md_bytes = brief_detail["markdown"].encode("utf-8")
                st.download_button("⬇️ Download Markdown (.md)", data=md_bytes, file_name=f"brief_{active_company_name}_{brief_detail['period']}.md", mime="text/markdown")
                st.markdown(brief_detail["markdown"])

            with tab_html:
                html_resp = requests.get(f"{API_BASE_URL}/briefs/{chosen_brief_id}/html", timeout=10)
                html_code = html_resp.text if html_resp.status_code == 200 else ""
                st.download_button("⬇️ Download Email HTML (.html)", data=html_code.encode("utf-8"), file_name=f"brief_{active_company_name}_{brief_detail['period']}.html", mime="text/html")
                st.components.v1.html(html_code, height=750, scrolling=True)

            with tab_actions:
                st.markdown("### Action Item Tracker")
                actions = brief_detail.get("actions", [])
                if actions:
                    for act in actions:
                        with st.container():
                            ac1, ac2 = st.columns([3, 1])
                            with ac1:
                                st.markdown(f"**[{act['priority'].upper()}]** {act['text']}")
                                st.caption(f"Owner: `{act['owner']}` | Reason: {act.get('reason')}")
                            with ac2:
                                current_status = act.get("status", "open")
                                new_status = st.selectbox("Status", ["open", "in_progress", "completed", "dismissed"], index=["open", "in_progress", "completed", "dismissed"].index(current_status), key=f"act_stat_{act['id']}")
                                if new_status != current_status:
                                    api_patch(f"/actions/{act['id']}", json_data={"status": new_status})
                                    st.success(f"Status updated to '{new_status}'!")
                                    st.rerun()
                            st.markdown("---")
                else:
                    st.info("No actionable recommendations saved for this brief.")
        else:
            st.info("No briefings generated yet for this company. Click 'Generate Current Brief Now' above.")


# -------------------------------------------------------------
# PAGE 8: SETTINGS (BRIEFING TIME, TIME ZONE, FREQUENCIES)
# -------------------------------------------------------------
elif page == "Settings":
    st.subheader("⚙️ System Automation & Scheduler Settings")
    st.markdown('<div class="page-desc">Configure local APScheduler and cron frequencies, operational time zones, and crawler politeness rate limits. Stored persistently in the system_settings database table.</div>', unsafe_allow_html=True)

    current_settings = api_get("/jobs/system-settings", default={})

    with st.form("settings_form"):
        tz_val = st.text_input("Operational Time Zone", value=current_settings.get("timezone", "UTC"), help="e.g. UTC, Asia/Kolkata, America/New_York, Europe/London")
        weekly_cron = st.text_input("Weekly Briefing Schedule", value=current_settings.get("weekly_schedule", "mon 06:00"), help="e.g. mon 06:00 or standard cron")
        monthly_cron = st.text_input("Monthly Audit Schedule", value=current_settings.get("monthly_schedule", "1 06:00"), help="e.g. 1 06:00 (1st of month at 06:00)")
        crawl_delay = st.text_input("Per-Domain Crawl Rate Limit Delay (Seconds)", value=str(current_settings.get("crawl_delay", "2.0")))

        save_settings_btn = st.form_submit_button("Save Automation Settings", type="primary")

    if save_settings_btn:
        api_post("/jobs/system-settings", json_data={"key": "timezone", "value": tz_val})
        api_post("/jobs/system-settings", json_data={"key": "weekly_schedule", "value": weekly_cron})
        api_post("/jobs/system-settings", json_data={"key": "monthly_schedule", "value": monthly_cron})
        api_post("/jobs/system-settings", json_data={"key": "crawl_delay", "value": crawl_delay})
        st.success("Settings successfully updated in system_settings table!")
        st.rerun()


# -------------------------------------------------------------
# PAGE 9: JOBS (RUN LOGS, VISIBLE FAILURES, MANUAL TRIGGER BUTTONS)
# -------------------------------------------------------------
elif page == "Jobs":
    st.subheader("🤖 Autonomous Background Jobs & Execution Logs")
    st.markdown('<div class="page-desc">Manual triggers and comprehensive job execution history. Inspect real-time status and failure traces captured in job_logs.</div>', unsafe_allow_html=True)

    # Manual Trigger Buttons
    colA, colB, colC = st.columns(3)
    with colA:
        if st.button("🚀 Trigger Weekly Pipeline", type="primary"):
            with st.spinner("Executing crawl, rank, and brief generation..."):
                r = api_post(f"/jobs/weekly/trigger?company_id={active_company_id or ''}")
                if r.status_code == 200:
                    st.success("Weekly pipeline triggered!")
                    st.json(r.json())
                else:
                    st.error(f"Execution failed: {r.text}")
    with colB:
        if st.button("🔍 Trigger Monthly Source Audit"):
            with st.spinner("Auditing dead URLs and source portfolio health..."):
                r = api_post(f"/jobs/monthly-audit/trigger?company_id={active_company_id or ''}")
                if r.status_code == 200:
                    st.success("Monthly audit completed!")
                    st.json(r.json())
                else:
                    st.error(f"Execution failed: {r.text}")
    with colC:
        if st.button("⚠️ Force Failure Test"):
            with st.spinner("Triggering forced failure to test error logging..."):
                r = api_post("/jobs/weekly/trigger?fail_for_test=true")
                st.warning("Forced failure triggered! Check logs below.")
                st.json(r.json())

    st.markdown("---")
    st.markdown("### Execution History (`job_logs`)")
    logs = api_get("/jobs/logs?limit=50", default=[])
    if logs:
        for l in logs:
            status = l["status"]
            status_icon = "✅" if status == "success" else "❌" if status == "failed" else "⏳"
            with st.expander(f"{status_icon} Job #{l['id']} — {l['job_type'].upper()} ({status.upper()}) | Started: {l['started_at']}"):
                st.write(f"**Started**: {l['started_at']}")
                st.write(f"**Finished**: {l.get('finished_at') or 'Running...'}")
                if l.get("error"):
                    st.error(f"**Captured Failure Error**: {l['error']}")
    else:
        st.info("No job execution logs found.")
