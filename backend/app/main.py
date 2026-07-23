from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    suppliers, purchase_orders, deliveries,
    spot_checks, invoice_ocr, batches, alerts,
    am_checklist, ops_visit, one_on_one,
    auth, org_units, operational_alerts,
)
from app.db.database import SessionLocal
from app.services.am_tasks import seed_tasks


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Seed AM checklist tasks on startup (idempotent)
    db = SessionLocal()
    try:
        seed_tasks(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="Life & Brand Operations Platform",
    description="Stock control, spot-checks, freshness tracking, AM operations, and alerting platform",
    version="0.6.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth & org structure
app.include_router(auth.router, prefix="/api/v1")
app.include_router(org_units.router, prefix="/api/v1")

# Stock control
app.include_router(suppliers.router, prefix="/api/v1")
app.include_router(purchase_orders.router, prefix="/api/v1")
app.include_router(deliveries.router, prefix="/api/v1")
app.include_router(spot_checks.router, prefix="/api/v1")
app.include_router(invoice_ocr.router, prefix="/api/v1")
app.include_router(batches.router, prefix="/api/v1")
app.include_router(alerts.router, prefix="/api/v1")

# Area Manager tools
app.include_router(am_checklist.router, prefix="/api/v1")
app.include_router(ops_visit.router, prefix="/api/v1")
app.include_router(one_on_one.router, prefix="/api/v1")

# Operational alerts (Phase 1)
app.include_router(operational_alerts.router, prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok"}
