from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.db import init_db
from app.api.companies import router as companies_router
from app.api.interviews import router as interviews_router
from app.api.sources import router as sources_router
from app.api.crawler import router as crawler_router
from app.api.signals import router as signals_router
from app.api.internal_intel import router as internal_intel_router
from app.api.briefs import router as briefs_router
from app.api.jobs import router as jobs_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB on application startup
    init_db()
    yield


app = FastAPI(
    title="Signal Stack API",
    description="Autonomous Strategic Intelligence & Competitive Signal Engine",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS for Streamlit and dashboard frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(companies_router)
app.include_router(interviews_router)
app.include_router(sources_router)
app.include_router(crawler_router)
app.include_router(signals_router)
app.include_router(internal_intel_router)
app.include_router(briefs_router)
app.include_router(jobs_router)


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "signal-stack",
        "env": settings.APP_ENV,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=True,
    )
