from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import suppliers, purchase_orders, deliveries, stock_takes

app = FastAPI(
    title="Life & Brand Stock Control",
    description="Stock control, procurement, and CoS reporting platform",
    version="0.1.0",
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
app.include_router(stock_takes.router, prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok"}
