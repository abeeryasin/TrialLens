# TrialLens

A monitoring tool for clinical trials. It watches a therapeutic area over
time and tells you what changed — not a search box you re-run and re-read.

ClinicalTrials.gov holds only a trial's **current** version. Ask it what a
trial says today and it will tell you; ask it what the primary outcome said
last year, or when the completion date slipped, and it has no answer.
TrialLens records every change it sees, so it can.

```
NCT05231824 — Amended since TrialLens started watching on 28 August 2026

  Posted 4 September 2026
    ● Operational
    Completion date         2026-03-31 → 2025-02-28   pulled about 13 months earlier
    Enrollment              336        → 301          reduced by 35
    Enrollment figure type  ESTIMATED  → ACTUAL       the target of 336 became a real count of 301
    Overall status          ACTIVE_NOT_RECRUITING → COMPLETED
    Lead sponsor            Drexel University → Oregon Research Institute
```

That trial finished, reported a real headcount 35 short of its target, and
changed hands. Registry search cannot show you that story.

**Live:** [triallens-frontend.onrender.com](https://triallens-frontend.onrender.com)
· API at [triallens-api.onrender.com](https://triallens-api.onrender.com)
(Render's free tier — the first request after an idle period takes a moment
to wake.)

## Status

**Deployed and running unattended.** All five capabilities are built, a
6-hour cron has been ingesting and diffing since 28 August 2026, and a
clinician has judged real output.

| | |
|---|---|
| Trials watched | 11,453 |
| Conditions monitored | breast cancer, obesity |
| Changes recorded | 1,098 across 450 distinct trials |
| Primary-outcome changes on file | 22 — 19 substantive, 2 entry-completed, 1 reformatting |
| Tests | 914 |

Snapshot taken 2026-09-08. The app never holds a copy of these — it reads
them from `GET /watch` and `GET /changes` on every load, because an earlier
version of this table drifted within a day of being written down. The change
count is shown next to its distinct-trial count on purpose: 1,098 changes
across 450 trials is a different fact from 1,098 across 11,453.

- **Discover** — search a condition; tracked ones answer from our own data,
  anything else falls back to a live ClinicalTrials.gov lookup, and each
  result says which it was.
- **Understand** — one trial in full, including its amendment history and
  what each amendment did.
- **Monitor** — what changed across everything tracked, in one feed.
- **Explore** — how trials, sponsors, sites, investigators and interventions
  connect, over 191,864 real edges.
- **Investigate** — synthesis across everything tracked: timeline drift,
  enrolment against plan, lifecycle transitions, and changed primary outcomes
  read against published base rates.

The front page leads with the watch itself, not a search box. Most weeks
nothing happens, and a quiet week is stated as a finding rather than left as
an empty table. If the scheduled job stops, the alarm replaces the page
instead of sitting above a stale feed.

### Judged by a clinician, not just by tests

On 7 September 2026 a clinician read **every substantive primary-outcome
change on file** — 12 of 12 — and called **9 worth a researcher's attention.**
That found three blind spots, all fixed the same day. It also produced the
rule that stopped the obvious fix from shipping: a terminology change is
*sometimes* significant, so "terminology → dismiss" is exactly the rule that
must not be written.

## Where AI fits, and where it doesn't

**Almost all of this is plain code, and that is a result rather than a gap.**
There was once a ranking layer scoring trials across eight signals. It
worked, and it was deleted anyway, because measuring it answered a question
nobody had asked: *how many of these signals actually need a model?* Four of
five were **filters wearing a score's costume** — "is it recruiting?" is a
yes/no the researcher already stated, and turning it into 20 points that
blend into a 0.87 buries a decision already made.

Two model calls survived that test, both scoped by measurement first. The
**change interpreter** says in plain language what a *prose* amendment means
— and querying the real change-sets before writing the prompt cut it from 212
amendments to the 75 that contain anything a model could add to, at a
measured ~$0.00125/call under a $1.00 rolling ceiling. The **weekly synthesis
agent** is the one genuinely multi-step judgment: *is this week's movement a
pattern or a coincidence?* It files labelled-confidence proposals for a human
to accept or dismiss — never a verdict, never a summed score — and refuses to
run when the record cannot supply two prior windows.

Everything else is deterministic, because each of those questions has exactly
one correct answer. The full reasoning, including what the removal plan got
wrong, is in [`docs/decisions.md`](docs/decisions.md).

## How it works

```
ClinicalTrials.gov v2 API
         │
         ▼
  scripts/run_monitor.py ──── every 6 hours, GitHub Actions
         │                    cheap filter: has lastUpdatePostDate moved?
         │                    expensive diff: only for what actually moved
         ▼
    FastAPI  ─────────────── the only door to the database
         │                   (read-only Postgres role for every GET)
         ▼
  Neon Postgres ──────────▶  Streamlit · weekly agent · weekday digest
```

Change detection is two-phase on purpose: re-fetching 11,000 full records
every 6 hours would be slow and rude to a public API, so the job first
fetches only IDs and update dates, then pulls the full record for the handful
that moved. A typical run refetches under 100 trials.

The constraints the code actually follows — never "eligible", never invent a
study fact, every claim carries its source, no credential in user-visible
output — are in [`CLAUDE.md`](CLAUDE.md). Most of them exist because breaking
one produced a real bug.

## Running it

Requires Python 3.9 and a Postgres database (this uses [Neon](https://neon.tech)).

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

`.env.local` is gitignored and must stay that way. `requirements.txt` pins
the full 63-package closure and `.python-version` pins 3.9.6 — bare package
names once let a deploy resolve Python 3.14 while the suite passed on 3.9, a
green suite certifying software nobody was running.

### Tests

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/ -k "not real_data" -q   # iterate
PYTHONPATH=. .venv/bin/python -m pytest tests/ -q                      # before commit
```

**914 tests.** The ones reading the live database skip themselves without
`DATABASE_URL_READONLY`, so the suite runs green without credentials — that
is what CI does on every push. Endpoints are tested over HTTP, and the
honesty-critical paths are mutation-tested: a planted regression has to
actually turn a test red before the test is trusted.

## Layout

| path | what's in it |
|---|---|
| `api/` | FastAPI — the only door to the database |
| `frontend/` | Streamlit pages, reading through `api_client.py` only |
| `scripts/` | Ingestion, the Monitor/synthesis/digest jobs, schema application |
| `db/schema.sql` | One idempotent source of truth for the schema |
| `tests/` | Free tests; database-backed ones skip without credentials |
| [`docs/gotchas.md`](docs/gotchas.md) | The rules that cost something to learn |
| [`docs/decisions.md`](docs/decisions.md) | Every real decision, dated, with what it cost |
| [`docs/roadmap.md`](docs/roadmap.md) | Per-step build record |
| [`CLAUDE.md`](CLAUDE.md) | The project's constitution |

[`docs/decisions.md`](docs/decisions.md) is the file worth reading if you
want to know why anything here is the way it is. It records the bugs too,
including the ones that cost money and the ones where the fix was verified
wrong the first time.

## Data

All trial data comes from the [ClinicalTrials.gov v2
API](https://clinicaltrials.gov/data-api/api) — public, no authentication.
TrialLens stores the raw response alongside its normalized columns, so a
parsing decision made today can be revisited against the original record —
which has paid off four times, most recently recovering the entire 191,864-edge
graph from records already on disk with no re-fetch.

This is a personal engineering project. It is not a medical device, not
clinical decision support, and not a substitute for reading a trial protocol.
