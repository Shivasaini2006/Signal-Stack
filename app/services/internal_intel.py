import io
import os
import re
import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import pandas as pd
import pypdf
from pydantic import BaseModel, Field as PydanticField
from sqlmodel import Session, select

from app.core.config import settings
from app.core import db
from app.core.llm import generate_json
from app.models.entities import Company, Source, Document, Signal, utcnow
from app.services.crawler import compute_content_hash, compute_simhash
from app.services.analysis import validate_evidence_snippet
from app.services.ranking import compute_final_rank_score

logger = logging.getLogger("signal_stack.internal_intel")


class InternalSignalItem(BaseModel):
    category_type: str = PydanticField(
        description="'recurring_objection' | 'lost_deal_reason' | 'product_request' | 'sales_pattern' | 'emerging_risk'"
    )
    what_happened: str = PydanticField(
        description="Concise description of the internal finding"
    )
    evidence_snippet: str = PydanticField(
        description="VERBATIM quoted text excerpt from the file/row"
    )
    affected_business_area: str = PydanticField(
        default="pricing",
        description="Business area: pricing, product_core, gtm, compliance, partner_network",
    )
    type: str = PydanticField(
        default="threat",
        description="'opportunity' | 'threat' | 'neutral'",
    )
    urgency: str = PydanticField(
        default="medium",
        description="'low' | 'medium' | 'high' | 'critical'",
    )
    why_it_matters: str = PydanticField(
        description="Impact on company revenue, customer retention, or deal close rates"
    )
    suggested_action: str = PydanticField(
        description="Concrete recommended internal action"
    )
    interpretation: str = PydanticField(
        description="Strategic hypothesis derived from this internal data point"
    )


class InternalIntelExtraction(BaseModel):
    has_signals: bool = True
    signals: List[InternalSignalItem] = []


def parse_and_chunk_uploaded_file(
    file_bytes: bytes,
    filename: str,
) -> List[Dict[str, Any]]:
    """
    Parses CSV, Excel, PDF, and TXT files into discrete chunks with source references (file name + page/row).
    """
    ext = os.path.splitext(filename)[1].lower()
    chunks: List[Dict[str, Any]] = []

    # 1. CSV
    if ext == ".csv":
        df = pd.read_csv(io.BytesIO(file_bytes), comment="#")
        for idx, row in df.reset_index(drop=True).iterrows():
            row_num = int(idx) + 1
            # Build structured line
            items = [f"{col}: {val}" for col, val in row.items() if pd.notna(val)]
            row_text = f"Row {row_num}: " + " | ".join(items)
            chunks.append({
                "source_ref": f"{filename}#row={row_num}",
                "location_label": f"Row {row_num}",
                "text": row_text,
            })

    # 2. Excel (.xlsx, .xls)
    elif ext in (".xlsx", ".xls"):
        df = pd.read_excel(io.BytesIO(file_bytes))
        for idx, row in df.iterrows():
            row_num = idx + 1
            items = [f"{col}: {val}" for col, val in row.items() if pd.notna(val)]
            row_text = f"Row {row_num}: " + " | ".join(items)
            chunks.append({
                "source_ref": f"{filename}#row={row_num}",
                "location_label": f"Row {row_num}",
                "text": row_text,
            })

    # 3. PDF
    elif ext == ".pdf":
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        for p_idx, page in enumerate(reader.pages):
            page_num = p_idx + 1
            page_text = page.extract_text() or ""
            if len(page_text.strip()) > 20:
                chunks.append({
                    "source_ref": f"{filename}#page={page_num}",
                    "location_label": f"Page {page_num}",
                    "text": page_text.strip(),
                })

    # 4. Plain Text / Markdown
    elif ext in (".txt", ".md", ".log"):
        raw_text = file_bytes.decode("utf-8", errors="replace")
        paragraphs = [p.strip() for p in raw_text.split("\n\n") if len(p.strip()) > 5]
        for s_idx, para in enumerate(paragraphs):
            section_num = s_idx + 1
            chunks.append({
                "source_ref": f"{filename}#section={section_num}",
                "location_label": f"Section {section_num}",
                "text": para,
            })
    else:
        raise ValueError(f"Unsupported file format '{ext}'. Supported: CSV, Excel, PDF, TXT.")

    return chunks


