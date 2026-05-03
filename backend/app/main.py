from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import suppliers, purchase_orders, deliveries, spot_checks, invoice_ocr

app = FastAPI(
    title="Life & Brand Stock Control",
    description="Smart spot-check stock control, procurement, and CoS reporting",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(suppliers.router, prefix="/api/v1")
app.include_router(purchase_orders.router, prefix="/api/v1")
app.include_router(deliveries.router, prefix="/api/v1")
app.include_router(spot_checks.router, prefix="/api/v1")
app.include_router(invoice_ocr.router, prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok"}
