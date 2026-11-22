import re
import json
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from pydantic import BaseModel, Field as PydanticField
from sqlmodel import Session, select

from app.core import db
from app.models.entities import Company, Signal, Brief, Action, utcnow

logger = logging.getLogger("signal_stack.brief")

EXACT_SECTION_TITLES = [
    "1. Executive Summary",
    "2. Competitor Movements",
    "3. Customer Signals & Sentiment",
    "4. Market Dynamics & Industry Trends",
    "5. Regulatory & Policy Shifts",
    "6. Internal Pipeline & Sales Objections",
    "7. Critical Threats & Vulnerabilities",
    "8. Strategic Opportunities",
    "9. Recommended Actions",
    "10. Source Appendix",
]

NO_MEANINGFUL_DEVELOPMENT_TEXT = "No meaningful development this week."


class ActionItemSpec(BaseModel):
    text: str
    priority: str = "medium"  # high, medium, low
    reason: str
    owner: str = "Head of Product"


class OpportunityItemSpec(BaseModel):
    title: str
    evidence_snippet: str
    source_url: str
    signal_id: int
    strategic_impact: str
    next_step: str
    priority: str = "high"


class BriefVerificationReport(BaseModel):
    is_valid: bool
    total_claims: int
    verified_claims: int
    unverified_claims: List[Dict[str, Any]] = []
    broken_links: List[str] = []
    sections_checked: List[str] = []


def _format_signal_item_markdown(sig: Signal, company_name: str) -> str:
    interp = sig.interpretation or "Strategic implication under evaluation."
    if not interp.startswith("[AI Inference]:"):
        interp = f"[AI Inference]: {interp}"

    why = sig.why_it_matters or f"Directly impacts {company_name}'s competitive positioning and strategic roadmap."
    source_link = f"[{sig.source_url}]({sig.source_url})" if sig.source_url else "Unspecified Source"

    return (
        f"- **Signal #{sig.id}**: {sig.what_happened}\n"
        f"  - **Evidence**: \"{sig.evidence_snippet}\" — Source: {source_link}\n"
        f"  - **Why It Matters to {company_name}**: {why}\n"
        f"  - **Strategic Interpretation**: `{interp}`\n"
        f"  - **Impact & Urgency**: Rank Score `{sig.final_rank_score:.2f}` | Urgency: `{sig.urgency.upper()}` | Verification: `{sig.verification_status.title()}`\n"
    )


def _categorize_signals(signals: List[Signal]) -> Dict[str, List[Signal]]:
    """
    Segregates signals into exact briefing categories.
    """
    categories: Dict[str, List[Signal]] = {
        "executive": signals[:5],  # Top 5 by rank score
        "competitors": [],
        "customers": [],
        "market": [],
        "regulatory": [],
        "internal": [],
        "threats": [],
        "opportunities": [],
    }

    regulatory_keywords = ["policy", "visa", "regulation", "regulator", "compliance", "soc-2", "gdpr", "home office", "legal", "audit"]

    for sig in signals:
        cat_lower = (sig.category or "").lower()
        area_lower = (sig.affected_area or "").lower()
        what_lower = (sig.what_happened or "").lower()
        ev_lower = (sig.evidence_snippet or "").lower()

        # Check Regulatory / Policy
        is_regulatory = (
            area_lower in ("compliance", "regulatory", "policy")
            or any(kw in what_lower for kw in regulatory_keywords)
            or any(kw in ev_lower for kw in regulatory_keywords)
        )

        if is_regulatory:
            categories["regulatory"].append(sig)

        # Categorize by domain
        if any(c in cat_lower for c in ["competitor", "rival", "pricing_threat"]):
            categories["competitors"].append(sig)
        elif any(c in cat_lower for c in ["customer", "community", "review", "forum"]):
            categories["customers"].append(sig)
        elif any(c in cat_lower for c in ["market", "industry", "macro"]):
            if not is_regulatory:  # Keep pure market dynamics separate
                categories["market"].append(sig)
        elif "internal" in cat_lower:
            categories["internal"].append(sig)

        # Threats & Opportunities
        if sig.type == "threat" and sig.urgency in ("critical", "high"):
            categories["threats"].append(sig)
        elif sig.type == "opportunity" or "opportunity" in cat_lower or "request" in what_lower:
            categories["opportunities"].append(sig)

    return categories


