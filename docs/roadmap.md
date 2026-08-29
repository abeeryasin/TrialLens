# Roadmap — TrialLens

Working document, not permanent — delete once the project is far enough
along that this stops being useful. Time estimates are approximate
active-build hours, assuming ~4 hrs/day; they don't include the ~2
calendar weeks the review queue (step 9) needs to just sit and run
before it produces real evaluation data, which can overlap with later
steps if sequenced well. Total below (~73.5 hrs) lines up with the
original ~70-75 hr estimate made during planning — a useful sanity
check, not a coincidence to worry about.

**Update this file, and the "Current Status" line in `CLAUDE.md`, every
time a step starts or finishes.**

| # | Step | Status | Est. hours |
|---|---|---|---|
| 1 | Schema + Ingestion | **Done** (2026-08-26/27) | — |
| 2 | FastAPI layer (only door to the DB, read-only enforcement) | **Done** (2026-08-27) | — |
| 3 | Scheduler/cron automation (turn `ingest.py` into the real Monitor job; cheap-filter/expensive-diff change detection) | **Done** (2026-08-28) — pushed to GitHub, real 6-hour cron live, first run verified end-to-end on GitHub's infrastructure (11,466 studies checked, 91 needed a full refetch, 102 real changes detected, 33 flagged out of scope, none deleted) | 5-7 |
| 4 | Discover live-fallback (ad-hoc live query for an untracked topic) | **Done** (2026-08-28) — `GET /discover`, verified with a real tracked hit, a real "incidentally already stored" hit, and a real live CT.gov fallback. **Known gap, deferred (see `docs/decisions.md`, 2026-08-28): an untracked condition that incidentally has a few local rows (comorbid tags on tracked trials) is reported as if it were the complete picture — real fix decided (merge local+live, dedupe, per-result source tag) but not built; revisit at step 5 or before step 6 trusts these results** | 3-4 |
| 5 | Frontend (Streamlit) — Discover/Understand surface, reads through FastAPI | **Done** (2026-08-29) — Discover (search, per-result tracked/live tagging, click-through) and Understand (full detail, eligibility as explicit source text, change history) both real, reading through `api_client.py` only. Also fixed the step-4 `/discover` gap along the way rather than deferring it further (see `docs/decisions.md`, 2026-08-29) | 8-10 |
| 6 | Monitor page — aggregate recent-changes feed across all tracked trials, not just per-trial inside Understand (decided 2026-08-29: kept separate from the notifications/digest-email idea in step 12, not a replacement for it) | Not started | 3-4 |
| 7 | AI ranking/evidence layer ("potential fit" screening, visible evidence + uncertainty, eval harness built alongside) | Not started | 10-14 |
| 8 | Knowledge graph (relationships between trials/sponsors/interventions, multi-hop queries) — Explore | Not started | 10-14 |
| 9 | Multi-agent synthesis (agent specialization/handoff, review queue w/ confidence scoring) — Investigate | Not started | 8-10 |
| 10 | Real deployment (Railway/Vercel, production env vars, staging-vs-production split) | Not started | 4-6 |
| 11 | Autonomous-ops hardening (guardrails, safety monitoring, escalation protocol, observability) | Not started | 4-6 |
| 12 | Notifications (Resend daily digest, tied to Monitor) | Not started | 2-3 |

**Total estimate: ~64-83 active hours** (midpoint ~73.5), plus the
unavoidable ~2-week review-queue running time noted above.

Steps 2-4 are the near-term candidates already scoped in detail in
`docs/decisions.md`. Everything from step 5 onward depends on those
existing first.
