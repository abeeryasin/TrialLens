# Roadmap — TrialLens

**All twelve steps are built, deployed and verified against real data.**
This file is the per-step build record. The dated reasoning behind every
decision is in [`decisions.md`](decisions.md); the rules that came out of the
painful ones are in [`gotchas.md`](gotchas.md).

Original estimate ~70-75 active hours, which held.

## The twelve steps

| # | Step | Done | What shipped |
|---|---|---|---|
| 1 | Schema + ingestion | 2026-08-26/27 | `scripts/ingest.py`, `studies`/`study_conditions`, 11,415 studies from two conditions chosen on real research-interest data |
| 2 | FastAPI layer | 2026-08-27 | The only door to the database. Read-only enforced by a `SELECT`-only Postgres role, verified by a rejected `UPDATE` |
| 3 | Scheduler / cron | 2026-08-28 | `monitor.yml`, 6-hourly. Cheap-filter/expensive-diff change detection, `study_changes`, and a no-`DELETE` guardrail |
| 4 | Discover live-fallback | 2026-08-28/29 | `GET /discover`. The under-reporting gap found the same day was fixed, not deferred: merged local+live with per-result source tags |
| 5 | Frontend (Streamlit) | 2026-08-29 | Discover + Understand, reading through `api_client.py` only |
| 6 | Monitor page | 2026-08-29/30 | `GET /changes`, pagination, five filters, inline diffs, and an honesty pass on labels, drop reasons and enrollment type |
| 7 | AI ranking/evidence layer | **Built, measured, removed** 2026-08-30/09-01 | Ten files deleted. Four of five scored signals were filters wearing a score's costume; real cost was ~$0.019/trial, 3x the figure in the old notes. What the removal plan itself got wrong is recorded in `decisions.md` |
| 7b | What replaced it | 2026-09-01/02 | Amendment history (`GET /studies/{id}/amendments`), the watch (`GET /watch`, Home rebuilt), and the watch record (`monitor_runs`) |
| 7c | One AI call, scoped by measurement | 2026-09-03/04 | `api/prose_interpreter.py`. Interprets the prose half of an amendment, in the scheduled job, never in the request path. Measured ~$0.00125/call; ceilings $0.25 + 50 calls per run, $1.00 per rolling 30 days |
| 8 | Knowledge graph — Explore | 2026-09-02/04 | Relational tables, not a graph database. 6,207 organizations, 51,272 sites, 7,717 investigators, 14,468 intervention terms, **191,864 edges**, all from stored `raw_json` with no CT.gov call. Then site enrichment, a deterministic canonical merge, `GET /explore/{nct_id}` and the page |
| 9 | Synthesis — Investigate | 2026-09-04/05 | `GET /investigate` + `/landscape` + `/summary`, the page, and the weekly agent (`synthesis.yml`) filing into `review_queue`. The review UI followed 2026-09-06 |
| 10 | Real deployment | 2026-09-05/07 | Render free tier, both services live, Neon `dev`→`production` rename finally landed, tracked conditions moved into a database table, dependencies pinned, UptimeRobot keep-warm pings |
| 11 | Autonomous-ops hardening | 2026-09-06 | `GET /ops/status`, the `error` third state on every run table, `api/safe_errors.py`, `scripts/check_ops_health.py` failing the workflow on a critical alert, and `6_System.py` |
| 12 | Notifications | 2026-09-07 | `api/digest.py`, `scripts/send_digest.py`, `digest_runs`, weekday `digest.yml`. First live send verified (Resend id `3ff01a1f`) |

## Work that came after the table

| | |
|---|---|
| Clinician review of real output | 2026-09-07 — all 12 substantive primary-outcome changes judged, 9 of 12 worth a researcher's attention. Found three blind spots, all fixed the same day |
| Observation windows compared | 2026-09-07 |
| Endpoint descriptions compared, three change categories | 2026-09-07 |
| Agent payload cut 89.7% (`/investigate/summary`) | 2026-09-07 |
| Per-endpoint frontend caching | 2026-09-07 |
| Removing a tracked condition | 2026-09-08 — needed `study_tracked_conditions` first; the old substring link missed 19% of in-scope trials |
| Drift-check cadence moved off every tick | 2026-09-08 — the unattended job was spending ~1.6 GB of the Neon transfer allowance |

## What is not built, and why

- **Per-user accounts.** Deliberately rejected, not deferred. Auth is
  undifferentiated work demonstrating none of the skills this project was
  chosen to practise, and a reviewer forced to sign up before seeing
  anything usually leaves. A watchlist with no login would give the
  interesting half.
- **The relevance column** (`plan_relevance_column.md`). Deferred, gated on
  a real complaint that has not arrived.
- **Literature Q&A per trial.** Logged since 2026-08-26, with the technical
  reason finally recorded 2026-09-08: the other project it would connect to
  has no HTTP door and local-disk storage, so this is a new project rather
  than an integration.
- **A synonym-aware scope-drop query.** The 19% attribution blind spot is
  fixed in one direction only — a synonym-tagged trial still cannot age out
  of scope. Measured and recorded, not yet changed, because switching that
  query would move live rows.
- **Prompt caching for the weekly agent.** Verified applicable and deferred:
  Haiku 4.5 has the highest minimum cacheable prefix of any current model
  (4,096 tokens) and this agent's static prefix is 1,918, so the obvious
  breakpoint would cache nothing, silently.

## The one thing no amount of building shortens

The weekly synthesis agent needs real weeks. Its first run filed zero
proposals — correctly, because monitoring had been live for eight days and
the agent's own prompt forbids calling one week a trend. A history
precondition now refuses to spend money on that foregone conclusion.
