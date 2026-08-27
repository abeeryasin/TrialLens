# Roadmap — TrialLens

Working document, not permanent — delete once the project is far enough
along that this stops being useful. Time estimates are approximate
active-build hours, assuming ~4 hrs/day; they don't include the ~2
calendar weeks the review queue (step 8) needs to just sit and run
before it produces real evaluation data, which can overlap with later
steps if sequenced well. Total below (~71.5 hrs) lines up with the
original ~70-75 hr estimate made during planning — a useful sanity
check, not a coincidence to worry about.

**Update this file, and the "Current Status" line in `CLAUDE.md`, every
time a step starts or finishes.**

| # | Step | Status | Est. hours |
|---|---|---|---|
| 1 | Schema + Ingestion | **Done** (2026-08-26/27) | — |
| 2 | FastAPI layer (only door to the DB, read-only enforcement) | **Next up** | 6-8 |
| 3 | Scheduler/cron automation (turn `ingest.py` into the real Monitor job; cheap-filter/expensive-diff change detection) | Not started | 5-7 |
| 4 | Discover live-fallback (ad-hoc live query for an untracked topic) | Not started | 3-4 |
| 5 | Frontend (Streamlit) — Discover/Understand surface, reads through FastAPI | Not started | 8-10 |
| 6 | AI ranking/evidence layer ("potential fit" screening, visible evidence + uncertainty, eval harness built alongside) | Not started | 10-14 |
| 7 | Knowledge graph (relationships between trials/sponsors/interventions, multi-hop queries) — Explore | Not started | 10-14 |
| 8 | Multi-agent synthesis (agent specialization/handoff, review queue w/ confidence scoring) — Investigate | Not started | 8-10 |
| 9 | Real deployment (Railway/Vercel, production env vars, staging-vs-production split) | Not started | 4-6 |
| 10 | Autonomous-ops hardening (guardrails, safety monitoring, escalation protocol, observability) | Not started | 4-6 |
| 11 | Notifications (Resend daily digest, tied to Monitor) | Not started | 2-3 |

**Total estimate: ~61-79 active hours** (midpoint ~71.5), plus the
unavoidable ~2-week review-queue running time noted above.

Steps 2-4 are the near-term candidates already scoped in detail in
`docs/decisions.md`. Everything from step 5 onward depends on those
existing first.