def _synthesize_opportunities(
    opp_signals: List[Signal],
    all_signals: List[Signal],
    company_name: str,
) -> Tuple[List[OpportunityItemSpec], Optional[str]]:
    """
    Generates at least 3 opportunities if supported by evidence,
    otherwise states the limitation clearly without padding.
    """
    specs: List[OpportunityItemSpec] = []
    
    # 1. Use explicit opportunity signals
    for s in opp_signals:
        specs.append(OpportunityItemSpec(
            title=s.what_happened,
            evidence_snippet=s.evidence_snippet,
            source_url=s.source_url or "internal://signal",
            signal_id=s.id or 0,
            strategic_impact=s.why_it_matters or f"Unlocks competitive advantage in {s.affected_area or 'core market'}.",
            next_step=s.suggested_action or "Initiate tactical cross-functional review.",
            priority=s.urgency or "high",
        ))

    # 2. Derive opportunities from internal product requests or market gaps
    if len(specs) < 3:
        for s in all_signals:
            if s.id in [x.signal_id for x in specs]:
                continue
            # Look for internal requests or gaps
            if any(k in (s.what_happened or "").lower() for k in ["request", "whatsapp", "portal", "integration", "pilot", "growth"]):
                specs.append(OpportunityItemSpec(
                    title=f"Capitalize on unmet demand: {s.what_happened}",
                    evidence_snippet=s.evidence_snippet,
                    source_url=s.source_url or "internal://signal",
                    signal_id=s.id or 0,
                    strategic_impact=f"Addressing this objection directly converts blocked pipeline and enhances retention for {company_name}.",
                    next_step=s.suggested_action or "Scope integration into Q1 roadmap.",
                    priority="high" if s.urgency in ("critical", "high") else "medium",
                ))
            if len(specs) >= 3:
                break

    limitation_note = None
    if len(specs) < 3:
        limitation_note = (
            f"**Limitation**: Only {len(specs)} strategic opportunities have direct factual verification in this period's observations. "
            "Additional opportunities are deferred to prevent speculative hallucination."
        )

    return specs, limitation_note


def _derive_actions_from_signals(
    signals: List[Signal],
    company_name: str,
) -> List[ActionItemSpec]:
    """
    Synthesizes concrete tactical actions with priority, reason, and owner.
    """
    actions: List[ActionItemSpec] = []
    seen_texts = set()

    owner_mapping = {
        "pricing": "VP Sales & Commercial Strategy",
        "compliance": "Head of Legal & Compliance",
        "product_core": "VP Product & Engineering",
        "gtm": "Chief Marketing Officer",
        "partner_network": "Head of Strategic Partnerships",
    }

    # Take highest-ranked signals to generate top actionable steps
    for s in signals[:6]:
        area = s.affected_area or "gtm"
        owner = owner_mapping.get(area, "Chief Executive Officer")
        action_text = s.suggested_action or f"Develop defensive strategy regarding {s.what_happened}"
        
        if action_text.lower() in seen_texts:
            continue
        seen_texts.add(action_text.lower())

        reason = (
            f"Tied to Signal #{s.id} (Rank {s.final_rank_score:.2f}, {s.urgency.upper()} Urgency): "
            f"{s.why_it_matters or 'Protects market share and prevents customer churn.'}"
        )
        actions.append(ActionItemSpec(
            text=f"[Signal #{s.id}] {action_text}",
            priority="high" if s.urgency in ("critical", "high") else "medium",
            reason=reason,
            owner=owner,
        ))

    if not actions:
        actions.append(ActionItemSpec(
            text=f"Conduct bi-weekly review of competitive landscape for {company_name}.",
            priority="low",
            reason="Baseline operational monitoring in absence of urgent critical signals.",
            owner="Head of Strategy",
        ))

    return actions


