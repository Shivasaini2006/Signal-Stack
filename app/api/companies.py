from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlmodel import Session, select
from urllib.parse import urlparse

from app.core.db import get_session
from app.models.entities import Company, ProfileField
from app.services.research import research_company

router = APIRouter(prefix="/companies", tags=["companies"])


class CompanyCreate(BaseModel):
    name: str
    url: str


class ProfileFieldResponse(BaseModel):
    key: str
    value: str
    status: str
    is_verified_fact: bool
    source_url: Optional[str] = None
    evidence_snippet: Optional[str] = None


class CompanyResponse(BaseModel):
    id: int
    name: str
    url: Optional[str] = None
    domain: Optional[str] = None
    industry: Optional[str] = None
    description: Optional[str] = None


class CompanyResearchResponse(BaseModel):
    company: CompanyResponse
    crawled_pages_count: int
    search_results_count: int
    profile_fields: List[ProfileFieldResponse]


@router.post("", response_model=CompanyResponse, status_code=201)
def create_company(payload: CompanyCreate, session: Session = Depends(get_session)):
    """Create a new company to monitor."""
    domain = urlparse(payload.url if payload.url.startswith(("http://", "https://")) else f"https://{payload.url}").netloc
    
    # Check if already exists
    statement = select(Company).where(Company.name == payload.name)
    existing = session.exec(statement).first()
    if existing:
        return existing

    company = Company(
        name=payload.name,
        url=payload.url,
        domain=domain,
    )
    session.add(company)
    session.commit()
    session.refresh(company)
    return company


@router.get("", response_model=List[CompanyResponse])
def list_companies(session: Session = Depends(get_session)):
    """List all tracked companies."""
    return session.exec(select(Company)).all()


@router.get("/{company_id}")
def get_company(company_id: int, session: Session = Depends(get_session)):
    """Retrieve company details along with stored profile fields."""
    company = session.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    pfs = session.exec(select(ProfileField).where(ProfileField.company_id == company_id)).all()
    return {
        "company": company,
        "profile_fields": pfs,
    }


@router.post("/{company_id}/research", response_model=CompanyResearchResponse)
def trigger_company_research(company_id: int, session: Session = Depends(get_session)):
    """
    Execute autonomous intelligence research for a company:
    1. Crawl homepage + up to 8 key internal pages (respecting robots.txt)
    2. Run 5-8 ddgs searches
    3. LLM structured extraction with verified fact attribution or assumption tagging
    4. Persist to profile_fields
    """
    company = session.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    if not company.url:
        raise HTTPException(status_code=400, detail="Company does not have a URL configured")

    result = research_company(
        company_name=company.name,
        url=company.url,
        company_id=company.id,
    )

    return result
