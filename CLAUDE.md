# TrialLens — Project Constitution

## 1. Project Identity

TrialLens is a clinical-trial intelligence and monitoring tool for a
clinical researcher tracking a therapeutic area over time — not a
one-time patient search. Built on the real ClinicalTrials.gov v2 API
(public, no auth, ~50 req/min, verified live 2026-08-25).

Five capabilities, each a different kind of question:
- **Discover** — what trials match this? (search)
- **Understand** — why does this trial matter? (reading comprehension)
- **Monitor** — tell me when something changes (watch-over-time)
- **Explore** — who else works in this space? (relationships — the knowledge graph's job)
- **Investigate** — what's happened across everything tracked? (synthesis)

Also a vehicle for an external engineering course. When project
progress and genuine course understanding are ever in tension, course
understanding wins. Detailed course-tracking material is kept private,
outside this repo.

## 2. Non-Negotiable Product & Safety Rules

- Never call this "patient eligibility" — the system doesn't know
  enough about a real person to determine that. Use "potential fit,"
  "potential conflict," "requires review," "insufficient information."
- No real patient data (PHI) ever enters this system — public,
  registered study data only.
- Never invent a study fact. Never represent an LLM's inference as a
  source fact. Never claim a patient is eligible. Never make a clinical
  decision. Never silently resolve ambiguous eligibility criteria — when
  evidence is insufficient, say so explicitly.

## 3. Evidence Requirements

Every substantive trial claim preserves: source study, source field,
the relevant source text/value, the interpretation, and the
uncertainty. Never produce an unexplained relevance score. Never hide a
ranking's reasoning behind a black box — the evidence stays visible,
not just the conclusion.

## 4. Source-of-Truth Rules

- ClinicalTrials.gov v2 API is the only source of trial facts. Store
  the raw record, a normalized version, and the fetch timestamp.
- Real snapshot-diffing, not an LLM's judgment, decides whether a trial
  changed — cheap filter first (did `lastUpdatePostDateStruct` move?),
  expensive diff only on what passes. See `docs/decisions.md`.

## 5. Architecture Principles

- **Deterministic first, AI second, agents third.** Plain code for
  anything with one correct, repeatable answer. A single AI call only
  where the task needs language understanding. A full agent only where
  the task needs multi-step judgment.
- **FastAPI is the only door to the database** — the frontend reads
  through it, the scheduled fetcher writes through it. Deliberate and
  load-bearing from day one, not speculative scaffolding — also where
  read-only enforcement for query-side agents lives.
- **No vector store yet** — a real later addition once a local trial
  cache exists, not needed for the walking skeleton.
- Pulling in supporting literature per trial (via a separate document
  Q&A capability) is a logged future idea, not built now.

## 6. Development Workflow

- **Schema-first**: read the real schema before writing a query, every
  time.
- **Teaching loop flexes per task** — explain-then-attempt for
  substantial concepts, direct build for boilerplate. Ask if unclear.
- **Close the loop** after meaningful work: what happened, what got
  learned, what gets written down, what's next.
- **Quiz before writing a course artifact** — write from corrected
  understanding, not before it.
- **Verify external claims before trusting them** — API behavior,
  pricing, tool limits, what another AI suggests. Keep applying this
  through the build, not just during planning.

## 7. Verification & Quality Gates

- Code generating successfully is never the finish line. After a
  meaningful change: run relevant tests, run type/lint checks where
  applicable, test actual behavior, inspect real output, verify against
  the original acceptance criteria.
- For AI behavior specifically, use explicit evaluation cases (search /
  ranking / eligibility / change-detection) rather than qualitative
  inspection alone — built from the start, not bolted on.
- Nothing is "done" because a file exists — real evidence only.

## Current Status

Planning complete as of 2026-08-26 — persona, architecture, and safety
framing decided, see `docs/decisions.md`. Phase A (schema + ingestion)
not yet started.
