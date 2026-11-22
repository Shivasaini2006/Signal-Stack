from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlmodel import Session, select

from app.core import db
from app.models.entities import Company, Signal
from app.services.internal_intel import process_internal_file_upload

router = APIRouter(prefix="/companies/{company_id}/internal-intel", tags=["Internal Intelligence"])

ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".pdf", ".txt", ".md", ".log"}


@router.post("/upload")
async def upload_internal_file(
    company_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(db.get_session),
) -> Dict[str, Any]:
    """
    Upload an internal document (CSV, Excel, PDF, TXT) to extract commercial signals:
    - Recurring objections
    - Lost-deal reasons
    - Product requests
    - Sales patterns
    - Emerging risks

    Every signal extracts a verbatim quote and records the filename and page/row as source reference.
    Test datasets are automatically tagged as synthetic test data.
    """
    company = session.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail=f"Company with ID {company_id} not found")

    filename = file.filename or "unknown_file.txt"
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file extension '{ext}'. Supported: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        # Detect test data disclaimer
        is_test_data = b"[TEST DATA" in content or "test_sales_objections" in filename.lower()

        signals = process_internal_file_upload(
            company_id=company_id,
            file_bytes=content,
            filename=filename,
        )

        return {
            "company_id": company_id,
            "filename": filename,
            "is_test_data": is_test_data,
            "signals_extracted_count": len(signals),
            "signals": [
                {
                    "id": s.id,
                    "category": s.category,
                    "what_happened": s.what_happened,
                    "evidence_snippet": s.evidence_snippet,
                    "interpretation": s.interpretation,
                    "affected_area": s.affected_area,
                    "type": s.type,
                    "urgency": s.urgency,
                    "final_rank_score": s.final_rank_score,
                    "rank_explanation": s.rank_explanation,
                    "source_url": s.source_url,
                    "verification_status": s.verification_status,
                }
                for s in signals
            ],
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process internal intelligence file: {e}")
