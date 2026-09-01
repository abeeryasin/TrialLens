# TrialLens

A monitoring tool for clinical trials. It watches a therapeutic area over
time and tells you what changed — not a search box you re-run and re-read.

ClinicalTrials.gov holds only a trial's **current** version. Ask it what a
trial says today and it will tell you; ask it what the primary outcome said
last year, or when the completion date slipped, and it has no answer.
TrialLens records every change it sees, so it can.

```
NCT02954874 — Amended twice since TrialLens started watching on 28 August 2026
              One of them, on 28 August 2026, changed only fields TrialLens
              doesn't store — the record changed, but not in anything we hold.

  Posted 31 August 2026
    ⚙ Operational
    Completion date         2026-08-31 → 2027-08-27   pushed about 12 months later
    Enrollment              1,155      → 1,195        increased by 40
    Enrollment figure type  ESTIMATED  → ACTUAL       the target became a real count
    Primary completion      2026-08-31 → 2026-08-03   pulled about 4 weeks earlier
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
| Trials with results posted | 1,056 (751 of them completed) |
| Runs | every 6 hours on GitHub Actions, unattended |

Three of five planned capabilities are built:

- **Discover** ✅ — search a condition; tracked ones answer from our own
  data, anything else falls back to a live ClinicalTrials.gov lookup, and
  each result says which it was.
- **Understand** ✅ — one trial in full, including its amendment history.
- **Monitor** ✅ — what changed across everything tracked, in one feed.
- **Explore** ⬜ — how trials, sponsors and interventions connect. Not built.
- **Investigate** ⬜ — synthesis across everything tracked. Not built.

## Where AI fits, and where it doesn't

**There is no model call in this system today, and that is a result rather
than a gap.**

There was one. A ranking layer scored trials against a stated research
interest across eight signals. It worked — it returned real scored trials
over HTTP with visible evidence for each. It was deleted anyway, because
measuring it answered a question nobody had asked: *how many of these
signals actually need a model?*

Four of the five scored signals were **filters wearing a score's costume**.
"Is it recruiting?" is a yes/no the researcher already stated; turning it
into 20 points that blend into a 0.87 buries a decision that was already
made. The test that separates them: *could the user have answered this
before seeing any results?* If yes, it is a filter. Exactly one signal
survived — "is this trial actually about the condition, or merely tagged
with it?" — and its value scales with volume, in a product that deliberately
sees about 17 changed trials a week.

Real measured cost was **~$0.019 per trial**, three times the figure this
project's own earlier notes claimed, because those were measured against
synthetic fixtures rather than real records.

### What is planned, and what it is waiting on

**One call, scoped by measurement rather than ambition.** The change
interpreter: given an amendment, say in plain language what it means for a
researcher. Before writing the prompt, the change-sets were queried, and the
data cut the feature down:

| of 212 real amendments | |
|---|---|
| 99 (47%) | change nothing TrialLens stores — nothing to interpret, and asking a model would invite invention |
| 38 (18%) | move one structured field — a lookup, answered exactly by code |
| 29 (14%) | multi-field combinations, where the *set* means something |
| 46 (22%) | change prose — real language understanding |

So **75 of 212**, not 212. And within those, the *category* half
(scientific / operational / administrative) turned out to be a static
field-name mapping — paying a model for a verdict code produces exactly is
the mistake the ranking layer already made once.

**The deterministic half shipped first, on purpose.** `api/amendments.py`
now says what an amendment did wherever arithmetic has a real answer: a date
that slipped, sites added, a target that became an actual, results
published. It refuses, permanently and by test, to say what a *prose* change
means — "+3 / −14 words" is arithmetic; "the trial narrowed its population"
is a reading of clinical text.

That refusal is the boundary where a model would genuinely earn its cost.
Shipping the free half first also produces something this project has never
had: **a baseline the AI layer has to beat.** "Does the model's prose add
anything over this?" is now an answerable question with a control.

It is blocked on API credits, will run in the scheduled job and never in the
request path, and will carry a hard batch cap and spend ceiling. A second,
further-deferred AI feature — per-trial relevance classification — is specced
in [`docs/plan_relevance_column.md`](docs/plan_relevance_column.md).

Full dated reasoning for all of it is in
[`docs/decisions.md`](docs/decisions.md); the removal commit is kept in
history rather than rewritten away.

## Rules the code follows

These are constraints, not aspirations — most exist because breaking one
produced a real bug.

- **Never "eligible."** The system says "potential fit", "requires review",
  or "insufficient information". It does not know enough about a real
  person to determine eligibility, and it never claims to.
- **Never invent a study fact.** When the record doesn't say, the answer is
  "we can't tell" — shown to the user in those words. A large minority of
  amendments touch only fields TrialLens doesn't store, and those are named
  by date as exactly that, never rendered as "no changes". The system also
  does not guess *which* fields they were: it cannot see them, and saying
  otherwise would be inventing a finding.
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

Each amendment is grouped by ClinicalTrials.gov's own version stamp, and
what it did is described in plain language by code, not by a model — a date
that slipped, a recruitment target that became a real headcount, sites added
or removed, results published.

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

201 tests. The 12 that read the live database skip themselves when
`DATABASE_URL_READONLY` is unset, so the suite runs green without
credentials — that is what CI does.

**Test coverage is uneven and this is the honest summary:** the amendment
history, `/changes` and `/discover` endpoints have HTTP-level tests, the
CT.gov parser is checked against real stored responses, and the real-data
checks catch upstream drift. Everything in `scripts/` — including the
scheduled job itself — and `ctgov_client.py`'s network paths still have
none.

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
