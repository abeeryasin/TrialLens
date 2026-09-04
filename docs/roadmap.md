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
| 7b | **What replaces it** — amendment history, the watch, the watch record (agreed 2026-09-01). See `docs/plan_after_ranking.md` | **In progress.** Unit 0 (removal) and **direction 1 (amendment history) done 2026-09-01/02** — `GET /studies/{nct_id}/amendments`, `api/amendments.py`, Understand leads with it, and `has_results` added after finding the parser never read it. **Direction 2 (the watch) done 2026-09-02** — `GET /watch`, `frontend/Home.py` rebuilt from `design/Main.dc.html`: the watch leads, the capability grid moved below it, and all three states (quiet / news / stopped) are real and tested. **Direction 3 (the watch record / `monitor_runs`) done 2026-09-02** — every scheduled run opens and closes a row, `/watch` reads `last_checked_at` from the newest completed one, and the proxy plus its `last_checked_source` label are gone. The empty-table blocker was solved by seeding one row from the old proxy rather than deferring. **Step 7b complete.** 278 tests pass | 6-8 |
| 7c | **One AI call, scoped by measurement** — interpret the prose half of an amendment, in the scheduled job, never in the request path | **Live and genuinely storing, as of 2026-09-03/04.** It was **Done (2026-09-02)** on paper and stored **zero rows** for a day: the write used MySQL's `UPDATE ... ORDER BY ... LIMIT`, Postgres rejected it, and an `except` swallowed the error — the $0.168 was really spent and the interpretations were dropped. There was also no `ANTHROPIC_API_KEY` secret, so it could not run on the schedule at all. Key added 2026-09-03; first real batch found 14 prose changes and stored 8. Reading those 8 row by row then found two more faults: the no-change gate was an exact string match the model rephrased past, and `why_matters` was ~48% of output tokens carrying every weak line. Gate is now a structured `MEANINGFUL: yes|no`; `why_matters` dropped (§2 — a researcher judges significance, the model spots the change). Verified on the exact rows the old gate got wrong: **4 real calls, 4/4 agreement with a human reading**. Honest quality verdict on the first batch: **2 clearly valuable, 2 debatable, 4 reformatting**. Billing now reads `response.usage` instead of multiplying a constant, which exposed a third bug — "no change" calls were real money recorded as $0.00. Measured cost **~$0.00125/call**, not $0.004. Ceilings: $0.25 + 50 calls per run, **$1.00 per rolling 30 days**. **7 interpretations on file, and Understand renders all of them as of 2026-09-04** — `AmendedField.interpretation`, drawn by `labels.render_interpretation` with the model attribution inside the element and the diff still one click below. Note `primary_outcomes` is both a structured field and one of the three interpreted ones, and carries 5 of the 7. See `docs/decisions.md`, 2026-09-04 | 3-5 |
| 8 | Knowledge graph (relationships between trials/sponsors/interventions, multi-hop queries) — Explore | **In progress.** **Unit 1 (shape) done 2026-09-02** — relational tables, not a graph database: the graph already exists in `studies`, and at 11,518 trials with 2-3 hop questions, index-free adjacency buys nothing a second sync path doesn't cost back. **Unit 2 (extraction) done 2026-09-03** — 6,207 organizations (lead sponsors and collaborators in ONE table; 887 names are both), 51,272 sites, 7,717 investigators, 14,468 intervention terms, 191,864 edges, all from stored `raw_json` with no CT.gov call. Nothing merged on purpose: 381 Madrid facility strings are 381 sites. Reconciliation against source counts failed twice and was right both times — once on snapshot staleness, once on insert-only edges outliving the record, which produced the `delisted_at` decision (stamp, never delete). 12 real-data tests, all 7 mutations caught. **Unit 2b (node ranking + site enrichment) done 2026-09-03** — an evidence review (`docs/plan_explore_nodes.md`) asked whether researchers actually care about collaborations and found the field is defined as covering funders *and* co-designers with no way to separate them, reaching only 37.4% of trials with 63% of those at degree 1; it is kept but demoted from a network to an attribute. Sites lead instead at 93.8%, so the fields the parser had dropped were backfilled from `raw_json` with no network call: 49,606 of 51,272 sites now carry coordinates and 40,011 live edges carry a per-site recruitment status (31,442 RECRUITING). Disputed values are stored as NULL and counted — 109 sites are reported at geoPoints up to 52 degrees apart. 18 real-data tests, 14/14 mutations caught. **Units 3a (endpoint) and 3b (page) done 2026-09-04** — `GET /explore/{nct_id}` and `frontend/pages/4_Explore.py`, built ahead of the merge and the ordering reversed deliberately: the merge fixes "381 Madrid facility strings are 381 sites", but no page had ever shown a site list, so it would have been a layer measured against nothing (the step 7 mistake). The page groups by country and city, where those variants collapse anyway. The endpoint answers where a trial runs (country/city rollups, three-way site status, unplaceable count, dropped locations), who runs it (sponsor, collaborators as an attribute, investigators, intervention terms, each with a two-hop "also on N trials"), and who else works in the space — trials reachable in two hops through a shared site, investigator or term, in three lists never fused into one score. Every capped list carries its real denominator. A planned shared-condition count was built and discarded the same hour: it printed "0 in common" for two breast cancer trials, because nothing is merged there either (7,808 condition strings over 32,701 rows) — replaced by the neighbour's own tags as text. 46 new tests, 9/9 planted mutations caught, though 5 only by the real-data half. **Unit 3 (the merge) done 2026-09-04** — `canonical_id` on sites, intervention_terms and investigators; a pointer, never a delete, so the unmerged baseline is still exactly on file and NULLing the column undoes it. Deterministic casefold+punctuation rule only. Scope was cut by measuring first: 2,395 site groups (3,033 rows), 650 term groups (783), 99 investigator groups (111), and **0 for organizations, which therefore got no column**. Sites merge on the (facility, city, country) triple — a mutation dropping city/country was caught by the script's abort guard at 8,856 cross-place merges, nothing committed. Visible through the endpoint: RxPONDER's site-neighbours 1,497 → 1,624, Letrozole's reach 114 → 125, and NCT01740427's 299 sites resolved to the 292 real places they are. Runs in `monitor.yml` after the backfill. **Step 8 complete** | 10-14 |
| 9 | Multi-agent synthesis — Investigate | **Engine, endpoints and page done 2026-09-04.** `GET /investigate` (window findings) and `GET /investigate/landscape` (the corpus), `api/investigate.py`, `frontend/pages/5_Investigate.py`, Home's fifth card live. **All five capabilities now exist.** Deterministic, per sec. 5: every question has one correct answer, and external evidence said the same about the agent shape — a 3-agent pipeline costs ~2.9x a single agent's tokens and the findings payload is a few KB, so **one specialist agent, weekly, reading pre-computed findings**, ~$0.63/month inside the existing $1.00 ceiling. The headline finding, **primary-outcome changes**, was chosen from published literature rather than from what the columns allowed (31.7% prevalence, OR 1.82 with funding source, 16% effect-size inflation) — the validation step 7 never got. 17 outcome changes in the record, 5 after the trial's own primary completion date; normalisation de-escalates 9 as reformatting, including one on a trial with results posted past completion whose change was capitalisation. Flags are listed, never summed. **Then a human read the page and found nine things the tests did not** — including a categorical axis that thinned its labels and so reported 78 terminated trials where the figure is 237, and an enrolment chart whose linear axis made a 57% shortfall on a small trial invisible. Fixed, with the layout guarantee moved into `tests/test_charts.py` because a PNG export could not reproduce the fault. **The synthesis agent itself — built 2026-09-05.** `api/synthesis_agent.py` (hand-rolled Anthropic Messages API tool-use loop, claude-haiku-4-5, matching `api/prose_interpreter.py`'s existing style), `review_queue` + `synthesis_runs` tables (migrated onto the real `dev` database), `GET /synthesis/proposals`, `scripts/run_synthesis.py`, a separate weekly `synthesis.yml` cron (Monday 13:00 UTC, `ANTHROPIC_API_KEY`/`DATABASE_URL` secrets already on the repo from step 7c). See `docs/decisions.md`, 2026-09-05, for the nine build decisions. **First real run, same day: $0.1099, zero proposals** — not a silent-write bug like step 7c's first two: `/investigate` for `weeks_ago=2,3,4` returns 0/0/0/0 because real monitoring only started 2026-08-28, so the agent (correctly, per its own system prompt) had only one prior week to compare against and nothing yet to call a trend. One loose thread left open rather than guessed at: whether the agent considered and declined the one flagged lifecycle anomaly in that window as a standalone `single_trial_flag`, or never looked — resolves for free once more weekly history exists. See `docs/decisions.md`, 2026-09-05. **660 tests pass** | 8-10 |
| 10 | Real deployment (Render, production env vars, staging-vs-production split, user-managed conditions) | **In progress, started 2026-09-05.** Platform: **Render**, not the roadmap's original Railway/Vercel candidates — Vercel ruled out by research (serverless, doesn't fit Streamlit's stateful WebSocket server or FastAPI's persistent DB connections); Railway Hobby costs less than Render's paid always-on tier but this project has no income behind it, so **Render free tier + a free UptimeRobot 5-min ping** (keeps both services from sleeping at $0/mo) won out over paying for either platform's paid tier. See `docs/decisions.md`, 2026-09-05. **Neon rename done**: `dev` (the real live database) → `production`; old empty `production` → `production-old-unused`; `sandbox` untouched. Verified live — same `DATABASE_URL` still connects post-rename. **Tracked conditions moved off `config/tracked_conditions.json` into a real `tracked_conditions` table** — `GET`/`POST /tracked-conditions`, a "+ Add" popover on Home.py, `scripts/run_monitor.py` reading the table directly. Verified live over HTTP, not just by test. `render.yaml` written (two services, no secrets in the file). **Live as of 2026-09-05**, both services on Render's free tier: `triallens-api` (`https://triallens-api.onrender.com`) and `triallens-frontend` (`https://triallens-frontend.onrender.com`). Verified end to end — every read endpoint, a full write round-trip (201/409/200), and a human loading the real page: watch headline with 11,461 trials, condition chips, and the Investigate charts all rendering. **Dependencies pinned** (`requirements.txt` full 63-package closure + `.python-version` 3.9.6) after the first deploy silently resolved Python 3.14/streamlit 1.63/pandas 3.0 against a suite that runs on 3.9/1.50/2.3; the rebuild confirmed `cp39` wheels and exact version matches, so deployed now equals tested. **Two real incidents, both in `docs/decisions.md`:** a misconfigured `API_BASE_URL` put the live database password on a public page via an error message (fixed in `api_client.py`, credential now never echoed; password rotated), and a `LIKE '__%'` cleanup wiped the `tracked_conditions` registry because `_` is a SQL wildcard (restored within seconds). **Still open:** the UptimeRobot keep-warm monitor, and moving Neon's `Default` branch flag off `production-old-unused`. | 4-6 |
| 11 | Autonomous-ops hardening (guardrails, safety monitoring, escalation protocol, observability) | Not started | 4-6 |
| 12 | Notifications (Resend daily digest, tied to Monitor) | Not started | 2-3 |

