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

## Current Status

Steps 1-6 are built, tested, and live: schema + ingestion, the
FastAPI-only-door layer, scheduler/cron automation (a real 6-hour cron
running on GitHub Actions), Discover live-fallback (`GET /discover`), and
the Streamlit frontend — Discover, Understand, and the Monitor feed
(`GET /changes`). Explore and Investigate aren't built yet.

**Step 7 (AI ranking/evidence layer) is in progress** — the first LLM in
the system. `POST /rank` works: five of its eight fit signals run in plain
code (`api/ranking_deterministic.py`, no model client imported), three are
model-judged, and the researcher's interest is parsed once per search
rather than per trial. 103 free tests pass, including every deterministic
scorer against all 11,474 real trials. **Nothing renders it yet — Unit 4,
the Streamlit ranking page, is the next task.** Read
`docs/STEP7_SESSION_SUMMARY.md` first; it carries the eight bugs already
fixed and four decisions the user has deliberately left open.

**Hard constraint: the Anthropic API budget is $5 total, ~$4.45 left.**
An on-disk response cache (`.ranking_cache/`) replays identical requests
for $0, so iterating on weights, scoring, or display costs nothing — only
a real prompt/model change spends. Never put the paid eval harness in CI.

Three standing gotchas worth knowing before touching data: the Neon branch
named `dev` is the real live database (`production` is an empty leftover;
use `sandbox` to rehearse destructive changes); a `JOIN` against
`study_conditions` needs `DISTINCT` before its output feeds a write; and
the stored values rarely match what the API docs imply — phase is `PHASE2`
not "Phase 2", 64% of trials have no usable phase, ages carry units other
than years, and `CLOSED` is not a real status. Query the real
distributions before writing a query **or a prompt** (§6). Full status and
dated reasoning: `docs/roadmap.md`, `docs/decisions.md`.
