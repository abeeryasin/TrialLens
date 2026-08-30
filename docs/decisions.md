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
