"""TrialLens FastAPI layer — the only door to the database.

Run for real development:
    .venv/bin/uvicorn api.main:app --reload

Interactive docs (auto-generated from the Pydantic schemas) at /docs.
"""
from fastapi import FastAPI

from api.studies import router as studies_router

app = FastAPI(title="TrialLens API")
app.include_router(studies_router)


@app.get("/health")
def health():
    return {"status": "ok"}
