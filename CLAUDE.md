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
(`GET /changes`). Explore and Investigate aren't built yet.

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

**Step 7b is done** (2026-09-02, two commits). Three time-based directions:
**Direction 1, amendment history** — `GET /studies/{nct_id}/amendments` groups
a trial's changes into the amendments that caused them, `api/amendments.py`
says what each did — dates that slipped, targets that became actuals, sites
added, results posted — with no model. Understand leads with it.

**Direction 2, the watch** — `GET /watch` and a rebuilt `frontend/Home.py`
where the watch leads and the capability grid sits below it. Three states,
all tested through Streamlit's `AppTest` — the quiet week stated as a finding
with its zero days drawn as zeros, a news week led by what changed the science
rather than by a row count, and an alarm that *replaces* the page instead of
sitting above it. `last_checked_at` is a labelled proxy (`max(studies.last_matched_at)`) because nothing yet records that a run happened. The footer states "212 trial updates · 498 individual field changes" — concrete enough that users needn't decode what the numbers mean.

**Direction 3, the watch record** — a `monitor_runs` table, deferred to step 10.
It would replace the proxy and add runs-completed/checks-missed, but it starts
empty (an empty run table reads as "never checked" — the alarm), so the proxy
has to survive until the table fills. Worth doing when deploying.

**Also done this session:** enrollment_type switches now name the numbers,
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

**One AI call is planned and scoped, not built** (step 7c): interpreting
the *prose* half of an amendment, in the scheduled job, never in the
request path. Querying first shrank it from "interpret every amendment" to
75 of 212 — 47% change nothing we store, and the category half is a static
field lookup. It is blocked on credits, and the deterministic layer shipped
first on purpose, so the question "does a model add anything over this?"
has a control. `docs/plan_relevance_column.md` holds a second, further
deferred AI feature.

**The amendment grouping key is the trial's own `last_update_post_date`,
never `detected_at`** — one cron run spreads its writes across a minute
boundary, so grouping by minute reports one amendment as two. Rows of one
amendment share an exact `detected_at` because Postgres `now()` is
transaction-start time; three real-data tests hold that.

**Hard constraint: the Anthropic account is out of credits as of
2026-09-01.** No paid call can run. Everything except ranking is
unaffected. Real measured cost is **~$0.019 per trial** on the step-7
prompt, and **~$0.0016** on the one-question replacement — *not* the
$0.006 in older notes, which was measured against synthetic fixtures. This
project's real text is **2.61 characters per token**, not the usual ~4.0
rule of thumb; assuming 4.0 understates any estimate by ~53%. Re-measure
before quoting. `.ranking_cache/` still replays recorded requests for $0.
Never put a paid harness in CI.

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
