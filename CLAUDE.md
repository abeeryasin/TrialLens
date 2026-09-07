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
- **Nor into user-visible output.** An error message is output: on 2026-09-05 a misconfigured `API_BASE_URL` put the live database password on a public page, because the message interpolated the raw env var and the raw `requests` exception. Name the host, never the whole address; scrub the raw value out of exception text too (`frontend/api_client.py`).
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
6-hour GitHub Actions cron, and the Streamlit frontend. **914 tests pass.**
Dated reasoning: `docs/decisions.md`. Per-step build status:
`docs/roadmap.md`. This section stays short on purpose — a status essay
copied into three files goes stale in three files.

**The weekly synthesis agent (step 9 follow-on) is built and live** — the
one genuinely multi-step judgment in the product ("is this week's movement a
pattern or a coincidence?"), reading `/investigate` as its tools and filing
labelled-confidence proposals into `review_queue` for human review. Never a
verdict, never a summed score (§3). Its own weekly `synthesis.yml` cron
live, and **the review UI it files into is built as of 2026-09-06** —
`POST /synthesis/proposals/{id}/review` plus `frontend/pages/7_Review.py`,
so the "a human decides" half of the design finally exists somewhere a
human can reach. First real run (2026-09-04, $0.1099) filed zero proposals — explained,
not assumed: real monitoring is only ~1 week old, so the agent had nothing
yet to call a trend, per its own system prompt. Design, build, and that
first-run read: `docs/decisions.md`, 2026-09-04/05.

**Step 10 (real deployment) is LIVE as of 2026-09-05.** TrialLens runs on
Render's free tier — API at `https://triallens-api.onrender.com`, frontend
at `https://triallens-frontend.onrender.com` — reading the same Neon
database the 6-hour cron writes to. Verified by a human loading the real
page, not just by curl. The long-flagged Neon rename is done (`dev` →
`production`), tracked conditions moved off a config file into a database
table with a UI to add one, and the dependency stack is pinned so deployed
equals tested. **Neon's `Default` flag moved onto `production` on
2026-09-06**, so a tool that picks the default branch (the Neon MCP,
`neonctl` with no branch argument) no longer lands on an empty database.
The branch these URLs actually reach is `br-fancy-bird-ay7zb0sb` — an
identifier, not a credential, and the thing to compare against if the flag
is ever in doubt. **Step 10 closed 2026-09-07** with the UptimeRobot
keep-warm pings; the API one had to be a *keyword* monitor because
UptimeRobot sends HEAD by default and FastAPI's `/health` answers 405 to
HEAD. **Step 12 (notifications) is the only unstarted step.**

**A clinician judged real output for the first time on 2026-09-07** — all
22 primary-outcome changes on file, 9 of 12 substantive ones worth a
researcher's attention. That is the validation `docs/verify_ranking_results.md`
asked for and step 7 never got. It found three blind spots, all now fixed
the same day: observation windows were ignored, endpoint **descriptions**
were ignored, and the reformatting bucket was unreachable from the page.
The comparison reads three fields of a primary outcome — name, time frame,
description — and an outcome change now lands in one of **three** named
categories, not two: `substantive` (something moved), `entry_completed` (a
definition was filled in where the entry was silent — a more complete
record, not a moved endpoint) and `reformatting`. Live: 19 / 2 / 1. Each
keeps its own milestone flags, so a definition appearing after results were
posted says so on its own card and the reviewer judges. Calling that
"reformatting only", as the first cut did, was a false statement about the
record. `docs/decisions.md`, 2026-09-07.

**The weekly agent's cost was measured, not argued (2026-09-07).** One
`GET /investigate` response is 39,972 characters, of which 99.3% is
per-trial reading lists built for a human to click and 277 characters are
the numbers the agent reasons with — and the Messages API is stateless, so
every window it reads is re-sent on every later turn.
**`GET /investigate/summary`** returns the counts plus bare NCT IDs at 4,099
characters (89.7% smaller, **84% off the loop's input cost**); detail comes
from `get_trial_amendments` for the one trial it names. A history
precondition (`MIN_PRIOR_WINDOWS`, read off the agent's own prompt) also
refuses to run when the record cannot supply two prior windows — which is
what the first live run's $0.1099 and zero proposals bought. Prompt caching
was verified applicable and deferred: **Haiku 4.5 has the highest minimum
cacheable prefix of any current model, 4,096 tokens**, and this agent's
static prefix is 1,918 — the obvious breakpoint would cache nothing,
silently.

**Step 11 (autonomous-ops hardening) is done, 2026-09-06.** The two
unattended jobs — the 6-hourly monitor cron and the weekly synthesis agent —
now have a health surface, an honest run record, and an escalation that
fires without a human looking. The gap was never "a job crashed" (that is
loud); it was **a job that finishes green while doing nothing**, which this
project has been in twice. `GET /ops/status` (deterministic per §5, a list
of named alerts each carrying its measurement, never a summed score per §3),
`monitor_runs.error` / `synthesis_runs.error` for the third state
("finished, but part of me broke"), `api/safe_errors.py` scrubbing
credentials out of an exception before it reaches a database column a page
prints, `scripts/check_ops_health.py` failing `monitor.yml` on a critical
alert so GitHub's own notification is the alarm, and
`frontend/pages/6_System.py`. Every alert rule is a real incident from this
project's own history. Design, and what live data corrected on the first
call: `docs/decisions.md`, 2026-09-06.

**A condition can be removed as of 2026-09-08, and building it found that
the record could not say which trials a condition brought in.** `DELETE
/tracked-conditions/{condition}` untracks (never deletes) the trials no other
watched condition brings in, logs the flip like any scope drop, and returns
what it did — untracked, kept for another condition, and unattributed. It
needed `study_tracked_conditions` first: the old substring link missed 19% of
in-scope trials. Two refusals on purpose — the last condition on the list, and
any removal before attribution exists. Removing a condition ends all ongoing
cost immediately (nothing is refetched, diffed or interpreted); it does not
reclaim the ~60 MB of disk, which is the deliberate trade for keeping the
amendment history the digest and Investigate are computed from.
`docs/decisions.md`, 2026-09-08.

**Step 12 (notifications) is built as of 2026-09-07** — the last step on the
table. `api/digest.py` composes, `scripts/send_digest.py` sends, `digest_runs`
records, and a weekday `digest.yml` cron fires it; `/ops/status` gets a third
job. **No domain was needed**: Resend's shared `onboarding@resend.dev` sender
needs no DNS, and its one restriction — it delivers only to the account
owner's own address — is exactly this product's shape. The mail leads with
substantive primary-outcome changes named individually (0-5 a day) over
counts for everything else (65-136 trials a day). **Weekends are dropped and
an empty window sends nothing**, which forced whole-weekday windows rather
than a rolling 24 hours — Monday reports Friday. 52 free tests cover
composition with no account and no mail sent. **The first live send is
verified** (Resend id `3ff01a1f`, `digest_runs` #1, 4 outcome changes named);
secrets are set and the weekday cron is live. Running it found two more
faults, both fixed the same day — see the stateful-cadence and
alarm-actionability gotchas below.

**Two live bugs in the weekly agent, found and fixed 2026-09-07** when its
scheduled run failed for real. `run_synthesis()` now returns
`(proposals, spend, error)` instead of raising, so a partial spend reaches
the run record; and a `stop_reason == "tool_use"` with no `tool_use` block
stops the loop with a recorded error instead of sending an empty user
message the API rejects.

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
- **Delete test rows by explicit list, never by pattern.** `_` is a
  wildcard in SQL `LIKE`, so `LIKE '__%'` means "2+ characters", not "starts
  with two underscores" — on 2026-09-05 that wiped the whole
  `tracked_conditions` registry while cleaning up one probe row (restored
  within seconds; the cron that reads it was ~70 min away). Same class as
  the over-broad test cleanup of 2026-08-27. Use `WHERE x IN (...)`.
- **`pkill -f <pattern>` matches your own command line too.** On
  2026-09-06 `pkill -f "port 8011"` killed the backgrounded shell running
  the test suite, because that shell's command string also contained the
  pattern — the run died at exit 144 with zero output and read as a test
  failure. Same class as the `LIKE '__%'` incident below: a pattern
  matching more than the one thing you pictured. Match on something only
  the target has, or kill by PID.
- **A comment describing an invariant is not the invariant.** On
  2026-09-07 the weekly agent's caller carried an accurate comment — "whatever
  was spent before the failure must still reach the run record", citing the
  2026-09-03 postmortem — above code that could not do it: `proposals, spend
  = f()` never binds when `f` raises, so a run that made five paid calls
  recorded `$0.0000`. The same accounting hole, written up once, restated in
  a comment, and reopened at the new site. **The tell was the number, not the
  exception.** Where a value must survive an exception, return it — don't
  assign it from a call that may not return.
- **Iterate on `pytest -k "not real_data"`; run the full suite once, before
  committing.** Measured 2026-09-07: the free 757 tests cost **0.5 MB and
  38s**, the 121 real-data tests cost **56 MB and 161s** — 86% of the
  coverage for 0.8% of the bytes. Neon's free tier allows 5 GB of public
  network transfer a month, and ten full-suite runs in one session is ~560 MB
  of it. The real-data half is not optional before a commit (it is the only
  thing that tests the SQL), it is just not the thing to run forty times
  while editing a docstring. **And check what runs it unattended**:
  `monitor.yml` was running the same full suite on all four daily ticks —
  29 runs, ~1.6 GB — which the 2026-09-07 postmortem missed because both
  suspects it considered were things a human types. Drift checks now run on
  the 00:0x and 12:0x ticks only (2026-09-08). `tests.yml`, on every push,
  deliberately holds no database credentials, so pushing costs nothing on
  that meter. **Running out is not a slowdown — Neon's free tier suspends the
  compute**, so the deployed site goes dark until the period resets (26th of
  the month here). Drift checks are therefore weekly until 2026-09-26 and
  twice daily after, decided by a date in the workflow rather than by a
  comment promising to restore it. Storage is the quieter meter: 0.5 GB
  allowed, 249 MB used.
- **A substring link between two vocabularies is not attribution.** Until
  2026-09-08 the only thing connecting a watched condition to its trials was
  `study_conditions.condition ILIKE '%breast cancer%'` — and **2,173 of
  11,453 in-scope trials (19%) match no tracked term at all**, because
  CT.gov expands synonyms when it searches (`Breast Neoplasms`,
  `Breast Carcinoma`, `Obese`, `Overweight`). A condition-removal built on
  that rule would have stranded them: `active_in_scope = true`, counted in
  the watch headline, with no query left that returns them.
  `study_tracked_conditions` records the real pair at ingest, written by
  `POST /studies/reconcile-scope`, which already had both halves. The same
  blind spot still means a synonym-tagged trial can never age out of scope —
  measured, recorded, not yet changed.
- **A cache on a monitoring tool has to be classified per endpoint.** The
  frontend cached nothing until 2026-09-07, so a Streamlit rerun re-issued a
  page's whole read set — 43,842 measured bytes for one Investigate
  interaction. The fix is an allowlist in `frontend/api_client.py`
  (`CACHEABLE_PATHS`), not `@st.cache_data` on `get`: `/ops/status` exists to
  say what is true *now*, and `/discover`'s live CT.gov fallback could hide a
  trial registered minutes ago. **Any write clears every cached read** — a
  tool that appears not to register a condition the user just added is worse
  than one that costs bandwidth. Unclassified paths are never cached, and a
  canary fails if a page reads a path in neither list, or a list carries an
  entry no page reads.
- **A stateful cadence needs a simulation, not a table of cases.** Every
  window assertion for the digest passed, each written against one call with
  a hand-picked previous value. Feeding each run's output into the next
  showed **every Tuesday pulling the weekend back in** — Monday's digest
  reports Friday, so it leaves `covered_until` at Saturday 00:00, which is
  always earlier than Tuesday's Monday 00:00, and the catch-up test read
  that deliberate gap as a missed run (2026-09-07). Compare against what a
  *healthy predecessor* would have left, not against this window's own start
  — and walk a whole week in a test.
- **An alarm nobody can act on trains people to ignore the ones they can.**
  The synthesis history-skip fired CRITICAL and would have failed
  `monitor.yml` every six hours for a fortnight over a condition that
  resolves itself with calendar time. Skip severity now splits on whether a
  human can *do* anything: `SELF_RESOLVING_SKIPS` are WARNING, `budget`
  stays CRITICAL, and an unclassified prefix stays CRITICAL too — an
  allowlist, so an unconsidered skip is never quieter than a considered one.
- **A rolling window cannot exclude a weekend.** "Everything since the last
  run" necessarily spans Saturday and Sunday on a Monday, and clipping its
  start to Monday 00:00 silently drops everything filed after Friday
  breakfast. If a cadence needs to skip days, the window has to be whole
  days, not elapsed time (step 12, 2026-09-07).
- **A number that can never bind is a lie in the code.** The summary
  route's first draft carried `SUMMARY_ID_CAP = 20` over lists already
  capped at 8 upstream — unreachable, and harmless only by luck. Same shape
  as the cap fault below, which was not harmless. If a limit cannot fire,
  delete it and document the one that does.
- **A cap in one place can silently undo a fix in another.** On
  2026-09-07 the reformatting bucket was made listable so a human could
  check the filter; measured against the live record hours later, the page
  listed 8 changes of which **zero** were reformatting, because one
  `NAMED_CAP` over a substantive-first sort pushed the whole bucket off the
  end. Every test passed — both suites asserted on the *classification*,
  never on what survived the cap, and the fixtures were too small to reach
  it. Cap per bucket, assert on what the reader actually receives, and say
  "showing the first N of M" wherever a list is shorter than the count
  printed above it.
- **When mutation-testing, diff the restored file against the backup
  before believing the result.** Mutating and restoring inside one shell
  command produced a run where correct, restored code appeared to fail —
  long enough to nearly "fix" working code (2026-09-06).
- This project's real text runs ~2.61 chars/token, not ~4.0 — re-measure
  any cost estimate rather than trusting an old one.
- **`requirements.txt` is pinned, and must stay pinned** (with
  `.python-version`, 3.9.6). It was bare names until 2026-09-05, which let
  Render's first deploy resolve Python 3.14 + streamlit 1.63 + pandas 3.0
  while the suite passed on 3.9 + 1.50 + 2.3 — a green suite certifying
  software nobody was running. Pin the whole closure, not the direct deps:
  pandas/numpy arrive through streamlit. Classify by resolver
  (`pip install --dry-run`), never by eye — streamlit requires GitPython,
  which "obviously dev tooling" got wrong.

**Doesn't travel with a clone**, all gitignored: `.env.local` (DB URLs —
real-data tests skip cleanly without it), `.ranking_cache/` (orphaned
since step 7's removal), `.claude/skills/`, `design/triallens-the-watch.html`
(rebuild from `design/*.dc.html`).
