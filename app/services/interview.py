import logging
import re
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field as PydanticField
from sqlmodel import Session, select

from app.core.config import settings
from app.core import db
from app.core.llm import generate_json
from app.models.entities import Company, ProfileField, InterviewTurn, utcnow

logger = logging.getLogger("signal_stack.interview")

# 10 core strategic intelligence themes
STRATEGIC_THEMES = [
    {
        "id": "differentiation",
        "name": "Core Value Proposition & Unique Differentiation",
        "description": "How the solution uniquely solves the core problem vs alternative products or manual methods.",
    },
    {
        "id": "icp_customers",
        "name": "Ideal Customer Profile & Segmentation",
        "description": "Primary high-value customer profile, decision makers, and segments with highest retention.",
    },
    {
        "id": "competitors",
        "name": "Competitive Landscape & Threat Perception",
        "description": "Primary direct competitors, emerging alternatives, and aggressive market entrants.",
    },
    {
        "id": "pricing_monetization",
        "name": "Pricing Model & Unit Economics",
        "description": "Pricing structure, billing tiers, discounting dynamics, and average contract values.",
    },
    {
        "id": "gtm_distribution",
        "name": "Go-to-Market & Acquisition Channels",
        "description": "Primary acquisition motion (PLG, direct sales, channel partners, inbound organic) and velocity.",
    },
    {
        "id": "product_defensibility",
        "name": "Product Moat & Switching Costs",
        "description": "Technical moats, proprietary datasets, integration locks, or network effects preventing churn.",
    },
    {
        "id": "regulatory_risks",
        "name": "Regulatory, Compliance & Platform Dependencies",
        "description": "External regulatory hurdles, compliance liabilities, or third-party platform dependencies.",
    },
    {
        "id": "strategic_vulnerabilities",
        "name": "Strategic Blindspots & Weaknesses",
        "description": "The company's biggest vulnerability, operational bottlenecks, or areas competitors attack.",
    },
    {
        "id": "unit_economics",
        "name": "Key Metrics, Conversion & Retention",
        "description": "North star performance metrics, churn rates, customer payback periods, and conversion rates.",
    },
    {
        "id": "future_roadmap",
        "name": "Forward Roadmap & Strategic Expansion",
        "description": "High-priority roadmap bets, geographic expansion, or new feature lines planned for the next 6-12 months.",
    },
]


class GeneratedQuestionSchema(BaseModel):
    question: str
    theme: str
    reasoning: str


class FollowUpCheckSchema(BaseModel):
    needs_follow_up: bool
    follow_up_question: Optional[str] = None
    reasoning: Optional[str] = None


class ExtractedInterviewFactsSchema(BaseModel):
    facts: List[Dict[str, str]] = PydanticField(
        default=[],
        description="List of extracted facts with 'key', 'value', and 'evidence_snippet'",
    )


def calculate_semantic_overlap(text1: str, text2: str) -> float:
    """Calculate simple word-level Jaccard similarity to prevent duplicate questions."""
    words1 = set(re.findall(r"\w+", text1.lower()))
    words2 = set(re.findall(r"\w+", text2.lower()))
    if not words1 or not words2:
        return 0.0
    intersection = words1.intersection(words2)
    union = words1.union(words2)
    return len(intersection) / len(union)


