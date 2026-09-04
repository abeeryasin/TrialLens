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

All five capabilities are live (Discover, Understand, Monitor, Explore,
Investigate) — schema + ingestion, the FastAPI-only-door layer, a real
6-hour GitHub Actions cron, and the Streamlit frontend. **669 tests pass.**
Dated reasoning: `docs/decisions.md`. Per-step build status:
`docs/roadmap.md`. This section stays short on purpose — a status essay
copied into three files goes stale in three files.

**The weekly synthesis agent (step 9 follow-on) is built and live** — the
one genuinely multi-step judgment in the product ("is this week's movement a
pattern or a coincidence?"), reading `/investigate` as its tools and filing
labelled-confidence proposals into `review_queue` for human review. Never a
verdict, never a summed score (§3). Its own weekly `synthesis.yml` cron
live. First real run (2026-09-04, $0.1099) filed zero proposals — explained,
not assumed: real monitoring is only ~1 week old, so the agent had nothing
yet to call a trend, per its own system prompt. Design, build, and that
first-run read: `docs/decisions.md`, 2026-09-04/05.

**Step 10 (real deployment) is in progress, started 2026-09-05.** Platform
is Render (free tier + a free UptimeRobot ping, not a paid always-on tier —
real budget constraint, see `docs/decisions.md`). The long-flagged Neon
rename is done (`dev` → `production`), and tracked conditions moved off a
config file into a real database table with a UI to add one. `render.yaml`
is written; deploying it and wiring env vars is the user's own dashboard
work, in progress. Steps 11-12 (ops hardening, notifications) untouched.

Standing gotchas, dated postmortem for each in `docs/decisions.md`:

- A `JOIN` against `study_conditions` needs **`DISTINCT`** before feeding a
  write — that table is wiped and re-inserted wholesale every batch upsert.
- **Never `SELECT *` against `studies`** — `raw_json` is 52% of the table.
  Use `STUDY_DETAIL_COLUMNS`.
- Stored values rarely match the API docs: phase is `PHASE2` not "Phase 2",
  64% of trials have no usable phase, `hasResults` sits above
  `protocolSection`. Query real distributions before a query **or prompt** (§6).
- **`git add -A` is not safe here** — it has committed an installed skill
  and a 2.4 MB design canvas in one session. Stage deliberately.
- This project's real text runs ~2.61 chars/token, not ~4.0 — re-measure
  any cost estimate rather than trusting an old one.

**Doesn't travel with a clone**, all gitignored: `.env.local` (DB URLs —
real-data tests skip cleanly without it), `.ranking_cache/` (orphaned
since step 7's removal), `.claude/skills/`, `design/triallens-the-watch.html`
(rebuild from `design/*.dc.html`).
