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
| 4 | Discover live-fallback (ad-hoc live query for an untracked topic) | **Done** (2026-08-28) — `GET /discover`, verified with a real tracked hit, a real "incidentally already stored" hit, and a real live CT.gov fallback. The under-reporting gap found the same day (an untracked condition with a few incidental local rows being reported as the complete picture) was **fixed 2026-08-29**, not left deferred: merged local+live with per-result source tags | 3-4 |
| 5 | Frontend (Streamlit) — Discover/Understand surface, reads through FastAPI | **Done** (2026-08-29) — Discover (search, per-result tracked/live tagging, click-through) and Understand (full detail, eligibility as explicit source text, change history) both real, reading through `api_client.py` only. Also fixed the step-4 `/discover` gap along the way rather than deferring it further (see `docs/decisions.md`, 2026-08-29) | 8-10 |
| 6 | Monitor page — aggregate recent-changes feed across all tracked trials, not just per-trial inside Understand (decided 2026-08-29: kept separate from the notifications/digest-email idea in step 12, not a replacement for it) | **Done** (2026-08-29/30) — `GET /changes` (own top-level router, real JOIN against `studies`, `idx_study_changes_detected_at`), `frontend/pages/3_Monitor.py`, Home wired to it. Extended 2026-08-30 after real use: 25-per-page paging, five filters (condition / change type / field / detected-within / trial-freshness), inline structured diffs, and honest rendering of stored values (see step 6b) | 3-4 |
| 6b | Data-honesty follow-ups surfaced by actually using Monitor (2026-08-30) | **Done** — real `reconcile_scope` bug fixed (missing `DISTINCT` duplicated a change row per matching condition tag; one trial with 19 "breast cancer" AJCC stage tags logged 19 copies), 22 duplicate rows + 3 rows of leftover 2026-08-28 test data removed; `enrollment_type` (ACTUAL vs ESTIMATED) stored/diffed/displayed after finding 6,577 of 11,482 records report a target, not a headcount; deterministic drop reasons (`api/tracking.py`) that say "we can't tell" rather than guess; trial-content vs tracking change categories; readable booleans/timestamps | — |
| 7 | AI ranking/evidence layer | **Built, measured, removed** (2026-08-30/09-01). Ten files deleted; `/rank` no longer exists on the app; 75 free tests pass. Four of five scored signals were filters wearing a score's costume; the one genuine judgment scales with volume, and this product is deliberately low-volume. Real cost was ~$0.019/trial, 3x the figure in the old notes. Kept: the deterministic scorers (no importer yet — they are waiting to become filter predicates), their live-database vocabulary guard, `paid_preflight.py`, `.ranking_cache/`, and every dated entry in `decisions.md`. What the removal plan itself got wrong is recorded there (2026-09-01) | 10-14 |
| 7b | **What replaces it** — amendment history, the watch, the watch record (agreed 2026-09-01). See `docs/plan_after_ranking.md` | **In progress.** Unit 0 (removal) and **direction 1 (amendment history) done 2026-09-01/02** — `GET /studies/{nct_id}/amendments`, `api/amendments.py`, Understand leads with it, and `has_results` added after finding the parser never read it. **Direction 2 (the watch) done 2026-09-02** — `GET /watch`, `frontend/Home.py` rebuilt from `design/Main.dc.html`: the watch leads, the capability grid moved below it, and all three states (quiet / news / stopped) are real and tested. `last_checked_at` is an explicitly-labelled proxy until direction 3 exists. **Direction 3 (the watch record / `monitor_runs`) not started — next.** 248 tests (226 free, 22 needing the live database) | 6-8 |
| 7c | **One AI call, scoped by measurement** — interpret the prose half of an amendment, in the scheduled job, never in the request path | Not started, and deliberately smaller than first planned. Querying the data before writing the prompt cut it from "interpret every amendment" to 75 of 212: 99 change nothing we store, 38 are single-field lookups, and the category half turned out to be a static field mapping. Blocked on credits; the deterministic layer shipped first specifically so this becomes measurable against a baseline. See `docs/decisions.md`, 2026-09-02 | 3-5 |
| 8 | Knowledge graph (relationships between trials/sponsors/interventions, multi-hop queries) — Explore | Not started | 10-14 |
| 9 | Multi-agent synthesis (agent specialization/handoff, review queue w/ confidence scoring) — Investigate | Not started | 8-10 |
| 10 | Real deployment (Railway/Vercel, production env vars, staging-vs-production split, user-managed conditions) | Not started. **Note before starting:** the Neon branch names don't mean what they say — the planned `dev`→`production` cutover never happened, so `dev` is the real live database (~226MB, what the cron and frontend actually use), `production` is an empty 32MB leftover, and `sandbox` (added 2026-08-30) is the disposable copy for testing destructive changes. Decide the real naming/cutover here rather than assuming. See `docs/decisions.md`, 2026-08-29. **Also:** conditions are currently hardcoded in `config/tracked_conditions.json`, requiring code/config changes to add a new one. Step 10 should move them to a database table so users can manage them through the UI (form on Home.py or a Settings page, one POST endpoint, cron reads from DB not file — ~2–3 hrs). | 4-6 |
| 11 | Autonomous-ops hardening (guardrails, safety monitoring, escalation protocol, observability) | Not started | 4-6 |
| 12 | Notifications (Resend daily digest, tied to Monitor) | Not started | 2-3 |

