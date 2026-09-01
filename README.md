# TrialLens

A monitoring tool for clinical trials. It watches a therapeutic area over
time and tells you what changed — not a search box you re-run and re-read.

ClinicalTrials.gov holds only a trial's **current** version. Ask it what a
trial says today and it will tell you; ask it what the primary outcome said
last year, or when the completion date slipped, and it has no answer.
TrialLens records every change it sees, so it can.

```
NCT02954874 — Amended twice since TrialLens started watching on 28 August 2026

  Posted 31 August 2026
    Completion date          2026-08-31  →  2027-08-27
    Enrollment               1,155       →  1,195
    Enrollment figure type   ESTIMATED   →  ACTUAL
    Primary completion       2026-08-31  →  2026-08-03

  Posted 28 August 2026
    ClinicalTrials.gov posted an amendment, but every field it touched
    is one TrialLens doesn't store. The record changed; we can't show what.
```

That trial finished enrolling, reported a real headcount instead of a
target, and pushed completion out a year. Registry search cannot show you
that story.

## Status, honestly

**A working local application, not a deployed product.** It runs on
localhost; nothing is hosted, and no clinical researcher has used it yet.

| | |
|---|---|
| Trials tracked | 11,518 (11,427 currently in scope) |
| Conditions monitored | breast cancer, obesity |
| Changes recorded | 498, since 2026-08-28 |
| Runs | every 6 hours on GitHub Actions, unattended |

Three of five planned capabilities are built:

- **Discover** ✅ — search a condition; tracked ones answer from our own
  data, anything else falls back to a live ClinicalTrials.gov lookup, and
  each result says which it was.
- **Understand** ✅ — one trial in full, including its amendment history.
- **Monitor** ✅ — what changed across everything tracked, in one feed.
- **Explore** ⬜ — how trials, sponsors and interventions connect. Not built.
- **Investigate** ⬜ — synthesis across everything tracked. Not built.

There is no AI in the system right now. There was: a ranking layer that
scored trials against a stated research interest. It was built, measured
against real data, and deleted — four of its five scored signals turned out
to be filters wearing a score's costume, and the one genuine judgment it
made scales with volume in a product that deliberately sees about 17
changed trials a week. The reasoning is in
[`docs/decisions.md`](docs/decisions.md); the commit is kept in history
rather than rewritten away.

## Rules the code follows

These are constraints, not aspirations — most exist because breaking one
produced a real bug.

- **Never "eligible."** The system says "potential fit", "requires review",
  or "insufficient information". It does not know enough about a real
  person to determine eligibility, and it never claims to.
- **Never invent a study fact.** When the record doesn't say, the answer is
  "we can't tell" — shown to the user in those words. Nearly half of all
  amendments touch fields TrialLens doesn't store, and those render as
  "the record changed; we can't show what", never as "no changes".
- **Every claim carries its source.** Source study, source field, the
  actual stored value, the interpretation, and the uncertainty. No
  unexplained scores.
- **No patient data.** Public registered study data only.
- **FastAPI is the only door to the database.** The frontend reads through
  it; the scheduled job writes through it. Read-only enforcement lives at
  that boundary, in a Postgres role that cannot write whatever the route
  code does.
- **Deterministic first, AI second, agents third.** Plain code for anything
  with one correct answer. That principle is why the ranking layer was
  removed rather than improved.

## How it works

```
ClinicalTrials.gov v2 API
         │
         ▼
  scripts/ingest.py ──── every 6 hours, GitHub Actions
         │               cheap filter: has lastUpdatePostDate moved?
         │               expensive diff: only for what actually moved
         ▼
    FastAPI  ─────────── the only door to the database
         │               (read-only role for every GET)
         ▼
  Neon Postgres          raw record + normalized columns + fetch timestamp
         │               study_changes: every field-level change, kept
         ▼
    Streamlit            Discover · Understand · Monitor
```

Change detection is two-phase on purpose: re-fetching 11,000 full records
every 6 hours would be slow and rude to a public API, so the job first
fetches only IDs and update dates, then pulls the full record for the
handful that moved. A typical run refetches under 100 trials.

## Running it

Requires Python 3.9+ and a Postgres database (this uses [Neon](https://neon.tech)).

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

cp .env.example .env.local        # then fill in your own DATABASE_URL
.venv/bin/python scripts/apply_schema.py

# terminal 1 — the API
PYTHONPATH=. .venv/bin/uvicorn api.main:app --reload

# terminal 2 — the UI
.venv/bin/streamlit run frontend/Home.py
```

Populate it with a first ingest, then let the scheduler take over:

```bash
PYTHONPATH=. .venv/bin/python scripts/run_monitor.py
```

`.env.local` is gitignored and must stay that way. Rotating a leaked key
does not remove it from git history.

### Tests

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/ -q
```

101 tests. The 12 that read the live database skip themselves when
`DATABASE_URL_READONLY` is unset, so the suite runs green without
credentials — that is what CI does.

**Test coverage is uneven and this is the honest summary:** the amendment
history endpoint has HTTP-level tests, the deterministic scorers have
thorough ones, and the real-data checks catch upstream drift. `api/discover.py`,
`api/changes.py`, `ctgov_client.py` and most of `scripts/` have none yet.

## Layout

| path | what's in it |
|---|---|
| `api/` | FastAPI — the only door to the database |
| `frontend/` | Streamlit pages, reading through `api_client.py` only |
| `scripts/` | Ingestion, the scheduled Monitor job, schema application |
| `db/schema.sql` | One idempotent source of truth for the schema |
| `tests/` | Free tests; database-backed ones skip without credentials |
| `docs/decisions.md` | Every real decision, dated, with what it cost to learn |
| `CLAUDE.md` | The project's constitution — rules that override convenience |

`docs/decisions.md` is the file worth reading if you want to know why
anything here is the way it is. It records the bugs too, including the ones
that cost money.

## Data

All trial data comes from the [ClinicalTrials.gov v2
API](https://clinicaltrials.gov/data-api/api) — public, no authentication.
TrialLens stores the raw response alongside its normalized columns, so a
parsing decision made today can be revisited against the original record.

This is a personal engineering project. It is not a medical device, not
clinical decision support, and not a substitute for reading a trial
protocol.
