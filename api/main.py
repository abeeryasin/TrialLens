"""TrialLens FastAPI layer — the only door to the database.

Run for real development:
    .venv/bin/uvicorn api.main:app --reload

Interactive docs (auto-generated from the Pydantic schemas) at /docs.
"""
import json
from pathlib import Path
from typing import List

from fastapi import FastAPI

from api.changes import router as changes_router
from api.discover import router as discover_router
from api.explore import router as explore_router
from api.studies import router as studies_router
from api.watch import router as watch_router

app = FastAPI(title="TrialLens API")
app.include_router(studies_router)
app.include_router(discover_router)
app.include_router(changes_router)
app.include_router(watch_router)
app.include_router(explore_router)

TRACKED_CONDITIONS_PATH = Path(__file__).resolve().parent.parent / "config" / "tracked_conditions.json"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/tracked-conditions", response_model=List[str])
def tracked_conditions():
    """The real registry Monitor comprehensively tracks — same file
    api/discover.py checks. Exposed as its own tiny read so the frontend
    can show what's actually being watched without reading a local file
    directly (frontend goes through FastAPI only, same rule as everywhere
    else)."""
    return json.loads(TRACKED_CONDITIONS_PATH.read_text())
