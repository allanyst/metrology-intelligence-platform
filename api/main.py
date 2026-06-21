"""
MIP FastAPI — Metrology Intelligence Platform API.

Exposes Gold-layer calibration data and alerts.
UQaaS uncertainty calculations are delegated to the UQaaS microservice.
"""
from fastapi import FastAPI
from routers import calibration, alerts

app = FastAPI(
    title="Metrology Intelligence Platform API",
    description=(
        "REST API for analytical instrument calibration QC. "
        "Reads Bronze→Silver→Gold dbt pipeline results. "
        "Uncertainty quantification delegated to UQaaS microservice (GUM Supl. 1)."
    ),
    version="1.0.0",
)

app.include_router(calibration.router)
app.include_router(alerts.router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok", "service": "mip-api"}