**Total estimate: ~64-83 active hours** (midpoint ~73.5), plus the
unavoidable ~2-week review-queue running time noted above.

**Where things stand (2026-09-02):** steps 1-6 are done and running for
real — the 6-hour GitHub Actions cron fires reliably on its own, and three
of the five capabilities (Discover, Understand, Monitor) work end to end
against real ClinicalTrials.gov data. Explore and Investigate aren't built
yet. **Steps 7b and 7c are done** — the watch leads Home.py now, amendment
history shows in Understand, enrollment numbers are named instead of gestured
at, and one AI call interprets the prose half of an amendment in the
scheduled job. 283 tests pass.

**Step 7 (the ranking layer) was built, measured, and removed** on 2026-09-01.
Four of its five scored signals were filters wearing a score's costume, and
the one real judgment scales with volume. (**The "~17 changed trials a week"
figure once cited here was wrong by ~20x** — measured 2026-09-04, the real
rate is ~370 trials amended per week. The removal decision stands on the
four-of-five-signals argument, which is unaffected; the volume leg is not
true and should not be re-cited. See `docs/decisions.md`, 2026-09-04.) No clinician ever read a real ranked result — the synthetic
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

3. **Watch record** (`monitor_runs` table) — DONE 2026-09-02, and not deferred
   to step 10 after all. The blocker was that an empty run table reads as
   "never checked" and fires the alarm on a healthy watch. Resolved by
   noticing the proxy it replaces IS evidence a run completed:
   `scripts/backfill_monitor_runs.py` seeds one row from
   `max(studies.last_matched_at)`, the cron takes over, and
   `last_checked_source` is deleted because the value is a record now rather
   than a proxy needing a label. Verified live — `/watch` healthy off run #1.