def _heuristic_industry_question(
    company_name: str,
    industry: str,
    theme_id: str,
    previous_questions: List[str],
) -> str:
    """
    Deterministic industry-contextualized question generator.
    Phrased distinctly for each company's domain.
    """
    ind_lower = (industry or "").lower()
    comp = company_name

    # Domain-specific question templates
    if any(k in ind_lower for k in ["edtech", "education", "university", "study"]):
        templates = {
            "differentiation": f"In the crowded study abroad and education advisory space, what is {comp}'s distinct edge over traditional overseas education consultancies?",
            "icp_customers": f"What specific student profile or university tier generates the highest conversion and placement rate for {comp}?",
            "competitors": f"Which regional consultancies or digital edtech portals does {comp} encounter most frequently in student head-to-head evaluations?",
            "pricing_monetization": f"How is {comp}'s business model split between direct student advisory fees versus institutional commissions from partner universities?",
            "gtm_distribution": f"What is {comp}'s primary student acquisition channel—campus partnerships, digital search marketing, or student word-of-mouth referrals?",
            "product_defensibility": f"Does {comp} possess proprietary university admissions data, visa algorithm models, or exclusive institutional agreements that competitors cannot easily copy?",
            "regulatory_risks": f"How do shifting international student visa policies (e.g. in the UK, Canada, or Australia) impact {comp}'s application volume?",
            "strategic_vulnerabilities": f"What is the single biggest operational bottleneck in {comp}'s workflow—counselor capacity, visa processing delays, or university response times?",
            "unit_economics": f"What is {comp}'s key enrollment success rate, and how do you track student-to-enrolled conversion efficiency?",
            "future_roadmap": f"Which new destination countries, test prep verticals, or digital platform features are top priorities for {comp} over the next 12 months?",
        }
    elif any(k in ind_lower for k in ["fintech", "payment", "bank", "financial"]):
        templates = {
            "differentiation": f"How does {comp} differentiate its transaction infrastructure and merchant fee economics against incumbent payment gateways?",
            "icp_customers": f"What size merchant or platform developer represents {comp}'s highest lifetime value (LTV) cohort?",
            "competitors": f"Which payment service providers or regional fintech challengers represent the most aggressive competitive pressure for {comp}?",
            "pricing_monetization": f"What is {comp}'s fee structure—interchange-plus, flat percentage per transaction, or SaaS subscription?",
            "gtm_distribution": f"How does {comp} acquire new merchants—developer-led self-serve integration or enterprise sales outreach?",
            "product_defensibility": f"What technological or regulatory moats (such as banking licenses or fraud models) protect {comp} from disintermediation?",
            "regulatory_risks": f"How does {comp} manage cross-border payment compliance, AML/KYC regulations, and state financial oversight?",
            "strategic_vulnerabilities": f"What is {comp}'s primary exposure—fraud loss rates, partner bank dependencies, or fee compression?",
            "unit_economics": f"What is {comp}'s net take rate and gross payment volume (GPV) expansion across existing cohorts?",
            "future_roadmap": f"What new financial products—such as corporate cards, treasury management, or global payout rails—are on {comp}'s immediate roadmap?",
        }
    else:
        templates = {
            "differentiation": f"What is the primary technical or economic reason a customer chooses {comp} over alternative market offerings?",
            "icp_customers": f"What specific organizational archetype or buyer persona is {comp}'s ideal customer profile (ICP)?",
            "competitors": f"Who are the top three direct competitors or disruptive substitutes {comp} actively competes with for budget?",
            "pricing_monetization": f"How does {comp} structure its pricing tiers, contract commitments, and expansion triggers?",
            "gtm_distribution": f"What is {comp}'s primary growth engine—product-led growth (PLG), outbound enterprise sales, or channel partnerships?",
            "product_defensibility": f"What constitutes {comp}'s core defensibility—data network effects, proprietary software, or high switching costs?",
            "regulatory_risks": f"What regulatory mandates, data governance laws, or ecosystem dependencies pose the largest strategic risk to {comp}?",
            "strategic_vulnerabilities": f"Where is {comp} most vulnerable to competitive displacement or customer churn today?",
            "unit_economics": f"What is {comp}'s primary North Star efficiency metric—net revenue retention, payback period, or gross margins?",
            "future_roadmap": f"What are the top two strategic product initiatives or market expansions planned for {comp} in the next two quarters?",
        }

    q = templates.get(theme_id, f"What is {comp}'s strategic focus regarding {theme_id}?")
    # Check if duplicate
    for prev in previous_questions:
        if calculate_semantic_overlap(q, prev) > 0.65:
            q = f"{q} Specifically from {comp}'s current operational perspective."
            break
    return q


