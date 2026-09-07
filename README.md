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
(Render's free tier — the first request after an idle period can take a
moment to wake.)

## Status, honestly

**Deployed and running unattended.** All five capabilities are built, a
6-hour cron has been ingesting and diffing since 28 August 2026, and a
clinician has judged real output.

| | |
|---|---|
| Trials watched | 11,453 |
| Conditions monitored | breast cancer, obesity |
| Changes recorded | ~1,100, since 2026-08-28 |
| Primary-outcome changes on file | 22 — 19 substantive, 2 entry-completed, 1 reformatting |
| Runs | every 6 hours on GitHub Actions, unattended |
| Tests | 914 |

Those figures move. The app reads them live from `GET /watch` rather than
holding a copy — three of the five in an earlier version of this table had
already drifted a day after they were written down.

The front page leads with the watch itself, not a search box: *"Watching
11,453 trials · checked every 6 hours · last checked 4 hours ago"*, the last
week of amendments including the days with none, and the last thing that
happened. Most weeks nothing does, and a quiet week is stated as a finding
rather than left as an empty table. If the scheduled job stops, the alarm
replaces the page instead of sitting above a stale feed.

All five capabilities are built:

- **Discover** ✅ — search a condition; tracked ones answer from our own
  data, anything else falls back to a live ClinicalTrials.gov lookup, and
  each result says which it was.
- **Understand** ✅ — one trial in full, including its amendment history and
  what each amendment did.
- **Monitor** ✅ — what changed across everything tracked, in one feed.
- **Explore** ✅ — how trials, sponsors, sites, investigators and
  interventions connect, over 191,864 real edges.
- **Investigate** ✅ — synthesis across everything tracked: timeline drift,
  enrolment against plan, lifecycle transitions, and changed primary
  outcomes read against published base rates.

### Judged by a clinician, not just by tests

On 7 September 2026 a clinician read **every substantive primary-outcome
change on file** — 12 of 12 — and called **9 of them worth a researcher's
attention.** That is the validation this project had been missing, and it
found three real blind spots, all fixed the same day: observation windows
were ignored, endpoint descriptions were ignored, and the reformatting
bucket was unreachable from the page.

It also produced the rule that stopped the obvious "fix" from shipping: a
terminology change is *sometimes* significant, so "terminology → dismiss"
is exactly the rule that must not be written. A description match may only
ever de-escalate a specific case, never auto-dismiss a category.

## Where AI fits, and where it doesn't

**Almost all of this is plain code, and that is a result rather than a
gap.** There was once a ranking layer scoring trials across eight signals.
It worked, and it was deleted anyway, because measuring it answered a
question nobody had asked: *how many of these signals actually need a
model?* Four of five were **filters wearing a score's costume** — "is it
recruiting?" is a yes/no the researcher already stated, and turning it into
20 points that blend into a 0.87 buries a decision already made.

Two model calls survived that test, both scoped by measurement:

**The change interpreter** (`api/prose_interpreter.py`) says in plain
language what a *prose* amendment means. Before the prompt was written, the
change-sets were queried, and the data cut the feature down:

| of 212 real amendments | |
|---|---|
| 99 (47%) | change nothing TrialLens stores — nothing to interpret |
| 38 (18%) | move one structured field — a lookup, answered exactly by code |
| 29 (14%) | multi-field combinations, where the *set* means something |
| 46 (22%) | change prose — real language understanding |

So 75 of 212, not 212. And the *category* half turned out to be a static
field-name mapping — paying a model for a verdict code produces exactly is
the mistake the ranking layer already made once. The deterministic half
shipped first, on purpose, which gave the AI layer **a baseline it has to
beat**. It runs in the scheduled job, never in the request path, at a
measured ~$0.00125/call under a $1.00 rolling 30-day ceiling.

**The weekly synthesis agent** (`api/synthesis_agent.py`) is the one
genuinely multi-step judgment in the product: *is this week's movement a
pattern or a coincidence?* It reads `GET /investigate/summary` as its tools
and files labelled-confidence proposals into a review queue for a human to
accept or dismiss — **never a verdict, never a summed score.** It refuses
to run at all when the record cannot supply two prior windows, because
calling one week a trend is something its own prompt forbids.

Everything else — what an amendment did, whether a date slipped, whether an
outcome moved, the whole Investigate engine, the digest, the ops health
surface — is deterministic, because each of those questions has exactly one
correct answer.

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
  does not guess *which* fields they were.
- **Every claim carries its source.** Source study, source field, the
  actual stored value, the interpretation, and the uncertainty. No
  unexplained scores, and no summed ones — flags are listed, never added up.
