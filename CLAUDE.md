# TrialLens — Project Constitution

## Project overview

TrialLens is a clinical-trial intelligence and monitoring tool for a clinical researcher tracking a
therapeutic area over time — not a one-time patient search. Built on the real ClinicalTrials.gov v2
API (public, no auth, ~50 req/min). Five capabilities, each a different kind of question:
**Discover** (what matches this?), **Understand** (why does this trial matter?), **Monitor** (tell
me when something changes), **Explore** (who else works in this space?), **Investigate** (what
happened across everything tracked?).

**§4 — Source of truth.** ClinicalTrials.gov v2 is the only source of trial facts; store the raw
record, a normalized version, and the fetch timestamp. Real snapshot-diffing decides whether a
trial changed — cheap filter first (`lastUpdatePostDateStruct` moved?), expensive diff only on what
passes.

## Key commands

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env.local              # then fill in your own DATABASE_URL
.venv/bin/python scripts/apply_schema.py
PYTHONPATH=. .venv/bin/uvicorn api.main:app --reload   # the API
.venv/bin/streamlit run frontend/Home.py               # the UI
PYTHONPATH=. .venv/bin/python -m pytest tests/ -k "not real_data" -q  # iterate
PYTHONPATH=. .venv/bin/python -m pytest tests/ -q                     # pre-commit
PYTHONPATH=. .venv/bin/python scripts/run_monitor.py     # one Monitor cycle
PYTHONPATH=. .venv/bin/python scripts/paid_preflight.py  # before any paid call
PYTHONPATH=. .venv/bin/python scripts/check_ops_health.py
```

## Preferences

**§2 — Non-negotiable product & safety rules**

- Never "patient eligibility" — use "potential fit," "potential conflict," "requires review,"
  "insufficient information." The system doesn't know enough about a real person to determine it.
- No real patient data (PHI) — public, registered study data only.
- **Never write a live credential into a repo file**, even an untracked one. Keys live in
  `.env.local` (gitignored); repo files get a placeholder. Rotating does not un-commit a key.
- **Nor into user-visible output.** A misconfigured `API_BASE_URL` once put the live database
  password on a public page by interpolating the raw env var and the raw exception. Name the host,
  never the address; scrub the raw value out of exception text (`api/safe_errors.py`).
- Never invent a study fact, represent an LLM's inference as a source fact, claim a patient is
  eligible, or make a clinical decision — say so explicitly when the evidence is insufficient.

**§3 — Evidence requirements.** Every substantive trial claim preserves source study, source field,
the relevant source text/value, the interpretation, and the uncertainty. No unexplained relevance
scores, no black-box ranking, no summed scores.

**§5 — Architecture principles**

- **Deterministic first, AI second, agents third** — plain code for one-correct-answer tasks, one
  AI call only where language understanding is needed, a full agent only for multi-step judgment.
- **FastAPI is the only door to the database** — the frontend reads through it, the scheduled jobs
  write through it, and a `SELECT`-only Postgres role enforces it below the route code.
- **No vector store.** Literature Q&A per trial stays a logged future idea (`docs/decisions.md`,
  2026-08-26 and 2026-09-08).

**§6 — Development workflow**

- **Schema-first**: read the real schema before writing a query, every time.
- **Status-first**: check `docs/decisions.md` before re-deciding something settled, and
  `docs/gotchas.md` before touching the database layer, the scheduler, or any script deleting rows.
- **Verify external claims** before trusting them (API behavior, pricing, tool limits, another AI's
  suggestions) — through the build, not through planning.

**§7 — Verification & quality gates**

- Code generating successfully isn't the finish line — run tests, inspect real output, verify
  against acceptance criteria. Nothing is "done" because a file exists. For AI behavior: explicit
  evaluation cases, not inspection.
- **No paid model call until a free test of the same path passes**, and batch the paid questions
  that remain. `scripts/paid_preflight.py` refuses when the free suite is red.
- A test calling an endpoint function directly is not testing the endpoint — only an HTTP call
  exercises request binding and response validation.

## Current status

**All twelve roadmap steps are built, deployed and verified. 914 tests pass.** Live on Render's
free tier — API `https://triallens-api.onrender.com`, frontend
`https://triallens-frontend.onrender.com` — against a Neon Postgres `production` branch
(`br-fancy-bird-ay7zb0sb`; an identifier, not a credential). Watching 11,453 trials.

Four unattended jobs: `monitor.yml` (6-hourly ingest, diff, prose interpretation, graph sync),
`synthesis.yml` (weekly proposals into `review_queue`), `digest.yml` (weekday Resend email), and
`tests.yml` (every push, deliberately holding no database credentials).

`GET /ops/status` is the health surface — deterministic per §5, named alerts each carrying its
measurement, never a summed score per §3, shown by `frontend/pages/6_System.py`. Every alert rule
is a real incident from this project's history, because the failure mode that matters is not a
crash but **a job that finishes green while doing nothing**, which this project has been in twice.

The one genuinely multi-step judgment is the weekly synthesis agent ("is this week's movement a
pattern or a coincidence?"). It reads `GET /investigate/summary`, files labelled-confidence
proposals — never a verdict — and a human decides in `frontend/pages/7_Review.py`.

**Read more:** `docs/gotchas.md` for the rules that cost something to learn, `docs/decisions.md`
for the dated reasoning behind each, `docs/roadmap.md` for the per-step record.