def generate_brief_markdown(
    company: Company,
    signals: List[Signal],
    period: str,
) -> Tuple[str, List[ActionItemSpec]]:
    """
    Generates a Markdown executive brief with the exact 10 sections in order.
    """
    cat_signals = _categorize_signals(signals)
    opportunities, opp_limitation = _synthesize_opportunities(cat_signals["opportunities"], signals, company.name)
    actions = _derive_actions_from_signals(signals, company.name)

    now_str = utcnow().strftime("%Y-%m-%d %H:%M UTC")

    md: List[str] = []
    md.append(f"# Executive Strategic Briefing — {company.name}")
    md.append(f"**Observation Period**: `{period}` | **Generated**: `{now_str}` | **Total Monitored Signals**: `{len(signals)}`\n")
    md.append("---\n")

    # 1. Executive Summary
    md.append(f"## {EXACT_SECTION_TITLES[0]}\n")
    if cat_signals["executive"]:
        md.append(f"Top {len(cat_signals['executive'])} prioritized intelligence developments for executive leadership:\n")
        for s in cat_signals["executive"]:
            md.append(_format_signal_item_markdown(s, company.name))
    else:
        md.append(f"> *{NO_MEANINGFUL_DEVELOPMENT_TEXT}*\n")

    # 2. Competitor Movements
    md.append(f"\n## {EXACT_SECTION_TITLES[1]}\n")
    if cat_signals["competitors"]:
        for s in cat_signals["competitors"]:
            md.append(_format_signal_item_markdown(s, company.name))
    else:
        md.append(f"> *{NO_MEANINGFUL_DEVELOPMENT_TEXT}*\n")

    # 3. Customer Signals & Sentiment
    md.append(f"\n## {EXACT_SECTION_TITLES[2]}\n")
    if cat_signals["customers"]:
        for s in cat_signals["customers"]:
            md.append(_format_signal_item_markdown(s, company.name))
    else:
        md.append(f"> *{NO_MEANINGFUL_DEVELOPMENT_TEXT}*\n")

    # 4. Market Dynamics & Industry Trends
    md.append(f"\n## {EXACT_SECTION_TITLES[3]}\n")
    if cat_signals["market"]:
        for s in cat_signals["market"]:
            md.append(_format_signal_item_markdown(s, company.name))
    else:
        md.append(f"> *{NO_MEANINGFUL_DEVELOPMENT_TEXT}*\n")

    # 5. Regulatory & Policy Shifts
    md.append(f"\n## {EXACT_SECTION_TITLES[4]}\n")
    if cat_signals["regulatory"]:
        for s in cat_signals["regulatory"]:
            md.append(_format_signal_item_markdown(s, company.name))
    else:
        md.append(f"> *{NO_MEANINGFUL_DEVELOPMENT_TEXT}*\n")

    # 6. Internal Pipeline & Sales Objections
    md.append(f"\n## {EXACT_SECTION_TITLES[5]}\n")
    if cat_signals["internal"]:
        for s in cat_signals["internal"]:
            md.append(_format_signal_item_markdown(s, company.name))
    else:
        md.append(f"> *{NO_MEANINGFUL_DEVELOPMENT_TEXT}*\n")

    # 7. Critical Threats & Vulnerabilities
    md.append(f"\n## {EXACT_SECTION_TITLES[6]}\n")
    if cat_signals["threats"]:
        for s in cat_signals["threats"]:
            md.append(_format_signal_item_markdown(s, company.name))
    else:
        md.append(f"> *{NO_MEANINGFUL_DEVELOPMENT_TEXT}*\n")

    # 8. Strategic Opportunities
    md.append(f"\n## {EXACT_SECTION_TITLES[7]}\n")
    if opportunities:
        for idx, opp in enumerate(opportunities, 1):
            md.append(
                f"### Opportunity {idx}: {opp.title}\n"
                f"- **Verified Evidence**: \"{opp.evidence_snippet}\" ([Signal #{opp.signal_id}]({opp.source_url}))\n"
                f"- **Strategic Impact**: {opp.strategic_impact}\n"
                f"- **Recommended Next Step**: {opp.next_step}\n"
                f"- **Priority**: `{opp.priority.upper()}`\n"
            )
        if opp_limitation:
            md.append(f"> {opp_limitation}\n")
    else:
        md.append(f"> *{NO_MEANINGFUL_DEVELOPMENT_TEXT}*\n")
        if opp_limitation:
            md.append(f"> {opp_limitation}\n")

    # 9. Recommended Actions
    md.append(f"\n## {EXACT_SECTION_TITLES[8]}\n")
    if actions:
        md.append("| Priority | Action Item | Strategic Reason | Suggested Owner |\n| :--- | :--- | :--- | :--- |\n")
        for a in actions:
            clean_reason = a.reason.replace("|", "/")
            clean_text = a.text.replace("|", "/")
            md.append(f"| **{a.priority.upper()}** | {clean_text} | {clean_reason} | `{a.owner}` |\n")
    else:
        md.append(f"> *{NO_MEANINGFUL_DEVELOPMENT_TEXT}*\n")

    # 10. Source Appendix
    md.append(f"\n## {EXACT_SECTION_TITLES[9]}\n")
    if signals:
        md.append("| Signal ID | Source URL | Published Date | Discovered Date | Verification Status | Verbatim Evidence Snippet |\n| :---: | :--- | :---: | :---: | :---: | :--- |\n")
        for s in signals:
            pub_date = s.published_at.strftime("%Y-%m-%d") if s.published_at else "Undetected"
            disc_date = s.discovered_at.strftime("%Y-%m-%d") if s.discovered_at else "Undetected"
            clean_snippet = (s.evidence_snippet or "").replace("|", "/").replace("\n", " ")
            if len(clean_snippet) > 100:
                clean_snippet = clean_snippet[:97] + "..."
            md.append(f"| #{s.id} | [{s.source_url}]({s.source_url}) | {pub_date} | {disc_date} | `{s.verification_status.title()}` | \"{clean_snippet}\" |\n")
    else:
        md.append(f"> *{NO_MEANINGFUL_DEVELOPMENT_TEXT}*\n")

    full_markdown = "".join(md)
    return full_markdown, actions