- **No patient data.** Public registered study data only.
- **No credential in user-visible output.** An error message is output: a
  misconfigured env var once put a live database password on a public page.
  Exceptions are scrubbed before they reach a page or a database column.
- **FastAPI is the only door to the database.** The frontend reads through
  it; the scheduled jobs write through it. Read-only enforcement lives at
  that boundary, in a Postgres role that cannot write whatever the route
  code does.
- **Deterministic first, AI second, agents third.** That principle is why
  the ranking layer was removed rather than improved.

## How it works

```
ClinicalTrials.gov v2 API
         │
         ▼
  scripts/run_monitor.py ──── every 6 hours, GitHub Actions
         │                    cheap filter: has lastUpdatePostDate moved?
         │                    expensive diff: only for what actually moved
         │                    then: graph sync, entity merge, prose interpretation
         ▼
    FastAPI  ─────────────── the only door to the database
         │                   (read-only Postgres role for every GET)
         ▼
  Neon Postgres              raw record + normalized columns + fetch timestamp
         │                   study_changes: every field-level change, kept
         │                   review_queue · monitor_runs · synthesis_runs · digest_runs
         │
         ├──▶ Streamlit      the watch · Discover · Understand · Monitor
         │                   Explore · Investigate · System · Review
         ├──▶ synthesis.yml  weekly agent → review_queue
         ├──▶ digest.yml     weekday email via Resend
         └──▶ /ops/status    named alerts, each carrying its measurement
```

Each amendment is grouped by ClinicalTrials.gov's own version stamp, and
what it did is described in plain language by code — a date that slipped, a
recruitment target that became a real headcount, sites added, results
published.

Change detection is two-phase on purpose: re-fetching 11,000 full records
every 6 hours would be slow and rude to a public API, so the job first
fetches only IDs and update dates, then pulls the full record for the
handful that moved. A typical run refetches under 100 trials.

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

`.env.local` is gitignored and must stay that way. Rotating a leaked key
does not remove it from git history.

`requirements.txt` pins the full 63-package closure, and `.python-version`
pins 3.9.6. That is deliberate: bare package names once let a deploy resolve
Python 3.14 while the suite passed on 3.9 — a green suite certifying
software nobody was running.

### Tests

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/ -k "not real_data" -q   # iterate
PYTHONPATH=. .venv/bin/python -m pytest tests/ -q                      # before commit
```

**914 tests.** The ones that read the live database skip themselves when
`DATABASE_URL_READONLY` is unset, so the suite runs green without
credentials — that is what CI does on every push.

Run the free subset while iterating. Measured on 2026-09-07: the free tests
cost **0.5 MB and 38s**, the real-data tests **56 MB and 161s** — 86% of the
coverage for 0.8% of the bytes, against a 5 GB/month transfer allowance. The
real-data half is not optional before a commit — it is the only thing that
tests the SQL — it just should not run forty times while a docstring is being
edited.

**Coverage is uneven and this is the honest summary:** the endpoints have
HTTP-level tests (a test that calls an endpoint function directly is not
testing the endpoint), pages are rendered through Streamlit's `AppTest`,
the CT.gov parser is checked against real stored responses, real-data tests
catch upstream drift, and the honesty-critical paths are mutation-tested —
a planted regression has to actually turn a test red before the test is
trusted. `ctgov_client.py`'s network paths still have none.

## Layout

| path | what's in it |
|---|---|
| `api/` | FastAPI — the only door to the database |
| `frontend/` | Streamlit pages, reading through `api_client.py` only |
| `scripts/` | Ingestion, the Monitor/synthesis/digest jobs, schema application |
| `db/schema.sql` | One idempotent source of truth for the schema |
| `tests/` | Free tests; database-backed ones skip without credentials |
| `docs/gotchas.md` | The rules that cost something to learn |
| `docs/decisions.md` | Every real decision, dated, with what it cost |
| `docs/roadmap.md` | Per-step build record |
| `CLAUDE.md` | The project's constitution — rules that override convenience |

`docs/decisions.md` is the file worth reading if you want to know why
anything here is the way it is. It records the bugs too, including the ones
that cost money, and the ones where the fix was verified wrong the first
time.

## Data

All trial data comes from the [ClinicalTrials.gov v2
API](https://clinicaltrials.gov/data-api/api) — public, no authentication.
TrialLens stores the raw response alongside its normalized columns, so a
parsing decision made today can be revisited against the original record.
That has paid off four times: `has_results`, site coordinates, per-site
recruitment status and the whole graph extraction were all recovered from
records already on disk, with no re-fetch.

This is a personal engineering project. It is not a medical device, not
clinical decision support, and not a substitute for reading a trial
protocol.
