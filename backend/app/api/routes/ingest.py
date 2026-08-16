"""Ingest pipeline endpoints (Phase 1)."""
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.connectors.micros_adapter import MicrosExportAdapter
from app.db.database import get_db
from app.models import RawIngest
from app.services.ingest_pipeline import known_hashes, run_pipeline

router = APIRouter(prefix="/ingest", tags=["ingest"])

ADAPTERS = {"micros": MicrosExportAdapter}


class RunIn(BaseModel):
    source: str = "micros"
    watch_dir: str | None = None


class RunResultOut(BaseModel):
    ingest_id: int | None
    source: str
    stage: str
    ok: bool
    rows: int
    message: str


class IngestOut(BaseModel):
    id: int
    source: str
    file_name: str
    stage: str
    business_date: date | None
    row_count: int | None
    error: str | None
    created_at: datetime

    class Config:
        from_attributes = True


@router.post("/run", response_model=list[RunResultOut])
def run(payload: RunIn, db: Session = Depends(get_db)):
    """Run the 5-stage pipeline for a source. Cron target / manual trigger."""
    adapter_cls = ADAPTERS.get(payload.source)
    if adapter_cls is None:
        raise HTTPException(400, f"Unknown source: {payload.source}")
    adapter = adapter_cls(known_hashes=known_hashes(db))
    watch_dir = payload.watch_dir or settings.ingest_watch_dir
    results = run_pipeline(db, adapter, watch_dir)
    return [RunResultOut(**vars(r)) for r in results]


@router.get("/", response_model=list[IngestOut])
def recent(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.execute(
        select(RawIngest).order_by(RawIngest.created_at.desc()).limit(min(limit, 200))
    ).scalars().all()
    return [
        IngestOut(
            id=r.id, source=r.source, file_name=r.file_name,
            stage=r.stage.value, business_date=r.business_date,
            row_count=r.row_count, error=r.error, created_at=r.created_at,
        )
        for r in rows
    ]
