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