def generate_next_question(company_id: int) -> Dict[str, Any]:
    """
    Generates the next interview question for a company:
    - Exactly 10 main questions, asked one at a time.
    - Uses research profile and full interview memory.
    - Covers the 10 assignment themes, phrased for the company's industry.
    - Triggers follow-up if last answer was vague/brief (follow-ups don't count toward the 10).
    - Checks semantic overlap to prevent repeated questions.
    """
    with Session(db.engine) as session:
        company = session.get(Company, company_id)
        if not company:
            raise ValueError(f"Company ID {company_id} not found")

        # 1. Fetch all profile fields (memory)
        pfs = session.exec(select(ProfileField).where(ProfileField.company_id == company_id)).all()
        profile_summary = "\n".join([f"- {pf.key}: {pf.value} ({'verified' if pf.is_verified_fact else 'assumption'})" for pf in pfs])

        # 2. Fetch existing interview turns
        turns = session.exec(
            select(InterviewTurn)
            .where(InterviewTurn.company_id == company_id)
            .order_by(InterviewTurn.id)  # type: ignore
        ).all()

        # Check if there is already an active pending question
        pending_turn = next((t for t in turns if t.status == "pending"), None)
        if pending_turn:
            return {
                "turn_id": pending_turn.id,
                "question": pending_turn.question,
                "theme": pending_turn.theme,
                "is_follow_up": pending_turn.is_follow_up,
                "turn_index": pending_turn.turn_index,
                "status": "pending",
                "message": "Answer or skip this pending question before requesting a new one.",
            }

        # 3. Check for Follow-up on the last answered turn
        last_answered_turn = None
        for t in reversed(turns):
            if t.status == "answered":
                last_answered_turn = t
                break

        # Check if last answered turn already received a follow up
        has_follow_up_already = False
        if last_answered_turn:
            has_follow_up_already = any(t.parent_turn_id == last_answered_turn.id for t in turns)

        # Check if last answer was brief or warrants follow-up (< 25 chars or opened a thread)
        if last_answered_turn and not has_follow_up_already and last_answered_turn.answer:
            answer_clean = last_answered_turn.answer.strip()
            is_brief = len(answer_clean.split()) <= 6 or len(answer_clean) < 35

            if is_brief:
                # Generate follow up
                follow_up_q = (
                    f"You mentioned '{answer_clean}'. Could you elaborate with specific operational metrics, "
                    f"client examples, or key challenges {company.name} faces here?"
                )
                follow_turn = InterviewTurn(
                    company_id=company.id,
                    turn_index=last_answered_turn.turn_index,  # Keeps same main question index
                    question=follow_up_q,
                    theme=last_answered_turn.theme,
                    is_follow_up=True,
                    parent_turn_id=last_answered_turn.id,
                    status="pending",
                )
                session.add(follow_turn)
                session.commit()
                session.refresh(follow_turn)
                return {
                    "turn_id": follow_turn.id,
                    "question": follow_turn.question,
                    "theme": follow_turn.theme,
                    "is_follow_up": True,
                    "turn_index": follow_turn.turn_index,
                    "status": "pending",
                    "message": "Follow-up question generated (does not count toward the 10 main questions).",
                }

        # 4. Count main questions completed (answered or skipped)
        main_turns = [t for t in turns if not t.is_follow_up]
        if len(main_turns) >= 10:
            return {
                "status": "completed",
                "message": "Interview completed! Exactly 10 main strategic questions have been addressed.",
                "total_main_questions": len(main_turns),
            }

        # 5. Identify next unaddressed theme
        covered_theme_ids = {t.theme for t in main_turns if t.theme}
        remaining_themes = [t for t in STRATEGIC_THEMES if t["id"] not in covered_theme_ids]
        target_theme = remaining_themes[0] if remaining_themes else STRATEGIC_THEMES[len(main_turns) % 10]

        previous_questions = [t.question for t in turns]

        # 6. Generate question tailored to company & industry
        new_question_text = None
        if settings.GEMINI_API_KEY or settings.GROQ_API_KEY:
            try:
                system_prompt = (
                    "You are an executive interviewer and chief strategy officer for Signal Stack.\n"
                    "Formulate a sharp, highly contextualized strategic interview question for this company.\n"
                    "RULES:\n"
                    "- Formulate ONE question specifically exploring the assigned strategic theme.\n"
                    "- Phrase the question specifically for this company's industry, business model, and products.\n"
                    "- NEVER repeat or semantically duplicate any previously asked question.\n"
                    "- Avoid generic corporate clichés; ask a probing, analytical question."
                )
                prompt = (
                    f"Company: {company.name}\n"
                    f"Industry: {company.industry}\n"
                    f"Profile Context:\n{profile_summary}\n\n"
                    f"Previous Questions Asked:\n"
                    + "\n".join([f"- {q}" for q in previous_questions])
                    + f"\n\nAssigned Theme: {target_theme['name']} ({target_theme['description']})\n"
                    f"Generate a customized strategic question for {company.name}."
                )

                res = generate_json(
                    prompt=prompt,
                    schema=GeneratedQuestionSchema,
                    system_prompt=system_prompt,
                )
                q_candidate = res.get("question", "").strip()
                # Overlap check
                if q_candidate and all(calculate_semantic_overlap(q_candidate, pq) < 0.65 for pq in previous_questions):
                    new_question_text = q_candidate
            except Exception as e:
                logger.warning(f"LLM question generation failed, using heuristic: {e}")

        if not new_question_text:
            new_question_text = _heuristic_industry_question(
                company_name=company.name,
                industry=company.industry or "Technology",
                theme_id=target_theme["id"],
                previous_questions=previous_questions,
            )

        # 7. Store new turn in database
        new_turn = InterviewTurn(
            company_id=company.id,
            turn_index=len(main_turns) + 1,
            question=new_question_text,
            theme=target_theme["id"],
            is_follow_up=False,
            status="pending",
        )
        session.add(new_turn)
        session.commit()
        session.refresh(new_turn)

        return {
            "turn_id": new_turn.id,
            "question": new_turn.question,
            "theme": new_turn.theme,
            "is_follow_up": False,
            "turn_index": new_turn.turn_index,
            "status": "pending",
            "main_questions_progress": f"{new_turn.turn_index} of 10",
        }


