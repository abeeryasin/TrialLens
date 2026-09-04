"""TrialLens FastAPI layer — the only door to the database.

Run for real development:
    .venv/bin/uvicorn api.main:app --reload

Interactive docs (auto-generated from the Pydantic schemas) at /docs.
"""
from fastapi import FastAPI

from api.changes import router as changes_router
from api.conditions import router as conditions_router
from api.discover import router as discover_router
from api.explore import router as explore_router
from api.investigate import router as investigate_router
from api.studies import router as studies_router
from api.synthesis import router as synthesis_router
from api.watch import router as watch_router

app = FastAPI(title="TrialLens API")
app.include_router(studies_router)
app.include_router(discover_router)
app.include_router(changes_router)
app.include_router(watch_router)
app.include_router(explore_router)
app.include_router(investigate_router)
app.include_router(synthesis_router)
app.include_router(conditions_router)


@app.get("/health")
def health():
    return {"status": "ok"}
