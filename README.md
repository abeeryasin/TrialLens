# TrialLens

TrialLens watches clinical trials and tells you what changed.

ClinicalTrials.gov only shows you a trial as it looks today. Ask it what the
primary outcome said last year, or when the completion date slipped, and it
has no answer. TrialLens checks every six hours and keeps the record.

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

That trial finished, enrolled 35 fewer people than it planned to, and changed
hands. A search box can't tell you any of that.

**Live:** [triallens-frontend.onrender.com](https://triallens-frontend.onrender.com)
· API at [triallens-api.onrender.com](https://triallens-api.onrender.com)

## Status

Deployed and running on its own since 28 August 2026.

| | |
|---|---|
| Trials watched | 11,453 |
| Conditions | breast cancer, obesity |
| Changes recorded | 1,098, across 450 different trials |
| Primary-outcome changes | 22 |
| Tests | 914 |

Snapshot from 2026-09-08. The app doesn't keep a copy of these — it asks the
API on every load, because an earlier version of this table was out of date
within a day.

All five parts work:

- **Discover** — search a condition. Tracked ones answer from our own data,
  anything else falls back to a live ClinicalTrials.gov lookup, and each
  result tells you which it was.
- **Understand** — one trial in full, with its amendment history and what
  each amendment actually did.
- **Monitor** — everything that changed across all tracked trials, in one feed.
- **Explore** — how trials, sponsors, sites, investigators and drugs connect.
  191,864 edges.
- **Investigate** — patterns across everything: timelines slipping, enrolment
  falling short, trials reopening, primary outcomes being rewritten.

The home page leads with the watch, not a search box. Most weeks nothing
happens, and it says so rather than showing an empty table. If the scheduled
job dies, an alarm replaces the page instead of sitting quietly above a stale
feed.

## I checked the output myself

I'm a doctor. On 7 September I read all 12 substantive primary-outcome
changes TrialLens had flagged and decided which ones mattered. Nine of the
twelve were worth a researcher's time.

That's me grading my own work, not independent review, and it should be read
that way. It was still worth doing — it found three real bugs in how the flag
was calculated, all fixed the same day, and it stopped a bad fix from
shipping. I nearly wrote a rule that dismissed terminology changes
automatically. Some terminology changes matter, so that rule would have
quietly hidden real ones.

What TrialLens still needs is a researcher who didn't build it.

## Where AI fits, and where it doesn't

Most of this is ordinary code, on purpose.

I built an AI ranking layer that scored trials against a stated research
interest across eight signals. It worked. I deleted it anyway, because
measuring it answered a question I hadn't thought to ask: how many of these
signals actually need a model? Four of five were filters dressed up as
scores. "Is it recruiting?" is a yes/no the researcher already told me.
Turning that into 20 points that blend into a 0.87 hides a decision they'd
already made.

Two model calls survived, and I measured before building both:

**The change interpreter** explains what a written amendment means. I queried
the real amendments first, which cut the job down: of 212, only 75 contained
anything a model could add to. The rest changed nothing we store, or moved a
single field that arithmetic handles exactly. It runs in the scheduled job,
never while you're waiting, at about $0.00125 a call.

**The weekly agent** asks the one question that genuinely needs judgement: is
this week's movement a pattern, or a coincidence? It writes up what it thinks
and leaves it for a human to accept or reject. It never decides. If the
record doesn't hold two prior weeks to compare against, it refuses to run
rather than spend money reaching a conclusion it can't support.

Everything else is plain code, because every other question here has one
right answer. The full reasoning, including what I got wrong deleting the
ranking layer, is in [`docs/decisions.md`](docs/decisions.md).

## How it works

```
ClinicalTrials.gov v2 API
         │
         ▼
  scripts/run_monitor.py ──── every 6 hours, GitHub Actions
         │                    cheap check: did the update date move?
         │                    full diff: only for the ones that did
         ▼
    FastAPI  ─────────────── the only way anything reaches the database
         │                   (read-only Postgres role for every GET)
         ▼
  Neon Postgres ──────────▶  Streamlit · weekly agent · weekday digest
```

Re-downloading 11,000 full records every six hours would be slow and rude to
a public API. So each run first asks for IDs and update dates only, then
fetches the full record for the handful that moved. A typical run refetches
under 100 trials.

The rules the code follows — never say "eligible", never invent a study fact,
every claim carries its source, no credentials in anything a user can see —
are in [`CLAUDE.md`](CLAUDE.md). Most of them exist because breaking one
caused a real bug.

## Running it

Needs Python 3.9 and a Postgres database (I use [Neon](https://neon.tech)).

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt

cp .env.example .env.local        # then add your own DATABASE_URL
.venv/bin/python scripts/apply_schema.py

# terminal 1 — the API
PYTHONPATH=. .venv/bin/uvicorn api.main:app --reload

# terminal 2 — the UI
.venv/bin/streamlit run frontend/Home.py
```

Fill it with a first ingest, then let the scheduler take over:

```bash
PYTHONPATH=. .venv/bin/python scripts/run_monitor.py
```

`.env.local` is gitignored and needs to stay that way. The dependencies are
pinned to exact versions: with bare package names, one deploy quietly
resolved Python 3.14 while the tests were passing on 3.9, so the suite was
certifying software nobody was running.

### Tests

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/ -k "not real_data" -q   # while working
PYTHONPATH=. .venv/bin/python -m pytest tests/ -q                      # before committing
```

914 tests. The ones that read the live database skip themselves when there
are no credentials, so the suite is green on a fresh clone — that's what CI
runs. Endpoints are tested over HTTP, and the tests that matter most are
mutation-tested: I break the code on purpose and check the test actually goes
red before trusting it.

## Layout

| path | what's in it |
|---|---|
| `api/` | FastAPI — the only way anything reaches the database |
| `frontend/` | Streamlit pages |
| `scripts/` | Ingestion and the scheduled jobs |
| `db/schema.sql` | The schema, in one idempotent file |
| `tests/` | 914 of them |
| [`docs/gotchas.md`](docs/gotchas.md) | Rules that cost me something to learn |
| [`docs/decisions.md`](docs/decisions.md) | Every decision, dated, with what it cost |
| [`docs/roadmap.md`](docs/roadmap.md) | What got built, step by step |
| [`CLAUDE.md`](CLAUDE.md) | The rules the code follows |

If you only read one, read [`docs/decisions.md`](docs/decisions.md). It has
the bugs in it too — including the ones that cost money, and the ones where
my fix turned out to be wrong.

## Data

Everything comes from the [ClinicalTrials.gov v2
API](https://clinicaltrials.gov/data-api/api) — public, no key needed.
TrialLens keeps the raw response next to the parsed columns, so a parsing
decision I make today can be revisited against the original record later.
That's paid off four times, most recently when the entire 191,864-edge graph
was built from records already on disk without a single new request.

This is a personal project. It is not a medical device, not clinical decision
support, and not a substitute for reading the protocol.