def answer_or_skip_question(
    company_id: int,
    turn_id: int,
    answer: Optional[str] = None,
    is_skip: bool = False,
) -> Dict[str, Any]:
    """
    Record an answer or skip for an interview turn:
    - If skip: mark 'skipped', never re-ask.
    - If answer: update profile_fields via LLM extraction step with source='interview' and is_verified_fact=True.
    """
    with Session(db.engine) as session:
        turn = session.get(InterviewTurn, turn_id)
        if not turn or turn.company_id != company_id:
            raise ValueError(f"Interview turn {turn_id} not found for company {company_id}")

        company = session.get(Company, company_id)

        if is_skip or (answer and answer.strip().lower() == "skip"):
            turn.status = "skipped"
            turn.answer = None
            turn.updated_at = utcnow()
            session.add(turn)
            session.commit()
            session.refresh(turn)
            return {
                "turn_id": turn.id,
                "status": "skipped",
                "message": "Question skipped. This theme will not be re-asked.",
                "extracted_fields": [],
            }

        # Process Answer
        clean_answer = answer.strip() if answer else ""
        turn.status = "answered"
        turn.answer = clean_answer
        turn.updated_at = utcnow()
        session.add(turn)
        session.commit()

        # Step 3: Extract structured intelligence from answer and save to profile_fields
        extracted_fields = _extract_and_save_interview_facts(
            session=session,
            company=company,
            turn=turn,
            answer=clean_answer,
        )

        session.commit()
        session.refresh(turn)

        return {
            "turn_id": turn.id,
            "status": "answered",
            "turn_index": turn.turn_index,
            "is_follow_up": turn.is_follow_up,
            "extracted_fields": extracted_fields,
        }


def edit_interview_answer(
    company_id: int,
    turn_id: int,
    new_answer: str,
) -> Dict[str, Any]:
    """
    Allow editing any previous interview answer, which re-extracts the profile fields.
    """
    return answer_or_skip_question(
        company_id=company_id,
        turn_id=turn_id,
        answer=new_answer,
        is_skip=False,
    )


def _extract_and_save_interview_facts(
    session: Session,
    company: Company,
    turn: InterviewTurn,
    answer: str,
) -> List[Dict[str, Any]]:
    """
    Extract structured facts from an interview answer and save/update profile_fields.
    """
    extracted_records = []
    field_key = f"interview_{turn.theme or 'strategic_input'}"

    # Upsert profile field for this turn's theme
    existing = session.exec(
        select(ProfileField)
        .where(ProfileField.company_id == company.id)
        .where(ProfileField.key == field_key)
    ).first()

    if not existing:
        existing = ProfileField(
            company_id=company.id,
            key=field_key,
            value=answer,
            source="interview",
            is_verified_fact=True,
            evidence_snippet=answer[:300],
            source_url=f"internal://interview/turn/{turn.id}",
            updated_at=utcnow(),
        )
    else:
        existing.value = answer
        existing.evidence_snippet = answer[:300]
        existing.updated_at = utcnow()

    session.add(existing)
    extracted_records.append({
        "key": existing.key,
        "value": existing.value,
        "is_verified_fact": True,
        "source": "interview",
        "evidence_snippet": existing.evidence_snippet,
    })

    return extracted_records


def get_interview_history(company_id: int) -> Dict[str, Any]:
    """Retrieve complete interview memory and progress for a company."""
    with Session(db.engine) as session:
        turns = session.exec(
            select(InterviewTurn)
            .where(InterviewTurn.company_id == company_id)
            .order_by(InterviewTurn.id)  # type: ignore
        ).all()

        main_turns = [t for t in turns if not t.is_follow_up]
        answered_main = [t for t in main_turns if t.status == "answered"]
        skipped_main = [t for t in main_turns if t.status == "skipped"]
        follow_ups = [t for t in turns if t.is_follow_up]

        return {
            "company_id": company_id,
            "total_turns": len(turns),
            "main_questions_total": len(main_turns),
            "main_questions_answered": len(answered_main),
            "main_questions_skipped": len(skipped_main),
            "follow_up_questions_count": len(follow_ups),
            "is_completed": len(main_turns) >= 10 and not any(t.status == "pending" for t in turns),
            "turns": [
                {
                    "id": t.id,
                    "turn_index": t.turn_index,
                    "theme": t.theme,
                    "question": t.question,
                    "answer": t.answer,
                    "status": t.status,
                    "is_follow_up": t.is_follow_up,
                    "parent_turn_id": t.parent_turn_id,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                }
                for t in turns
            ],
        }
