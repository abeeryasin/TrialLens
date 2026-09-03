# TrialLens — Project Constitution

## 1. Project Identity

TrialLens is a clinical-trial intelligence and monitoring tool for a clinical researcher tracking a therapeutic area over time — not a one-time patient search. Built on the real ClinicalTrials.gov v2 API (public, no auth, ~50 req/min, verified live 2026-08-25).

Five capabilities, each a different kind of question:
- **Discover** — what trials match this? (search)
- **Understand** — why does this trial matter? (reading comprehension)
- **Monitor** — tell me when something changes (watch-over-time)
- **Explore** — who else works in this space? (relationships — knowledge graph)
- **Investigate** — what's happened across everything tracked? (synthesis)

Also a vehicle for an external engineering course — when the two conflict, course understanding wins. Course-tracking material stays private, outside this repo.

## 2. Non-Negotiable Product & Safety Rules

- Never "patient eligibility" — use "potential fit," "potential conflict," "requires review," "insufficient information." The system doesn't know enough about a real person to determine eligibility.
- No real patient data (PHI) — public, registered study data only.
- **Never write a live credential into a repo file** — no API keys in code, docs, session notes, or handoff files, even untracked ones. Keys live in `.env.local` (gitignored); repo files get a placeholder name only. A committed key can't be un-committed by rotating it.
- Never invent a study fact, represent an LLM's inference as a source fact, claim a patient is eligible, make a clinical decision, or silently resolve ambiguous eligibility — say so explicitly when evidence is insufficient.

## 3. Evidence Requirements

Every substantive trial claim preserves source study, source field, the relevant source text/value, the interpretation, and the uncertainty. No unexplained relevance scores, no black-box ranking — evidence stays visible, not just the conclusion.

## 4. Source-of-Truth Rules

- ClinicalTrials.gov v2 API is the only source of trial facts. Store the raw record, a normalized version, and the fetch timestamp.
- Real snapshot-diffing decides whether a trial changed — cheap filter first (`lastUpdatePostDateStruct` moved?), expensive diff only on what passes. See `docs/decisions.md`.

## 5. Architecture Principles

- **Deterministic first, AI second, agents third** — plain code for one-correct-answer tasks, a single AI call only where language understanding is needed, a full agent only where multi-step judgment is needed.
- **FastAPI is the only door to the database** — frontend reads through it, the scheduled fetcher writes through it; also where read-only enforcement for query-side agents lives. Load-bearing from day one, not speculative.
- **No vector store yet** — real once a local trial cache exists, not needed for the walking skeleton.
- Literature Q&A per trial is a logged future idea, not built now.

## 6. Development Workflow

