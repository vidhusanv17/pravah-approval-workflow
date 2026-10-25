import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import clock, monitor
from .api_compliance import router as compliance_router
from .api_core import router as core_router
from .db import Base, SessionLocal, engine
from .seed import seed

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="PRAVAH - AICTE Approval Workflow, Compliance Monitoring & Alerts (SIH26262 prototype)", version="0.1.0",
              description="Prototype for SIH 2026 PS 26262. Synthetic data only. Automated alerts and routing support the approval process; statutory decisions stay with competent AICTE authorities.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(core_router)
app.include_router(compliance_router)


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()
    interval = int(os.getenv("MONITOR_INTERVAL_SECONDS", "120"))
    if interval > 0:
        monitor.start_background(interval)


@app.get("/api/health")
def health():
    return {"ok": True, "service": "pravah", "now": clock.now().isoformat(), "clock_offset_days": clock.offset_days(), "monitor": monitor.status()}


app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")


@app.get("/")
@app.get("/verify/{code}")
@app.get("/app/{rest:path}")
def index(code: str = None, rest: str = None):
    return FileResponse(str(FRONTEND / "index.html"))