**Total estimate: ~64-83 active hours** (midpoint ~73.5), plus the
unavoidable ~2-week review-queue running time noted above.

**Where things stand (2026-09-02):** steps 1-6 are done and running for
real — the 6-hour GitHub Actions cron fires reliably on its own, and three
of the five capabilities (Discover, Understand, Monitor) work end to end
against real ClinicalTrials.gov data. Explore and Investigate aren't built
yet. **Step 7b is done** — the watch leads Home.py now, amendment history
shows in Understand, and enrollment numbers are named instead of gestured at.
270 tests pass.

**Step 7 (the ranking layer) was built, measured, and removed** on 2026-09-01.
Four of its five scored signals were filters wearing a score's costume, and
the one real judgment scales with volume in a low-volume product (~17 changed
trials a week). No clinician ever read a real ranked result — the synthetic
harness scored 15/15 on ties resolved by fixture order, while published
systems report 0.32–0.45. The deterministic scorers survive as future filter
predicates; the removal commit stays in history as a documented dead end.

**Step 7b three directions** (deferred from step 8 for timeline, 2026-09-01):

1. **Amendment history** — DONE. `GET /studies/{nct_id}/amendments` groups
   changes into amendments, `api/amendments.py` describes what each did —
   dates, enrollment counts with numbers now shown, results posted.

2. **The watch** — DONE. `GET /watch` + rebuilt Home.py. Three states (quiet /
   news / stopped), all tested via AppTest. The quiet week stated as a
   finding with zeros shown, not omitted. The alarm replaces the page, not
   sits above it. `last_checked_at` is a labelled proxy until direction 3.

3. **Watch record** (`monitor_runs` table) — DEFERRED to step 10. Would replace
   the proxy and add run counts, but starts empty (reads as "never checked",
   the alarm). The proxy has to survive until it fills. Worth doing when
   deploying.

**Next: step 8, Explore** (knowledge graph / relationships).

**Also this session:** enrollment switches name both numbers now (not just
"replaced by a real count"). This required walking a trial's history
backwards — a count move establishes which count was true AT THAT AMENDMENT,
not today's value (CLAUDE.md §2). The record footer shows "212 trial
updates · 498 field changes" concretely. Conditions stay hardcoded in
`config/` for now — moving to the database so users can add them through
the UI is step 10 work (~2–3 hrs).