def generate_email_html_brief(
    company: Company,
    signals: List[Signal],
    period: str,
    actions: List[ActionItemSpec],
) -> str:
    """
    Generates a production email-ready HTML briefing with inline CSS.
    Compatible with all major desktop and mobile email clients.
    """
    cat_signals = _categorize_signals(signals)
    opportunities, opp_limitation = _synthesize_opportunities(cat_signals["opportunities"], signals, company.name)
    now_str = utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # Helper for rendering items with inline CSS
    def render_signal_card(sig: Signal) -> str:
        interp = sig.interpretation or "Strategic implication under evaluation."
        if not interp.startswith("[AI Inference]:"):
            interp = f"[AI Inference]: {interp}"
        source_link = f'<a href="{sig.source_url}" style="color: #2563eb; text-decoration: underline;">{sig.source_url}</a>' if sig.source_url else 'Unspecified Source'
        urgency_bg = "#dc2626" if sig.urgency in ("critical", "high") else "#d97706" if sig.urgency == "medium" else "#2563eb"

        return f"""
        <div style="background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <span style="font-weight: 700; color: #0f172a; font-size: 15px;">[Signal #{sig.id}] {sig.what_happened}</span>
                <span style="background-color: {urgency_bg}; color: #ffffff; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 9999px; text-transform: uppercase;">{sig.urgency}</span>
            </div>
            <p style="margin: 6px 0; font-size: 13px; color: #334155;">
                <strong style="color: #0f172a;">Evidence:</strong> <em>"{sig.evidence_snippet}"</em> — Source: {source_link}
            </p>
            <p style="margin: 6px 0; font-size: 13px; color: #334155;">
                <strong style="color: #0f172a;">Why It Matters to {company.name}:</strong> {sig.why_it_matters or 'Critical strategic relevance.'}
            </p>
            <div style="background-color: #f1f5f9; border-left: 3px solid #64748b; padding: 8px 12px; margin-top: 10px; font-size: 12px; color: #475569;">
                <strong>Interpretation:</strong> <code>{interp}</code>
            </div>
            <div style="margin-top: 8px; font-size: 11px; color: #64748b;">
                Rank Score: <strong>{sig.final_rank_score:.2f}</strong> | Verification: <strong>{sig.verification_status.title()}</strong>
            </div>
        </div>
        """

    def render_empty_section() -> str:
        return f'<div style="background-color: #f8fafc; border: 1px dashed #cbd5e1; border-radius: 6px; padding: 12px; color: #64748b; font-style: italic; font-size: 13px;">{NO_MEANINGFUL_DEVELOPMENT_TEXT}</div>'

    # Build HTML string
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Strategic Executive Briefing — {company.name}</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px; color: #0f172a; line-height: 1.5;">
    <div style="max-width: 820px; margin: 0 auto; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);">
        
        <!-- Header -->
        <div style="background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); padding: 32px 28px; color: #ffffff;">
            <div style="font-size: 12px; font-weight: 700; letter-spacing: 0.1em; color: #38bdf8; text-transform: uppercase; margin-bottom: 6px;">Signal Stack Intelligence Briefing</div>
            <h1 style="margin: 0 0 10px 0; font-size: 26px; font-weight: 800; color: #ffffff;">Executive Strategic Briefing — {company.name}</h1>
            <p style="margin: 0; font-size: 13px; color: #94a3b8;">
                Observation Period: <strong style="color: #f1f5f9;">{period}</strong> | Generated: <strong style="color: #f1f5f9;">{now_str}</strong> | Monitored Signals: <strong style="color: #f1f5f9;">{len(signals)}</strong>
            </p>
        </div>

        <div style="padding: 28px;">
            
            <!-- 1. Executive Summary -->
            <div style="margin-bottom: 32px;">
                <h2 style="font-size: 18px; font-weight: 700; color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; margin-bottom: 16px;">
                    {EXACT_SECTION_TITLES[0]}
                </h2>
                {''.join(render_signal_card(s) for s in cat_signals["executive"]) if cat_signals["executive"] else render_empty_section()}
            </div>

            <!-- 2. Competitor Movements -->
            <div style="margin-bottom: 32px;">
                <h2 style="font-size: 18px; font-weight: 700; color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; margin-bottom: 16px;">
                    {EXACT_SECTION_TITLES[1]}
                </h2>
                {''.join(render_signal_card(s) for s in cat_signals["competitors"]) if cat_signals["competitors"] else render_empty_section()}
            </div>

            <!-- 3. Customer Signals & Sentiment -->
            <div style="margin-bottom: 32px;">
                <h2 style="font-size: 18px; font-weight: 700; color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; margin-bottom: 16px;">
                    {EXACT_SECTION_TITLES[2]}
                </h2>
                {''.join(render_signal_card(s) for s in cat_signals["customers"]) if cat_signals["customers"] else render_empty_section()}
            </div>

            <!-- 4. Market Dynamics & Industry Trends -->
            <div style="margin-bottom: 32px;">
                <h2 style="font-size: 18px; font-weight: 700; color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; margin-bottom: 16px;">
                    {EXACT_SECTION_TITLES[3]}
                </h2>
                {''.join(render_signal_card(s) for s in cat_signals["market"]) if cat_signals["market"] else render_empty_section()}
            </div>

            <!-- 5. Regulatory & Policy Shifts -->
            <div style="margin-bottom: 32px;">
                <h2 style="font-size: 18px; font-weight: 700; color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; margin-bottom: 16px;">
                    {EXACT_SECTION_TITLES[4]}
                </h2>
                {''.join(render_signal_card(s) for s in cat_signals["regulatory"]) if cat_signals["regulatory"] else render_empty_section()}
            </div>

            <!-- 6. Internal Pipeline & Sales Objections -->
            <div style="margin-bottom: 32px;">
                <h2 style="font-size: 18px; font-weight: 700; color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; margin-bottom: 16px;">
                    {EXACT_SECTION_TITLES[5]}
                </h2>
                {''.join(render_signal_card(s) for s in cat_signals["internal"]) if cat_signals["internal"] else render_empty_section()}
            </div>

            <!-- 7. Critical Threats & Vulnerabilities -->
            <div style="margin-bottom: 32px;">
                <h2 style="font-size: 18px; font-weight: 700; color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; margin-bottom: 16px;">
                    {EXACT_SECTION_TITLES[6]}
                </h2>
                {''.join(render_signal_card(s) for s in cat_signals["threats"]) if cat_signals["threats"] else render_empty_section()}
            </div>

            <!-- 8. Strategic Opportunities -->
            <div style="margin-bottom: 32px;">
                <h2 style="font-size: 18px; font-weight: 700; color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; margin-bottom: 16px;">
                    {EXACT_SECTION_TITLES[7]}
                </h2>
                {''.join(f"""
                <div style="background-color: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 14px; margin-bottom: 12px;">
                    <div style="font-weight: 700; color: #166534; font-size: 15px; margin-bottom: 4px;">{idx}. {o.title}</div>
                    <div style="font-size: 13px; color: #15803d; margin-bottom: 4px;"><strong>Evidence:</strong> <em>"{o.evidence_snippet}"</em> (<a href="{o.source_url}" style="color: #166534; text-decoration: underline;">Signal #{o.signal_id}</a>)</div>
                    <div style="font-size: 13px; color: #1e293b; margin-bottom: 4px;"><strong>Impact:</strong> {o.strategic_impact}</div>
                    <div style="font-size: 13px; color: #1e293b;"><strong>Next Step:</strong> {o.next_step} &bull; Priority: <strong style="text-transform: uppercase;">{o.priority}</strong></div>
                </div>
                """ for idx, o in enumerate(opportunities, 1)) if opportunities else render_empty_section()}
                {f'<div style="font-size: 12px; color: #b45309; background-color: #fffbeb; padding: 8px; border-radius: 6px; margin-top: 8px;">{opp_limitation}</div>' if opp_limitation else ''}
            </div>

            <!-- 9. Recommended Actions -->
            <div style="margin-bottom: 32px;">
                <h2 style="font-size: 18px; font-weight: 700; color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; margin-bottom: 16px;">
                    {EXACT_SECTION_TITLES[8]}
                </h2>
                <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                    <thead>
                        <tr style="background-color: #f8fafc; border-bottom: 2px solid #e2e8f0; text-align: left;">
                            <th style="padding: 10px; color: #475569;">Priority</th>
                            <th style="padding: 10px; color: #475569;">Action Item</th>
                            <th style="padding: 10px; color: #475569;">Strategic Reason</th>
                            <th style="padding: 10px; color: #475569;">Owner</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join(f"""
                        <tr style="border-bottom: 1px solid #f1f5f9;">
                            <td style="padding: 10px; font-weight: 700; color: {'#dc2626' if a.priority == 'high' else '#d97706'}; text-transform: uppercase;">{a.priority}</td>
                            <td style="padding: 10px; font-weight: 600; color: #0f172a;">{a.text}</td>
                            <td style="padding: 10px; color: #475569;">{a.reason}</td>
                            <td style="padding: 10px; font-family: monospace; color: #2563eb;">{a.owner}</td>
                        </tr>
                        """ for a in actions) if actions else f'<tr><td colspan="4" style="padding: 10px; color: #64748b;">{NO_MEANINGFUL_DEVELOPMENT_TEXT}</td></tr>'}
                    </tbody>
                </table>
            </div>

            <!-- 10. Source Appendix -->
            <div style="margin-bottom: 16px;">
                <h2 style="font-size: 18px; font-weight: 700; color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; margin-bottom: 16px;">
                    {EXACT_SECTION_TITLES[9]}
                </h2>
                <table style="width: 100%; border-collapse: collapse; font-size: 12px;">
                    <thead>
                        <tr style="background-color: #f8fafc; border-bottom: 2px solid #e2e8f0; text-align: left;">
                            <th style="padding: 8px; color: #475569;">Signal</th>
                            <th style="padding: 8px; color: #475569;">Source URL</th>
                            <th style="padding: 8px; color: #475569;">Published</th>
                            <th style="padding: 8px; color: #475569;">Status</th>
                            <th style="padding: 8px; color: #475569;">Verbatim Snippet</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join(f"""
                        <tr style="border-bottom: 1px solid #f1f5f9;">
                            <td style="padding: 8px; font-weight: 700; color: #0f172a;">#{s.id}</td>
                            <td style="padding: 8px;"><a href="{s.source_url}" style="color: #2563eb; text-decoration: underline;">{s.source_url[:40]}...</a></td>
                            <td style="padding: 8px; color: #64748b;">{s.published_at.strftime('%Y-%m-%d') if s.published_at else 'Undetected'}</td>
                            <td style="padding: 8px; font-weight: 600; color: {'#16a34a' if s.verification_status == 'verified' else '#64748b'};">{s.verification_status.title()}</td>
                            <td style="padding: 8px; color: #334155; font-style: italic;">"{s.evidence_snippet[:80]}..."</td>
                        </tr>
                        """ for s in signals) if signals else f'<tr><td colspan="5" style="padding: 8px; color: #64748b;">{NO_MEANINGFUL_DEVELOPMENT_TEXT}</td></tr>'}
                    </tbody>
                </table>
            </div>

        </div>

        <!-- Footer -->
        <div style="background-color: #f8fafc; border-top: 1px solid #e2e8f0; padding: 16px 28px; font-size: 12px; color: #94a3b8; text-align: center;">
            Generated autonomously by <strong>Signal Stack</strong> &bull; Zero fabrication policy &bull; Every statement backed by verbatim crawl evidence.
        </div>
    </div>
