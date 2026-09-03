# Decisions & Learning Log — TrialLens

Dated entries capturing real decisions and why — a decision happens,
then it gets written down before moving on, so it isn't lost when
context resets.

## 2026-08-25 — Domain considered and shelved: maternal-health / Three Delays

Explored a Maternal Death Surveillance & Response project built on the
WHO "Three Delays" framework, using the WHO GHO API (verified live,
works) plus PDHS/MICS microdata (real but gated behind manual
registration, not autonomously fetchable, non-redistributable) plus
literature grounding for the framework (corrected from an initial,
wrong assumption that de-identified Pakistani case narratives are
publicly available — they aren't; verified via search, found none).
Reframed to literature-grounded proxies rather than case-level data.
Ultimately shelved — a second candidate (TrialLens) matched a genuinely
different set of unpracticed skills more directly. Logged as a
legitimate future project, not discarded.

## 2026-08-25 — Domain chosen: TrialLens

Chose a clinical-trial intelligence project after auditing what was
already genuinely demonstrated versus what remained unpracticed:
knowledge graphs, autonomous scheduled operations, multi-agent
handoff/parallel execution, and real MCP plus database read-only
enforcement. Verified against ClinicalTrials.gov's real, public,
no-auth v2 API (live-tested 2026-08-25, ~50 req/min, public domain
data) before committing to it.

## 2026-08-25 — Persona: clinical researcher, not a one-time patient search

A patient searching once wouldn't justify the scheduled-monitoring,
change-detection, or review-queue features at all — just a search box.
A researcher tracking a therapeutic area over time is what makes the
multi-agent, autonomous shape of the project actually necessary rather
than decorative.

## 2026-08-25 — Notification mechanism: Resend, not SendGrid

Checked both rather than assuming either was still free. SendGrid
dropped its permanent free tier in 2023 (now a 60-day trial only — no
good for something meant to run indefinitely). Resend has a real
permanent free tier (100 emails/day, 3,000/month, no expiration) — far
more than one daily digest email needs. Chosen for that reason.

## 2026-08-26 — External product spec: adopted in part, corrected in part

A detailed product spec from another AI model proposed the
five-capability framing (Discover/Understand/Monitor/Explore/
Investigate), "deterministic first, AI second, agents third," using
"potential fit" instead of "patient eligibility" language, and building
evaluation cases from day one — all adopted, genuinely stronger than
what existed before.

Pushed back on three things: (1) its architecture diagram proposed a
FastAPI layer built speculatively, "for later," with no real consumer
lined up — resolved by making FastAPI a real, load-bearing boundary
from day one instead: the frontend and the scheduled fetcher both
genuinely go through it, and it's also where read-only enforcement for
query-side agents lives, since there's an explicit intent to learn
FastAPI regardless of whether the architecture strictly requires it
yet. (2) Its proposed "vector store" risked building unrelated
document-retrieval infrastructure this project doesn't need — clarified
this is a legitimate, different use case (semantic search over a local
trial cache, not long-document grounding) but sequenced for once real
cached data exists, not the walking skeleton. (3) Its claim that
"ClinicalTrials.gov itself maintains record versions" was checked
(true — a separate archive site, plus a per-trial RSS feed worth
investigating later) rather than accepted at face value, since it was
being used to justify the whole monitoring feature's legitimacy.

Also worth naming as its own lesson: the document's own later section
warned against building everything at once, immediately after many
earlier sections describing almost exactly that. Read a big
AI-generated proposal's own later caveats against its earlier scope
before adopting either.

## 2026-08-26 — Database: Neon Postgres, chosen and verified (retroactively logged)

Chosen earlier but never actually logged here — caught during a
documentation audit and fixed. Verified live via search rather than assumed: Neon
has a real permanent free tier (0.5 GB storage, 100 compute-hours/month,
no credit card, commercial use allowed), it's real Postgres (not a
NoSQL substitute, so standard SQL/relational vocabulary applies
directly), and it supports instant branching — a free, disposable copy
of the database. Used that branching feature immediately: schema work
happens on a `dev` branch, `production` stays untouched until the
schema is trusted, which is a genuine staging-vs-production split, not
a theoretical one.

## 2026-08-26 — Discover vs. Monitor: an untracked topic falls through to a live lookup

Found a real gap while walking through the query flow: if a researcher
asks about a therapeutic area that was never fetched into the local
database, a plain read of our own database comes back empty — which
looks identical to "no trials exist," and that's actively wrong, not
just incomplete.

Fixed by splitting behavior into two distinct paths. An ad-hoc question
about a topic with nothing relevant stored locally falls through to a
one-time, live call to ClinicalTrials.gov, answered fresh, not from
cache. Separately, actually deciding to track a therapeutic area going
forward is its own explicit action, registering that topic with the
scheduled fetch job so it keeps refreshing and change-detection can
work on it over time. Without this split, a live search and a
persistently-monitored topic would silently collapse into the same
broken thing.

## 2026-08-26 — Ingestion scope: filter by trial status, not just condition name

Checked real counts before assuming feasibility, rather than guessing
either "trivial" or "impossible." A broad condition search like
"diabetes" alone matches 24,289 studies across the entire history of
the registry — roughly 410 MB of raw data at the registry's average
study size, for one topic. Three topics that broad would exceed the
entire 0.5 GB Neon free-tier storage on their own.

Filtering to currently active trial statuses (recruiting and similar)
cuts this by roughly 10x — the same diabetes search drops to 1,958
studies once filtered. Tracking around 10-12 therapeutic areas at a
time, filtered to active trials, fits comfortably within the free tier;
tracking full historical registries per topic does not. Ingestion
filters by status from the start, not just by condition name.

## 2026-08-26 — Ingestion pipeline built and verified with real data

First working ingestion script (`scripts/ingest.py`): fetches active +
recently-closed trials for a condition (see the two decisions above)
and upserts them into `studies`/`study_conditions` on Neon's `dev`
branch. Ran it for real against two topics chosen from verified current
research interest (oncology and obesity, per IQVIA's 2026 therapeutic
area data): breast cancer (6,545 studies) and obesity (4,912 studies),
totaling 11,415 unique studies and 32,417 condition tags.

Caught and fixed a real bug before trusting the first version: it
wrapped the entire run in one giant transaction with nothing committed
until the end, making progress both invisible from outside and
all-or-nothing on failure. Found by querying Postgres's own
`pg_stat_activity` directly rather than assuming a long runtime meant
either "fine" or "broken." Fixed to commit per 200-row batch, with
unbuffered progress output.

Verified the shared-trial (same study, two tracked conditions) case
isn't hypothetical: `NCT03284346` genuinely matched both the breast
cancer and obesity searches and upserted correctly rather than erroring
or duplicating.

## 2026-08-26 — Future literature integration: logged, not built

Pulling supporting literature for a given trial via a separate
document-Q&A capability is a genuine, non-forced idea — trials and
literature about the same interventions are actually connected in the
real world. Deferred anyway: this project's own core capabilities don't
need it to work, and a cross-tool integration now would add real
complexity before this project stands on its own. Logged as a future
idea, not built now, not forgotten.

## 2026-08-27 — FastAPI built as the real only door to the database

`api/` now exists: `GET /health`, `GET /studies` (filter by condition/
status, paginated), `GET /studies/{nct_id}`, `POST /studies/batch`
(upsert). `ingest.py` was refactored to call `POST /studies/batch`
over HTTP instead of writing to Postgres directly with `psycopg2` —
this was the part that made "only door" real today instead of a design
intention for later; the script no longer holds a database credential
at all, only `API_BASE_URL`.

Read-only access is enforced at the database layer, not just the
application layer: a `trial_lens_reader` Postgres role
(`scripts/create_readonly_role.py`) has `SELECT`-only grants, and every
`GET` route connects as that role. Verified for real, not assumed: a
direct `UPDATE` attempt through that role's connection was rejected by
Postgres itself (`permission denied for table studies`), while a
`SELECT` through the same connection returned all rows normally. An
app-layer check alone wouldn't survive a bug in the app code; a missing
database grant can't be bypassed that way.

## 2026-08-28 — Monitor: real cheap-filter/expensive-diff, a changelog table, and a no-delete guardrail

Turned `ingest.py` into a real, two-phase sync instead of a full re-fetch every
run. Verified live before building: ClinicalTrials.gov's v2 API supports
`fields=` to return just `NCTId`/`LastUpdatePostDate` for a whole search (a
few bytes per trial instead of a full record) and `filter.ids=` to re-fetch
full records for a specific ID list. So each run now does: (1) a lightweight
fetch of every trial currently matching a tracked condition, just ID +
last-updated date; (2) ask the API which of those we already have and at
what date; (3) only pull full records for the ones that are new or whose
date moved; (4) diff those full records field-by-field against what's
stored and write any real difference to a new `study_changes` table (old
value, new value, field, timestamp) before overwriting — the old
`UPSERT ... ON CONFLICT` alone would have silently discarded the previous
value with no record anything changed, which defeats the entire point of a
Monitor capability.

Also decided, after checking both general practice and ClinicalTrials.gov's
own behavior: the scheduler never issues a `DELETE`, full stop. Two
reasons: (1) this project already has a real incident where a script
matched-and-removed rows it shouldn't have (2026-08-27, below); (2)
ClinicalTrials.gov itself never deletes a record either — a trial's status
changes and its full history stays visible, it doesn't disappear. Mirrored
that model: a trial that stops matching a tracked condition's
active/recency filter gets flagged (`active_in_scope = false`,
`last_matched_at` timestamp) via a new `POST /studies/reconcile-scope`
endpoint, never removed. That endpoint refuses to run at all against an
empty ID set — a real edge case caught while testing: an upstream fetch
failure returning zero results would otherwise flag every currently-tracked
study for that condition as dropped in one shot, which is exactly the kind
of silent mass-change an unattended job must not be able to do.

Scheduling itself is a GitHub Actions workflow
(`.github/workflows/monitor.yml`) on a 6-hour cron, plus a manual trigger
for testing. It starts FastAPI fresh inside the job itself rather than
calling a permanently-deployed instance, since real deployment is a
separate, later step — this keeps "FastAPI is the only door to the
database" true without requiring that step to happen first. Verified live
(GitHub's own docs) that a scheduled workflow's failure automatically
emails whoever owns/last-edited it — used as the failure-escalation path
instead of building a custom notifier now, since a change-digest email is
already separately planned later and would duplicate the concern. Network
calls (both to ClinicalTrials.gov and to our own API) get one automatic
retry before being allowed to fail the run.

Tested for real, not just written: ran the new ingest twice back-to-back
against a small condition — the second run's cheap filter correctly found 0
of 56 studies changed and made zero full-record fetches. Then deliberately
corrupted one real row's stored date and enrollment count to simulate
drift, re-ran ingest, and confirmed the diff caught exactly those two
fields and wrote them to `study_changes` with correct old/new values.
Separately tested the drop path by calling `reconcile-scope` with one real
study excluded from the current set — confirmed its row was flagged
`active_in_scope = false` (not deleted) and the transition itself was
recorded as a change. Found and fixed a real bug in the same pass: the
drop-detection query's `ILIKE` was matching the condition string exactly
instead of as a substring (inconsistent with how `GET /studies` already
matches conditions), so it silently matched nothing until wrapped in
`%...%` like the existing route does.

## 2026-08-27 — Found and fixed: client-side connection pooling against Neon's pooled endpoint

First version of `api/database.py` kept a long-lived `psycopg2`
connection pool open for the lifetime of the FastAPI process. That
broke during real testing: a write succeeded right after startup, then
a second write ~20 seconds later (after `ingest.py` spent time fetching
from ClinicalTrials.gov) failed with `OperationalError: server closed
the connection unexpectedly`. `DATABASE_URL` points at Neon's
`-pooler` endpoint, which is already a PgBouncer pool on Neon's side —
it silently drops idle connections held by a client rather than keeping
them alive indefinitely, and `psycopg2` only discovers this on the next
query, not when it happens. Fixed by connecting fresh per request
instead of pooling client-side; Neon's own pooler is the pool.

## 2026-08-27 — Caught and corrected: an overly broad test cleanup deleted 3 real studies

While verifying the new write path, ingested a small unrelated test
condition (`achalasia`) through the real running API, then deleted it
afterward by matching on the condition tag. ClinicalTrials.gov's
condition search does synonym expansion, and 3 of the 56 studies that
search returned turned out to already be part of the real tracked
breast-cancer/obesity dataset (matched by both searches). Deleting by
`nct_id` after filtering on the test condition tag removed those
studies' full `studies` row, not just the test tag — real data loss,
caught immediately by comparing the row count before and after against
the known baseline (11,415), rather than assuming a "cleanup" script
did only what it was meant to. Fixed by re-running real ingestion for
both actual tracked conditions (`breast cancer`, `obesity`), which
restored anything wrongly deleted and is safe to re-run regardless
since every write is an upsert. Lesson: a test/cleanup pass against a
real dataset needs to record exactly what it added (by ID) up front,
not reconstruct it after the fact from a tag that can also match
pre-existing rows.

## 2026-08-28 — Discover live-fallback built: `GET /discover`

Implemented the split decided 2026-08-26 ("Discover vs. Monitor"). New
route checks our own DB first, using the exact same condition-match SQL
`GET /studies` already uses; if that comes back with any rows, those are
returned (`source: "tracked"`) and nothing external is called. Only when
the local match is genuinely empty does it fall through to one live,
unpersisted ClinicalTrials.gov call (`source: "live"`), capped at
`limit` results (default 25, max 100), active-status trials only, using
`fields=` to request just the five fields the response needs instead of
full records. A live result is never written to the DB — tracking a
topic going forward stays its own explicit action
(`config/tracked_conditions.json` + the Monitor job), not a side effect
of asking a question.

Verified for real, not just by reading the code: `condition=breast
cancer` (tracked) returned 3 real stored rows, `source: "tracked"`, no
outbound request. `condition=psoriasis` also returned `source:
"tracked"` — a genuine, correct edge case, not a bug: several already-
ingested breast-cancer/obesity trials list psoriasis as a comorbid
condition in their own `conditions` array, so a plain DB read for
"psoriasis" isn't actually empty. `condition=tuberculosis` (nothing
related stored) correctly fell through to `source: "live"` and returned
3 real, current trials fetched from ClinicalTrials.gov on the spot.

Refactored `extract_fields`/`fetch_pages`/`request_with_retry` out of
`scripts/ingest.py` into a new shared `ctgov_client.py` at repo root —
both `ingest.py` and the new `api/discover.py` need the identical
CT.gov parsing logic, and duplicating it would let the two drift if
CT.gov's response shape ever changes. Lives outside both `scripts/` and
`api/` on purpose: it never touches the database, so it isn't part of
either side of the "FastAPI is the only door to the DB" boundary.

## 2026-08-28 — Found and deferred: `/discover` can silently under-report an untracked condition

Found while walking through the route's real behavior: the local-vs-live
check is a plain "did the DB return anything," but a condition that was
never deliberately tracked can still have a handful of local rows —
e.g. a few breast-cancer trials that happen to list melanoma as a
comorbid condition in their own records (the same mechanism as the
psoriasis case earlier in this same section). Today's code treats that
as "found it locally" and stops, returning those few incidental rows as
if they were the complete current picture for that condition, with
nothing telling the caller it might not be. That's a real instance of
the exact ambiguity this whole feature exists to solve, one level
deeper: "found something" isn't the same as "found everything," and the
response doesn't currently say which one it is.