**Where to pick up (after 2026-09-04).** The graph is visible now — Explore
is live and the capability grid's fifth card opens a real page. Step 7c's seven prose
interpretations are visible too, rendered in Understand with the model
attribution inside the element and the diff still one click below.

Unit 3, the merge, is done: the empirical
question was answered by measuring rather than by architecture (2,395 site
groups, 3,033 rows collapsed, and 54 trial-site pairs that really did show
one hospital twice), and organizations turned out to have zero duplicates
so they got no column at all.

What remains: **step 9, Investigate** — the last unbuilt capability.

416 tests pass.

**Step 8, Explore, is built through the page** — units 1 (shape), 2
(extraction), 2b (node ranking + site enrichment) and 3a/3b (endpoint +
page) are done; see the step 8 row above and `docs/decisions.md`,
2026-09-03 and 2026-09-04. Unit 3 (the merge) is the remaining piece.

**Explore should lead with sites, then investigators — not collaborators.**
Decided 2026-09-03 from external evidence rather than taste, and written up
in `docs/plan_explore_nodes.md` with what would overturn it. The short
version: CT.gov defines "collaborator" as any organization providing support
*including funding*, so NCI (480 trials) and NIDDK (264) dominate the field
and an edge cannot distinguish a co-designer from a cheque; it also
explicitly excludes individuals, so it cannot answer "who else works here"
when *who* means a person. Sites reach 93.8% of trials and answer the
question clinicians currently phone sites about. This is the validation step
7 never got — and it is still second-hand: no clinician has looked at
TrialLens, and `docs/verify_ranking_results.md` remains unanswered.

**Two live-only bugs were fixed on 2026-09-03**, both found by dispatching
the monitor workflow rather than waiting for a tick. The scheduled job had
been passing `API_BASE_URL` but not `DATABASE_URL`, so `monitor_runs` had
never been written by a real run; and step 7c's storage used MySQL's
`UPDATE ... ORDER BY ... LIMIT`, which Postgres rejects, so
`prose_interpretation` held zero rows despite the $0.168 spent. **Step 7c
still cannot run on the schedule** — there is no `ANTHROPIC_API_KEY` secret
on the repo, only the two database URLs.

**Also this session:** enrollment switches name both numbers now (not just
"replaced by a real count"). This required walking a trial's history
backwards — a count move establishes which count was true AT THAT AMENDMENT,
not today's value (CLAUDE.md §2). The record footer shows "212 trial
updates · 498 field changes" concretely. Conditions stay hardcoded in
`config/` for now — moving to the database so users can add them through
the UI is step 10 work (~2–3 hrs).