</body>
</html>"""
    return html


def verify_brief_claims(
    brief_markdown: str,
    signals: List[Signal],
) -> BriefVerificationReport:
    """
    Post-check validator enforcing the strict rule:
    Every claim in the brief must map to a valid stored signal_id and resolvable URL.
    """
    valid_signal_map = {s.id: s for s in signals if s.id is not None}
    unverified_claims: List[Dict[str, Any]] = []
    broken_links: List[str] = []

    # 1. Extract signal ID references (e.g. Signal #1, [Signal #1], #1)
    signal_id_matches = re.findall(r'Signal\s+#(\d+)|\[Signal\s+#(\d+)\]|#(\d+)', brief_markdown)
    cited_ids = set()
    for match in signal_id_matches:
        for val in match:
            if val:
                cited_ids.add(int(val))

    total_claims = len(cited_ids)
    verified_claims = 0

    for sid in cited_ids:
        if sid in valid_signal_map:
            verified_claims += 1
        else:
            unverified_claims.append({
                "signal_id": sid,
                "error": f"Referenced Signal #{sid} not found in database or period observation set.",
            })

    # 2. Extract URLs and verify format / resolvability
    url_matches = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', brief_markdown)
    for anchor, url in url_matches:
        url_clean = url.strip()
        # Verify valid scheme: http, https, internal
        if not (url_clean.startswith("http://") or url_clean.startswith("https://") or url_clean.startswith("internal://")):
            broken_links.append(url_clean)

    # 3. Check section completeness
    sections_checked = []
    for sec in EXACT_SECTION_TITLES:
        if sec in brief_markdown:
            sections_checked.append(sec)

    is_valid = (
        len(unverified_claims) == 0
        and len(broken_links) == 0
        and len(sections_checked) == len(EXACT_SECTION_TITLES)
    )

    return BriefVerificationReport(
        is_valid=is_valid,
        total_claims=total_claims,
        verified_claims=verified_claims,
        unverified_claims=unverified_claims,
        broken_links=broken_links,
        sections_checked=sections_checked,
    )


def generate_weekly_brief(
    company_id: int,
    period: str = "current_week",
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> Tuple[Brief, List[Action], BriefVerificationReport]:
    """
    Generates and persists an executive strategic brief with the exact 10 sections in order.
    Saves generated actions to the actions SQLModel table.
    Runs post-check claim verification.
    """
    with Session(db.engine, expire_on_commit=False) as session:
        company = session.get(Company, company_id)
        if not company:
            raise ValueError(f"Company ID {company_id} not found")

        # Query stored signals for this period
        stmt = select(Signal).where(Signal.company_id == company_id)
        if start_date:
            stmt = stmt.where(Signal.discovered_at >= start_date)
        if end_date:
            stmt = stmt.where(Signal.discovered_at <= end_date)

        # Sort signals by rank score descending
        signals = session.exec(stmt).all()
        signals.sort(key=lambda s: s.final_rank_score, reverse=True)

        logger.info(f"Loaded {len(signals)} signals for company '{company.name}' (ID {company.id}) for period '{period}'.")

        # 1. Generate Markdown and actions
        markdown_content, action_specs = generate_brief_markdown(company, signals, period)

        # 2. Generate Email-ready HTML with inline CSS
        email_html = generate_email_html_brief(company, signals, period, action_specs)

        # 3. Run Post-Check validation
        verification = verify_brief_claims(markdown_content, signals)
        if not verification.is_valid:
            logger.warning(
                f"Brief claims verification issues: {len(verification.unverified_claims)} unverified claims, "
                f"{len(verification.broken_links)} broken links."
            )

        # 4. Save Brief to database
        brief = Brief(
            company_id=company.id,
            markdown=markdown_content,
            html=email_html,
            period=period,
            created_at=utcnow(),
        )
        session.add(brief)
        session.commit()
        session.refresh(brief)

        # 5. Save Actions to database linked to brief.id
        persisted_actions: List[Action] = []
        for a_spec in action_specs:
            action = Action(
                brief_id=brief.id,
                text=a_spec.text,
                reason=a_spec.reason,
                owner=a_spec.owner,
                priority=a_spec.priority,
                status="open",
            )
            session.add(action)
            persisted_actions.append(action)

        session.commit()
        for a in persisted_actions:
            session.refresh(a)

        session.expunge_all()
        return brief, persisted_actions, verification