Decided fix, deferred rather than built now: when the asked-for
condition isn't itself in `config/tracked_conditions.json` (the real
registry of what's deliberately, comprehensively tracked), query both
local and live, merge the results de-duplicated by `nct_id`, and tag
each individual result with where it came from — `DiscoverResponse.source`
as a single response-level field won't be enough once a response can mix
both, so that field moves onto each `DiscoverResult` instead. Not built
yet — revisit alongside whichever step actually surfaces this gap in
practice (e.g. the frontend, step 5, or before Understand/ranking work
starts treating `/discover` results as trustworthy inputs).

## 2026-08-29 — `/discover` gap fixed: per-result source, merged local+live

Built the fix decided above, at the start of step 5 rather than deferred
further, since the frontend was about to display these results directly.
`GET /discover` now branches three ways instead of two: (1) nothing
stored locally at all -> live lookup only, unchanged from before; (2)
local rows exist *and* the condition is an exact match in
`config/tracked_conditions.json` -> local data only, no live call, since
Monitor already keeps it comprehensive; (3) local rows exist but the
condition is only an incidental substring match (comorbid tag on a trial
tracked under a different condition) -> both local and live are queried,
merged de-duplicated by `nct_id` (a local hit wins over a live duplicate),
and each result carries its own `source`. `DiscoverResponse.source` was
removed from the schema entirely — nothing else in the codebase read it,
confirmed by grep before removing.

Verified live against real data, all three branches: `condition=breast
cancer` (exact tracked match) returned 3 rows, all `source: "tracked"`,
no outbound call. `condition=psoriasis` (incidental match — several
tracked breast-cancer/obesity trials list it as a comorbid condition)
returned a real mix, 2 `"live"` + 3 `"tracked"` results in one response,
each correctly tagged. `condition=tuberculosis` (nothing local) returned
3 real live results, unchanged behavior from before. Also added an
explicit degraded path: if the live call fails specifically in the
merge branch, the route now returns the local rows it already has with a
note that a live check was attempted and failed, instead of a hard 502 —
those incidental local rows are still real, useful data even when we
can't currently confirm whether they're the whole picture.

## 2026-08-29 — Streamlit frontend built: Discover + Understand

`frontend/` now exists: `Home.py` (entry point + a live check that the
API is reachable), `pages/1_Discover.py`, `pages/2_Understand.py`, and a
shared `api_client.py` — every page reads through it via HTTP, never
Postgres directly, extending "FastAPI is the only door" (CLAUDE.md sec.
5) to a second real consumer the same way `ingest.py` already does.

Discover: a search form (`st.form`, so typing doesn't trigger a rerun on
every keystroke — only "Search" does) hits `GET /discover` and stashes
the response in `st.session_state`, since a later rerun — clicking
"View" on a result row — would otherwise throw the results away like any
Streamlit rerun does. Each row shows its own tracked/live source and the
response's evidence note. "View" sets `selected_nct_id` and calls
`st.switch_page` to Understand.

Understand: takes an NCT ID either via that session-state handoff or a
direct paste, calls `GET /studies/{nct_id}`. Eligibility fields are shown
as explicit source text with a standing caption that TrialLens never
determines whether a real person qualifies (CLAUDE.md sec. 2) — this is
the first UI surface where that rule has an actual, concrete
implementation instead of just being a written rule. Also shows
`fetched_at`/`last_matched_at` (data freshness) and the real Monitor
change log from `GET /studies/{nct_id}/changes`. An NCT ID not in the DB
(e.g. a live-only Discover result) surfaces FastAPI's real 404 as an
explicit "not tracked" message with a link to view it directly on
ClinicalTrials.gov, rather than a blank page or an invented answer —
added `status_code` to the frontend's `ApiError` specifically so pages
can tell "not found" apart from "the API is actually broken."

Fixed the step-4 `/discover` gap (see above, 2026-08-28/29) at the start
of this step rather than deferring it again, since the frontend was
about to display these results directly to a researcher.

Verified in a real headless browser (Playwright, via `npx playwright` —
`chromium-cli` wasn't available in this environment), not just by
reading the code: Home shows a live "Connected to the API" check;
Discover renders a pure-tracked search (breast cancer), a real mixed
tracked+live search in one response (psoriasis), and validates an empty
search; the "View" click-through actually navigates to `/Understand`
(confirmed by URL and page content, not just the click firing);
Understand renders a real trial's full detail both via click-through and
a direct-pasted NCT ID, and a real live-only NCT ID correctly hits the
404 path; and with FastAPI killed entirely, Home shows the "could not
reach the API" message instead of a silent failure.

## 2026-08-29 — Understand extended to live-only trials; UI copy de-jargoned

Real usage immediately surfaced a gap: clicking "View" on a live (untracked)
Discover result led Understand straight to a 404, since it only ever
checked our own DB. Fixed by giving Understand the same tracked-or-live
split Discover already has for search: new `GET /discover/{nct_id}`
checks our DB first, and if not found, fetches the single trial directly
from ClinicalTrials.gov's real single-study endpoint
(`GET /api/v2/studies/{nctId}`, verified live — returns the same
`protocolSection` shape `extract_fields()` already parses, so no new
parsing logic needed). A live result has no `fetched_at`/`last_matched_at`
or change history, since those describe a trial we actually store; the
UI says so explicitly instead of just omitting them silently. New
`TrialDetail` schema carries a `source` field the same way `DiscoverResult`
already does.

Found and fixed a real bug while verifying this: CT.gov returns 404 for a
well-formed-but-nonexistent NCT ID, but 400 for a malformed one (checked
live, both against a real trial ID with digits changed vs. a garbage
string) — the new live-fetch code only treated 404 as "not found" at
first, so a genuinely bad ID pasted into Understand surfaced as a
confusing 502 instead of a clean "not found." Fixed to treat both as
"not found," since neither is a trial to show and a researcher pasting
an ID doesn't need to know CT.gov's status-code distinction between them.

Also fixed, same pass: `request_with_retry` (shared by ingest.py and both
CT.gov client paths) was retrying every failure including 4xx errors,
which can never succeed on retry — a bad NCT ID was hitting a pointless
5-second sleep before correctly reporting "not found." Now only retries
on a network error or 5xx; a 4xx raises immediately.

Separately, cleaned up several places where internal/developer language
had leaked into user-facing copy, caught by actually using the UI: the
Discover caption named "Monitor" (our internal capability name, meaningless
to a researcher); the `/discover` response notes referenced literal
`source` field values (`source: "tracked"`) and a config file path
(`config/tracked_conditions.json`) as if the reader were a developer;
and Home showed a permanent green "Connected to the API" banner on every
successful load, which is confirmation noise — every other page here only
speaks up when something's actually wrong, not when things are fine.
Home's banner was removed (the failure path still fires on a real outage)
and all four `/discover` note strings were rewritten in plain language
describing what's actually happening, with no internal names, field
values, or file paths. Home's one-line caption was also expanded slightly
to actually say what the product does (search + full detail + real
change tracking) instead of one generic sentence.

Verified live again after these changes: `GET /discover/NCT06744179`
(the exact trial that surfaced the original gap) now returns full detail
instead of 404; a genuinely bad ID now returns a clean 404 instead of
502; the Home page loads with no banner on success and the new caption;
Discover's caption and the mixed-source note read in plain language,
confirmed in a real browser screenshot, not just by reading the code.

## 2026-08-29 — Discover's results table rebuilt on st.dataframe, not hand-rolled columns

Real usage found Discover's table wrapping short values (a status like
`ACTIVE_NOT_RECRUITING`, an NCT ID, `PHASE1`) onto two lines even after
switching the page to Streamlit's wide layout. Root cause, confirmed by
inspecting the actual rendered container: `layout="wide"` genuinely
widened the page (1024px content area, verified via the block
container's computed width), but the table itself was seven manually
`st.columns()`-ratio'd cells — fixed relative widths that don't reflow
to content, so a short value in a narrow ratio slot still force-wraps
mid-word once its column runs out of room, regardless of how much space
is free elsewhere on the page.

Replaced the hand-rolled columns with a real `st.dataframe` (backed by
`pandas`, already a Streamlit dependency, no new one added), using
`on_select="rerun"` / `selection_mode="single-row"` for the "pick a
trial" interaction instead of a `st.button` in a seventh column per row.
This is Streamlit's own documented pattern for a selectable table — the
grid auto-sizes each column to its actual content instead of a fixed
ratio, so short values render on one line without needing to guess pixel
budgets per column, and the row-count no longer means one widget key per
row (`view_{nct_id}` × up to 100) the way the old per-row button did.

Verified for real, including finding a real testing gotcha along the
way: Streamlit's dataframe renders to an HTML canvas
(`glide-data-grid`), so a plain click-simulation at reasonable-looking
pixel coordinates didn't register a selection — confirmed via DOM
inspection that a `dvn-scroller` overlay div sits over the canvas and
intercepts pointer events, and the component listens for real
`pointerdown`/`pointerup` events, not a synthesized `click`. Dispatching
actual `PointerEvent`s at the checkbox's real screen coordinates (read
from `getBoundingClientRect()`) selected the row correctly, and the
full flow — select a row, "View NCT06120283 →" button appears with the
right ID, click navigates to `/Understand` — worked end to end in a real
headless browser. Also set `layout="wide"` on Home for visual
consistency with Discover; left Understand at the default centered
width on purpose, since it's mostly prose (eligibility text, and soon a
brief summary) where a comfortable reading width matters more than
table density.

## 2026-08-29 — Narrative/design fields added: what a trial is, not just who's eligible

Real usage surfaced a real gap: Understand showed status, phase, and
eligibility text, but never *why the trial exists* — no summary, no
intervention, no outcome measure. Checked against real research rather
than guessing what to add: two studies on what clinicians/researchers
actually look for both independently rank condition, brief summary,
intervention name, outcome measures, trial dates, and location among the
handful of fields that matter most (search links kept in conversation,
not duplicated here per this file's own no-course-framework rule — the
finding is: brief summary + intervention were the two most-helpful
results-list fields after title/condition, and location/dates ranked
second and third among search factors after condition itself). This is
also directly why the change log looked useless in practice: it could
only ever report a change to a field we actually parsed, and
`last_update_post_date` alone doesn't explain what changed.

Added 7 fields to `studies` (`brief_summary`, `lead_sponsor`,
`start_date`, `primary_completion_date`, `completion_date`,
`interventions`, `primary_outcomes`, `locations`) via `db/schema.sql`'s
existing idempotent `ADD COLUMN IF NOT EXISTS` pattern, extended
`extract_fields()` to parse them, and added them to `DIFF_FIELDS` so a
real change to an outcome measure or intervention now shows up as an
actual change-log entry, not silence.

Two real things caught and fixed before this shipped, not after:

1. **Date precision.** Verified live against a real sample of 50 studies
   before trusting a `DATE` column: ~23% of `startDateStruct` /
   `primaryCompletionDateStruct` / `completionDateStruct` values are
   month-only ("2027-06", no day) — unlike `last_update_post_date`, which
   is always full-precision. A `DATE` column would have rejected those
   rows or forced fabricating a day CT.gov never reported, which CLAUDE.md
   sec. 2 explicitly forbids. Fixed to `TEXT` before any data was written,
   caught by checking real API responses rather than assuming ISO-8601
   day precision.
2. **Migration cost on Neon's free tier.** The columns were briefly
   applied as `DATE` before catching the above; fixing them with
   `ALTER COLUMN ... TYPE TEXT` hit `DiskFull: project size limit (512 MB)
   exceeded` mid-migration, even though the live database was only 181MB
   — a type change forces Postgres to rewrite the whole table even for an
   all-NULL column. Fixed by `DROP COLUMN` + `ADD COLUMN` instead (cheap
   on an empty column), wrapped in a one-off idempotent `DO` block in
   `schema.sql` so it's a no-op on a database that never had the wrong
   type.