def _heuristic_internal_extractor(
    chunk_text: str,
    source_ref: str,
) -> List[InternalSignalItem]:
    """
    Deterministic fallback extractor for internal files when LLM is offline.
    Extracts guaranteed verbatim quotes from the chunk text.
    """
    signals: List[InternalSignalItem] = []
    text_lower = chunk_text.lower()

    # Identify category
    cat_type = "sales_pattern"
    stype = "threat"
    area = "pricing"

    if any(k in text_lower for k in ["lost", "lost deal", "lost-deal", "closed lost"]):
        cat_type = "lost_deal_reason"
        stype = "threat"
    elif any(k in text_lower for k in ["objection", "pushback", "expensive", "cheaper", "fee", "cost"]):
        cat_type = "recurring_objection"
        stype = "threat"
        area = "pricing"
    elif any(k in text_lower for k in ["request", "feature", "want", "missing", "need", "wish"]):
        cat_type = "product_request"
        stype = "opportunity"
        area = "product_core"
    elif any(k in text_lower for k in ["risk", "delay", "visa", "compliance", "fraud"]):
        cat_type = "emerging_risk"
        stype = "threat"
        area = "compliance"

    # Select verbatim snippet from chunk
    # Find quotes or specific clause
    quote_match = re.search(r'["\']([^"\']{15,})["\']', chunk_text)
    if quote_match:
        snippet = quote_match.group(1).strip()
    else:
        parts = [p.strip() for p in chunk_text.split("|")]
        # Prioritize quote or verbatim fields
        quote_part = next((p for p in parts if any(k in p.lower() for k in ["quote", "verbatim"])), None)
        if quote_part and ":" in quote_part:
            snippet = quote_part.split(":", 1)[1].strip()
        else:
            relevant_part = next((p for p in parts if any(k in p.lower() for k in ["reason", "objection", "notes", "lost"])), None)
            if relevant_part and ":" in relevant_part:
                snippet = relevant_part.split(":", 1)[1].strip()
            else:
                snippet = chunk_text[:120].strip()

    if len(snippet) < 10:
        snippet = chunk_text[:100].strip()

    signals.append(InternalSignalItem(
        category_type=cat_type,
        what_happened=f"Internal pattern identified in {source_ref}: {snippet[:80]}",
        evidence_snippet=snippet,
        affected_business_area=area,
        type=stype,
        urgency="high" if stype == "threat" else "medium",
        why_it_matters="Directly impacts sales conversion rates and customer satisfaction.",
        suggested_action="Review operational workflow and adjust positioning or feature roadmap.",
        interpretation=f"Internal customer feedback highlights critical decision criteria around {area}.",
    ))

    return signals


def extract_internal_intel_from_chunk(
    chunk_text: str,
    source_ref: str,
    company_name: str,
) -> List[InternalSignalItem]:
    """
    Extracts recurring objections, lost-deal reasons, product requests,
    sales patterns, and emerging risks using LLM structured generation.
    """
    if settings.GEMINI_API_KEY or settings.GROQ_API_KEY:
        try:
            system_prompt = (
                "You are an executive sales intelligence and customer retention analyst for Signal Stack.\n"
                "Analyze the provided internal document excerpt for commercial signals.\n"
                "Extract any of the following 5 dimensions:\n"
                "- recurring_objection\n"
                "- lost_deal_reason\n"
                "- product_request\n"
                "- sales_pattern\n"
                "- emerging_risk\n\n"
                "HARD RULES:\n"
                "- ZERO FABRICATION: `evidence_snippet` MUST be an EXACT, VERBATIM substring quote from the text.\n"
                "- Do NOT paraphrase `evidence_snippet`.\n"
                "- If no meaningful signal is in this excerpt, return `has_signals = false`."
            )
            prompt = (
                f"Target Company: {company_name}\n"
                f"Source Reference: {source_ref}\n"
                f"Excerpt:\n{chunk_text}\n\n"
                "Extract structured internal signals."
            )
            res = generate_json(
                prompt=prompt,
                schema=InternalIntelExtraction,
                system_prompt=system_prompt,
            )
            parsed = InternalIntelExtraction.model_validate(res)
            if parsed.has_signals and parsed.signals:
                return parsed.signals
        except Exception as e:
            logger.warning(f"LLM internal extraction failed, using heuristic: {e}")

    return _heuristic_internal_extractor(chunk_text, source_ref)