- **Schema-first**: read the real schema before writing a query, every time.
- **Status-first**: read `docs/roadmap.md` before a build step; check `docs/decisions.md` before re-deciding something already settled.
- **Teaching loop flexes per task** — explain-then-attempt for substantial concepts, direct build for boilerplate.
- **Close the loop** after meaningful work: what happened, what got learned, what's written down, what's next.
- **Quiz before writing a course artifact** — from corrected understanding, not before it.
- **Verify external claims** before trusting them (API behavior, pricing, tool limits, another AI's suggestions) — through the build, not just planning.

## 7. Verification & Quality Gates

- Code generating successfully isn't the finish line — run tests, type/lint checks, test actual behavior, inspect real output, verify against acceptance criteria.
- For AI behavior: explicit evaluation cases (search/ranking/eligibility/change-detection), not qualitative inspection alone, built from the start.
- Nothing is "done" because a file exists — real evidence only.
- **No paid model call until a free test of the same path passes**, and
  batch the paid questions that remain. Run `scripts/paid_preflight.py`
  first; it refuses when the free suite is red and lists what is still
  waiting on a paid answer. Bug #9 cost $0.13 to discover live and was
  findable for $0 by an HTTP-level test written afterwards instead of first.
- A test that calls an endpoint function directly is not testing the
  endpoint — request binding and response validation are FastAPI's job, and
  only an HTTP-level call exercises them.

## Current Status

Steps 1-6 are built, tested, and live: schema + ingestion, the
FastAPI-only-door layer, scheduler/cron automation (a real 6-hour cron
running on GitHub Actions), Discover live-fallback (`GET /discover`), and
the Streamlit frontend — Discover, Understand, and the Monitor feed
(`GET /changes`). **332 tests pass.** Investigate isn't built.

**START HERE (next session, 2026-09-04).** Step 8's graph is built and
**entirely invisible** — nothing a user can see changed in three days. There
is no `explore` router (`api/main.py` registers studies, discover, changes,
watch) and nothing in `api/` or `frontend/` reads the graph tables. Sitting
in the database, unreachable: **191,864 edges** across 8 tables, **49,606
sites with coordinates**, **40,011 edges with a recruitment status**, and
**7 prose interpretations**. `frontend/labels.format_site_status()` is
written and called by nothing.

So: **build `GET /explore/{nct_id}` and `frontend/pages/4_Explore.py`
first, and defer unit 3 (the merge step).** The roadmap lists merge first;
that order is wrong. The merge exists to fix "381 Madrid facility strings
are 381 sites", but no page has ever displayed a site list — group by city
and country, which is what "who else works in this space?" actually asks,
and those 381 variants may never surface. Building the merge first risks
solving a problem the UI does not have, which is the step 7 mistake exactly.
Let the real page say whether merging is needed. Requirements the page must
meet are already written in `docs/plan_explore_nodes.md` §4b — including
that 1,666 sites cannot be placed on a map and the page has to say so rather
than silently shrinking the result set.

**Step 7 (AI ranking layer) was built, measured, and removed** on
2026-09-01. Measuring it produced the case against it: four of its five
scored signals were filters wearing a score's costume, and only "is this
trial actually about the condition?" was a genuine judgment — whose value
scales with volume, in a product that is deliberately low-volume (~17
changed trials a week). `/rank` no longer exists; 75 free tests pass. The
deterministic scorers survive with no importer yet, waiting to become
filter predicates. `f9ccb45` stays in history as the documented dead end —
a commit saying "we built this, measured it, and it didn't earn its place"
is evidence, not clutter.

**Step 7b is done** (2026-09-02). Three time-based directions:
**Direction 1, amendment history** — `GET /studies/{nct_id}/amendments` groups
a trial's changes into the amendments that caused them, `api/amendments.py`
says what each did — dates that slipped, targets that became actuals, sites
added, results posted — with no model. Understand leads with it.

**Direction 2, the watch** — `GET /watch` and a rebuilt `frontend/Home.py`
where the watch leads and the capability grid sits below it. Three states,
all tested through Streamlit's `AppTest` — the quiet week stated as a finding
with its zero days drawn as zeros, a news week led by what changed the science
rather than by a row count, and an alarm that *replaces* the page instead of
sitting above it. The footer states "212 trial updates · 498 individual field changes" — concrete enough that users needn't decode what the numbers mean.

**Direction 3, the watch record** — `monitor_runs` table (2026-09-02). Every
scheduled run opens a row at the start and closes it `completed` at the end,
with trials checked and changes detected. `/watch` reads `last_checked_at`
from the newest completed run, and `last_checked_source` is gone — the value
is a record now, not a proxy needing a label.

**The empty-table trap that deferred this was solved by backfilling, not by
waiting.** A fresh `monitor_runs` reads as "never checked" and fires the
alarm on a healthy watch — the exact reason the roadmap pushed this to step
10. The way out: the proxy it replaces *is* evidence a run completed, so
`scripts/backfill_monitor_runs.py` seeds one row from
`max(studies.last_matched_at)` and the cron takes over from there. Its
`changes_detected` is left NULL — nothing on file says how many changes that
particular run found, and writing a number would invent one (§2). Verified
live: `/watch` reports healthy, 4.95 hours since check, off run #1. 278
tests pass.

**Step 7b refinement (2026-09-02, committed):** enrollment counts now tracked
through amendment history via `enrollment_context()` function. When an amendment
changes enrollment_type, the description now includes both counts as they were
at that moment, not today's value. Real case: NCT03402139 now reads "the target
of 400 was replaced by a real count of 163" instead of the old generic sentence.
Required walking the trial's history backwards to establish which count was true
before each amendment. All 279 tests pass.

**Step 8 (Explore) — units 1, 2 and 2b are done** (2026-09-02/03), unit 3
and the UI are not. See the START HERE block above for what to do next and
why the roadmap's ordering was changed.

- **Unit 1, the shape:** relational tables, not a graph database. The graph
  already exists in `studies` — `lead_sponsor` holding 'Mayo Clinic' on 134
  rows *is* 134 edges, written as repeated text. At 11,518 trials and 2-3
  hop questions, index-free adjacency buys nothing a second sync path
  doesn't cost back.
- **Unit 2, extraction:** 6,207 organizations (lead sponsors and
  collaborators in ONE table — 887 names are both), 51,272 sites, 7,717
  investigators, 14,468 intervention terms, 191,864 edges. All from stored
  `raw_json`, no CT.gov call. **Nothing is merged on purpose** — 381 Madrid
  facility strings are 381 sites, and that unmerged extraction is the
  baseline any later merge gets checked against.
- **Unit 2b, node ranking + site enrichment:** an evidence review
  (`docs/plan_explore_nodes.md`) asked whether researchers care about
  collaborations. They don't, and the reason is definitional — CT.gov's
  collaborator field covers funders *and* co-designers with no way to
  separate them, reaches 37.4% of trials, and explicitly excludes
  individuals. **Kept, but demoted from a network to traverse to an
  attribute to filter on.** Sites lead instead at 93.8% coverage, so the
  fields the parser had dropped were backfilled from `raw_json`.
- **Edges are stamped `delisted_at`, never deleted.** Extraction is
  insert-only, so a trial dropping a site left the edge live and Explore
  would have said the trial still runs there. Stamping keeps it as a
  finding — "this trial quietly dropped three sites" is a result in a
  watch-over-time product. NULL means live. **The backfill now runs inside
  `monitor.yml` after every ingest**, so the graph no longer goes stale.
- 18 real-data tests, 14/14 mutations caught, all rolled back in-transaction.

**Also done earlier this session:** enrollment_type switches now name the numbers,
e.g. "the target of 400 was replaced by a real count of 163" instead of
just "the recruitment target was replaced". This required walking a trial's
history backwards to establish which count was true AT EACH AMENDMENT, not
just today's value. 270 free tests pass.

**`has_results` was found missing on 2026-09-02 and added.** `hasResults`
sits at the TOP level of the CT.gov response, not inside `protocolSection`,
so the parser never saw it; 1,056 of 11,518 trials already had results
posted, and each of those amendments had been rendering as "the record
changed; we can't show what". Backfilled from stored `raw_json` with no
network call — the first time §4's keep-the-raw-record rule paid for
itself. Roughly 40% of amendments still show nothing: `referencesModule`
(4,443 trials), `oversightModule` and central contacts remain unread.

**There is a README, and CI actually runs the tests** (both new 2026-09-02).
`tests.yml` runs the suite on every push without secrets — 226 pass, 22
skip; the 22 data-drift/real-data tests run in `monitor.yml` instead, on
the data's schedule. Before this, nothing ever ran the suite automatically.
Streamlit pages are testable: `streamlit.testing.v1.AppTest` renders a page
and returns its element tree, which is the only way the alarm state is ever
seen (it needs a 12-hour-dead cron). `st.metric` carries its heading on
`.label` and its figure on `.value` — read both, or half the footer is
invisible to every assertion.

**Step 7c is live and now genuinely stores interpretations** (2026-09-03/04).
The `ANTHROPIC_API_KEY` secret was added on 2026-09-03 and the first real
batch ran: 14 prose changes found, 8 stored. Everything below replaces the
earlier "stores nothing" state, which was true until that key existed.

Three faults were fixed once real output could be read:

- The write used MySQL's `UPDATE ... ORDER BY ... LIMIT`; Postgres rejects it
  and the `except` swallowed it. Writes by primary key now, and
  `get_prose_amendments` carries `id` so an interpretation lands on the exact
  row it describes.
- The no-change gate was `summary.lower() != "no change"`, an exact match
  against prose the model writes freely. It wrote "No meaningful change—the
  criteria were reformatted…" and a paid call announcing nothing was stored
  as a finding. The model now fills in **`MEANINGFUL: yes|no`** and the gate
  reads that field.
- **`why_matters` was dropped** — ~48% of output tokens, and every weak line
  in the batch lived there. `summary` is tethered to the diff and checkable;
  `why_matters` was speculation stored beside it with equal authority (§2).
  A clinical researcher told the AE denominator moved to all randomized
  patients does not need to be told that is an ITT shift.

**Quality verdict on the first real batch, read row by row: 2 clearly
valuable, 2 debatable, 4 reformatting.** Not "7 of 8 are real" — that claim
was made after reading only four. The gate was then verified on the exact
rows the old one got wrong: 4 real calls, **4/4 agreement with a human
reading** (dropped NCT03674567 and NCT06803888, stored NCT06635980 and
NCT05846789). Stored data reconciled: non-change row cleared, `why_matters`
stripped, **7 interpretations on file**.

**Cost is measured now, not multiplied.** `COST_ESTIMATE_PER_CALL` used to be
the recorded spend as well as the pre-flight guess, so the ceiling summed a
constant. Spend comes from `response.usage` at haiku-4-5's $1/$5 per MTok.
A third bug fell out of that: spend was added only when an interpretation came
back, so every "no change" call was real money recorded as $0.00 — invisible
to its own ceiling. Billing keys on *a call happened* now.

**Real cost: ~$0.00125/call** (measured over 4 calls, range
$0.00066–$0.00297; the spread is input length). The 0.004 estimate is ~3x
high and is left that way deliberately — it is the "may I spend more?" guard,
and over-estimating stops early while under-estimating walks through the
ceiling.

**Two ceilings, and the binding one is cumulative:** `PROSE_BUDGET_USD = 0.25`
and `PROSE_MAX_CALLS = 50` bound one run; `PROSE_ROLLING_CEILING_USD = 1.00`
over `PROSE_ROLLING_WINDOW_DAYS = 30` bounds the month, read from
`monitor_runs.prose_spend_usd`. Per-run budget is `min(budget, remaining)`.
At the measured rate $1.00 buys roughly 800 calls, not the ~250 assumed when
it was set. Recorded 30-day spend is $0.0320 — still yesterday's inflated
arithmetic; every run from here records real money.
`docs/plan_relevance_column.md` holds a second, further deferred AI feature.

**The amendment grouping key is the trial's own `last_update_post_date`,
never `detected_at`** — one cron run spreads its writes across a minute
boundary, so grouping by minute reports one amendment as two. Rows of one
amendment share an exact `detected_at` because Postgres `now()` is
transaction-start time; three real-data tests hold that.

**Anthropic account credits: $0.30 max budget for step 7c.** Real measured
cost on step 7c: **~$0.004 per amendment** (claude-haiku-4-5). Step 7
measured **~$0.019 per trial** (opus, now deleted), **~$0.0016** on the
one-question replacement — *not* the $0.006 in older notes (measured
against synthetic fixtures). This project's real text is **2.61 characters
per token**, not the usual ~4.0 rule of thumb; assuming 4.0 understates
any estimate by ~53%. Re-measure before quoting. `.ranking_cache/` still
replays recorded requests for $0. Never put a paid harness in CI.

Standing gotchas, before touching data or git:

- The Neon branch named **`dev` is the real live database** (`production`
  is an empty leftover; use `sandbox` to rehearse destructive changes).
- A `JOIN` against `study_conditions` needs **`DISTINCT`** before its
  output feeds a write, and that table is **deleted and re-inserted
  wholesale on every batch upsert** — never store anything durable on it.
- **Never `SELECT *` against `studies`** — `raw_json` is 52% of the table
  and no query reads it. Use `STUDY_DETAIL_COLUMNS`.
- Stored values rarely match what the API docs imply — phase is `PHASE2`
  not "Phase 2", 64% of trials have no usable phase, ages carry units
  other than years, `CLOSED` is not a real status, and `hasResults` sits
  a level above every other field. Query the real distributions before
  writing a query **or a prompt** (§6).
- **`git add -A` is not safe in this repo.** It has committed an installed
  skill into the public tree and a 2.4 MB generated design canvas, both in
  one session. Stage deliberately.

**What does not travel with a clone**, all gitignored: `.env.local` (the
database URLs — without it the 12 real-data tests skip cleanly rather than
failing), `.ranking_cache/` (71 recorded responses; nothing reads them now
that ranking is gone — keep or delete deliberately), `.claude/skills/`, and
`design/triallens-the-watch.html` (rebuild it from `design/*.dc.html`).

Full status and dated reasoning: `docs/roadmap.md`, `docs/decisions.md`.
Where the project is going next, and its known gaps: `docs/roadmap.md` rows
7b/7c and the Current Status above — deliberately not a separate handoff
file, which went stale twice and was read only when someone remembered it
existed.