Backfilled all 11,490 existing rows from their already-stored `raw_json`
— no CT.gov re-fetch needed, since the raw record was already kept per
CLAUDE.md sec. 4. `scripts/backfill_narrative_fields.py` connects to
Postgres directly rather than through `POST /studies/batch`, deliberately:
that endpoint's diff logic would log a "changed" entry for all ~11k rows
(NULL → real value), which isn't a real Monitor-detected change and would
flood `study_changes` with same-day noise — a one-time structural backfill
is administrative work, the same category as `scripts/apply_schema.py`
and `scripts/create_readonly_role.py`. First version issued one `UPDATE`
per row (200 round trips per batch against Neon's pooled endpoint) and was
on pace for roughly 90 minutes; rewritten to a single bulk
`UPDATE ... FROM (VALUES ...)` per batch of 1000, which completed all
11,490 rows in under 3 minutes. Final database size: 183MB (up from 181MB
— the new columns mostly duplicate data already in `raw_json`, so the
storage cost was negligible, well inside the free-tier cap).

Understand now shows brief summary, intervention(s), primary outcome(s),
sponsor, and real study dates above eligibility (matches "why does this
trial matter" coming before "who can join"), plus a locations summary
(site count + countries, full list in an expander — one real backfilled
trial has 542 sites). Change history now renders human-readable field
names instead of raw column names, and structured fields
(interventions/outcomes/locations) render as a real before/after JSON
diff instead of one unreadable inline string — verified with a real
controlled test (inserted a fake `interventions` change row, confirmed
it rendered as a proper two-column diff, then deleted it). Also added an
honest fallback: when the *only* detected change is
`last_update_post_date` itself, the page now says plainly that
ClinicalTrials.gov marked the record updated but none of the fields we
track actually changed value, rather than leaving the researcher to
wonder what changed.

Verified end to end with real data, not just by reading the code: a
tracked trial (NCT00070564) shows real summary/interventions/outcomes/
sponsor/dates/542 real locations; a live-only trial (NCT06744179) shows
the same set of fields via the live-fetch path with zero extra code
(the response shapes already matched); `GET /discover` regression-checked
clean after the schema change.

## 2026-08-29 — Small UI fixes + honest, interactive Home page

Three real usability issues found by actually using the app: `st.metric`
truncates a long value with an ellipsis instead of wrapping (real example:
`ACTIVE_NOT_RECRUITING` got cut off) — switched Status/Phase/Study type to
the same plain markdown layout already used for Sponsor/dates, which
wraps correctly; `st.write()` on a bare integer renders it in an inline
`<code>` chip (confirmed by inspecting the real DOM), which looks like
unintended UI chrome for a plain enrollment count — fixed by writing the
string instead; and the small icon next to each `st.subheader` is
Streamlit's own built-in anchor-link feature (confirmed via DOM
inspection: an `<a href="#conditions">` wrapping a link-shaped SVG, not
anything this project added) — not changed, just confirmed and explained.

Home was too sparse to convey what the product actually does. Rebuilt
around two things: a live stats row (real trial count and tracked
condition list via a new `GET /tracked-conditions` — small, single-purpose,
keeps the frontend reading through FastAPI rather than a local config
file directly, same rule as everywhere else) instead of static claims,
and an honest capability grid for all five real capabilities (CLAUDE.md
sec. 1) — Discover/Understand get a working "Open" button
(`st.switch_page`), Monitor is marked as genuinely running in the
background with a pointer to where its output actually shows up
(Understand's change history), and Explore/Investigate are labeled "Not
built yet," not hidden or implied. Deliberately not overstating what's
live, matching the same honesty rule already applied everywhere else in
this project.

Verified in a real browser: Status/Phase/Study type render on one line
each now; a bare enrollment count (`3294`) renders as plain text, not a
code chip (confirmed via DOM diff, not just visually); Home's "Open
Discover" button actually navigates to `/Discover`.

## 2026-08-29 — Monitor gets its own roadmap step, separate from the digest email

Home's new capability grid made a real gap visible: Monitor's output is
only reachable per-trial, inside Understand's change history — there's
no way to answer "what changed across everything tracked this week"
without already knowing which NCT ID to look at. That's exactly the
question a researcher tracking a therapeutic area over time would
actually ask.

Decided: a real aggregate Monitor page (recent `study_changes` entries
across all tracked trials) is worth building, but as its own step, not
folded into the frontend step just finished or merged with the planned
Resend digest-email idea (step 12) — those two are genuinely different
things: a page for pulling up "what changed" on demand vs. an email that
pushes it. Inserted as roadmap step 6 (before AI ranking, since it needs
no new capability the app doesn't already have — just an aggregate read
over data already being written); everything from the old step 6 onward
renumbered by one (now 7-12), `CLAUDE.md`'s "Next" line and the
review-queue step reference in `docs/roadmap.md`'s own intro updated to
match.

## 2026-08-29 — Monitor page built: `GET /changes` + `frontend/pages/3_Monitor.py`

Built the aggregate feed decided above. `study_changes` only has
`nct_id`/`field_name`/`old_value`/`new_value`/`detected_at` — no trial
title of its own — so the new route joins it against `studies` for
`brief_title` on every row. New route lives at `/changes`, its own
top-level router (`api/changes.py`), not nested under `/studies`:
`/studies/changes` would collide with the existing `/studies/{nct_id}`
path (FastAPI would need it registered first, in that exact order,
forever, to avoid `{nct_id}` swallowing "changes" — too fragile to rely
on). Same `{total, limit, offset, results}` shape `GET /studies` already
uses; default `limit` 50, capped at 200 (higher than Discover's 100 cap
on purpose — a chronological activity feed is a different read pattern
than a search-result list). Added `idx_study_changes_detected_at`
(`detected_at DESC`) since the existing `idx_study_changes_nct_id` index
doesn't help a query that scans across every trial; added now rather
than waiting for the table to grow past its current 142 rows.

Frontend: `frontend/pages/3_Monitor.py`, same `st.dataframe` +
`on_select="rerun"` + session-state click-through-to-Understand pattern
Discover already uses, reused rather than reinvented. Pulled
`FIELD_LABELS`/`STRUCTURED_FIELDS` out of `pages/2_Understand.py` into a
new shared `frontend/labels.py` both pages import — the same
duplication-risk reasoning that `ctgov_client.py` was extracted for. A
structured-field change (interventions/outcomes/locations, stored as
JSON) shows as `"(changed — see Understand for detail)"` in the compact
table rather than a truncated JSON fragment, since a table row has no
room for a real two-column diff the way Understand's per-trial view
does. Home's capability grid now gives Monitor a real "Open" button
instead of the placeholder text pointing at Understand.

Verified for real: `GET /changes` against the live API returns real
rows with real trial titles (not just NCT IDs) and a real total (142,
matching the known `study_changes` row count); offset pagination
confirmed to return distinct rows. Real headless-browser pass
(Playwright): the Monitor page loads with real data, a real
`PointerEvent`-based row selection on the `glide-data-grid` canvas works
(same technique Discover's own verification established), and the full
click-through — select a row, click "View →", land on Understand
showing the right trial — works end to end, as does Home's new "Open
Monitor" button. One real timing gotcha hit and fixed during
verification, not a product bug: Streamlit's `on_select="rerun"`
round-trip and a subsequent `switch_page` both take several real seconds
under Playwright — an initial 1.5-2.5s wait made the click-through look
broken when it wasn't; polling up to ~6s after each interaction was
what actually confirmed it worked.

## 2026-08-29 — Monitor page: real pagination, filters, inline detail, a real dedup fix, and honest formatting

Six follow-up improvements to the Monitor page built in one interactive
pass, each verified for real before moving to the next:

**Real pagination.** The "rows to show" slider is gone; `frontend/pages/3_Monitor.py`
now shows a fixed 25 rows per page with Previous/Next, tracking the
current page in `st.session_state` the same way `selected_nct_id`
already is. `GET /changes` already supported `limit`/`offset` from the
original build, so this was a frontend-only change. The dataframe's
widget `key` is now suffixed with the current page number
(`monitor_changes_table_{page}`) — without that, a stale row selection
from the previous page's data could otherwise carry over into the new
page's differently-ordered rows.

**Real filters.** `GET /changes` gained two optional query params:
`condition` (same `study_conditions` ILIKE-join pattern `GET /studies`
already uses) and `field_name` (a plain equality match). A new
`GET /changes/fields` returns only the field names that actually have a
change on record right now (`SELECT DISTINCT field_name`), so the
frontend's filter dropdown can never offer an option that filters to an
empty result. The condition filter is a dropdown sourced from the real
`GET /tracked-conditions` list, not free text — this feed only ever
contains tracked trials, so a typo'd search box would just risk a
confusing empty result for no benefit.

**Real inline detail.** A structured-field change (interventions/
outcomes/locations) now shows an `st.expander` with the real before/after
JSON diff when its row is selected, instead of just a placeholder
string. The diff-rendering code itself was pulled out of
`pages/2_Understand.py` into a shared `render_structured_diff()` in
`frontend/labels.py` — both pages render the exact same
`study_changes` rows, so duplicating that rendering logic would let them
drift the same way `ctgov_client.py` was extracted to prevent for the
CT.gov parsing logic.

**A real duplicate-row bug found and fixed.** The Monitor feed surfaced
something that had been sitting in the data since the very first
scheduler run (2026-08-28): `NCT06074926` had the identical
`active_in_scope: true→false` change logged twice, same microsecond
timestamp. Root cause: `POST /studies/reconcile-scope`'s "what dropped
out of scope" query joins `studies` to `study_conditions` and matches
`condition ILIKE '%obesity%'` — this trial carries two condition tags
that both contain "obesity" (`Obesity, Childhood` and `Pediatric
Obesity`), so the join produced two rows for one trial, and the
following `SELECT` (no `DISTINCT`) carried that duplicate straight into
the list `study_changes` gets built from. Any trial with two or more
condition tags matching the same ILIKE pattern would hit this, not just
this one case. Verified read-only before touching anything: the old
query returned 8 rows for 7 unique trials on real data; adding
`DISTINCT s.nct_id` returned exactly 7. Fixed in `api/studies.py`, then
cleaned up the one real duplicate row already sitting in `study_changes`
(142 → 141 total rows) — the underlying `active_in_scope = false` state
itself was correct and left alone; only the doubled log entry was wrong.

**Correction, same day — the above cleanup was incomplete, and the
verification behind it was wrong.** The check that produced "the one real
duplicate row" only queried the `obesity` condition, then reported the
data as clean. `breast cancer` was never checked, and that's where the
real damage was: the user spotted `NCT04835597` repeated 19 times in the
Monitor feed. Root cause identical (the missing `DISTINCT`), but the
blast radius scales with how many condition tags a trial carries that
match the same `ILIKE` pattern — and that trial has **19** tags all
containing "breast cancer" (every AJCC anatomic/prognostic stage
variant: "Anatomic Stage IA Breast Cancer AJCC v8", "Prognostic Stage
IIIC Breast Cancer AJCC v8", and so on). `NCT04276272` and `NCT04123704`
had 3 tags each → 3 rows each. Duplicate count matched tag count exactly
in all three cases, confirming the mechanism.

Full cleanup then run properly: 22 excess rows removed (141 → 119),
keeping the earliest row per real event. Tested on the new `sandbox`
branch first (see the entry below) before touching live data — the
sandbox run reproduced the exact numbers, and the guard that actually
matters was checked on both: `COUNT(DISTINCT (nct_id, field_name,
detected_at))` stayed at 119 before and after, proving no real change
event was lost, only redundant copies. Verified through the live API
afterward too: `/changes` returns 119, zero duplicate rows in the feed,
`NCT04835597` appearing exactly once.

Real lesson, worth more than the bug: **verifying a fix against one
sample of a filtered dataset is not verifying the fix.** The first check
looked rigorous (read-only, compared row counts, real data) but sampled
only one of two tracked conditions, and the conclusion "the data is now
clean" was drawn far wider than the evidence supported. A dedup check
belongs against the whole table (`GROUP BY ... HAVING count(*) > 1`),
not one filter's slice of it.

**A distinct-trial count.** `GET /changes` (and `/changes/fields`'s
sibling total) now also returns `distinct_trials`
(`COUNT(DISTINCT nct_id)` under the same filters), so Monitor's caption
reads "141 change(s) detected across 94 distinct trial(s)" instead of
just a raw change count that conflates "many small changes to one trial"
with "many trials each changing once."

**Honest formatting instead of raw values.** `study_changes` stores
everything as `TEXT`, so a boolean field's transition showed up as the
literal strings `"true"`/`"false"`, and every timestamp rendered as a
raw ISO string (`2026-08-29T00:02:06.604034Z`). Checked real UX guidance
before picking a fix rather than guessing (Cloudscape's and UX
Movement's timestamp-display patterns, plus general audit-log
readability practice) — short version: show a real date/time a person
would say, and translate a status flag into what actually happened, not
its raw stored value. Added `humanize_value()` and `format_detected_at()`
to `frontend/labels.py`, used by both Monitor's table and Understand's
change history (the same rows, the same raw-value problem, in two
places). `active_in_scope` specifically renders as "Tracked" /
"Dropped from tracking" rather than a generic Yes/No, since that's what
the transition actually means; any other boolean field falls back to
Yes/No. Timestamps render as `"Aug 29, 2026, 12:02 AM UTC (15h ago)"` —
absolute and relative together, since Streamlit's table can't easily
attach a hover tooltip per cell the way a real UI framework could.

Two real gotchas hit during verification, neither a product bug:
(1) Streamlit reloads the *page* script fresh on every rerun, but a
plain `import`ed module like `labels.py` gets cached in the process's
`sys.modules` for its whole lifetime — editing `labels.py` alone doesn't
take effect until the server process restarts, unlike editing
`pages/3_Monitor.py` itself, which hot-reloads immediately. This produced
a real `ImportError` mid-verification before the restart. (2) `st.selectbox`'s
round-trip (close dropdown → widget value change → script rerun) took
longer under Playwright than a button click's — an 8-9s wait was needed
to see the correct post-filter result, versus ~6s for a button-triggered
rerun.

Verified for real throughout: real pagination confirmed via server-side
session-state logging (page genuinely advances 0→1→2, distinct rows per
page) and a real browser render; both filters confirmed against the live
API (`condition=obesity` → 47/36, `field_name=overall_status` → 7) and in
a real browser; the structured-field dropdown verified with a real
controlled test row (inserted, confirmed the two-column diff rendered,
then deleted, matching the same controlled-test pattern used for the
narrative-fields diff work); the dedup fix verified read-only against
real data before any write, then confirmed live (`total` 142 → 141); the
distinct-trial count and the humanized formatting both confirmed via
live API responses and real-browser screenshots on both Monitor and
Understand.

## 2026-08-29 — Found: the `dev`→`production` cutover never happened; added a real `sandbox` branch

Caught while answering a direct question about whether the day's database
writes were hitting a disposable copy or real data. They were hitting real
data — and checking the actual Neon branches explained why.

The 2026-08-26 decision ("Database: Neon Postgres, chosen and verified")
described a two-phase plan: schema work happens on a `dev` branch,
`production` stays untouched until the schema is trusted. Phase 1 happened
exactly as written. **Phase 2 — actually cutting over to `production` —
never happened, and was never tracked anywhere as a remaining step.** So
across ingestion, the FastAPI layer, the live 6-hour cron, the frontend,
and everything since, `.env.local` kept pointing at `dev`, and `dev`
quietly became the permanent real database by inertia rather than by
decision. Confirmed from Neon's own branch metadata, not assumed: `dev` is
226MB with 4,815 CPU-seconds and 736MB of data transfer; `production` is
32MB with 81 CPU-seconds and zero data transfer — schema applied once on
2026-08-26 and never touched again.

Decided: **don't** migrate data into `production` just to make the names
match their original intent. Everything working today (local `.env.local`,
the live GitHub Actions cron secret) points at `dev`; re-pointing all of it
carries real risk of breaking a working, unattended scheduled job purely to
fix a label. Instead, added a third branch, `sandbox`, created from `dev` —
that's now the real disposable copy to point at before running anything
destructive against real data. `dev` remains the live database, name
notwithstanding, and this entry is the record of why the names no longer
mean what they did on 2026-08-26.

Verified for real, not assumed: `sandbox` came up as a 226MB copy carrying
the true row counts (11,490 studies, 141 `study_changes`, matching `dev`
including the same day's dedup fix) and inherited both real roles
(`neondb_owner` and the SELECT-only `trial_lens_reader`). Isolation proved
directly rather than trusted: inserted one test row into `sandbox` only,
confirmed `sandbox` went to 142 while `dev` stayed at 141, then deleted it
and confirmed `sandbox` back to 141. Not one of Neon's stated guarantees
taken on faith — the actual behavior this project depends on, tested.

Still unverified, flagged rather than guessed: whether the GitHub Actions
cron's `DATABASE_URL` secret also points at `dev`. It's an encrypted
secret, unreadable from here. `production`'s near-zero activity strongly
implies it does, but that's inference, not evidence — worth confirming
directly in the repo's secret settings.


## 2026-08-30 — Monitor honesty pass: labels, drop reasons, change categories, enrollment type

A round of changes driven entirely by real questions asked while using the
Monitor page — each one a case where the UI was technically accurate but
practically misleading.

**"Active in tracking scope" was self-contradictory.** The row read
"Active in tracking scope: Tracked → Dropped from tracking" — a field name
that *asserts* the trial is active, sitting next to a value saying the
opposite. Unlike "Status", which is a neutral noun, this label made a
claim of its own. Renamed the label to "Tracking status" (neutral,
parallel to "Status") and the value to "No longer tracked". The Monitor
table's column header also went from "Field" to "Field changed", matching
the filter above it.

**A dropped trial now says *why*, deterministically.** "No longer tracked"
raised the obvious question and the answer turned out to be fully
derivable from stored data — no AI, no guessing. `api/tracking.py`'s
`drop_reason()` reads the trial's own status and last-update date against
the exact scope rules `scripts/ingest.py` applies, producing e.g. "This
trial is completed and ClinicalTrials.gov hasn't updated it since Aug 2024
— closed trials are only tracked for about 24 months after their last
update." Tested against all 14 real dropped trials: every one explained,
zero unexplained. Crucially it returns None rather than a guess when the
stored facts don't explain the drop, and the UI shows that honestly
("we can't tell from the data we've stored") — CLAUDE.md sec. 2 forbids
presenting an inference as a source fact, and this is exactly where that
temptation lives.

To make that safe, `CLOSED_STATUSES` and `RECENCY_DAYS` moved from
`scripts/ingest.py` into `ctgov_client.py` (already shared by both api/
and scripts/). The explanation now imports the same constants the fetcher
uses rather than restating them — a second copy would let the explanation
quietly start lying if either changed.

**Trial content vs. tracking, split properly.** `study_changes` mixes two
genuinely different kinds of event: real facts CT.gov reports about a
trial (status, eligibility, outcomes) and TrialLens's own bookkeeping
(are we still watching this?). Listing them undifferentiated implied a
scope flip is the same class of event as a status change. Monitor gained
a "Change type" filter (All / Trial content / Tracking) that also narrows
the field dropdown, so the two filters can't combine into a guaranteed-
empty result; Understand's history split into "What ClinicalTrials.gov
changed" and "Our tracking of this trial". The categorization lives only
in `api/tracking.py` and rides along on each row (`ChangeFeedEntry.category`,
`StudyChange.category`, and `GET /changes/fields` now returning
name+category) — deliberately not duplicated in the frontend. Verified the
split partitions the feed exactly: 104 trial-content + 15 tracking = 119.

**Enrollment was ambiguous and is now explicit.** "Enrollment: 34" gave no
indication whether 34 people actually enrolled or 34 is the sponsor's
recruitment target — and CT.gov reports exactly that distinction in
`enrollmentInfo.type`, which extract_fields() was silently discarding.
Across the real dataset it matters: 6,577 ESTIMATED vs 4,905 ACTUAL, so
the majority of bare counts were targets being read as headcounts.
Discarding it was precisely the dropped uncertainty CLAUDE.md sec. 3
forbids. Added `enrollment_type` (schema, extract_fields, DIFF_FIELDS so a
target→actual switch is itself reportable), backfilled all 11,482
applicable rows from stored raw_json in ~60s using the same bulk
`UPDATE ... FROM (VALUES ...)` pattern the narrative backfill established,
and Understand now shows "3,294 participants / Actual number enrolled" vs
"600 participants / The sponsor's target — not a count of people actually
enrolled", with an honest fallback for the 8 records CT.gov gives no type
for. Verified through both the tracked and live paths.

**Two real data problems found while verifying, both cleaned up.**

1. *The earlier dedup fix was verified wrong.* The 2026-08-29 entry above
   claimed the duplicate rows were cleaned up; that check only queried the
   `obesity` condition. The user spotted `NCT04835597` repeated 19 times in
   the feed — it carries 19 condition tags all containing "breast cancer"
   (every AJCC anatomic/prognostic stage variant), and the missing
   `DISTINCT` produced one row per matching tag. 22 excess rows removed
   (141 → 119). Full detail and the lesson are recorded as a correction on
   that entry.

2. *Test residue was sitting in the real change log.* `NCT00260585` carried
   three change rows with ids 1, 2, 3 — the first rows ever written to
   `study_changes` — all artifacts of the 2026-08-28 drift/drop testing
   (an injected `enrollment_count` of 999999, a corrupted date, and an
   artificially triggered scope drop). The tests were documented; the rows
   they created were never cleaned up, and they had been rendering as
   genuine CT.gov changes ever since. A feed row claiming enrollment
   changed from 999,999 is a fact CT.gov never reported. Deleted all three
   (119 → 116); the trial's own record was untouched and had already
   self-corrected on a later real run. This also explains a 15-vs-14
   discrepancy between tracking changes and currently-dropped trials.

Both cleanups were run against the new `sandbox` branch first and only
applied to live data after the sandbox run reproduced the exact expected
numbers — the branch created earlier the same day, earning its keep
immediately. The dedup deletion additionally asserted
`COUNT(DISTINCT (nct_id, field_name, detected_at))` was unchanged before
and after, proving only redundant copies were removed, not real history.

## 2026-08-30 — Long text changes: a real word-level diff, and honest "formatting only" labelling

Real use surfaced the problem: an `eligibility_criteria` change rendered
both versions in full, side by side — roughly 4,000 characters each, 8,400
in total — to communicate a handful of edited words. Unreadable, and it
actively buried what changed.

Checked the specific case before building anything (`NCT07787728`, a Phase
Ib MWN109 obesity trial): the two versions are 94.8% similar by word, and
after normalising punctuation, casing and whitespace they are **identical**.
The sponsor had reformatted exclusion criterion 5 from a run-on sentence
into a bulleted list. Nothing clinical changed at all, and the UI gave a
researcher no way to know that without reading 8,400 characters.

**Deterministic, not an agent.** A text diff has exactly one correct
answer, so this is `difflib` (Python stdlib, the same approach `git diff`
takes), not an LLM call — CLAUDE.md sec. 5's "deterministic first". An LLM
summarising eligibility criteria would risk paraphrasing or softening
clinical text, which sec. 2 forbids outright. The diff shows the real words
that changed; it never rewrites them.

Built in `frontend/labels.py`, shared by Monitor and Understand:
- `is_long_text()` — a length threshold (200 chars) rather than a
  hardcoded field list, so it applies to any long value, not just
  eligibility criteria.
- `summarize_text_change()` — a short, honest cell label
  ("Text changed (+3 / −14 words)"), a count of what moved, never a
  paraphrase of the content.
- `render_text_diff()` — one inline passage, removals struck through in
  red, additions highlighted in green, unchanged text plain. Chosen over
  side-by-side columns because for 4,000 characters of prose, side-by-side
  reproduces the original problem.
- `is_formatting_only()` — true only when the two versions differ purely
  in punctuation, casing or whitespace.

**The formatting-only check is deliberately biased toward saying "no".**
Only non-alphanumeric differences are ignored, so anything touching a word
or a number counts as a real change. Missing a genuinely cosmetic edit is
harmless; the opposite — telling a researcher nothing changed when it did
— would be a false claim about a study fact. Verified explicitly against
the cases that would matter most: `BMI 27.0 to 35.0` -> `45.0`,
`age 18 and 65` -> `75`, `eGFR < 60` -> `< 30`, and `no pregnancy plans` ->
`pregnancy plans` all correctly return False. Across the real dataset, 2 of
13 stored text changes are genuinely formatting-only.

The diff earned its place immediately on a different trial (`NCT06585306`),
surfacing two real changes that had been invisible in the wall of text:
`sedative gastroscopy` -> `gastrointestinal endoscopy` (procedure scope
broadened), and a set of airway-difficulty criteria ("interincisal distance
<6.5cm, no micrognathia, limited mouth opening and limited cervical spine
movement") replaced outright by `BMI >28kg/m2`. That is exactly the kind of
protocol change a researcher tracking a trial needs to see.

Left as-is on purpose: CT.gov's own markdown escaping shows through in the
diff (`BMI\>28kg/m2`). Stripping characters from stored study text would be
editing the source rather than displaying it.

One testing note for next time: a browser normalises inline `style="...#hex"`
to `rgb(...)`, so a Playwright selector matching the literal hex string
finds nothing even when the markup rendered perfectly. Assert on a
structural property (`style*="line-through"`) or inspect the real DOM
instead of trusting a hex-string match — this looked like a rendering
failure for several minutes when nothing was wrong.

## 2026-08-30 — Age shown as a real bracket, not a lower bound

`minimum_age` alone can only ever render "18 Years and older", which is a
lower bound rather than the trial's actual age eligibility. CT.gov does
report `maximumAge` — 5,712 of 11,490 stored trials have one — and
`extract_fields()` was discarding it.

Added `maximum_age` following the same path as `enrollment_type`
(2026-08-29): schema column, parsed in `ctgov_client.py`, added to
`DIFF_FIELDS` since a changed age limit is a genuine protocol amendment,
and backfilled from stored `raw_json` (5,712 rows in ~28s, no CT.gov
re-fetch). `TEXT`, not numeric: CT.gov reports each bound with its unit
attached and the unit really does vary ("18 Years", "18 Months"), so
parsing to a number would mean either losing the unit or inventing a
conversion.

Understand's "Minimum age" field became "Age", rendering
`format_age_range()`: "18 Years to 65 Years" with both bounds, "18 Years
and older" with only a lower one, "Up to 17 Years" with only an upper.
Roughly half of trials genuinely specify no upper bound — that's a real
fact about the trial, not missing data, so it reads as "and older" rather
than an empty value.

Skipped deliberately: CT.gov's `stdAges` (CHILD / ADULT / OLDER_ADULT) is
available alongside the numeric bounds but is a coarser restatement of the
same information. Worth revisiting only if age-category filtering is ever
wanted, where a controlled vocabulary beats free text with mixed units.

Verified the write path on `sandbox` before trusting it, since adding a
column to the upsert means the INSERT column list, the `ON CONFLICT` set,
the row tuple, and the `execute_values` template all have to stay aligned —
a mismatch would surface as silently shifted column values, or as a failure
on the next unattended cron run. Applied the schema to sandbox, pointed a
FastAPI instance at it, ran a real `ingest.py` (56 trials matched, 2
written, no errors), then posted a record with `maximum_age = "65 Years"`
and confirmed it landed in `maximum_age` while its neighbours (`sex`,
`healthy_volunteers`) stayed NULL — exactly what a misaligned tuple would
have corrupted. Sandbox is left contaminated with that test data on
purpose; it's the disposable branch, recreated from `dev` when needed.

## 2026-08-31 — Ranking: five of eight signals moved out of the model

The first ranking implementation sent all seven fit signals to one LLM call
per trial. Four of them were field comparisons with exactly one correct
answer — `overall_status == "RECRUITING"`, `len(locations)`, an age-bracket
overlap, an enrollment-size band — and a fifth (phase) became one once the
researcher's stated preference was parsed. Routing those through a model
means they can drift between runs on identical input, which makes an
evaluation harness unable to attribute a score change to a code change.

Moved to `api/ranking_deterministic.py`, which imports no model client at
all. The researcher's interest is now parsed once per search rather than
re-interpreted per trial, so a search of N trials makes `1 + N` calls
instead of N larger ones. Cost fell from ~$0.03 to ~$0.006 per call, but
the reason for the split is reproducibility and the fact that deterministic
signals can carry the literal stored value as evidence rather than a
model's paraphrase of it.

Every vocabulary and threshold in that module came from querying the live
`dev` branch rather than from the CT.gov documentation, and the two
disagreed in ways that mattered. The prompt being replaced instructed the
model that `COMPLETED/CLOSED` means not-enrolling; `CLOSED` is not a
ClinicalTrials.gov status at all. The eight real values are RECRUITING
(3,982), COMPLETED (3,413), ACTIVE_NOT_RECRUITING (1,841),
NOT_YET_RECRUITING (1,447), TERMINATED (385), ENROLLING_BY_INVITATION (233),
WITHDRAWN (149) and SUSPENDED (40) — only two of which the prompt named,
leaving roughly 20% of trials unguided. The same prompt showed
`"phase": "Phase 2"` where the column stores `PHASE2`, and did not handle
the comma-separated multi-phase form (`PHASE1,PHASE2`, 461 trials).

Age parsing needed the unit, not just the number: `minimum_age` values
include Months, Weeks, Days, Hours and Minutes as well as Years, and `1 Day`
is a real value on 12 trials. Reading it as 1 year is a 365x error, so
`parse_age_to_years` returns `None` rather than a number whenever the unit
is absent or unrecognised.

## 2026-08-31 — "Unknown" excluded from the score denominator

A signal the researcher never asked about was scored 0.0 while its weight
stayed in the denominator, which made "we can't tell" arithmetically
identical to "this trial fails". For a plainly-worded interest like "I track
breast cancer trials", four of seven signals have nothing to compare
against, so the score was capped near 0.65 no matter how well the trial
matched. The previously recorded symptom — top-1 scores of 0.60 against an
expected 0.75+ — was this formula rather than model behaviour.

`unknown` is now excluded from both numerator and denominator; `no_match`
stays in the denominator contributing 0.0, because it is real evidence
against the trial. The score answers a narrower question — of the criteria
that could be assessed, what fraction matched — so `FitRanking` carries
`evaluated_weight_fraction` alongside it. A 1.00 assessed on 30% of criteria
and a 1.00 assessed on all of them are different claims, and the score alone
cannot distinguish them.

The synthetic test cases' expected score ranges were written against the old
denominator: reproducing the old arithmetic lands exactly inside each
declared range. Recalibrating them was deferred deliberately rather than
edited to make the suite pass.

## 2026-08-31 — Missing preferences are elicited, not scored

Excluding unknown signals is arithmetically honest but silently narrows what
the score means. A researcher seeing a number has no way to know that most
of the criteria went unevaluated because they were brief.

`POST /rank` now returns `unspecified`: the preferences the researcher did
not state, how much scoring weight each one costs, and the question that
would close it, ordered by how much coverage an answer would recover. It is
derived from the parsed preferences with no additional model call.

It only asks about gaps an answer can fix. A signal unscored because the
trial itself records no phase — 64% of trials, `NA` on 4,869 and NULL on
2,442 — is not recoverable by anything the researcher can say, so no
question is generated for it.

## 2026-08-31 — Observational studies cannot match a phase request

`phase_fit` returned `unknown` whenever no phase was recorded, which
excluded it from scoring and therefore cost the trial nothing. An
observational cohort study could rank alongside genuine Phase II trials for
a researcher who had explicitly asked for Phase II.

The two "no phase" cases separate almost perfectly by `study_type`: 2,440
OBSERVATIONAL with NULL, and 4,869 INTERVENTIONAL with `NA`. An
observational study has no phase by definition, which is a fact rather than
an ambiguity, so it now scores `no_match` with the reason stated. An
interventional trial recording `NA` — common for behavioural, device and
procedure trials — stays `unknown`.

## 2026-08-31 — Condition matching split, because the filter already answered it

`/rank` selects trials with `condition ILIKE`, so every trial reaching the
model had already matched on condition. A 30%-weighted `condition_match`
signal then asked the model whether the condition matched, and it always
said yes — granting 30% of the score to every trial automatically, which is
why scores clustered near 1.00 and the ranking barely discriminated. A
signal that nearly always returns the same value carries no information
regardless of its weight.

Replaced with two signals asking what the tag cannot answer:
`condition_is_subject` (20%) — is the condition the trial's actual subject,
or a comorbidity of enrolled patients, an exclusion criterion, or
background — and `approach_match` (10%) — does the mechanism or modality
match what was described. The prompt now states that the condition match is
already established and is not evidence of fit.

## 2026-08-31 — Few-shot examples removed in favour of schema-constrained output

The replaced prompt carried three worked examples. In all three,
`prior_treatment_compatible` and `age_range_fit` were filled in identically
as `{"status": "unknown", "confidence": "low"}`. Read as a pattern rather
than as three independent judgments, that teaches which fields to leave
blank; whatever an example holds constant, it teaches.

Both prompts now use `output_config.format` with a JSON schema, so the API
enforces shape and no example is needed to demonstrate it. This also removed
a real failure path: the previous code instructed the model to emit only
JSON and then called `json.loads` on the response, where a malformed reply
raised into the bare per-trial `except` and silently dropped the trial from
the results.

## 2026-08-31 — Two test tiers, split by whether they cost money

An LLM feature fails in two ways that look identical from outside: the data
never reached the model, or the model reasoned badly on data it did receive.
The bug that actually occurred was the first kind —
`prior_treatment_compatible` carried 15% of the scoring weight while
`eligibility_criteria` was never placed in the prompt payload, so the signal
could only ever return `unknown`. No amount of running the paid harness
distinguishes that from honest uncertainty, because the output string is the
same.

`tests/test_ranking_prompt_payload.py` asserts on the constructed payload
with no API call, and would have caught it immediately. It also asserts that
the five deterministic fields stay *out* of the payload, so the model cannot
re-judge settled facts and contradict the evidence displayed beside them.
`tests/test_ranking_real_data.py` runs every deterministic scorer against
all 11,474 active trials, read-only — it found no unparsed age, no unhandled
status, and no scorer exception.

103 tests now run free and belong in CI. The harness in
`tests/test_ranking_integration.py` makes 48 real calls per pass and stays
manual, run at decision points only.

## 2026-08-31 — On-disk response cache for the evaluation harness

Most iteration on ranking is on weights, thresholds and presentation, none
of which need a fresh model judgment. Responses are cached to
`.ranking_cache/` (gitignored), keyed on
`sha256(model + effort + system prompt + user content)`, so an identical
request replays from disk at no cost and only a genuine prompt, model or
effort change forces new spend. Verified by re-running a full 48-call suite
for $0.00 immediately after a paid run.

Each entry stores the user content and a hash of the system prompt
alongside the response, so a cached answer can be audited against the exact
question that produced it.

## 2026-08-31 — What the ranking evaluation does and does not establish

The harness reported correct ordering in 15 of 15 scenarios. Five of those
had the top two trials tied on both score and coverage, and Python's stable
sort resolved them by the order the fixture file listed them — which
happened to match the expected answer. Reversing the fixture list flipped
those five to failures with byte-identical scores, so the honest count is 10
genuinely correct and 5 undetermined.

The synthetic fixtures also do not resemble the stored data: two or three
trials per scenario against a real task of fifty, no eligibility criteria
text, one condition tag where a real trial carried nineteen, and every field
populated where real data is 64% missing phase and 50% missing an upper age
bound. The missing-data paths most of the design addresses are the ones the
fixtures never exercise. Published trial-matching systems report
precision/recall around 0.32-0.45; scoring 1.00 indicates the harness
measures an easier task, not a better system.

Treated as a regression harness rather than a quality measurement. Real
measurement needs a clinician reading real ranked output.

## 2026-08-31 — The ranking evaluation suite cannot pass; its rate is not a signal

Asked whether the declared target — top-1 score in [0.75, 0.95] with
confidence `high` — is reachable at all under the rewritten scoring. It is
not, for either half. Checked against the response cache at no cost;
`tests/reachability_check.py` reproduces it.

`confidence: "high"` requires `evaluated_fraction >= 0.80`. Seventy percent
of the signal weight is preference-gated — status 20, phase 15, prior
treatment 15, age 10, approach 10 — leaving 30 percentage points
(`condition_is_subject`, `sites_active`, `enrollment_feasibility`) that are
always evaluated. Reaching 0.80 therefore requires the researcher to state
at least 50 of the 70 gated points. The most any of the fifteen test
interests unlocks is 65%, and most sit between 30% and 55%, so `high` is
unreachable in 0 of 15 scenarios. It is unreachable in production for the
same reason: a realistic query rarely specifies all of recruitment status,
phase, prior therapy, age band and modality. Whether the 0.80 threshold is
correct — high confidence being genuinely rare — or miscalibrated is now an
open question; it was inherited from the first implementation and never
decided.

The score ranges are unreachable for a separate reason. Because `unknown`
signals are excluded from the denominator, a trial matching everything the
researcher asked about scores exactly 1.00, with nothing left to lose points
on. The fixtures deliberately designed their top-ranked trial to match
everything, so four of the five return 1.00 against a declared ceiling of
0.95, and the fifth returns 0.94 against a ceiling of 0.75. The ranges were
written against the old denominator, which reproduces each boundary exactly.

Separately, the harness computes `passed = order_correct and in_range` and
never asserts confidence at all — so the test case named for confidence
calibration does not check confidence, and would fail if it did.

Consequences recorded rather than patched, since recalibrating the numbers
would only hide the structural point: top-1 score is now a weak assertion,
because "matched everything asked" equals 1.00 however little was asked. The
informative assertions are the score gap between the first and second
result, which measures whether the system discriminates at all, and the
coverage fraction. Until that is settled the suite's pass rate is not a
regression baseline and must not be quoted as one.

## 2026-08-31 — `SELECT *` was spending the Neon transfer budget on a column nothing reads

Neon warned that the project had used 84% (4.2 GB) of its 5 GB monthly
public network transfer. Nothing about the app's traffic explained it —
the frontend is one user, the cron runs four times a day.

The cause was `SELECT *`. `studies.raw_json` holds the untouched CT.gov
response, ~22 KB per row on the wire (249 MB across 11,469 active
trials). Nothing has ever read it — `StudyDetail` has no such field, so
Pydantic silently dropped it on arrival. Four queries fetched it anyway:
`fetch_trials_for_condition`, `get_study`, `discover_trial`, and the
diff read inside `POST /studies/batch`.

The expensive one was `tests/test_ranking_real_data.py`, which reads
every active row and runs on every `pytest tests/`. Measured wire cost
(`sum(octet_length(col::text))`, which is what psycopg2 actually
receives):

| query shape | per full-table run |
|---|---|
| `SELECT *` (before) | **315 MB** |
| every `StudyDetail` column | 66 MB |
| only what the scorers read (now) | **16 MB** |

Fourteen runs of the free test suite is 4.4 GB. That is the entire
allowance, spent on a column that was discarded the moment it arrived.

Two fixes:

1. `STUDY_DETAIL_COLUMNS` in `api/schemas.py`, derived from
   `StudyDetail.model_fields` so it cannot drift as fields are added.
   Every former `SELECT *` read now names it. The batch diff selects
   `DIFF_FIELDS` instead, which is all it ever compared.
2. The real-data test narrows further, to the columns the five
   deterministic scorers actually read. It skips `eligibility_criteria`
   (16 MB), `brief_summary`, `interventions` and `primary_outcomes` —
   none of which any scorer touches.

The narrowing in (2) creates a trap: an unfetched column arrives as
`None`, so a scorer that started reading one would be tested against
nothing while still passing — bug #7 (`eligibility_criteria` never
reaching the prompt) in a new costume.

`test_fixture_fetches_every_column_the_scorers_read` guards it by walking
`api/ranking_deterministic.py`'s **AST** for every `trial.<field>` access
and asserting the fixture query fetches all of them. The first version
grepped for a hand-written list of omitted names; that was replaced
because a hand-written list only catches the mistakes whoever wrote it
already anticipated, and the entire risk here is the field nobody thought
of. The AST version needs no list, catches fields added later by someone
who never read the test, and fires in both directions — a scorer reading
a new field, or someone trimming a column out of the query. Both were
demonstrated failing before it was accepted. Free: no database, no model,
no network.

Side effect worth noting as corroboration: the free suite's wall time
fell from 79s to 10s. The tests were mostly waiting on the network.

**The rule: never `SELECT *` against `studies`.** The table is 69%
a column no query needs.

## 2026-08-31 — `raw_json` stays; the storage tradeoff is real but not due yet

Questioned during the Neon transfer investigation, since `raw_json` is 52%
of the `studies` table (95 MB on disk, 249 MB on the wire) against a
**0.5 GB per-project storage cap** on Neon's free plan, and no query in the
codebase reads it. An earlier note in this session called it a column
"nothing reads." That was wrong in the way that matters.

`decisions.md` records it earning its keep three times, each a schema
backfill run from stored raw records with **no CT.gov re-fetch**:
narrative fields (11,490 rows), `enrollment_type` (11,482 rows, ~60s),
`maximum_age` (5,712 rows, ~28s).

Speed is the weaker argument. The real one: **a re-fetch is not a
re-read.** CT.gov's record today is not the record that was stored, so
backfilling from a re-fetch would silently mix current values into
historical rows and make the diff history in `study_changes` a lie.
`raw_json` is what makes a backfill *honest*, not merely fast. CLAUDE.md
sec. 4 is right.

Confirmed again while scoping the alerting features below: 1,050 stored
trials already carry a `resultsSection` and 4,433 a `referencesModule`
(publication links), neither ever extracted into a column. Both are
backfillable today for free. That is the fourth payoff.

**Decision: keep it.** Current size 206 MB = 41% of the cap; the wall
arrives around ~28,000 trials. Revisit then, and the option at that point
is to *move* it (object storage, or keep only the newest raw record per
trial) — not to drop it.

## 2026-08-31 — Feature order for post-Step-7 work

Three features discussed with the user. Agreed order, with reasoning:

1. **Advanced filtering / noise reduction** (alert on
   RECRUITING→TERMINATED, phase change, new site, new results or
   publication links). First because it is almost entirely deterministic
   over data already stored — `study_changes` keeps old and new values,
   and `DIFF_FIELDS` already covers `overall_status`, `phase`,
   `enrollment_count`, `eligibility_criteria`, `locations`. Costs no API
   spend. "New site near me" stays at city/country level; real geocoding
   is scope creep for no extra insight.
2. **Curated summary of what changed.** Second, because it is the readable
   summary *of* (1)'s categories — building it first means writing it
   twice. Mostly counting ("2 opened, 1 completed, 7 amendments"); the
   model earns its place only for turning a ~4,000-character
   `eligibility_criteria` diff into one plain sentence. ~7 such changes in
   4 days, so a few cents.
3. **Per-user accounts — deferred.** Auth is undifferentiated work that
   demonstrates none of the skills this project was chosen to practise
   (2026-08-25), and it *hurts* the portfolio: a reviewer forced to sign
   up before seeing anything usually leaves. If per-user relevance is
   wanted, a **watchlist with no login** gives the interesting half — the
   many-to-many modelling that (1) needs anyway — without the boilerplate.

Grounding for (1): four days of Monitor produced 123 changes across 100
trials — 7 `overall_status` transitions (incl. RECRUITING →
ACTIVE_NOT_RECRUITING, ACTIVE_NOT_RECRUITING → COMPLETED,
NOT_YET_RECRUITING → RECRUITING), 7 `eligibility_criteria` amendments, 3
`enrollment_count` moves. The substantive signal is real and already on
disk; the features above are about surfacing it, not producing it.

## 2026-08-31 — Unit 4 verified; two more bugs, one fixed and one open

Building `frontend/pages/4_Ranking.py` and actually running it. Everything
below was found by running the thing, not by reading it — the page had
"existed" and compiled for an hour before any of this surfaced.

**Found free, before spending anything:**
- A `SyntaxError`: Python 3.9 forbids a backslash inside an f-string
  expression. The file had never been executed.
- `1 things you didn't specify` — pluralisation, visible to the user.

Free verification used `streamlit.testing.v1.AppTest`, which runs a page
headlessly and reports exceptions. Cheaper and faster than the Playwright
approach used for earlier pages, and it caught everything above. Also
validated all 33 response keys the page reads against the real Pydantic
models by AST — the previous ranking page was deleted for expecting
`studies` where `/studies` returns `results`, and that check is free.

**Bug #9 — `POST /rank` had never once returned successfully over HTTP.**
The endpoint passed a `ResearcherPreferences` (scoring module) into
`preferences`, typed `ResearcherPreferencesOut` (response schema). FastAPI
validates the *outgoing* response against `response_model`, so every
request raised a 500 — **after all 21 model calls had been billed**. Found
by spending $0.13 on a live 20-trial run that threw the entire result away.

This is bug #1's twin: the tests all called scoring functions directly, so
nothing exercised request binding or response validation. New free file
`tests/test_ranking_endpoint.py` calls the endpoint over HTTP with the
model layer stubbed. Proven to catch it: reintroducing the bug fails the
test, restoring the fix passes. **A test that calls the endpoint function
directly is not testing the endpoint.**

The response cache paid for itself here — the re-run after the fix replayed
all 21 responses for **$0.0000**. The bug cost $0.13 once, not twice.

**Bug #10 — `approach_match` cannot ever score. Found, NOT fixed.**
Across all 20 real trials, `approach_match` (10% weight) returned `unknown`
20/20, with evidence "Researcher named no specific approach" — for the
interest *"...testing immunotherapy or targeted agents in adults."*

`build_semantic_user_content()` sends the model only `condition_terms` and
`prior_treatment_context`. `raw_interest` appears solely as a *fallback*
when `condition_terms` is empty. Since the parse populated condition terms,
the words "immunotherapy or targeted agents" never reached the model.

This is bug #7 exactly — a weighted signal whose input is never plumbed
into the payload — recurring inside the very function whose docstring
describes bug #7. The free payload test asserts `eligibility_criteria` is
present but nothing asserts the approach is.

Worse, the system contradicts itself: `find_unspecified()` correctly did
*not* ask about approach (`_mentions_an_approach` matched "immunotherap"),
so it knows the researcher named one, while the signal says they didn't.

Consequence, visible in the real run: the top 5 were intermittent fasting,
ketorolac/pregabalin, electrosurgery, tDCS, and broccoli microgreens — not
one an immunotherapy or targeted agent. Half the stated interest was
silently discarded. **Not fixed here because the fix changes the prompt,
which invalidates the cache and costs real money to re-verify. The user
decides.**

**Also observed, corroborating two open questions:**
- `sites_active` returned `partial` 15/20 — open question #4 confirmed on
  real data, not just in aggregate.
- Real scores spread 0.92 → 0.27, against the synthetic harness's flat
  1.00. Further evidence the synthetic fixtures are far easier than reality.
- `fetch_trials_for_condition` orders by `last_matched_at DESC LIMIT 20`,
  so `/rank` scores *the 20 most recently matched* trials, not the best 20
  of 11,474. For a researcher that is "score these 20," not "search." Worth
  deciding before the page is called finished.

`Home.py` flipped Ranking to `"live"` only after the page rendered a real
ranking end to end. 108 free tests pass.

## 2026-08-31 — Researched against the literature: what TrialGPT settles

Searched rather than assumed, prompted by the user asking whether any of
this is needed. The reference system is **TrialGPT** (NIH/NLM, *Nature
Communications* 2024) — the same problem, done properly.

**What it validates.** TrialGPT is three modules: Retrieval → Matching →
Ranking. Retrieval recalls **>90% of relevant trials using <6% of the
collection**. The two-stage design built today (deterministic shortlist,
then model on the shortlist) is the same shape, arrived at independently
from CLAUDE.md sec. 5. Keep it.

**What it corrects — the label set.** TrialGPT labels each criterion
`{Included, Not included, Not enough information, Not applicable}`.
**"Not enough information" and "not applicable" are deliberately separate.**
TrialLens collapses both into `unknown`. That matters: 26.9% of TrialGPT's
residual errors were exactly this confusion — the second-largest error
class. And it is bug #3's lesson again ("can't tell" and "doesn't fit"
must not share an encoding), one level deeper: *"the trial has no phase
recorded"* and *"phase doesn't apply to an observational study"* are
currently indistinguishable here, and only one of them is a data gap.

**What it corrects — the benchmark in `step7_implementation_guide.md`.**
That file records published systems at precision/recall ~0.32-0.45 and the
2026-08-31 entry above leans on it to argue the synthetic 1.00 is
implausible. TrialGPT reports **NDCG@10 0.7275, P@10 0.6724**, and
criterion accuracy 0.873 against expert 0.887-0.900. The 0.32-0.45 figure
is not the current state of the art. The conclusion (synthetic fixtures are
far easier than reality) still stands on its own evidence — 2-3 trials per
scenario, no near-misses — but it should not be argued from that number.

**Other findings worth acting on:**
- **Chain of thought, ordered.** TrialGPT generates the rationale *first*,
  then the classification. Check whether `SEMANTIC_SCHEMA` puts `evidence`
  before `status`; if status comes first the model commits, then
  rationalises, and the evidence stops being load-bearing.
- **Aggregation.** Linear (six percentages) plus an LLM-generated
  relevance/eligibility pair; combining both beat either. TrialLens uses a
  single weighted average.
- **Explanations are the measurable part.** 87.8% of TrialGPT's
  explanations were rated correct, sentence-location F1 88.6%, close to
  human experts. This is the number a researcher's judgement can actually
  produce, and it is per-criterion, not per-trial.
- **LLM-as-judge biases** (2026 literature): verbosity bias (longer text
  scores higher regardless of quality), position bias, and scoring bias
  from minor prompt perturbations. Relevant here because `confidence` and
  `evidence` are both model-generated — length must not become a proxy for
  certainty.
- **Do we need the LLM at all?** For screening, LLMs beat the Cochrane
  highly sensitive filter (sensitivity 100% vs 99.5%, specificity 85.9% vs
  67.8%). But the local evidence is better than the citation: in today's
  real 20-trial run `condition_is_subject` returned match 9 / partial 9 /
  no_match 2 — real variance, on the one question a `condition ILIKE` tag
  provably cannot answer. That signal earns its cost. `approach_match`
  has not yet earned anything, because of bug #10.

## 2026-08-31 — The three process fixes, implemented as code not intentions

1. **No paid call until a free test of the same path passes**, and
2. **batch the paid questions** — both enforced by `scripts/paid_preflight.py`,
   which runs the free suite, exits non-zero and refuses if it is red, and
   otherwise prints every question still waiting on a paid answer so they
   are asked in one run instead of three. Proven in both directions: exit 0
   green, exit 1 with a refusal when the suite fails. Also written into
   CLAUDE.md sec. 7, since a rule that lives only in a script is a rule
   nobody reads first.
3. **The free payload guard for `approach`** — already built as
   `TestApproachReachesTheModel`, including a structural assertion that
   elicitation and the payload can never again disagree about whether an
   approach was named. That disagreement *was* bug #10.

## 2026-08-31 — Intervention category: the free half of the approach question

User's proposal, and a good one: CT.gov records `interventionType` as
structured data, so "the researcher follows surgical approaches, this trial
is 100% DRUG" is a fact, not an interpretation. It cannot tell a GLP-1 from
an SGLT2 (both DRUG) — so it narrows what needs the paid call rather than
replacing it, exactly as five of eight signals were already moved to code.

**Querying the real distribution first (sec. 6) changed the design twice:**

1. **There are 11 intervention types, not 6.** The proposal named DRUG,
   BEHAVIORAL, PROCEDURE, DEVICE, DIETARY_SUPPLEMENT, OTHER. The database
   also holds DIAGNOSTIC_TEST (625), RADIATION (618), BIOLOGICAL (575),
   COMBINATION_PRODUCT (136) and GENETIC (68) — 2,022 interventions that
   the shorter list would have left unclassifiable.
2. **985 of 11,420 active trials record no interventions at all**, and
   OTHER appears on 3,939. Both must *defer to the model*, never return
   `no_match`: absent data is not evidence against a trial (sec. 2), and
   treating the contentless OTHER as a conflicting category would
   manufacture false mismatches across a third of the database.

Implemented as `score_approach_category`, which returns a `no_match`
FitSignal **only** when both sides are informative and disjoint, and `None`
— defer — otherwise. Used in two places: candidate selection, where it
removes trials before any model call is spent on them, and `rank_one_trial`,
where a decisive verdict overrides the model's `approach_match` (a stored
`interventionType` is a fact; a model's reading of it is an inference).

Measured on the real 5,371-trial breast cancer pool:

| researcher's approach | ruled out for $0 |
|---|---|
| surgical / procedure | 3,373 (63%) |
| behavioural / lifestyle | 3,398 (63%) |
| immunotherapy (DRUG+BIOLOGICAL) | 1,507 (28%) |

Cost: stage-one transfer rose 10.0 → 12.6 MB per search for the
`interventions` column. The AST guard in `test_ranking_real_data.py`
demanded that column automatically the moment a scorer read it — the guard
working as designed, on its first real opportunity.

## 2026-08-31 — `not_applicable` added, but it belongs to the model, not the code

Added to `_STATUS_ENUM` and `FitSignal` after the TrialGPT research, and
scored identically to `unknown` (excluded from numerator and denominator)
while reading very differently to a researcher.

**Then a negative finding worth recording, because it stops this being
cargo-culted:** there is no clean use for it in any of the *deterministic*
scorers. TrialGPT's `not_applicable` labels individual eligibility criteria
within a trial ("must not be pregnant" is not applicable to a male
patient). TrialLens's eight signals are trial-level preferences that always
apply — a trial always has a status, always has or lacks a phase, always
has an age band. Where "the trial doesn't record it" is the answer, that is
a data gap, which is `unknown` by definition.

It does have a real use in the three **model-judged** signals: prior
treatment on a prevention trial in healthy volunteers with no treatment
history to have; approach on a trial registering no interventions. So the
label is defined in the schema and taught in the prompt, with an explicit
tie-break — *if unsure which applies, use `unknown`, because calling a
question meaningless is a stronger claim than admitting you cannot answer
it*. No deterministic scorer was forced to emit it.

## 2026-08-31 — Evidence before status in the output schema

`_signal_schema_fields` emitted `{name}_status` before `{name}_evidence`.
JSON is generated in order, so the model committed to a verdict and then
wrote a justification for it — the evidence was decoration, not reasoning,
which quietly undercuts sec. 3. TrialGPT generates the rationale first and
classifies from it, reporting 87.8% explanation accuracy. Reordered to
evidence → status → confidence, and the prompt now says so explicitly.
Also added an anti-verbosity instruction, since the 2026 LLM-as-judge
literature reports length inflating perceived quality and both `evidence`
and `confidence` here are model-generated.

## 2026-09-01 — Two honesty repairs found by re-reading what the UI claims

**1. A deterministic verdict resting on an inferred input must disclose it.**
`score_approach_category` rules out up to 63% of a condition's trials and
its evidence said the categories were "read from the registry's own
intervention types, not inferred." Half true: the *trial's* types are
registry fact, but the *researcher's* (`approach_types`) come from a model
reading their prose. A wrong or under-listed mapping silently removes
trials while the evidence claims registry certainty. The evidence now names
both sides and says which is which, `source_value` carries both, and the
mapping is surfaced in the page's "how your interest was read" panel with
an explicit warning that trials outside those types are dropped — because
that panel is the only place a bad mapping could ever be caught.

**2. The page was inferring a cause it had not checked.** An `unknown`
signal has two very different causes — "you didn't say" (fixable in a
sentence) and "the record doesn't carry it" (64% of trials have no phase;
no answer helps) — and they rendered identically. The API already knows
which is which: `unspecified[].signals_unscored` names exactly the signals
a researcher's answer would recover, so no schema change was needed.

But the first attempt wrote *"unscored because the trial's record doesn't
carry it"* for the non-elicitable case, which is an assertion about the
record the page never inspected — the model may return `unknown` for other
reasons entirely. Corrected to state only what is actually known:
*"answering below would recover it"* versus *"nothing you could add would
change it"*. The signal's own evidence line, directly below, carries the
real reason. Inventing a cause to sound more helpful is the same failure
as inventing a study fact (sec. 2), one level down.

## 2026-09-01 — Credits exhausted mid-batch; what was learned before they ran out

The Anthropic account ran out of usage credits during the batched paid run.
Paid verification stops here. Two of the five questions were answered first.

**1. Bug #10 is fixed, verified on real output.** `approach_match` went from
`unknown` 20/20 to **`match` 5/5 at high confidence**, with specific and
correct evidence — inavolisib named as a PI3Kalpha inhibitor, durvalumab as
anti-PD-L1, Dato-DXd and HER3-DXd as antibody-drug conjugates. The parse
mapped "immunotherapy or targeted agents" to
`DRUG, BIOLOGICAL, COMBINATION_PRODUCT, GENETIC` — generous, as the prompt
asks, so it will not wrongly rule trials out.

**2. The $0.006-per-call figure was wrong, and every projection built on it
was wrong.** Measured on the canary: **$0.1142 for 6 calls ≈ $0.019/call**,
~$0.015 marginal once the prompt cache is warm. The old number came from
this repo's own notes, measured against **synthetic fixtures**; real trial
records carry up to 2,500 characters of eligibility criteria and cost far
more. Corrected figures:

| | claimed | measured |
|---|---|---|
| 20-trial search | $0.13 | **~$0.32** |
| monthly re-ranking (271 trials) | $1.62 | **~$4.07** |

That makes the Haiku 4.5 comparison (5× cheaper) the decisive open question
for whether this feature is affordable at all — and it is now blocked.

**Caught before spending, by reading the API reference rather than
assuming:** `output_config.effort` is an Opus-tier parameter and is
**rejected on Haiku 4.5**. Every call in the Haiku comparison would have
failed. `_structured_call` now sends `effort` only to models that accept it
(`supports_effort`), and the cache key reflects its absence.

**Graceful failure, found the hard way.** `parse_researcher_interest` runs
before the per-trial loop and outside its `try`, so an unusable key escaped
as a raw 500 and a stack trace. Two fixes, both free and tested:
  - an `anthropic.APIError` from the parse now returns **503** saying nothing
    was scored and that the tracked data and Monitor feed are unaffected;
  - **every trial failing is an outage, not a ranking with no results** —
    it returns 503 rather than a 200 with an empty list, which would render
    as "no trials matched" and is a false statement about the data (sec. 2).

**The demo survives.** 71 cached responses; the canary request replays at
**$0.0000** with no credits at all, returning five real trials with real
scores. Ranking remains demonstrable — for that exact interest, condition
and limit — with an empty account. `.ranking_cache/` is gitignored, so it
does not travel with a clone; guard it.

**Still unanswered, blocked on credits:** Haiku vs Opus quality; the
prior-treatment case against real criteria text; whether effort=high changes
ordering; and the researcher-judgment protocol in
`docs/verify_ranking_results.md`, which needs ~$0.32 of fresh ranking (or can
run against the 5 cached trials for $0).

## 2026-09-01 — Step 7's two working docs deleted; what they held

`docs/STEP7_SESSION_SUMMARY.md` (361 lines) and
`docs/step7_implementation_guide.md` (237 lines) removed as redundant.
Both were working documents for a layer that is being removed, and both
were checked for unique content first rather than assumed redundant.

The implementation guide already carried a STALE banner naming six of its
own claims as wrong, and stated it was "retained for the research findings
near the bottom, in particular precision/recall around 0.32-0.45." That
figure is the one the 2026-08-31 TrialGPT entry above **corrects** —
NDCG@10 0.7275, P@10 0.6724 — so the doc's only stated reason to exist was
itself the error. Its other content (unit checklists, a files-created list
naming two files already deleted, six generic workflow findings) is either
superseded by the code or by that entry.

The session summary's substance — the eight bugs, the budget and cache
mechanics, the gitignored files that don't travel with a clone, the
`sites_active` and confidence-threshold questions — is all recorded above
and in CLAUDE.md. **Two of its four open questions were not, and are
recorded here now so deleting the file doesn't erase them:**

1. **The ranking tie.** When a researcher stated no preference, a
   recruiting and a completed trial could score identically. Options were
   (a) leave tied, (b) weak defaults, (c) a disclosed tiebreak. Partly
   answered 2026-08-31 — recency became the disclosed tiebreak — and
   **moot from here, because the score is being removed.**
2. **The paid prior-treatment eval case.** Designed against the real
   criteria text of the 3,407 trials carrying prior-therapy language,
   never built. **Moot: the `prior_treatment_compatible` signal is being
   cut** — it carried 15% of the weight while being relevant to 28% of
   breast cancer trials and 1% of obesity trials.

Both are recorded as closed, not as outstanding work.

## 2026-09-01 — The ranking layer removed; what the removal plan got wrong

Executed the deletion `docs/plan_after_ranking.md` specified. Ten files
gone: `api/ranking.py`, `api/ranking_schemas.py`,
`frontend/pages/4_Ranking.py`, five ranking test modules,
`scripts/rank_dry_run.py`, `scripts/cache_coverage.py`. The router is out
of `api/main.py` and `/rank` no longer exists on the app. 75 free tests
pass. The reasoning for removing it is in `f9ccb45` and the entries above
and is unchanged; this entry is only about executing it.

**A removal plan's file list is not the same as the dependency graph.**
The plan named exactly one test that had to be deleted with the removal.
Three more breakages were only visible by reading the survivors' imports:

1. `api/ranking_deterministic.py` — a keeper — imported `FitSignal` from
   `api/ranking_schemas.py`, a deletion. The model moved into the keeper.
2. `tests/test_ranking_real_data.py` — the other keeper — imported
   `SIGNAL_WEIGHTS` and `score_signals` from `api/ranking.py`. The weights
   were only ever passed through to scorers that don't combine them, so
   they became one named constant; the two tests that genuinely tested
   *combining* signals into a score were deleted, because nothing combines
   them any more.
3. `scripts/paid_preflight.py` — a keeper — excluded a paid harness that no
   longer exists and carried `COST_PER_CALL = 0.006`, the synthetic-fixture
   figure this file already corrects to ~$0.019. Both fixed. Its pending-
   questions list is now correctly empty: nothing in TrialLens calls a
   model.

The generalisable version: **grep for what the deleted files export, not
just for their module names.** A module name search finds `import
api.ranking`; it does not find `SIGNAL_WEIGHTS`, and that is the reference
that breaks a keeper.

**Deleting a test that guards a vocabulary needs a replacement, not just a
deletion.** The one test the plan did name —
`test_every_type_the_parse_may_emit_is_a_real_ctgov_value` — was the only
thing holding `INTERVENTION_TYPES` to anything at all. It compared that
list to a hand-written enum in the prompt schema: two hand-written lists
agreeing with each other, neither checked against the data. Its
replacement, `test_every_intervention_type_in_the_database_is_known`, asks
the live database instead and passes against all 11,469 active trials.
That is a strictly better guard than the one removed, and it exists only
because the deletion prompted the question "what was this actually
protecting?" — worth asking of every test a removal takes with it.

**Home lost the Ranking card entirely rather than reverting to
`"planned"`,** which is what the plan said to do. "Planned" would be a
false statement about the roadmap: the capability is not deferred, it is
rejected with the reasons recorded. A card saying "not built yet" invites
someone to build it.

`api/ranking_deterministic.py` now has no importer in the running app. Its
docstring says so explicitly, and says what it is waiting for (filter
predicates, `plan_after_ranking.md` item 4) and that it should be deleted
rather than left sitting if that work is dropped. `.ranking_cache/`, the
71 recorded responses, is untouched.

## 2026-09-02 — Where a model earns its place, decided by querying first

The plan after removing the ranking layer was to add one AI call: a "change
interpreter" turning an amendment into `{category, why_it_matters,
evidence[]}`. Before writing the prompt, the change-sets were queried —
§6 applies to a prompt as much as to SQL, which is the lesson step 7 paid
for. Four findings, and they moved the design more than the plan did.

**1. Most amendments are not interpretable, and shouldn't be sent.**
Of 212 amendments: 99 (47%) changed nothing TrialLens stores; 38 moved a
single structured field; 29 are multi-field combinations; 46 changed prose.
Only the last two categories — 75 of 212 — contain anything a model could
add to. Sending the other 137 would pay for invention or for arithmetic.

**2. The category half is a lookup, not a judgement.** The plan assumed a
model would sort changes into administrative / operational / scientific.
There are 14 distinct content fields in the data and every one maps
statically. A model asked for that verdict is step 7's error repeated: a
filter wearing a score's costume. It is now `FIELD_ASPECTS` in
`api/amendments.py`, free and instant.

**3. One amendment carries 252,041 characters of `locations` JSON.**
Average is 3,475. A naive "send the change-set" would occasionally ship
~100k tokens for a list of hospitals, and the honest summary of that diff
is "5 sites added, 5 removed". Structured list fields are now summarised
deterministically and never reach a prompt or a diff view.

**4. Dates cannot be subtracted naively.** ~23% of trials report them to
the month only. A shift is reported in months or weeks whenever either side
is imprecise, and a sub-fortnight difference between two month-only dates
is not reported at all — it is an artefact of anchoring to the 1st, not
movement. Saying "slipped 361 days" about a date CT.gov gave as "2027-06"
would invent precision the registry never stated (§2).

**What was built, and what deliberately was not.** Everything arithmetic
can answer: date shifts, headcount deltas, ESTIMATED→ACTUAL, site
add/remove counts, and status transitions written over status *groups* so
an unobserved transition still resolves correctly. `describe_effect`
returns `None` for every prose field, permanently, and a test fails if that
changes — "+3/−14 words" is arithmetic, "the trial narrowed its population"
is a reading of clinical text.

**Why this order matters more than the feature.** Shipping the
deterministic layer first creates a control. "Does a model's prose add
anything over this?" is now answerable, where step 7's equivalent question
never was — `docs/verify_ranking_results.md` was written and never run
partly because there was nothing to compare against. The AI call remains
unbuilt, and is now a smaller, better-scoped question than the one the plan
started with.

**Rejected: running it on a local model.** The machine is an 8 GB M1 Air,
which realistically runs a 3-4B model once macOS and the dev stack have
taken their share. The task is interpreting clinical prose diffs where
inventing a fact is the cardinal sin, and a 3B model is the worst available
tool for it — fluent, confident, and wrong is the exact failure §2 exists to
prevent. Cheap hosted non-Claude options (Gemini Flash, Groq) remain open
and would work on public registry data with no PHI concern.

**Two honesty bugs fixed in passing.** `GET /studies/{id}/changes` returned
200 with an empty list for an nct_id never seen — "no changes recorded" for
a trial that does not exist, which reads as "this trial has been quiet". It
had done so since it was written. And `is_formatting_only()`'s docstring
claimed four clinical cases "were checked"; nothing checked them. Both now
hold.

## 2026-09-02 — Why an amendment was invisible: we were not looking at the field

"Why can't we see one of the amendments?" turned out to have a better
answer than "CT.gov changed something we don't store."

The diff compares **21 normalized columns**. The raw record carries 11
protocol modules plus two top-level keys, and the most consequential thing
in it was never read: **`hasResults`**. It sits at the TOP level of the API
response, not inside `protocolSection`, so a parser that walked every
module one level down never saw it.

**1,056 of 11,518 stored trials already have results posted** — 751 of them
completed. A trial going `false -> true` means its findings are published,
which is the single most consequential amendment a researcher following a
therapeutic area can receive, and every one of those had been rendering as
"amended, but we can't see what."

Now stored, diffed, classified Scientific, and described in words
("results have been posted — the trial's findings are now published").

**The backfill needed no network call, and that is the point.** §4 says to
keep the raw record alongside the normalized one. This is the first time
that decision paid: `has_results` was recovered for all 11,518 trials
straight out of stored `raw_json`. A field nobody thought to normalize in
August was recoverable in September for free. Without raw_json it would
have meant refetching 11,518 records from a public API at ~50 req/min.

**Backfilled values are deliberately NOT written to `study_changes`.**
Doing so would log 1,056 "results were posted" amendments dated today for
trials that published months or years ago — a false claim about when
something happened (§2). The backfill sets the baseline; only transitions
the real diff detects from here are amendments.

**What is still unread, in descending order of likely value:**
`referencesModule` (4,443 trials — a new publication attached to a trial is
real news), `oversightModule` (11,361), central contacts (5,044), and
`derivedSection`. The remaining "invisible" amendments are mostly these.
A cheaper general fix exists and is not built: at diff time we hold both
the old and the new `raw_json` for the ~91 trials a run refetches, so
naming *which modules* changed would cost one extra column in a query
already running, and would convert most of the remaining invisible
amendments into "the sponsor changed the references section."

The generalisable lesson, and it is the same one as 2026-08-31: **the shape
of the real payload is not the shape the code assumes.** That time it was
values inside a field (`PHASE2`, not "Phase 2"). This time it was a field
one level up from where every other field lived.

## 2026-09-02 — The invisible amendment was over-weighted, and its copy guessed

Caught by reading the rendered page rather than the code. An amendment
TrialLens cannot see was getting a heading, a caption, a three-sentence
`st.info` box and a divider — **more visual weight than the amendment above
it carrying four real field changes.** That inverts the hierarchy of a page
whose entire purpose is what actually moved. Now one caption line.

Worse, the copy said the untouched fields were "contacts, oversight and
sponsor administrative details among them." **We do not know that.** The
system knows only that `last_update_post_date` moved and no stored field
did; which fields CT.gov actually touched is exactly what it cannot see.
Naming three of them reads as a finding and is a guess.

This is the *same* error as the 2026-09-01 entry above ("The page was
inferring a cause it had not checked"), committed by the same reasoning:
the honest line felt too thin, so plausible detail got added to make it
useful. It is worth naming the pattern, because it has now happened twice
in two days and both times it looked like helpfulness — **when a true
statement feels unsatisfying, the fix is a better true statement or
silence, never a plausible one.**

Corrected to: "amended, but only in fields TrialLens doesn't store. The
record changed; we can't show what." Every clause is checkable.

Also: the divider now renders only BETWEEN amendments. A rule after the
last one closes a section that has already ended and reads as something
missing below it.

## 2026-09-02 — The watch leads the page, and "last checked" is a proxy that says so

Step 7b direction 2, built from `design/Main.dc.html`. What `Home.py` had
was a capability grid: five cards explaining what the app can do. That is a
brochure. The thing TrialLens has that a fresh clone of this repo does not
is **elapsed time** — 11,427 trials watched since 28 August, every
amendment since recorded — so the page now leads with the watch and the
grid sits below it.

`GET /watch` is one endpoint rather than five reads, because the numbers
only mean anything together: "watching 11,427 trials" is a different claim
depending on whether the last check was 2 hours or 3 days ago.

**The screen has three states and the least eventful one mattered most.**
29 and 30 August had zero amendments across all 11,427 trials — real
recorded data — and that rendered as an empty table, which reads as a
broken app rather than a working watch. The quiet week is the screen a
researcher sees most often, so it is stated as a finding, and the empty
days are drawn as zeros rather than omitted: a zero is evidence the watch
ran and found nothing, which is the opposite of missing data. The day strip
is therefore built from `generate_series`, not `GROUP BY` — grouping alone
has no rows for a quiet day and would silently delete the only proof it was
watched.

**The alarm replaces the page rather than sitting above it.** A stale feed
under a small warning still reads as current, and that is the failure being
designed out. Nothing but a test will ever catch a regression here — the
alarm only appears after 12 hours of a dead cron, which is exactly when
nobody is looking — so `tests/test_home_watch_page.py` renders all three
states through Streamlit's `AppTest` and asserts the feed, the day strip
and the last-amendment card are *absent* when the watch is stopped.

### The proxy, and why it is not `detected_at`

Direction 2's headline fact — "last checked 2 hours ago" — is a
`monitor_runs` fact, and `monitor_runs` is direction 3, not built. The
build order was kept anyway, with an explicitly labelled proxy:
`max(studies.last_matched_at)`, which POST /studies/reconcile-scope stamps
on every in-scope trial at the end of every run.

The obvious alternative, `max(study_changes.detected_at)`, is **wrong in
exactly the case this screen exists for**: on a quiet week nothing is
detected, so it would report "last checked 2 days ago" and fire the alarm
on the primary screen. A proxy that fails on the common case is not a
proxy.

What the proxy cannot do is count runs, which is why the record footer
shows "Last check" and not the artboard's "Checks run: 21", and why the
page says in its own words that the figure is *inferred from when trials
were last confirmed in scope, not from a record of scheduled runs*. The
load-bearing assumption — that `last_matched_at` is never behind the newest
change it should explain — is asserted against the live database, because
if ingest ever stops calling reconcile-scope the watch reports itself
healthy while dead, with no error anywhere.

### Building direction 3 first was considered and rejected

`monitor_runs` starts empty, and the next cron was six hours out. A fresh
run table means "no check has ever been recorded", which is the alarm —
so building the record first would have shipped a screen that screams the
watch has stopped while it is demonstrably running. Backfilling it from the
8 distinct `last_matched_at` timestamps was rejected too: those are the
last run each trial was matched in, not the 21 runs that happened, and
presenting 8 of them as the run history would be inventing a record.

### Counted by what it means, not by how many rows moved

The news-week headline says "one trial published its results, three others
changed something scientific, out of 63 amendments" — not "63 amendments".
A row count is precisely what the removed ranking layer was good at and
useless for. `WatchRecent` therefore carries both: the finding for the
headline, the total for the honesty. `results_posted` is a *subset* of
`scientific` (has_results is a scientific field), so the UI subtracts; a
test on the live database asserts `results_posted ≤ scientific ≤
amendments`, because if that containment broke the page would state a
negative number of trials as fact.

The amendment, not the changed row, is the unit. An amendment that moved
four dates is one thing that happened, and counting its rows would announce
it as four.

### Aspect markers: dots, on both screens

`🔬 ⚙️ 📝` became coloured dots, in `labels.py` so Home and Understand
cannot disagree about what "Scientific" looks like. The emoji carried
meanings that fought the label — a microscope is not what "Scientific"
means here; the whole trial is science — and rendered at different sizes
per platform. The colours are a hierarchy rather than a palette: Scientific
is the only one with any hue, because it is the only group whose change can
change what the trial *means*. Uncategorised is a hollow dot — it is the
absence of a classification, and a filled dot would look like one.

### The artboards claimed "every number is real". Four were not.

Building the screen is what checked them, and the corrections are recorded
in `design/README.md`: 751 → 747 and 1,056 → 1,050 (drifted overnight), the
alarm's "13 checks missed" → 12 (76 elapsed hours over 6-hour slots is 12;
the figure was written by hand), and NewsWeek's "3 changed something
scientific, 59 other" → 14 and 49 (estimated before anyone queried it).

**The worst one was not a number.** NewsWeek's lead card shows a trial
publishing its results — `has_results` false → true — and **no such
transition has ever been recorded.** The column was added and backfilled on
2026-09-02, and backfilled values are deliberately not written to
`study_changes` (see the entry above: doing so would log 1,056 "results
posted" amendments dated today for trials that published months ago).
NCT05599334 is a real watched trial that really does have results; what has
not happened is TrialLens *watching* them appear. The card is now labelled
on the artboard as a designed treatment for an unobserved state.

That is the third instance in two days of the pattern this file already
named twice — **when a true statement feels unsatisfying, the fix is a
better true statement or silence, never a plausible one.** The first two
were in page copy. This one was in a design file, which is worse in one
specific way: **a drawn number has no test.** Copy that guesses gets caught
by reading the rendered page; a figure inside an artboard is only ever
checked if someone re-queries it on purpose.

No number on the built page is hardcoded, which is the durable version of
that claim — and the reason to build a designed screen rather than maintain
a drawn one.

## 2026-09-02 — Step 7b direction 3: the watch record, un-deferred by backfilling

`monitor_runs` now exists and `/watch` reads `last_checked_at` from the
newest completed run. `scripts/run_monitor.py` opens a row at the start of a
run and closes it `completed` at the end, carrying trials checked and changes
detected. `WatchStatus.last_checked_source` is deleted: it existed to label a
proxy as a proxy, and there is no proxy left to label.

**What actually unblocked this.** Direction 3 was deferred to step 10 on the
reasoning that a new `monitor_runs` starts empty, an empty run table reads as
"no check has ever run", and that fires the alarm on a watch that is fine —
so the proxy had to survive until the table filled on its own. That reasoning
was sound and its conclusion was still wrong. The proxy it replaces,
`max(studies.last_matched_at)`, is not merely correlated with a run having
happened: POST /studies/reconcile-scope stamps it on every in-scope trial at
the end of every run, so it *is* a real completion time for a real run. That
makes it backfillable. `scripts/backfill_monitor_runs.py` writes exactly one
row from it, the cron takes over from the next run, and the alarm never fires
falsely. The blocker was a gap of one row, not a gap of two weeks.

`changes_detected` on that seeded row is NULL rather than 0. Nothing on file
records how many changes that particular run found, and 0 would be a claim
that it found none — inventing a fact about a run to avoid a null (sec. 2).

**The test that has to survive this.** The real-data suite previously asserted
that `max(last_matched_at)` was not behind `max(study_changes.detected_at)`,
because if ingest ever stopped calling reconcile-scope after the diff, `/watch`
would report a dead watch as healthy with no error anywhere. The same silent
failure exists in the new shape — run_monitor.py could record changes and then
never close its run row — so the test was rewritten against `monitor_runs`
rather than deleted. A guard that moves when the mechanism moves is the point;
deleting it because its subject was replaced would have retired the invariant
along with the implementation.

Verified live before claiming done: `/watch` over HTTP against the real
database returns healthy, 4.95 hours since check, reading run #1. 278 tests
pass, including the 12 that need the live database.

## 2026-09-02 — Record the writer's own count, not a timestamp window

`monitor_runs.changes_detected` was first written by re-deriving it after the
run: `count(*) FROM study_changes WHERE detected_at >= started_at`. That is
close to right and quietly not true — the window also catches rows written by
anything else active at the same time (a manual ingest, a backfill) and files
them under this run's id. A number that is usually correct, in a column
nothing reads yet, is the easiest kind of wrong to ship.

**The exact number already existed and was being discarded.** `sync_group`
sums what POST /studies/batch reports as it writes, printed it to the log,
and returned a bare `set` of nct_ids. It and `run_ingest` now return an
`IngestResult(nct_ids, changes)` named tuple and `run_monitor.py` sums that;
`count_changes_detected`, its query, and the second database connection it
opened are deleted. The general form: before deriving a value, check whether
something upstream already knows it exactly. Re-derivation is how an
approximation gets into a table that is later displayed as fact (sec. 3).

**Urgency came from the column being unread, not despite it.** Nothing
displays `changes_detected` yet, so the instinct was to defer. Backwards:
every cron run writes another approximate row, and once a screen shows the
number the wrong history is already on file and cannot be recomputed — the
evidence of what each past run found is gone. Cheap now, impossible later.

**Documented rather than changed:** nothing marks a run `'failed'`. A run
that dies leaves its row `'running'`, `/watch` keeps reading the last
completed run, and the gap grows until the alarm fires — the honest outcome
for a run that did not finish, so the comment now says so to stop a later
reader "fixing" it.

`tests/test_ingest_counts.py` is the first test to touch `scripts/ingest.py`;
the module had zero coverage, so the suite went green on this refactor while
proving nothing about it. Five tests, no network or database. Proven able to
fail before being trusted (sec. 7): dropping the trailing batch flush, `=`
for `+=`, and returning studies counted instead of changes each turn it red.
283 tests pass.

## 2026-09-02 — Step 8 unit 1: the Explore graph is tables, not a graph database

**No Neo4j.** The graph already exists — `studies.lead_sponsor` holding
"Mayo Clinic" on 134 rows *is* 134 edges, just written in a shape that is
awkward to walk. Step 8 makes it walkable; it does not create it.

A native graph database earns its keep through index-free adjacency, which
pays off when traversals are deep and the graph is large. Measured shape
here: 11,518 trials, 3,173 sponsors, largest sponsor 163 trials, and the
questions Explore answers ("who else works in this space?") are 2-3 hops.
Postgres joins over 11k rows are not the bottleneck at any of those numbers.
The conditions that would reverse this, recorded so the decision can be
re-opened honestly: row counts in the millions, materially denser linkage,
or traversals that are deep and open-ended rather than 2-3 hops.

The operational half is decisive on its own. A second database is a second
sync path and a second thing that can be stale, and sec. 5 says FastAPI is
the only door to the database. Two stores means two doors, or a door behind
a door.

**Controlled vs. free text is a property of a FIELD, not an entity.** The
useful test for whether an entity's identity can be defined upfront is
whether CT.gov enforces a controlled value or accepts free-typed text — and
almost every entity here is half of each. Measured 2026-09-02:

| Field | Distinct | Collapsed on case/space | Verdict |
|---|---|---|---|
| `lead_sponsor` | 3,173 | 3,173 | controlled, zero duplicates |
| location `country` | 123 | 123 | controlled |
| intervention `type` | 11 | — | controlled enum |
| investigator `role` | 3 | — | controlled enum |
| location `facility` | 42,842 | 41,710 | free text — 1,132 differ only by case |
| intervention `name` | 13,307 | — | free text — 11,598 used exactly once |
| investigator `name` | 7,332 | 7,275 | free text |

Madrid alone carries 381 distinct facility strings, New York 322. A city does
not have 381 trial sites; those are the same institutions typed differently.
So sponsors and countries get identity upfront, while facility, intervention
and investigator identity has to emerge from the real values.

**The intervention merge rule.** Merge only when the difference is *naming*;
never when it is *substance* — dose, route, formulation, or role in the
trial. The data forces this: 55 distinct intervention names begin with
"semaglutide" (dose and route arms of the same trials, where the difference
IS the study), and 159 begin with "placebo" — merging those would build the
densest node in the graph out of a thing that is by definition nothing, and
route every multi-hop query through it. Merging never overwrites: both source
strings stay, linked to the shared node, with the link recorded as inferred
rather than reported (sec. 3). A merge that destroys the source text is the
Procrustean cut — the problem is not the inference, it is that the evidence
is gone and a researcher cannot disagree with it.

## 2026-09-03 — Step 8 unit 2: extraction, and the edges a trial takes back

The extraction ran against the live `dev` branch: 6,207 organizations,
51,272 sites, 7,717 investigators, 14,468 intervention terms, and 191,864
edges, all from records already on file. No CT.gov call — investigators and
collaborators had been sitting unread in `raw_json` since ingestion, the
third time §4's keep-the-raw-record rule has paid for itself.

Nothing is merged, on purpose. 381 Madrid facility strings are 381 sites and
68 semaglutide names are 68 terms. That unmerged extraction is the baseline
any later merge gets checked against.

**Reconciliation, and what it caught.** Counting source distinct values
against graph rows was not a formality — it failed twice, each time for a
different real reason.

The first failure was staleness: the extraction ran, then a monitor run
ingested 70 trials, and every entity was short. That is the snapshot gap
`test_the_graph_is_not_behind_the_studies_it_describes` exists to name, and
it went red on real drift with the right message before anyone mutated
anything. Re-running the backfill closed it.

The second failure was the interesting one, and it pointed the other way:
the graph had **more** rows than the source. 7 sites and 15 `trial_sites`
edges traced to no current record. The extraction is insert-only, so when a
trial drops a site the edge outlives the record that justified it — Explore
would have gone on saying a trial runs at a location it had removed. One
6-hour run produced 15 of those.

**Decision: stamp `delisted_at`, never delete.** Deleting fixes the false
claim and destroys the finding. This is a watch-over-time product; "this
trial quietly dropped three sites" is a result, not a row to tidy away, and
§3 wants the evidence kept rather than silently reconciled. NULL means the
connection is in the current record; a timestamp is the first run that could
not find it. It is deliberately *not* the date the trial made the change —
nothing on file says that, and writing the real amendment date there would
invent precision the backfill does not have (§2).

Consequences worth recording:

- Edge inserts became `ON CONFLICT DO UPDATE SET delisted_at = NULL`, so a
  re-listed site comes back. The action carries its own `WHERE
  delisted_at IS NOT NULL`; without it every pass would dirty all 140,000
  edges writing NULL over NULL.
- The withdrawal UPDATEs are guarded by `delisted_at IS NULL`, so an edge
  keeps the date it was *first* seen missing. Re-running does not walk the
  stamp forward and destroy the only timing information it has.
- `test_no_site_was_invented` had to be scoped to sites holding a live edge.
  Unscoped it called those 7 dropped sites inventions, which is the wrong
  word: they were reported once and later withdrawn, and that distinction is
  the whole point.

**The tests were proven able to fail.** Seven mutations — inventing a site
with a live edge, un-withdrawing a dropped one, deleting a LEAD edge,
deleting an investigator edge, future-dating a withdrawal, stripping a
trial's edges, collapsing semaglutide to one term — each injected inside a
transaction and rolled back, never committed. 7/7 turned the matching
assertion red. Table counts were identical before and after.

## 2026-09-03 — Two monitor bugs that could only exist on the schedule

Both found by dispatching the workflow after fixing the upsert template,
rather than waiting for the next 6-hour tick. Neither was reachable locally.

**`KeyError: 'DATABASE_URL'`.** `run_monitor.py` opens its own connection to
write the `monitor_runs` record and to store prose interpretations, but the
workflow's "Run the Monitor job" step passed only `API_BASE_URL`. Locally
this is invisible because `load_dotenv` reads `.env.local`; in the job the
environment is the only source. So the watch record added on 2026-09-02 had
never once been written by a real run — `monitor_runs` held nothing but the
backfilled seed row, and every "successful" cron since recorded nothing.

**`UPDATE ... ORDER BY ... LIMIT` is MySQL.** Postgres rejects it outright
("syntax error at or near ORDER"), and `run_prose_interpretation`'s except
clause swallowed it into a printed one-liner. `study_changes.prose_
interpretation` had **zero rows**: step 7c's $0.168 bought interpretations
that were computed and then dropped. Verified with `EXPLAIN`, which parses
without executing.

The write now goes by primary key, so `get_prose_amendments` carries `id`.
Matching on `(nct_id, field_name)` and taking the newest was independently
wrong: a trial that amends the same prose field twice inside one window has
two rows, and the older interpretation would land on the newer one —
attaching an inference to source text it was not drawn from (§3).

**Still open: there is no `ANTHROPIC_API_KEY` secret on the repo.** Only
`DATABASE_URL` and `DATABASE_URL_READONLY` exist, so step 7c cannot run on
the schedule at all; it degrades through its except clause and the rest of
the run proceeds. Step 7c has therefore never run unattended, and the
claims elsewhere in the docs that it runs in the scheduled job describe the
intent, not the behaviour. Adding the secret is the only thing that turns it
on, and a key must never be written into a repo file (§2).

## 2026-09-03 — Site enrichment: the fields the parser dropped, and the evidence that asked for them

Prompted by a question that should have come earlier: *do researchers care
about collaborations?* The full evidence review is in
`docs/plan_explore_nodes.md`; the short version is that the collaborator
edge is the weakest node in the graph and sites are the strongest, so sites
got the work.

**Collaborator is weak by definition, not by accident.** CT.gov defines a
collaborator as any organization "providing support," where "support may
include **funding**, design, implementation, data analysis or reporting" —
one field for cheque-writers and co-designers, with no sub-field separating
them. The stored data matches: NCI 480, NIDDK 264, NIH 91, NHLBI 86.
Coverage is 37.4% and 63% of those trials have exactly one collaborator.
Registration guidance also states collaborators "should not include
individuals... not PIs", so the field cannot answer the people-shaped
reading of "who else works in this space" at all. Kept and extracted, but
demoted from a network to traverse to an attribute to filter on.

**Sites reach 93.8% and answer a documented question.** The oncology
literature describes the workflow as: search, find a candidate trial, then
*phone the site to ask whether it is still open*. A separate study of 8,893
cancer patients found 55.6% had no trial available at their treating
facility. Both are location questions, and both were answerable from data
already on disk.

**The `has_results` pattern, third recurrence.** `locations` had been
normalized down to facility/city/country and everything else discarded, so
across 142,777 stored locations these were sitting unread in `raw_json`:
geoPoint 140,285 (98.3%), zip 133,069, state 99,609, per-location status
41,027, contacts 25,197. Backfilled with no network call (§4). Result:
49,606 of 51,272 sites carry coordinates (96.8%), and 40,011 live edges
carry a recruitment status — RECRUITING 31,442, NOT_YET_RECRUITING 4,481,
ACTIVE_NOT_RECRUITING 2,044, SUSPENDED 903, WITHDRAWN 677, COMPLETED 385,
TERMINATED 69, ENROLLING_BY_INVITATION 10.

**Status is an edge property; place is a site property.** 2,616 site
identities report more than one status across the trials using them — of
course they do, a hospital recruiting for one trial and closed for another
is one place in two states. So `recruitment_status` lives on `trial_sites`,
for the same reason organization role lives on its edge. `state`, `zip`,
`lat`, `lon` describe the place and live on `sites`.

**Where the registry contradicts itself, store nothing.** 109 site
identities are reported at more than one geoPoint, and the disagreement is
real rather than rounding: 103 are 5km or further apart, the largest is 52
degrees — the same facility string placed on different continents — and
rounding to 4 decimal places removes none of them. zip disagrees on 3,344
identities, state on 484, and 172 (trial, site) pairs state two statuses at
once. All are left NULL and counted in the backfill's output, the same
"we can't tell" the tracking drop reasons use instead of a guess (§2). A
guessed coordinate on a "trials near me" map sends someone to the wrong
country.

**NULL means "not stated", never "not recruiting."** Only 28.6% of live
edges carry a status, because CT.gov mostly supplies it for actively
recruiting studies. Anything rendering this column has to preserve that
distinction or it repeats the step-4 under-reporting bug.

**Naming trap, recorded because it will bite.** One of CT.gov's per-site
status values is literally `WITHDRAWN`, and `trial_sites` also has our own
`delisted_at`. They are unrelated: `recruitment_status = 'WITHDRAWN'` means
the site withdrew from the trial before enrolling anyone; `delisted_at`
means the trial's record stopped listing that location at all. A site can be
live (`delisted_at IS NULL`) while reading `WITHDRAWN`.

**Proven able to fail.** Seven more mutations, injected in a transaction and
rolled back: filling a coordinate on a disputed site, swapping lat and lon
across every US site, putting a site off the planet, keeping a longitude
without its latitude, asserting RECRUITING where no record says so,
inventing a status value, and leaving the columns unpopulated. 7/7 red,
14/14 across both harnesses. The swap case is the one a range check misses —
most latitudes are also legal longitudes — and it moves US orientation from
100.0% to 0.0%.

**One test OOM-killed the backend before it worked.** The obvious form of
the coordinate check is a correlated `EXISTS` per site, which re-expands all
142,777 location objects for each of 51,272 sites; pytest died with exit 137
and no readable error. Rewritten as a CTE joined once, the whole file runs
in 15 seconds. Worth remembering: against `jsonb_array_elements`, a
correlated subquery is not a slow query, it is a dead one.

## 2026-09-03 — Follow-ups on unit 2b: the OOM had a survivor, and NULL got a guard

Three loose ends from the enrichment, closed rather than noted.

**The correlated-subquery problem was not a one-off.** After the coordinate
check was rewritten, `test_no_organization_was_invented` was still the
slowest test in the file at 9.32s against ~1.0s for its neighbours — the
same shape, matching on `col->>'name'` and re-expanding every collaborator
array once per organization. It survived only because 6,207 organizations is
small next to 51,272 sites; it would have degraded quietly as the graph grew.
Rewritten as a CTE the file went from 26.7s to 15.3s, and the assertion still
turns red when an organization is invented (verified, rolled back).

The precise rule, which "avoid correlated subqueries" gets wrong:
**correlating on `s.nct_id` is fine** — that hits the studies primary key and
expands one trial's array. **Correlating on a value dug out of the JSON is
what turns linear into quadratic**, because there is no index to reach for.
Every withdrawal UPDATE in the backfill correlates on nct_id and runs in
seconds; the two that correlated on facility/city/country and `col->>'name'`
were the pathological ones.

**NULL got a guard before it got a consumer.** `recruitment_status` is NULL
on 71.4% of live edges, and the tempting shortcut — `status == 'RECRUITING'`
for open, everything else closed — would report roughly 100,000 sites as
shut that the registry never described. `frontend/labels.py` now holds
`format_site_status()` and `site_status_is_stated()`, added while nothing
consumes the column yet, which is the cheapest moment to make the wrong
thing hard to write. Six free tests cover it, including one asserting that a
missing value never renders with any closed-sounding word; the shortcut
implementation turns it red.

`site_status_is_stated` rejects whitespace rather than using `bool()`, which
would call `"   "` a stated status.

**The UI consequences are now requirements, not discoveries.** Written into
`docs/plan_explore_nodes.md` §4b: 1,666 sites cannot be placed on a map and
the page must say so rather than silently shrinking the result set; status
filters must offer "not reported" as its own option; site status renders as
sentences, not colour, because grey would mean both "closed" and "unknown".

## 2026-09-03 — `withdrawn_at` renamed to `delisted_at`

The column created earlier the same day sat in `trial_sites` beside
`recruitment_status`, whose CT.gov vocabulary contains the literal value
`WITHDRAWN`. The two mean entirely different things: CT.gov's says the site
withdrew before enrolling anyone; ours said the trial's record stopped
listing that location at all. A row could legitimately be live
(`withdrawn_at IS NULL`) while reading `WITHDRAWN`.

A schema comment and a UI test were written to hold the distinction. Neither
is worth much against a word that means two things in one table, and the
cost of keeping it only grows: at the time of the rename exactly three files
read the column, and after the Explore endpoint and page exist it would be
many more, plus every future reader having to carry the ambiguity. Renamed
rather than documented.

**The migration is the part worth recording.** `schema.sql` is idempotent
and every column in it is `ADD COLUMN IF NOT EXISTS`, so simply renaming the
text of those four lines would have added a second, empty `delisted_at`
beside a populated `withdrawn_at` and quietly stranded 17 stamped edges. The
rename runs first, inside a guarded `DO $$` block that fires only when the
old column exists and the new one does not — a no-op on a fresh database and
on every subsequent run. Verified: 4 columns renamed, 0 leftovers, 17 stamps
before and 17 after, then applied a second time to confirm idempotence, then
the backfill re-run as a clean 0-change no-op.

The prose moved too — `DELISTINGS`, "delisted: sites", "140,022 live, 15
delisted". Leaving the output saying "withdrawn" would have preserved
exactly the collision the rename was for. The one place "withdrawn" survives
correctly is CT.gov's own vocabulary: `recruitment_status = 'WITHDRAWN'`,
the trial-status list in `scripts/ingest.py`, and the label
"Withdrawn before enrolling anyone".

315 tests pass and both mutation harnesses still catch 14/14, re-run after
the rename rather than assumed.

**The general rule:** check the source vocabulary before naming a column.
CT.gov already used the best word for a different fact.