def process_internal_file_upload(
    company_id: int,
    file_bytes: bytes,
    filename: str,
) -> List[Signal]:
    """
    Full internal intelligence pipeline:
    1. Parse and chunk file (CSV, Excel, PDF, TXT)
    2. Extract internal signals (objections, lost deals, product requests, sales patterns, risks)
    3. Validate verbatim quotes
    4. Store in 'internal' category with file name and page/row as source reference
    5. Compute rank and explanation in code
    """
    with Session(db.engine) as session:
        company = session.get(Company, company_id)
        if not company:
            raise ValueError(f"Company ID {company_id} not found")

        # 1. Chunk file
        chunks = parse_and_chunk_uploaded_file(file_bytes, filename)
        logger.info(f"Parsed {len(chunks)} chunks from '{filename}' for {company.name}.")

        # 2. Get or create internal Source record
        source_url = f"internal://{company.domain or 'company'}/uploads/{filename}"
        statement = (
            select(Source)
            .where(Source.company_id == company_id)
            .where(Source.url == source_url)
        )
        source = session.exec(statement).first()
        if not source:
            source = Source(
                company_id=company_id,
                category="internal",
                name=f"Internal File: {filename}",
                url=source_url,
                reason="Primary internal corporate file uploaded for intelligence synthesis.",
                specific_score=0.99,
                recent_score=0.95,
                credible_score=0.98,
                status="approved",
                health="ok",
                last_checked=utcnow(),
            )
            session.add(source)
            session.commit()
            session.refresh(source)

        created_signals: List[Signal] = []

        # 3. Process each chunk
        for chunk in chunks:
            chunk_text = chunk["text"]
            source_ref = chunk["source_ref"]
            location = chunk["location_label"]

            # Create or update Document record for this chunk
            doc_url = f"internal://{source_ref}"
            chash = compute_content_hash(chunk_text)
            shash = str(compute_simhash(chunk_text))

            doc = Document(
                source_id=source.id,
                url=doc_url,
                content_hash=chash,
                title=f"{filename} ({location})",
                text=chunk_text,
                simhash=shash,
                published_at=utcnow(),
                fetched_at=utcnow(),
            )
            session.add(doc)
            session.commit()
            session.refresh(doc)

            # Extract signals
            items = extract_internal_intel_from_chunk(chunk_text, source_ref, company.name)

            for item in items:
                snippet = item.evidence_snippet or ""
                # Validate verbatim snippet
                if not validate_evidence_snippet(snippet, chunk_text):
                    logger.warning(f"Rejected hallucinated internal snippet from {source_ref}: '{snippet}'")
                    continue

                labeled_interp = (
                    item.interpretation
                    if item.interpretation.startswith("[AI Inference]:")
                    else f"[AI Inference]: {item.interpretation}"
                )

                # Compute ranking in code
                final_score, breakdown, explanation = compute_final_rank_score(
                    relevance=0.95,  # High relevance for proprietary internal intelligence
                    impact=0.85,
                    urgency=item.urgency,
                    source_credibility=0.98,  # First-party verified file
                    published_at=utcnow(),
                    fetched_at=utcnow(),
                    what_happened=item.what_happened,
                    affected_area=item.affected_business_area,
                    historical_signals=created_signals,
                )

                signal = Signal(
                    company_id=company.id,
                    document_id=doc.id,
                    category="internal",
                    what_happened=f"[{item.category_type.replace('_', ' ').title()}] {item.what_happened}",
                    evidence_snippet=snippet,
                    interpretation=labeled_interp,
                    affected_area=item.affected_business_area,
                    type=item.type,
                    urgency=item.urgency,
                    why_it_matters=item.why_it_matters,
                    suggested_action=item.suggested_action,
                    source_reliability=0.98,
                    evidence_strength=0.95,
                    strategic_relevance=0.95,
                    final_rank_score=final_score,
                    rank_explanation=explanation,
                    score_breakdown=json.dumps(breakdown),
                    verification_status="verified",
                    source_url=f"internal://{source_ref}",
                    published_at=utcnow(),
                    discovered_at=utcnow(),
                )
                session.add(signal)
                session.commit()
                session.refresh(signal)
                created_signals.append(signal)

        # Rank signals descending
        created_signals.sort(key=lambda s: s.final_rank_score, reverse=True)
        return created_signals
