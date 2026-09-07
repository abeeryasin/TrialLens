# Decisions & Learning Log — TrialLens

Dated entries capturing real decisions and why — a decision happens, then it
gets written down before moving on, so it isn't lost when context resets.

**How to read this file.** One `##` heading per decision, dated. Entries are
cited by date from code comments, `CLAUDE.md` and `docs/gotchas.md`, so the
headings are stable. Each entry states what was decided, what it was chosen
over, the numbers it was decided on, and what verified it. The rules that came
out of the painful ones are collected in [`gotchas.md`](gotchas.md).

## 2026-08-25 — Domain considered and shelved: maternal-health / Three Delays

A Maternal Death Surveillance project on the WHO "Three Delays" framework. The
WHO GHO API works, but PDHS/MICS microdata is gated behind manual registration
and not redistributable, and an initial assumption that de-identified Pakistani
case narratives are public was checked and found wrong. Reframed to
literature-grounded proxies, then shelved when TrialLens matched a different
set of unpracticed skills more directly. Logged as a future project.

## 2026-08-25 — Domain chosen: TrialLens

Chose clinical-trial intelligence after auditing what was already demonstrated
versus what wasn't: knowledge graphs, autonomous scheduled operations,
multi-agent handoff, real read-only database enforcement. Verified against
CT.gov's public no-auth v2 API (live-tested, ~50 req/min) before committing.

## 2026-08-25 — Persona: clinical researcher, not a one-time patient search

A patient searching once wouldn't justify scheduled monitoring, change
detection, or a review queue — just a search box. A researcher tracking a
therapeutic area over time is what makes the autonomous shape necessary rather
than decorative.

## 2026-08-25 — Notification mechanism: Resend, not SendGrid

Checked both rather than assuming either was still free. SendGrid dropped its
permanent free tier in 2023 (60-day trial only). Resend has a real permanent
free tier: 100/day, 3,000/month, no expiration.

## 2026-08-26 — External product spec: adopted in part, corrected in part

A spec from another AI model contributed the five-capability framing,
"deterministic first, AI second, agents third", "potential fit" instead of
"patient eligibility", and evaluation cases from day one — all adopted.

Pushed back on three things. Its FastAPI layer was speculative "for later"
with no consumer — resolved by making FastAPI load-bearing from day one
instead. Its "vector store" risked building document-retrieval infrastructure
this project doesn't need — sequenced for once a real trial cache exists. And
its claim that "CT.gov itself maintains record versions" was checked rather
than accepted, since it justified the whole monitoring feature (true — a
separate archive site plus a per-trial RSS feed).

Its own later section warned against building everything at once, immediately
after many earlier sections describing exactly that. **Read a big AI-generated
proposal's later caveats against its earlier scope before adopting either.**

## 2026-08-26 — Database: Neon Postgres, chosen and verified (retroactively logged)

Chosen earlier but never logged — caught in a documentation audit. Verified
rather than assumed: a real permanent free tier (0.5 GB storage, 100 compute
hours/month, commercial use allowed), real Postgres, instant branching. Schema
work on a `dev` branch, `production` untouched until trusted. (What actually
happened to that plan: 2026-08-29 and 2026-09-05.)

## 2026-08-26 — Discover vs. Monitor: an untracked topic falls through to a live lookup

A plain read of our own database for a never-fetched area comes back empty,
which looks identical to "no trials exist" — actively wrong, not just
incomplete. So an ad-hoc question about an unstored topic falls through to a
one-time live CT.gov call, while *deciding to track* an area is its own
explicit action registering it with the scheduled job. Without the split, a
live search and a monitored topic collapse into the same broken thing.

## 2026-08-26 — Ingestion scope: filter by trial status, not just condition name

Checked real counts before assuming feasibility. "diabetes" alone matches
**24,289 studies** across registry history — ~410 MB for one topic; three such
topics exceed the entire 0.5 GB free tier. Filtering to active statuses cuts it
~10x (**1,958**). 10-12 areas filtered to active trials fit; full historical
registries do not.

## 2026-08-26 — Ingestion pipeline built and verified with real data

Ran for real against two topics chosen from verified current research interest
(IQVIA 2026 data): breast cancer (6,545) and obesity (4,912) — **11,415 unique
studies, 32,417 condition tags**.

Caught a real bug before trusting v1: it wrapped the whole run in one
transaction, committing nothing until the end — progress invisible from
outside and all-or-nothing on failure. Found by querying `pg_stat_activity`
directly rather than assuming a long runtime meant "fine" or "broken". Fixed to
commit per 200-row batch. Verified the shared-trial case is not hypothetical:
`NCT03284346` matched both searches and upserted correctly.

## 2026-08-26 — Future literature integration: logged, not built

Pulling supporting literature for a trial via a separate document-Q&A
capability is a genuine, non-forced idea — trials and literature about the same
interventions really are connected. Deferred: the core capabilities don't need
it, and a cross-tool integration adds real complexity before this project
stands on its own. (Revisited with the technical detail it lacked: 2026-09-08.)

## 2026-08-27 — FastAPI built as the real only door to the database

`ingest.py` was refactored to call `POST /studies/batch` over HTTP instead of
writing Postgres directly — that is what made "only door" real today rather
than an intention for later; the script no longer holds a database credential
at all, only `API_BASE_URL`.

Read-only is enforced at the database layer, not just the app layer: a
`trial_lens_reader` role has `SELECT`-only grants and every `GET` connects as
it. Verified, not assumed: a direct `UPDATE` through that role was rejected by
Postgres itself while a `SELECT` returned normally. **An app-layer check
wouldn't survive a bug in the app code; a missing grant can't be bypassed.**

## 2026-08-28 — Monitor: real cheap-filter/expensive-diff, a changelog table, and a no-delete guardrail

Verified live first that CT.gov v2 supports `fields=` (ID + last-updated for a
whole search) and `filter.ids=`. Each run now fetches ID + date for everything
matching a tracked condition, pulls full records only for what moved, and
diffs those field-by-field into `study_changes` **before** overwriting — the
bare `UPSERT` would have discarded the previous value with no record, which
defeats the entire point of Monitor.

**The scheduler never issues a `DELETE`, full stop.** This project already has
an incident where a cleanup removed rows it shouldn't have (2026-08-27), and
CT.gov itself never deletes a record either. A trial that stops matching gets
flagged (`active_in_scope = false`) via `POST /studies/reconcile-scope`, which
**refuses to run against an empty ID set** — an upstream fetch failure
returning zero results would otherwise flag every tracked study as dropped in
one shot, exactly the silent mass-change an unattended job must not be able to
do.

Scheduling is `monitor.yml` on a 6-hour cron, starting FastAPI fresh inside the
job rather than calling a deployed instance — keeping "only door" true without
requiring deployment first. GitHub's own failure email is the escalation path,
so no custom notifier duplicates the planned digest.

Tested: ran ingest twice back-to-back — the second run's cheap filter found 0
of 56 changed and made zero full fetches. Corrupted one row's date and
enrollment to simulate drift and confirmed the diff caught exactly those two
fields. Fixed a real bug in the same pass: the drop query's `ILIKE` matched the
condition exactly instead of as a substring, so it silently matched nothing.

## 2026-08-27 — Found and fixed: client-side connection pooling against Neon's pooled endpoint

`api/database.py` v1 held a long-lived `psycopg2` pool. A write succeeded at
startup, then one ~20s later failed with `server closed the connection
unexpectedly`. `DATABASE_URL` points at Neon's `-pooler` endpoint, already a
PgBouncer pool that drops idle client-held connections, and `psycopg2` only
discovers this on the next query. Fixed by connecting fresh per request:
**Neon's own pooler is the pool.**

## 2026-08-27 — Caught and corrected: an overly broad test cleanup deleted 3 real studies

Ingested a test condition (`achalasia`), then deleted it by matching on the
condition tag. CT.gov's search does synonym expansion, and 3 of the 56 studies
returned were already part of the real dataset — so deleting by `nct_id` after
filtering on the test tag removed their whole `studies` row. **Real data
loss**, caught by comparing row count against the known baseline (11,415)
rather than assuming a cleanup script did only what it was meant to. Fixed by
re-running real ingestion, safe to repeat since every write is an upsert.

**Lesson:** a cleanup pass against a real dataset must record exactly what it
added, by ID, up front — never reconstruct it afterwards from a tag that can
also match pre-existing rows. (Same class as 2026-09-05's `LIKE '__%'`.)

## 2026-08-28 — Discover live-fallback built: `GET /discover`

The route checks our DB first with the same SQL `GET /studies` uses; only a
genuinely empty local match falls through to one live, unpersisted CT.gov call.
**A live result is never written to the DB** — tracking a topic stays an
explicit action, not a side effect of asking a question.

Verified for real: `breast cancer` returned stored rows with no outbound
request; `psoriasis` also returned `"tracked"` — a correct edge case, since
several ingested trials list it as a comorbid condition; `tuberculosis`
correctly fell through to live.

`extract_fields`/`fetch_pages`/`request_with_retry` moved into a shared
`ctgov_client.py` — both `ingest.py` and `api/discover.py` need identical
parsing and duplicating it would let them drift. It lives outside both
`scripts/` and `api/` on purpose: it never touches the database, so it is on
neither side of the "only door" boundary.

## 2026-08-28 — Found and deferred: `/discover` can silently under-report an untracked condition

The local-vs-live check is a plain "did the DB return anything", but an
untracked condition can still have incidental local rows (a breast-cancer trial
listing melanoma as a comorbidity). Today's code returns those few rows as if
they were the complete picture. **"Found something" is not "found everything",
and the response doesn't say which.**

Fix decided, deferred: when the condition isn't in the tracked registry, query
both, merge de-duplicated by `nct_id`, and move `source` from the response onto
each result.

## 2026-08-29 — `/discover` gap fixed: per-result source, merged local+live

Built at the start of step 5 rather than deferred again, since the frontend was
about to display these results. Three branches: nothing stored → live only;
local rows **and** an exact tracked match → local only, since Monitor keeps it
comprehensive; local rows from an incidental match → both, merged
de-duplicated (local wins), each result carrying its own `source`.
`DiscoverResponse.source` was removed entirely — nothing read it, confirmed by
grep before removing.

Verified against real data, all three branches, including `psoriasis` returning
a real mix of 2 live + 3 tracked in one response. Added a degraded path: if the
live call fails in the merge branch, the route returns the local rows with a
note rather than a hard 502 — those rows are still real data even when we can't
confirm they're the whole picture.

## 2026-08-29 — Streamlit frontend built: Discover + Understand

`frontend/` reads through `api_client.py` over HTTP, never Postgres, extending
"FastAPI is the only door" (sec. 5) to a second real consumer. Discover uses
`st.form` so typing doesn't rerun per keystroke, and stashes results in
`st.session_state` since a rerun would otherwise throw them away.

Eligibility is shown as explicit source text with a standing caption that
TrialLens never determines whether a real person qualifies (sec. 2) — **the
first UI surface where that rule has a concrete implementation rather than
being only a written rule.** An NCT ID not in the DB surfaces FastAPI's real
404 as "not tracked" with a link to CT.gov rather than a blank page or an
invented answer.

Verified in a real headless browser, not just by reading code — including,
with FastAPI killed, Home showing the "could not reach the API" message instead
of failing silently.

## 2026-08-29 — Understand extended to live-only trials; UI copy de-jargoned

Clicking "View" on a live Discover result led to a 404. Fixed with the same
tracked-or-live split: `GET /discover/{nct_id}` falls back to CT.gov's
single-study endpoint (same `protocolSection` shape, so no new parsing). A live
result has no `fetched_at` or change history; the UI says so explicitly instead
of silently omitting them.

Two bugs fixed while verifying. **CT.gov returns 404 for a well-formed
nonexistent NCT ID but 400 for a malformed one** (checked live against both),
and the code only treated 404 as "not found", so a bad ID surfaced as a
confusing 502. And `request_with_retry` was retrying every failure including
4xx, which can never succeed on retry.

Also cleaned up developer language that had leaked into user-facing copy: an
internal capability name in a caption, literal `source` values and a config
path quoted in notes, and a permanent green "Connected to the API" banner —
**confirmation noise, when every other surface here only speaks up when
something is wrong.**

## 2026-08-29 — Discover's results table rebuilt on st.dataframe, not hand-rolled columns

Short values wrapped onto two lines even in wide layout. Root cause, confirmed
by inspecting the rendered container: `layout="wide"` genuinely widened the
page, but the table was seven manually `st.columns()`-ratio'd cells — fixed
relative widths that don't reflow, so a short value in a narrow slot force-wraps
regardless of free space elsewhere. Replaced with `st.dataframe` +
`on_select="rerun"`, Streamlit's own documented pattern; the grid auto-sizes to
content and the row count no longer means one widget key per row.

**A real testing gotcha:** Streamlit's dataframe renders to an HTML canvas
(`glide-data-grid`), so a click at plausible pixel coordinates registers
nothing — an overlay intercepts pointer events and the component listens for
real `pointerdown`/`pointerup`, not a synthesized `click`. Dispatching actual
`PointerEvent`s at coordinates from `getBoundingClientRect()` worked.

## 2026-08-29 — Narrative/design fields added: what a trial is, not just who's eligible

Understand showed status, phase and eligibility but never *why the trial
exists*. Checked against real research: two studies on what researchers look
for both rank condition, brief summary, intervention, outcome measures, dates
and location among the fields that matter most. This is also why the change log
looked useless — it can only report a change to a field we parse.

Added 8 fields to `studies`, parsed in `extract_fields()` and added to
`DIFF_FIELDS`. Two things caught before shipping, not after:

1. **Date precision.** Verified against 50 real studies before trusting a
   `DATE` column: **~23%** of the date structs are month-only ("2027-06"). A
   `DATE` column would have rejected those rows or forced fabricating a day
   CT.gov never reported, which sec. 2 forbids. Changed to `TEXT` before any
   data was written.
2. **Migration cost on the free tier.** `ALTER COLUMN ... TYPE TEXT` hit
   `DiskFull: project size limit (512 MB) exceeded` on a 181 MB database — **a
   type change rewrites the whole table even for an all-NULL column.** Fixed
   with `DROP COLUMN` + `ADD COLUMN` in a guarded idempotent `DO` block.

Backfilled all **11,490** rows from stored `raw_json` — no CT.gov re-fetch,
since the raw record is kept per sec. 4. The backfill writes to Postgres
directly rather than through `POST /studies/batch` **deliberately**: that
endpoint's diff logic would log a "changed" entry for all ~11k rows (NULL →
value), which is not a Monitor-detected change. v1 issued one `UPDATE` per row
and was on pace for ~90 minutes; a single bulk `UPDATE ... FROM (VALUES ...)`
per 1000 rows finished in under 3.

Understand now leads with summary, interventions, outcomes, sponsor and dates
above eligibility, plus a locations summary (one real trial has **542 sites**).
Added an honest fallback: when the only change is `last_update_post_date`
itself, the page says plainly that CT.gov marked the record updated but no
field we track changed value.

## 2026-08-29 — Small UI fixes + honest, interactive Home page

Three issues found by using the app: `st.metric` truncates a long value with an
ellipsis instead of wrapping; `st.write()` on a bare integer renders an inline
`<code>` chip (confirmed in the real DOM), which reads as unintended chrome for
an enrollment count; and the small icon by each `st.subheader` is Streamlit's
own anchor link, not anything this project added.

Home was rebuilt around a live stats row (via a new `GET /tracked-conditions`,
keeping the frontend reading through FastAPI rather than a config file) and an
honest capability grid — Explore and Investigate labelled "Not built yet"
rather than hidden or implied.

## 2026-08-29 — Monitor gets its own roadmap step, separate from the digest email

Monitor's output was only reachable per-trial, inside Understand — no way to
answer "what changed across everything tracked this week" without already
knowing which NCT ID to look at, which is exactly the question the persona
asks. Built as its own step, not merged with the planned digest email: **a page
you pull up on demand and an email that pushes are genuinely different
things.** Inserted before AI ranking, since it needs no capability the app
lacks — just an aggregate read over data already written.

## 2026-08-29 — Monitor page built: `GET /changes` + `frontend/pages/3_Monitor.py`

`study_changes` has no trial title, so the route joins `studies`. It lives at
`/changes` as its own top-level router, **not** under `/studies`:
`/studies/changes` would collide with `/studies/{nct_id}`, needing permanent
registration-order discipline to stop `{nct_id}` swallowing "changes" — too
fragile. Added `idx_study_changes_detected_at`, since the per-trial index
doesn't help a query scanning across every trial. `FIELD_LABELS` and
`STRUCTURED_FIELDS` moved into a shared `frontend/labels.py` — the same drift
risk `ctgov_client.py` was extracted for.

One timing gotcha, not a product bug: Streamlit's `on_select="rerun"`
round-trip and a subsequent `switch_page` each take several real seconds under
Playwright — a short wait made a working click-through look broken.

## 2026-08-29 — Monitor page: real pagination, filters, inline detail, a real dedup fix, and honest formatting

Six follow-ups in one pass. **Pagination:** 25 rows per page, with the
dataframe's widget `key` suffixed by page number — without that, a stale
selection from the previous page could carry into differently-ordered rows.
**Filters:** `GET /changes/fields` returns only field names that actually have
a change on record, so the dropdown can never offer an option that filters to
nothing; the condition filter is a dropdown, not free text.

**A real duplicate-row bug.** `reconcile-scope`'s drop query joins
`study_conditions` and matches `condition ILIKE '%obesity%'`; a trial carrying
two tags containing "obesity" produced two rows, and the following `SELECT` —
**no `DISTINCT`** — carried the duplicate into `study_changes`.

**Correction, same day — that cleanup was incomplete and its verification was
wrong.** The check queried only `obesity`, then reported the data clean.
`breast cancer` was never checked, and that is where the damage was:
`NCT04835597` appeared **19 times**, because it carries 19 tags all containing
"breast cancer" (every AJCC stage variant). Duplicate count matched tag count
exactly in all three affected trials, confirming the mechanism. **22 excess
rows removed (141 → 119)**, run on `sandbox` first, with
`COUNT(DISTINCT (nct_id, field_name, detected_at))` asserted unchanged before
and after — proving only redundant copies were removed.

**Lesson, worth more than the bug: verifying a fix against one sample of a
filtered dataset is not verifying the fix.** The first check looked rigorous —
read-only, row counts, real data — but sampled one of two conditions, and "the
data is now clean" was drawn far wider than the evidence supported.

**A distinct-trial count** so the caption reads "141 changes across 94 distinct
trials" rather than a raw count conflating "many changes to one trial" with
"many trials changing once". **Honest formatting**: `active_in_scope` renders
as "Tracked" / "Dropped from tracking" rather than Yes/No, since that is what
the transition means; timestamps show absolute and relative together.

Two gotchas: Streamlit reloads the page script on every rerun, but an imported
module like `labels.py` stays cached in `sys.modules` for the process lifetime
— editing it does nothing until the server restarts.

## 2026-08-29 — Found: the `dev`→`production` cutover never happened; added a real `sandbox` branch

Caught while answering a direct question about whether the day's writes were
hitting a disposable copy or real data. They were hitting real data.

The 2026-08-26 decision described two phases. Phase 1 happened exactly as
written. **Phase 2 never happened, and was never tracked anywhere as a
remaining step** — so `dev` became the permanent real database by inertia
rather than by decision. Confirmed from Neon's branch metadata: `dev` at
226 MB with 736 MB transferred; `production` at 32 MB with zero transfer.

Decided: **don't** migrate data just to make the names match their original
intent — re-pointing everything risks breaking a working unattended job purely
to fix a label. Added a third branch, `sandbox`, as the real disposable copy.
(The rename landed 2026-09-05, when deployment forced it.)

Isolation was proved rather than trusted: inserted one row into `sandbox` only,
confirmed `sandbox` 142 while `dev` stayed 141, deleted it, confirmed 141.
Flagged rather than guessed: whether the cron's secret also points at `dev` is
inference from `production`'s near-zero activity, not evidence.

## 2026-08-30 — Monitor honesty pass: labels, drop reasons, change categories, enrollment type

Driven by real questions asked while using the page — each a case where the UI
was technically accurate but practically misleading.

**"Active in tracking scope" was self-contradictory** — a field name
*asserting* the trial is active beside a value saying the opposite. Renamed to
"Tracking status".

**A dropped trial now says why, deterministically.** Fully derivable from
stored data — no AI, no guessing. `drop_reason()` reads the trial's own status
and last-update date against the exact scope rules `ingest.py` applies.
**Tested against all 14 real dropped trials: every one explained.** It returns
`None` rather than a guess when the stored facts don't explain the drop, and
the UI says "we can't tell from the data we've stored" — sec. 2 forbids
presenting an inference as a source fact, and this is exactly where that
temptation lives. `CLOSED_STATUSES` and `RECENCY_DAYS` moved into
`ctgov_client.py` so the explanation imports the same constants the fetcher
uses; **a second copy could quietly start lying.**

**Trial content vs. tracking, split properly.** Listing them undifferentiated
implied a scope flip is the same class of event as a status change. The
categorization lives only in `api/tracking.py` and rides on each row —
deliberately not duplicated in the frontend. The split partitions the feed
exactly: 104 + 15 = 119.

**Enrollment was ambiguous.** "Enrollment: 34" gave no indication whether 34
people enrolled or 34 is the target — and CT.gov reports exactly that, which
`extract_fields()` was silently discarding. **6,577 ESTIMATED vs 4,905
ACTUAL**, so the majority of bare counts were targets read as headcounts —
precisely the dropped uncertainty sec. 3 forbids. Added `enrollment_type`,
backfilled 11,482 rows in ~60s, with an honest fallback for the 8 records
CT.gov gives no type for.

**Test residue was sitting in the real change log.** `NCT00260585` carried
change rows 1, 2, 3 — the first ever written — all artifacts of 2026-08-28
drift testing (an injected `enrollment_count` of 999999, a corrupted date, a
triggered scope drop). The tests were documented; the rows they created never
were, and had been rendering as genuine CT.gov changes ever since. **A feed row
claiming enrollment changed from 999,999 is a fact CT.gov never reported.**
Deleted (119 → 116), which also explained a 15-vs-14 discrepancy. Both cleanups
ran on `sandbox` first.

## 2026-08-30 — Long text changes: a real word-level diff, and honest "formatting only" labelling

An `eligibility_criteria` change rendered both versions in full — **8,400
characters** to communicate a handful of edited words. Checked the specific case
first: the two versions are 94.8% similar by word and, after normalising
punctuation, casing and whitespace, **identical**. The sponsor had reformatted
one criterion into a bulleted list, and the UI gave no way to know that without
reading 8,400 characters.

**Deterministic, not an agent.** A text diff has exactly one correct answer, so
this is `difflib` (sec. 5). An LLM summarising eligibility criteria would risk
paraphrasing clinical text, which sec. 2 forbids outright.

`is_long_text()` uses a 200-char threshold, not a hardcoded field list;
`summarize_text_change()` gives an honest label ("+3 / −14 words"), never a
paraphrase; `render_text_diff()` shows one inline passage rather than
side-by-side, which for 4,000 characters reproduces the original problem.

**The formatting-only check is deliberately biased toward saying "no".** Only
non-alphanumeric differences are ignored, so anything touching a word or number
counts as real. **Missing a cosmetic edit is harmless; telling a researcher
nothing changed when it did is a false claim about a study fact.** Verified
against the cases that matter most: `BMI 27.0 to 35.0` → `45.0`, `age 18 and
65` → `75`, `eGFR < 60` → `< 30` all correctly return False. Across the real
dataset, 2 of 13 stored text changes are genuinely formatting-only.

The diff earned its place immediately on `NCT06585306`, surfacing `sedative
gastroscopy` → `gastrointestinal endoscopy` and a set of airway-difficulty
criteria replaced outright by `BMI >28kg/m2`.

Left as-is on purpose: CT.gov's own markdown escaping shows through. **Stripping
characters from stored study text would be editing the source rather than
displaying it.**

**Testing note:** a browser normalises inline `style="...#hex"` to `rgb(...)`,
so a selector matching the literal hex finds nothing even when the markup
rendered perfectly. Assert on a structural property instead.

## 2026-08-30 — Age shown as a real bracket, not a lower bound

`minimum_age` alone can only render "18 Years and older", a lower bound rather
than the trial's actual age eligibility. CT.gov does report `maximumAge` —
**5,712 of 11,490** trials have one — and `extract_fields()` was discarding it.

`TEXT`, not numeric: CT.gov attaches the unit and it really does vary ("18
Years", "18 Months"), so parsing to a number means losing the unit or inventing
a conversion. Roughly half of trials genuinely specify no upper bound, **which
is a fact about the trial, not missing data.** Skipped deliberately: `stdAges`
is a coarser restatement of the same information.

Verified the write path on `sandbox` first, since adding a column means the
INSERT list, the `ON CONFLICT` set, the row tuple and the `execute_values`
template must all stay aligned — **a mismatch surfaces as silently shifted
column values, or as a failure on the next unattended cron run.**

## 2026-08-31 — Ranking: five of eight signals moved out of the model

The first ranking implementation sent all seven fit signals to one LLM call
per trial. Four were field comparisons with exactly one correct answer
(`overall_status == "RECRUITING"`, `len(locations)`, age-bracket overlap, an
enrollment band) and a fifth (phase) became one once the stated preference was
parsed. Routing those through a model lets them drift between runs on
identical input, which makes an evaluation harness unable to attribute a score
change to a code change.

Moved to `api/ranking_deterministic.py`, which imports no model client. The
interest is parsed once per search rather than per trial, so N trials cost
`1 + N` calls instead of N larger ones — cost fell ~$0.03 → ~$0.006 per call,
though the reason for the split is reproducibility and the fact that a
deterministic signal can carry the literal stored value as evidence rather
than a model's paraphrase of it.

**Every vocabulary and threshold came from querying the live database, not the
CT.gov docs, and the two disagreed in ways that mattered.** The replaced
prompt told the model `COMPLETED/CLOSED` means not-enrolling; `CLOSED` is not
a CT.gov status at all. The eight real values are RECRUITING (3,982),
COMPLETED (3,413), ACTIVE_NOT_RECRUITING (1,841), NOT_YET_RECRUITING (1,447),
TERMINATED (385), ENROLLING_BY_INVITATION (233), WITHDRAWN (149), SUSPENDED
(40) — the prompt named two, leaving ~20% of trials unguided. It also showed
`"phase": "Phase 2"` where the column stores `PHASE2`, and never handled the
comma-separated multi-phase form (`PHASE1,PHASE2`, 461 trials).

Age parsing needs the unit, not just the number: `minimum_age` includes
Months, Weeks, Days, Hours and Minutes, and `1 Day` is real on 12 trials —
reading it as 1 year is a 365x error. `parse_age_to_years` returns `None`
whenever the unit is absent or unrecognised.

## 2026-08-31 — "Unknown" excluded from the score denominator

A signal the researcher never asked about scored 0.0 while its weight stayed
in the denominator, making "we can't tell" arithmetically identical to "this
trial fails". For a plainly-worded interest, four of seven signals have
nothing to compare against, so the score was capped near 0.65 however well the
trial matched — the previously recorded symptom (top-1 of 0.60 against an
expected 0.75+) was this formula, not model behaviour.

`unknown` is now excluded from numerator and denominator; `no_match` stays in
the denominator at 0.0, because it is real evidence against the trial. The
score answers a narrower question — of the criteria that could be assessed,
what fraction matched — so `FitRanking` carries `evaluated_weight_fraction`
beside it. **A 1.00 assessed on 30% of criteria and a 1.00 assessed on all of
them are different claims, and the score alone cannot distinguish them.**

The synthetic cases' expected ranges were written against the old denominator;
recalibrating them was deferred deliberately rather than edited to make the
suite pass.

## 2026-08-31 — Missing preferences are elicited, not scored

Excluding unknown signals is arithmetically honest but silently narrows what
the score means, and a researcher seeing a number cannot tell that most
criteria went unevaluated. `POST /rank` now returns `unspecified`: the
preferences not stated, the scoring weight each costs, and the question that
would close it, ordered by how much coverage an answer recovers — derived from
the parsed preferences with no extra model call.

It only asks about gaps an answer can fix. A signal unscored because the trial
itself records no phase — **64% of trials, `NA` on 4,869 and NULL on 2,442** —
is not recoverable by anything the researcher can say, so no question is
generated.

## 2026-08-31 — Observational studies cannot match a phase request

`phase_fit` returned `unknown` whenever no phase was recorded, excluding it
from scoring and so costing the trial nothing — an observational cohort could
rank alongside genuine Phase II trials for someone who asked for Phase II.

The two "no phase" cases separate almost perfectly by `study_type`: 2,440
OBSERVATIONAL with NULL, 4,869 INTERVENTIONAL with `NA`. An observational
study has no phase **by definition**, which is a fact rather than an
ambiguity, so it scores `no_match` with the reason stated; an interventional
trial recording `NA` stays `unknown`.

## 2026-08-31 — Condition matching split, because the filter already answered it

`/rank` selects with `condition ILIKE`, so every trial reaching the model had
already matched on condition. A 30%-weighted `condition_match` signal then
asked the model whether the condition matched, and it always said yes —
granting 30% of the score to every trial automatically, which is why scores
clustered near 1.00 and the ranking barely discriminated. **A signal that
nearly always returns the same value carries no information regardless of its
weight.**

Replaced with two signals asking what the tag cannot answer:
`condition_is_subject` (20%) — is the condition the trial's actual subject, or
a comorbidity, exclusion criterion, or background — and `approach_match` (10%).
The prompt now states that the condition match is already established and is
not evidence of fit.

## 2026-08-31 — Few-shot examples removed in favour of schema-constrained output

The replaced prompt carried three worked examples in which
`prior_treatment_compatible` and `age_range_fit` were filled identically as
`{"status": "unknown", "confidence": "low"}`. Read as a pattern rather than
three independent judgments, that teaches which fields to leave blank —
**whatever an example holds constant, it teaches.**

Both prompts now use `output_config.format` with a JSON schema, so the API
enforces shape and no example is needed. This also removed a real failure
path: the previous code told the model to emit only JSON then called
`json.loads`, where a malformed reply raised into a bare per-trial `except`
and silently dropped the trial from the results.

## 2026-08-31 — Two test tiers, split by whether they cost money

An LLM feature fails in two ways that look identical from outside: the data
never reached the model, or the model reasoned badly on data it did receive.
The bug that actually occurred was the first — `prior_treatment_compatible`
carried 15% of the weight while `eligibility_criteria` was never placed in the
payload, so the signal could only ever return `unknown`. **No amount of
running the paid harness distinguishes that from honest uncertainty, because
the output string is the same.**

`tests/test_ranking_prompt_payload.py` asserts on the constructed payload with
no API call and would have caught it immediately. It also asserts the five
deterministic fields stay *out* of the payload, so the model cannot re-judge
settled facts and contradict the evidence shown beside them.
`tests/test_ranking_real_data.py` runs every deterministic scorer against all
11,474 active trials read-only — no unparsed age, no unhandled status, no
scorer exception. 103 tests run free and belong in CI; the 48-call paid
harness stays manual, at decision points only.

## 2026-08-31 — On-disk response cache for the evaluation harness

Most iteration on ranking is on weights, thresholds and presentation, none of
which need a fresh model judgment. Responses cache to `.ranking_cache/`
(gitignored), keyed on `sha256(model + effort + system prompt + user
content)`, so an identical request replays free and only a genuine prompt,
model or effort change forces new spend. Verified by re-running a full 48-call
suite for **$0.00** immediately after a paid run. Each entry stores the user
content and a hash of the system prompt, so a cached answer can be audited
against the exact question that produced it.

## 2026-08-31 — What the ranking evaluation does and does not establish

The harness reported correct ordering in 15 of 15 scenarios. **Five had the
top two trials tied on both score and coverage**, and Python's stable sort
resolved them by fixture order, which happened to match the expected answer —
reversing the fixture list flipped those five to failures with byte-identical
scores. The honest count is **10 correct, 5 undetermined**.

The synthetic fixtures also do not resemble the stored data: 2-3 trials per
scenario against a real task of fifty, no eligibility text, one condition tag
where a real trial carried nineteen, and every field populated where real data
is 64% missing phase and 50% missing an upper age bound. **The missing-data
paths most of the design addresses are the ones the fixtures never exercise.**
Treated as a regression harness, not a quality measurement. Real measurement
needs a clinician reading real ranked output. (That finally happened
2026-09-07.)

## 2026-08-31 — The ranking evaluation suite cannot pass; its rate is not a signal

Asked whether the declared target — top-1 score in [0.75, 0.95] with
confidence `high` — is reachable at all. It is not, for either half. Checked
against the response cache at no cost; `tests/reachability_check.py`
reproduces it.

`confidence: "high"` requires `evaluated_fraction >= 0.80`. Seventy percent of
the weight is preference-gated (status 20, phase 15, prior treatment 15, age
10, approach 10), leaving 30 points always evaluated — so reaching 0.80
requires the researcher to state at least 50 of the 70 gated points. The most
any of the fifteen test interests unlocks is 65%, most sit between 30% and
55%, so `high` is unreachable in **0 of 15** scenarios, and in production for
the same reason.

The score ranges are unreachable separately: because `unknown` is excluded
from the denominator, a trial matching everything asked scores exactly 1.00
with nothing left to lose on — and the fixtures deliberately designed their
top trial to match everything, so four of five return 1.00 against a ceiling
of 0.95. The harness also computes `passed = order_correct and in_range` and
**never asserts confidence at all**, so the case named for confidence
calibration does not check it, and would fail if it did.

Recorded rather than patched, since recalibrating the numbers would hide the
structural point: **top-1 score is a weak assertion, because "matched
everything asked" equals 1.00 however little was asked.** The informative
assertions are the gap between first and second result, and the coverage
fraction. Until that is settled the suite's pass rate is not a regression
baseline and must not be quoted as one.

## 2026-08-31 — `SELECT *` was spending the Neon transfer budget on a column nothing reads

Neon warned the project had used **84% (4.2 GB) of its 5 GB monthly transfer**.
Nothing about the app's traffic explained it — one frontend user, a cron four
times a day.

The cause was `SELECT *`. `studies.raw_json` holds the untouched CT.gov
response, ~22 KB per row on the wire (249 MB across 11,469 trials). Nothing
has ever read it — `StudyDetail` has no such field, so Pydantic silently
dropped it on arrival. Four queries fetched it anyway. The expensive one was
`tests/test_ranking_real_data.py`, which reads every active row on every
`pytest tests/`. Measured wire cost (`sum(octet_length(col::text))`):

| query shape | per full-table run |
|---|---|
| `SELECT *` (before) | **315 MB** |
| every `StudyDetail` column | 66 MB |
| only what the scorers read (now) | **16 MB** |

Fourteen runs of the free suite is 4.4 GB — the entire allowance, spent on a
column discarded the moment it arrived.

Two fixes: `STUDY_DETAIL_COLUMNS` in `api/schemas.py`, derived from
`StudyDetail.model_fields` so it cannot drift as fields are added, named by
every former `SELECT *`; and the real-data test narrowed further to what the
scorers actually read.

That narrowing creates a trap: an unfetched column arrives as `None`, so a
scorer that started reading one would be tested against nothing while still
passing — **bug #7 in a new costume**.
`test_fixture_fetches_every_column_the_scorers_read` guards it by walking the
scorer module's **AST** for every `trial.<field>` access and asserting the
fixture query fetches all of them. The first version grepped a hand-written
list of omitted names; that was replaced because **a hand-written list only
catches the mistakes whoever wrote it already anticipated, and the entire risk
is the field nobody thought of.** The AST version needs no list, catches
fields added later by someone who never read the test, and fires in both
directions. Both were demonstrated failing before it was accepted.

Corroboration: the free suite's wall time fell from 79s to 10s — the tests
were mostly waiting on the network.

**The rule: never `SELECT *` against `studies`.**

## 2026-08-31 — `raw_json` stays; the storage tradeoff is real but not due yet

Questioned during the transfer investigation, since `raw_json` is 52% of the
table (95 MB on disk, 249 MB on the wire) against a 0.5 GB cap, and no query
reads it. An earlier note called it a column "nothing reads". That was wrong
in the way that matters.

It has earned its keep three times, each a schema backfill run from stored raw
records with **no CT.gov re-fetch**: narrative fields (11,490 rows),
`enrollment_type` (11,482, ~60s), `maximum_age` (5,712, ~28s).

Speed is the weaker argument. The real one: **a re-fetch is not a re-read.**
CT.gov's record today is not the record that was stored, so backfilling from a
re-fetch would silently mix current values into historical rows and make the
diff history in `study_changes` a lie. `raw_json` is what makes a backfill
*honest*, not merely fast.

Confirmed again while scoping later features: 1,050 stored trials already
carry a `resultsSection` and 4,433 a `referencesModule`, neither ever
extracted — both backfillable today for free. That is the fourth payoff.

**Decision: keep it.** 206 MB = 41% of the cap; the wall arrives around
~28,000 trials. Revisit then, and the option is to *move* it (object storage,
or only the newest raw record per trial) — not to drop it.

## 2026-08-31 — Feature order for post-Step-7 work

1. **Advanced filtering / noise reduction** first, because it is almost
   entirely deterministic over data already stored — `study_changes` keeps old
   and new values and `DIFF_FIELDS` already covers status, phase, enrollment,
   eligibility and locations. No API spend. "New site near me" stays at
   city/country level; real geocoding is scope creep for no extra insight.
2. **A curated summary of what changed** second, because it is the readable
   summary *of* (1)'s categories — building it first means writing it twice.
   Mostly counting; the model earns its place only for turning a
   ~4,000-character eligibility diff into one plain sentence.
3. **Per-user accounts — deferred.** Auth is undifferentiated work
   demonstrating none of the skills this project was chosen to practise, and a
   reviewer forced to sign up before seeing anything usually leaves. A
   **watchlist with no login** gives the interesting half — the many-to-many
   modelling (1) needs anyway — without the boilerplate.

Grounding for (1): four days of Monitor produced **123 changes across 100
trials** — 7 `overall_status` transitions, 7 eligibility amendments, 3
enrollment moves. The substantive signal is real and already on disk.

## 2026-08-31 — Unit 4 verified; two more bugs, one fixed and one open

Everything below was found by *running* the ranking page, not reading it — it
had compiled for an hour before any of this surfaced.

**Found free, before spending anything:** a `SyntaxError` (Python 3.9 forbids
a backslash inside an f-string expression — the file had never been executed),
and `1 things you didn't specify`. Free verification used
`streamlit.testing.v1.AppTest`, which runs a page headlessly and reports
exceptions — cheaper and faster than the Playwright approach used for earlier
pages. It also validated all 33 response keys the page reads against the real
Pydantic models by AST.

**Bug #9 — `POST /rank` had never once returned successfully over HTTP.** The
endpoint passed a `ResearcherPreferences` into a field typed
`ResearcherPreferencesOut`. FastAPI validates the *outgoing* response against
`response_model`, so every request raised a 500 — **after all 21 model calls
had been billed.** Found by spending $0.13 on a live run that threw the entire
result away. This is bug #1's twin: the tests all called scoring functions
directly, so nothing exercised request binding or response validation. A free
`tests/test_ranking_endpoint.py` calls the endpoint over HTTP with the model
stubbed, proven to catch it in both directions. **A test that calls the
endpoint function directly is not testing the endpoint.** The response cache
paid for itself here — the re-run after the fix replayed all 21 responses for
$0.0000, so the bug cost $0.13 once, not twice.

**Bug #10 — `approach_match` cannot ever score. Found, NOT fixed.** Across all
20 real trials it returned `unknown` 20/20 with evidence "Researcher named no
specific approach" — for the interest *"...testing immunotherapy or targeted
agents in adults."* `build_semantic_user_content()` sends the model only
`condition_terms` and `prior_treatment_context`; `raw_interest` appears solely
as a fallback when condition terms are empty, so those words never reached the
model. **This is bug #7 exactly — a weighted signal whose input is never
plumbed into the payload — recurring inside the very function whose docstring
describes bug #7.** Worse, the system contradicted itself: `find_unspecified()`
correctly did *not* ask about approach, so it knew an approach was named while
the signal said it wasn't. Visible in the real run: the top 5 were intermittent
fasting, ketorolac/pregabalin, electrosurgery, tDCS and broccoli microgreens —
not one an immunotherapy or targeted agent. Not fixed here because the fix
changes the prompt, invalidating the cache and costing real money to
re-verify.

**Also observed:** `sites_active` returned `partial` 15/20; real scores spread
0.92 → 0.27 against the synthetic harness's flat 1.00, further evidence the
fixtures are far easier than reality; and `fetch_trials_for_condition` orders
by `last_matched_at DESC LIMIT 20`, so `/rank` scores *the 20 most recently
matched* trials, not the best 20 of 11,474 — "score these 20", not "search".

## 2026-08-31 — Researched against the literature: what TrialGPT settles

Searched rather than assumed, prompted by the user asking whether any of this
is needed. The reference system is **TrialGPT** (NIH/NLM, *Nature
Communications* 2024) — the same problem, done properly.

**What it validates.** Three modules, Retrieval → Matching → Ranking, with
retrieval recalling **>90% of relevant trials using <6% of the collection**.
The two-stage design built here (deterministic shortlist, then model on the
shortlist) is the same shape, arrived at independently from sec. 5. Keep it.

**What it corrects — the label set.** TrialGPT labels each criterion
`{Included, Not included, Not enough information, Not applicable}`, keeping
the last two deliberately separate; TrialLens collapses both into `unknown`.
**26.9% of TrialGPT's residual errors were exactly this confusion** — the
second-largest error class. It is bug #3's lesson one level deeper: "the trial
has no phase recorded" and "phase doesn't apply to an observational study" are
currently indistinguishable, and only one is a data gap.

**What it corrects — the benchmark.** The step-7 guide recorded published
systems at precision/recall ~0.32-0.45, and the entry above leaned on that to
argue a synthetic 1.00 is implausible. TrialGPT reports **NDCG@10 0.7275,
P@10 0.6724**, criterion accuracy 0.873 against expert 0.887-0.900. The
0.32-0.45 figure is not the state of the art. The conclusion still stands on
its own evidence, but must not be argued from that number.

**Other findings:** TrialGPT generates the rationale *first*, then classifies
— if status comes first the model commits then rationalises, and the evidence
stops being load-bearing. Its aggregation combined a linear score with an
LLM-generated pair, beating either alone. **Explanations are the measurable
part** — 87.8% rated correct, sentence-location F1 88.6% — and that is
per-criterion, not per-trial, which is what a researcher's judgement can
actually produce. LLM-as-judge biases (verbosity, position, prompt
perturbation) matter here because `confidence` and `evidence` are both
model-generated: length must not become a proxy for certainty. And on whether
the LLM is needed at all, the local evidence beat the citation — in the real
20-trial run `condition_is_subject` returned match 9 / partial 9 / no_match 2,
real variance on the one question a `condition ILIKE` tag provably cannot
answer. That signal earns its cost; `approach_match` has not, because of bug
#10.

## 2026-08-31 — The three process fixes, implemented as code not intentions

1. **No paid call until a free test of the same path passes**, and
2. **batch the paid questions** — both enforced by `scripts/paid_preflight.py`,
   which runs the free suite, exits non-zero if it is red, and otherwise
   prints every question still waiting on a paid answer so they are asked in
   one run instead of three. Proven in both directions. Also written into
   CLAUDE.md sec. 7, **since a rule that lives only in a script is a rule
   nobody reads first.**
3. **A free payload guard for `approach`**, including a structural assertion
   that elicitation and the payload can never again disagree about whether an
   approach was named. That disagreement *was* bug #10.

## 2026-08-31 — Intervention category: the free half of the approach question

CT.gov records `interventionType` as structured data, so "the researcher
follows surgical approaches, this trial is 100% DRUG" is a fact, not an
interpretation. It cannot tell a GLP-1 from an SGLT2 (both DRUG), so it
narrows what needs the paid call rather than replacing it.

**Querying the real distribution first (sec. 6) changed the design twice:**

1. **There are 11 intervention types, not 6.** The proposal named six; the
   database also holds DIAGNOSTIC_TEST (625), RADIATION (618), BIOLOGICAL
   (575), COMBINATION_PRODUCT (136) and GENETIC (68) — **2,022 interventions
   the shorter list would have left unclassifiable.**
2. **985 of 11,420 active trials record no interventions at all**, and OTHER
   appears on 3,939. Both must *defer to the model*, never return `no_match`:
   absent data is not evidence against a trial (sec. 2), and treating the
   contentless OTHER as a conflicting category would manufacture false
   mismatches across a third of the database.

`score_approach_category` returns a `no_match` **only** when both sides are
informative and disjoint, and `None` — defer — otherwise. Used in candidate
selection (removing trials before any model call is spent) and in
`rank_one_trial`, where a decisive verdict overrides the model's
`approach_match`: a stored `interventionType` is a fact, a model's reading of
it is an inference.

Measured on the real 5,371-trial breast cancer pool: surgical/procedure ruled
out 3,373 (63%), behavioural/lifestyle 3,398 (63%), immunotherapy 1,507 (28%)
— all for $0. Stage-one transfer rose 10.0 → 12.6 MB for the `interventions`
column, **and the AST guard demanded that column automatically the moment a
scorer read it — the guard working as designed on its first real opportunity.**

## 2026-08-31 — `not_applicable` added, but it belongs to the model, not the code

Added after the TrialGPT research and scored identically to `unknown`
(excluded from numerator and denominator) while reading very differently to a
researcher.

**A negative finding worth recording, because it stops this being
cargo-culted:** there is no clean use for it in any *deterministic* scorer.
TrialGPT's `not_applicable` labels individual eligibility criteria within a
trial ("must not be pregnant" for a male patient). TrialLens's signals are
trial-level preferences that always apply — a trial always has a status,
always has or lacks a phase. Where "the trial doesn't record it" is the
answer, that is a data gap, which is `unknown` by definition.

It has a real use in the three **model-judged** signals: prior treatment on a
prevention trial in healthy volunteers, approach on a trial registering no
interventions. So it is defined in the schema and taught in the prompt with an
explicit tie-break — *if unsure which applies, use `unknown`, because calling
a question meaningless is a stronger claim than admitting you cannot answer
it.* No deterministic scorer was forced to emit it.

## 2026-08-31 — Evidence before status in the output schema

`_signal_schema_fields` emitted `{name}_status` before `{name}_evidence`. JSON
is generated in order, so the model committed to a verdict and then wrote a
justification for it — **the evidence was decoration, not reasoning**, which
quietly undercuts sec. 3. TrialGPT generates the rationale first and
classifies from it (87.8% explanation accuracy). Reordered to evidence →
status → confidence, with the prompt saying so explicitly, plus an
anti-verbosity instruction, since the LLM-as-judge literature reports length
inflating perceived quality and both fields here are model-generated.

## 2026-09-01 — Two honesty repairs found by re-reading what the UI claims

**1. A deterministic verdict resting on an inferred input must disclose it.**
`score_approach_category` rules out up to 63% of a condition's trials and its
evidence said the categories were "read from the registry's own intervention
types, not inferred." Half true: the *trial's* types are registry fact, but
the *researcher's* come from a model reading their prose. A wrong or
under-listed mapping silently removes trials while the evidence claims
registry certainty. The evidence now names both sides and says which is which,
and the mapping is surfaced in the page's "how your interest was read" panel —
the only place a bad mapping could ever be caught.

**2. The page was inferring a cause it had not checked.** An `unknown` signal
has two different causes — "you didn't say" (fixable in a sentence) and "the
record doesn't carry it" (64% of trials have no phase; no answer helps) — and
they rendered identically. But the first attempt wrote *"unscored because the
trial's record doesn't carry it"*, **an assertion about the record the page
never inspected.** Corrected to state only what is known: *"answering below
would recover it"* versus *"nothing you could add would change it"*. Inventing
a cause to sound more helpful is the same failure as inventing a study fact
(sec. 2), one level down.

## 2026-09-01 — Credits exhausted mid-batch; what was learned before they ran out

The account ran out of credits during the batched paid run. Two of five
questions were answered first.

**1. Bug #10 is fixed, verified on real output.** `approach_match` went from
`unknown` 20/20 to **`match` 5/5 at high confidence** with specific, correct
evidence — inavolisib as a PI3Kalpha inhibitor, durvalumab as anti-PD-L1,
Dato-DXd and HER3-DXd as antibody-drug conjugates.

**2. The $0.006-per-call figure was wrong, and every projection built on it
was wrong.** Measured on the canary: **$0.1142 for 6 calls ≈ $0.019/call**.
The old number came from this repo's own notes, measured against **synthetic
fixtures**; real trial records carry up to 2,500 characters of eligibility
criteria and cost far more.

| | claimed | measured |
|---|---|---|
| 20-trial search | $0.13 | **~$0.32** |
| monthly re-ranking (271 trials) | $1.62 | **~$4.07** |

**Caught before spending, by reading the API reference rather than assuming:**
`output_config.effort` is an Opus-tier parameter and is **rejected on Haiku
4.5** — every call in the planned Haiku comparison would have failed.

**Graceful failure, found the hard way.** `parse_researcher_interest` runs
before the per-trial loop and outside its `try`, so an unusable key escaped as
a raw 500 with a stack trace. Two free, tested fixes: a parse `APIError` now
returns **503** saying nothing was scored and that tracked data and the
Monitor feed are unaffected; and **every trial failing is an outage, not a
ranking with no results** — 503 rather than a 200 with an empty list, which
would render as "no trials matched" and is a false statement about the data.

**The demo survives.** 71 cached responses; the canary replays at $0.0000 with
no credits at all. `.ranking_cache/` is gitignored, so it does not travel with
a clone.

## 2026-09-01 — Step 7's two working docs deleted; what they held

`docs/STEP7_SESSION_SUMMARY.md` (361 lines) and
`docs/step7_implementation_guide.md` (237 lines) removed, both checked for
unique content first rather than assumed redundant. The implementation guide
already carried a STALE banner naming six of its own claims as wrong and said
it was retained for "precision/recall around 0.32-0.45" — **the figure the
TrialGPT entry corrects**, so its only stated reason to exist was itself the
error.

Two of the session summary's four open questions were recorded nowhere else,
and are recorded here so deleting the file doesn't erase them. **The ranking
tie** (a recruiting and a completed trial could score identically when no
preference was stated) — partly answered by a disclosed recency tiebreak, and
moot from here because the score is being removed. **The paid prior-treatment
eval case** — never built, and moot because the signal is being cut: it
carried 15% of the weight while being relevant to 28% of breast cancer trials
and 1% of obesity trials. Both closed, not outstanding.

## 2026-09-01 — The ranking layer removed; what the removal plan got wrong

Ten files gone: `api/ranking.py`, `api/ranking_schemas.py`,
`frontend/pages/4_Ranking.py`, five ranking test modules,
`scripts/rank_dry_run.py`, `scripts/cache_coverage.py`. `/rank` no longer
exists on the app. 75 free tests pass.

**A removal plan's file list is not the same as the dependency graph.** The
plan named exactly one test that had to go. Three more breakages were visible
only by reading the survivors' imports: `api/ranking_deterministic.py` (a
keeper) imported `FitSignal` from a deletion; `tests/test_ranking_real_data.py`
imported `SIGNAL_WEIGHTS` and `score_signals` from `api/ranking.py`; and
`scripts/paid_preflight.py` excluded a harness that no longer exists and
carried `COST_PER_CALL = 0.006`, the synthetic figure already corrected to
~$0.019. **Grep for what the deleted files export, not just for their module
names** — a module search finds `import api.ranking`, it does not find
`SIGNAL_WEIGHTS`, and that is the reference that breaks a keeper.

**Deleting a test that guards a vocabulary needs a replacement, not just a
deletion.** The one test the plan named was the only thing holding
`INTERVENTION_TYPES` to anything — and it compared that list to a hand-written
enum in the prompt schema: **two hand-written lists agreeing with each other,
neither checked against the data.** Its replacement asks the live database
instead and passes against all 11,469 active trials — strictly better, and it
exists only because the deletion prompted "what was this actually protecting?"
Worth asking of every test a removal takes with it.

**Home lost the Ranking card entirely rather than reverting to "planned",**
which is what the plan said to do. "Planned" would be a false statement about
the roadmap: the capability is not deferred, it is rejected with reasons
recorded, and a card saying "not built yet" invites someone to build it.

## 2026-09-02 — Where a model earns its place, decided by querying first

The plan after the removal was to add one AI call: a change interpreter
turning an amendment into `{category, why_it_matters, evidence[]}`. Before
writing the prompt, the change-sets were queried — **§6 applies to a prompt as
much as to SQL**, which is the lesson step 7 paid for. Four findings, and they
moved the design more than the plan did.

1. **Most amendments are not interpretable and shouldn't be sent.** Of 212
   amendments: **99 (47%)** changed nothing TrialLens stores, 38 moved a
   single structured field, 29 are multi-field combinations, 46 changed prose.
   Only the last two — **75 of 212** — contain anything a model could add to.
   Sending the other 137 would pay for invention or for arithmetic.
2. **The category half is a lookup, not a judgement.** There are 14 distinct
   content fields and every one maps statically. A model asked for that
   verdict is step 7's error repeated: a filter wearing a score's costume.
   Now `FIELD_ASPECTS` in `api/amendments.py`, free and instant.
3. **One amendment carries 252,041 characters of `locations` JSON** (average
   3,475). A naive "send the change-set" would occasionally ship ~100k tokens
   for a list of hospitals, when the honest summary is "5 sites added, 5
   removed". Structured list fields are summarised deterministically and never
   reach a prompt or a diff view.
4. **Dates cannot be subtracted naively.** ~23% are month-only. A shift is
   reported in months or weeks whenever either side is imprecise, and a
   sub-fortnight difference between two month-only dates is not reported at
   all — it is an artefact of anchoring to the 1st, not movement. "Slipped 361
   days" about a date given as "2027-06" invents precision the registry never
   stated (§2).

Built: everything arithmetic can answer — date shifts, headcount deltas,
ESTIMATED→ACTUAL, site add/remove counts, and status transitions written over
status *groups* so an unobserved transition still resolves. `describe_effect`
returns `None` for every prose field permanently, and a test fails if that
changes.

**Why this order matters more than the feature.** Shipping the deterministic
layer first creates a control: "does a model's prose add anything over this?"
is now answerable, where step 7's equivalent question never was.

**Rejected: running it on a local model.** An 8 GB M1 Air realistically runs a
3-4B model, and the task is interpreting clinical prose diffs where inventing
a fact is the cardinal sin — **fluent, confident and wrong is the exact
failure §2 exists to prevent.**

**Two honesty bugs fixed in passing.** `GET /studies/{id}/changes` returned
200 with an empty list for an nct_id never seen — "no changes recorded" for a
trial that does not exist, reading as "this trial has been quiet" — since it
was written. And `is_formatting_only()`'s docstring claimed four clinical
cases "were checked"; nothing checked them.

## 2026-09-02 — Why an amendment was invisible: we were not looking at the field

The diff compares **21 normalized columns**. The raw record carries 11
protocol modules plus two top-level keys, and the most consequential thing in
it was never read: **`hasResults` sits at the TOP level of the response, not
inside `protocolSection`**, so a parser walking every module one level down
never saw it.

**1,056 of 11,518 stored trials already have results posted** — 751 completed.
A trial going `false → true` means its findings are published, the single most
consequential amendment a researcher following a therapeutic area can receive,
and every one had been rendering as "amended, but we can't see what."

**The backfill needed no network call, and that is the point.** `has_results`
was recovered for all 11,518 trials straight out of stored `raw_json` — a
field nobody thought to normalize in August, recoverable in September for
free. Without it, refetching 11,518 records at ~50 req/min.

**Backfilled values are deliberately NOT written to `study_changes`.** Doing
so would log 1,056 "results were posted" amendments dated today for trials
that published months or years ago — a false claim about *when* something
happened (§2). The backfill sets the baseline; only transitions the real diff
detects from here are amendments.

Still unread, in descending order of likely value: `referencesModule` (4,443
trials — a new publication attached to a trial is real news), `oversightModule`
(11,361), central contacts (5,044), `derivedSection`. A cheaper general fix
exists and is not built: at diff time both the old and new `raw_json` are held
for the ~91 trials a run refetches, so naming *which modules* changed would
cost one extra column in a query already running.

**The generalisable lesson is the same one as 2026-08-31: the shape of the
real payload is not the shape the code assumes.** That time it was values
inside a field (`PHASE2`, not "Phase 2"). This time it was a field one level
up from where every other field lived.

## 2026-09-02 — The invisible amendment was over-weighted, and its copy guessed

Caught by reading the rendered page rather than the code. An amendment
TrialLens *cannot see* was getting a heading, a caption, a three-sentence
`st.info` box and a divider — **more visual weight than the amendment above it
carrying four real field changes.** Now one caption line.

Worse, the copy said the untouched fields were "contacts, oversight and
sponsor administrative details among them." **We do not know that.** The
system knows only that `last_update_post_date` moved and no stored field did;
which fields CT.gov actually touched is exactly what it cannot see. Naming
three of them reads as a finding and is a guess.

This is the *same* error as the 2026-09-01 entry above, by the same reasoning:
the honest line felt too thin, so plausible detail got added to make it
useful. It has now happened twice in two days and both times it looked like
helpfulness — **when a true statement feels unsatisfying, the fix is a better
true statement or silence, never a plausible one.** Corrected to: "amended,
but only in fields TrialLens doesn't store. The record changed; we can't show
what." Every clause is checkable.

## 2026-09-02 — The watch leads the page, and "last checked" is a proxy that says so

Step 7b direction 2, built from `design/Main.dc.html`. What `Home.py` had was
a capability grid — a brochure. The thing TrialLens has that a fresh clone
does not is **elapsed time**: 11,427 trials watched since 28 August, every
amendment since recorded. So the page leads with the watch and the grid sits
below it. `GET /watch` is one endpoint rather than five reads, because the
numbers only mean anything together — "watching 11,427 trials" is a different
claim depending on whether the last check was 2 hours or 3 days ago.

**The screen has three states and the least eventful one mattered most.** 29
and 30 August had zero amendments across all 11,427 trials — real recorded
data — and that rendered as an empty table, which reads as a broken app rather
than a working watch. The quiet week is the screen a researcher sees most
often, so it is stated as a finding, and empty days are drawn as zeros rather
than omitted: **a zero is evidence the watch ran and found nothing, which is
the opposite of missing data.** The day strip is therefore built from
`generate_series`, not `GROUP BY` — grouping alone has no rows for a quiet day
and would silently delete the only proof it was watched.

**The alarm replaces the page rather than sitting above it**, because a stale
feed under a small warning still reads as current. Nothing but a test will
catch a regression here — the alarm only appears after 12 hours of a dead
cron, exactly when nobody is looking — so `tests/test_home_watch_page.py`
renders all three states through `AppTest` and asserts the feed, day strip and
last-amendment card are *absent* when the watch is stopped.

**The proxy, and why it is not `detected_at`.** The headline fact "last
checked 2 hours ago" is a `monitor_runs` fact, and that table was direction 3,
not built — so an explicitly labelled proxy was used:
`max(studies.last_matched_at)`, stamped on every in-scope trial at the end of
every run. The obvious alternative, `max(study_changes.detected_at)`, is
**wrong in exactly the case this screen exists for**: on a quiet week nothing
is detected, so it would report "last checked 2 days ago" and fire the alarm
on the primary screen. **A proxy that fails on the common case is not a
proxy.** The page said in its own words that the figure was inferred from when
trials were last confirmed in scope, not from a record of scheduled runs. The
load-bearing assumption — that `last_matched_at` is never behind the newest
change it should explain — was asserted against the live database, because if
ingest stopped calling reconcile-scope the watch would report itself healthy
while dead, with no error anywhere.

**Building direction 3 first was considered and rejected.** A fresh
`monitor_runs` means "no check has ever been recorded", which *is* the alarm —
so building the record first would ship a screen screaming that the watch has
stopped while it is demonstrably running. Backfilling from the 8 distinct
`last_matched_at` timestamps was rejected too: those are the last run each
trial was matched in, not the 21 runs that happened, and presenting 8 of them
as run history would be inventing a record.

**Counted by what it means, not by how many rows moved.** The news-week
headline says "one trial published its results, three others changed something
scientific, out of 63 amendments" — not "63 amendments". `WatchRecent` carries
both: the finding for the headline, the total for the honesty. `results_posted`
is a *subset* of `scientific`, so the UI subtracts, and a live-database test
asserts `results_posted ≤ scientific ≤ amendments` — if that containment broke
the page would state a negative number of trials as fact. **The amendment, not
the changed row, is the unit**: an amendment that moved four dates is one
thing that happened, and counting its rows would announce it as four.

**Aspect markers became coloured dots**, in `labels.py` so Home and Understand
cannot disagree about what "Scientific" looks like. The emoji carried meanings
that fought the label (a microscope is not what "Scientific" means here) and
rendered at different sizes per platform. The colours are a hierarchy rather
than a palette: Scientific is the only one with any hue, because it is the
only group whose change can change what the trial *means*. Uncategorised is a
hollow dot — it is the absence of a classification, and a filled dot would
look like one.

**The artboards claimed "every number is real". Four were not.** Building the
screen is what checked them: 751 → 747 and 1,056 → 1,050 (drifted overnight),
the alarm's "13 checks missed" → 12 (76 elapsed hours over 6-hour slots is 12;
written by hand), and NewsWeek's "3 changed something scientific, 59 other" →
14 and 49 (estimated before anyone queried it). **The worst one was not a
number:** NewsWeek's lead card shows a trial publishing its results —
`has_results` false → true — and **no such transition has ever been
recorded**, because backfilled values are deliberately not written to
`study_changes`. NCT05599334 really does have results; what has not happened
is TrialLens *watching* them appear. The card is now labelled on the artboard
as a designed treatment for an unobserved state.

That is the third instance in two days of the pattern named twice already —
**when a true statement feels unsatisfying, the fix is a better true statement
or silence.** The first two were page copy. This one was in a design file,
which is worse in one specific way: **a drawn number has no test.** Copy that
guesses gets caught by reading the rendered page; a figure inside an artboard
is only checked if someone re-queries it on purpose. No number on the built
page is hardcoded, which is the durable version of that claim — and the reason
to build a designed screen rather than maintain a drawn one.

## 2026-09-02 — Step 7b direction 3: the watch record, un-deferred by backfilling

`monitor_runs` now exists and `/watch` reads `last_checked_at` from the newest
completed run. `scripts/run_monitor.py` opens a row at the start of a run and
closes it `completed` at the end, carrying trials checked and changes detected.
`WatchStatus.last_checked_source` is deleted: it existed to label a proxy as a
proxy, and there is no proxy left to label.

**What actually unblocked this.** Direction 3 was deferred on the reasoning
that an empty run table reads as "no check has ever run" and fires the alarm
on a healthy watch. That reasoning was sound and its conclusion was still
wrong. The proxy it replaces is not merely *correlated* with a run having
happened — `reconcile-scope` stamps `last_matched_at` at the end of every run,
so it **is** a real completion time for a real run, which makes it
backfillable. One row seeded, the cron takes over from the next run, and the
alarm never fires falsely. **The blocker was a gap of one row, not a gap of
two weeks.**

`changes_detected` on that seeded row is NULL rather than 0. Nothing on file
records how many changes that run found, and 0 would be a claim that it found
none — inventing a fact about a run to avoid a null (sec. 2).

**The test that has to survive this.** The real-data suite asserted that
`max(last_matched_at)` was not behind `max(study_changes.detected_at)`, so a
dead watch could not report healthy. The same silent failure exists in the new
shape — `run_monitor.py` could record changes and never close its run row — so
the test was **rewritten against `monitor_runs` rather than deleted.** A guard
that moves when the mechanism moves is the point; deleting it because its
subject was replaced would retire the invariant along with the implementation.

## 2026-09-02 — Record the writer's own count, not a timestamp window

`monitor_runs.changes_detected` was first written by re-deriving it after the
run: `count(*) FROM study_changes WHERE detected_at >= started_at`. That is
close to right and quietly not true — the window also catches rows written by
anything else active at the same time (a manual ingest, a backfill) and files
them under this run's id. **A number that is usually correct, in a column
nothing reads yet, is the easiest kind of wrong to ship.**

**The exact number already existed and was being discarded.** `sync_group`
sums what `POST /studies/batch` reports as it writes, printed it to the log,
and returned a bare set of nct_ids. It now returns an
`IngestResult(nct_ids, changes)`, and the re-derivation query plus the second
database connection it opened are deleted. **Before deriving a value, check
whether something upstream already knows it exactly** — re-derivation is how
an approximation gets into a table later displayed as fact (sec. 3).

**Urgency came from the column being unread, not despite it.** The instinct
was to defer since nothing displays it. Backwards: every cron run writes
another approximate row, and once a screen shows the number the wrong history
is already on file and cannot be recomputed. Cheap now, impossible later.

**Documented rather than changed:** nothing marks a run `'failed'`. A run that
dies leaves its row `'running'`, `/watch` keeps reading the last completed
run, and the gap grows until the alarm fires — the honest outcome for a run
that did not finish, so the comment says so to stop a later reader "fixing"
it. (A real third state was eventually added for a different reason: 2026-09-06.)

`tests/test_ingest_counts.py` is the first test to touch `scripts/ingest.py`;
the module had zero coverage, so the suite went green on this refactor while
proving nothing about it. Proven able to fail before being trusted (sec. 7):
dropping the trailing batch flush, `=` for `+=`, and returning studies counted
instead of changes each turned it red.

## 2026-09-02 — Step 8 unit 1: the Explore graph is tables, not a graph database

**No Neo4j.** The graph already exists — `studies.lead_sponsor` holding "Mayo
Clinic" on 134 rows *is* 134 edges, just written in an awkward shape. Step 8
makes it walkable; it does not create it.

A native graph database earns its keep through index-free adjacency, which
pays off when traversals are deep and the graph is large. Measured shape here:
11,518 trials, 3,173 sponsors, largest sponsor 163 trials, and Explore's
questions are 2-3 hops. Postgres joins over 11k rows are not the bottleneck at
any of those numbers. Conditions that would reverse this, recorded so the
decision can be reopened honestly: row counts in the millions, materially
denser linkage, or deep open-ended traversals. The operational half is
decisive on its own — a second database is a second sync path and a second
thing that can be stale, and sec. 5 says FastAPI is the only door.

**Controlled vs. free text is a property of a FIELD, not an entity.** The
useful test is whether CT.gov enforces a controlled value or accepts
free-typed text, and almost every entity here is half of each:

| Field | Distinct | Collapsed on case/space | Verdict |
|---|---|---|---|
| `lead_sponsor` | 3,173 | 3,173 | controlled, zero duplicates |
| location `country` | 123 | 123 | controlled |
| intervention `type` | 11 | — | controlled enum |
| location `facility` | 42,842 | 41,710 | free text — 1,132 differ only by case |
| intervention `name` | 13,307 | — | free text — 11,598 used exactly once |
| investigator `name` | 7,332 | 7,275 | free text |

Madrid alone carries 381 distinct facility strings, New York 322. **A city
does not have 381 trial sites**; those are the same institutions typed
differently. So sponsors and countries get identity upfront, while facility,
intervention and investigator identity has to emerge from the real values.

**The intervention merge rule: merge only when the difference is *naming*,
never when it is *substance*** — dose, route, formulation, or role in the
trial. The data forces this: 55 distinct names begin with "semaglutide" (dose
and route arms where the difference IS the study) and 159 begin with
"placebo" — merging those would build the densest node in the graph out of a
thing that is by definition nothing, and route every multi-hop query through
it. Merging never overwrites: both source strings stay, linked to the shared
node, with the link recorded as inferred rather than reported (sec. 3). **A
merge that destroys the source text is the Procrustean cut** — the problem is
not the inference, it is that the evidence is gone and a researcher cannot
disagree with it.

## 2026-09-03 — Step 8 unit 2: extraction, and the edges a trial takes back

Extraction against the live database: **6,207 organizations, 51,272 sites,
7,717 investigators, 14,468 intervention terms, 191,864 edges**, all from
records already on file. No CT.gov call — investigators and collaborators had
been sitting unread in `raw_json` since ingestion, the third time §4's
keep-the-raw-record rule has paid for itself. Nothing is merged, on purpose:
381 Madrid facility strings are 381 sites, and that unmerged extraction is the
baseline any later merge gets checked against.

**Reconciliation was not a formality — it failed twice, each for a different
real reason.** The first was staleness: the extraction ran, a monitor run then
ingested 70 trials, and every entity was short. The freshness test went red on
real drift with the right message before anyone mutated anything.

The second pointed the other way: the graph had **more** rows than the source.
7 sites and 15 edges traced to no current record. **The extraction is
insert-only, so when a trial drops a site the edge outlives the record that
justified it** — Explore would have gone on saying a trial runs at a location
it had removed. One 6-hour run produced 15 of those.

**Decision: stamp `delisted_at`, never delete.** Deleting fixes the false
claim and destroys the finding. This is a watch-over-time product; "this trial
quietly dropped three sites" is a result, not a row to tidy away. NULL means
the connection is in the current record; a timestamp is the first run that
could not find it. It is deliberately *not* the date the trial made the change
— nothing on file says that, and writing the real amendment date there would
invent precision the backfill does not have (§2).

Consequences: edge inserts became `ON CONFLICT DO UPDATE SET delisted_at =
NULL` so a re-listed site comes back, carrying `WHERE delisted_at IS NOT NULL`
so every pass doesn't dirty all 140,000 edges writing NULL over NULL;
withdrawal UPDATEs are guarded by `delisted_at IS NULL` so an edge keeps the
date it was *first* seen missing; and `test_no_site_was_invented` had to be
scoped to sites holding a live edge — unscoped it called those 7 dropped sites
inventions, **which is the wrong word: they were reported once and later
withdrawn**, and that distinction is the whole point.

**Proven able to fail:** seven mutations — inventing a site with a live edge,
un-withdrawing a dropped one, deleting a LEAD edge, deleting an investigator
edge, future-dating a withdrawal, stripping a trial's edges, collapsing
semaglutide to one term — each injected inside a transaction and rolled back.
7/7 red, table counts identical before and after.

## 2026-09-03 — Two monitor bugs that could only exist on the schedule

Both found by dispatching the workflow rather than waiting for the next tick.
Neither was reachable locally.

**`KeyError: 'DATABASE_URL'`.** `run_monitor.py` opens its own connection to
write the `monitor_runs` record and store prose interpretations, but the
workflow step passed only `API_BASE_URL`. Locally this is invisible because
`load_dotenv` reads `.env.local`; in the job the environment is the only
source. **So the watch record added on 2026-09-02 had never once been written
by a real run** — `monitor_runs` held nothing but the backfilled seed, and
every "successful" cron since recorded nothing.

**`UPDATE ... ORDER BY ... LIMIT` is MySQL.** Postgres rejects it outright,
and `run_prose_interpretation`'s except clause swallowed it into a printed
one-liner. `study_changes.prose_interpretation` had **zero rows**: step 7c's
$0.168 bought interpretations that were computed and then dropped. Verified
with `EXPLAIN`, which parses without executing. The write now goes by primary
key. Matching on `(nct_id, field_name)` and taking the newest was
independently wrong: a trial amending the same prose field twice in one window
has two rows, and the older interpretation would land on the newer one —
attaching an inference to source text it was not drawn from (§3).

**Still open at the time: there was no `ANTHROPIC_API_KEY` secret on the
repo**, so step 7c could not run on the schedule at all; it degraded through
its except clause and the rest of the run proceeded. Claims elsewhere in the
docs that it ran in the scheduled job described intent, not behaviour.

## 2026-09-03 — Site enrichment: the fields the parser dropped, and the evidence that asked for them

Prompted by a question that should have come earlier: *do researchers care
about collaborations?* Full review in `docs/plan_explore_nodes.md`; the short
version is that the collaborator edge is the weakest node in the graph and
sites are the strongest.

**Collaborator is weak by definition, not by accident.** CT.gov defines a
collaborator as any organization "providing support", where support "may
include **funding**, design, implementation, data analysis or reporting" — one
field for cheque-writers and co-designers, with no sub-field separating them.
The data matches: NCI 480, NIDDK 264, NIH 91, NHLBI 86. Coverage is **37.4%
and 63% of those trials have exactly one collaborator.** Registration guidance
also says collaborators "should not include individuals... not PIs", so the
field cannot answer the people-shaped reading of "who else works in this
space" at all. Kept and extracted, but demoted from a network to traverse to
an attribute to filter on.

**Sites reach 93.8% and answer a documented question.** The oncology
literature describes the workflow as: search, find a candidate trial, then
*phone the site to ask whether it is still open*. A separate study of 8,893
cancer patients found **55.6% had no trial available at their treating
facility.** Both are location questions, both answerable from data on disk.

**The `has_results` pattern, third recurrence.** `locations` had been
normalized to facility/city/country and everything else discarded, so across
142,777 stored locations these sat unread in `raw_json`: geoPoint 140,285
(98.3%), zip 133,069, state 99,609, per-location status 41,027, contacts
25,197. Backfilled with no network call. Result: **49,606 of 51,272 sites
carry coordinates (96.8%)**, and 40,011 live edges carry a recruitment status
(RECRUITING 31,442, NOT_YET_RECRUITING 4,481, ACTIVE_NOT_RECRUITING 2,044,
SUSPENDED 903, WITHDRAWN 677, COMPLETED 385, TERMINATED 69,
ENROLLING_BY_INVITATION 10).

**Status is an edge property; place is a site property.** 2,616 site
identities report more than one status across the trials using them — of
course they do, a hospital recruiting for one trial and closed for another is
one place in two states. So `recruitment_status` lives on `trial_sites`;
`state`, `zip`, `lat`, `lon` live on `sites`.

**Where the registry contradicts itself, store nothing.** 109 site identities
are reported at more than one geoPoint, and the disagreement is real rather
than rounding: 103 are 5 km or further apart, **the largest 52 degrees** — the
same facility string placed on different continents. zip disagrees on 3,344
identities, state on 484, and 172 (trial, site) pairs state two statuses at
once. All left NULL and counted in the backfill's output — the same "we can't
tell" the drop reasons use instead of a guess (§2). **A guessed coordinate on
a "trials near me" map sends someone to the wrong country.**

**NULL means "not stated", never "not recruiting."** Only 28.6% of live edges
carry a status, because CT.gov mostly supplies it for actively recruiting
studies. Anything rendering this column must preserve that distinction or it
repeats the step-4 under-reporting bug.

**Naming trap, recorded because it will bite.** One CT.gov per-site status
value is literally `WITHDRAWN`, and `trial_sites` also has our own
`delisted_at`. They are unrelated: `WITHDRAWN` means the site withdrew before
enrolling anyone; `delisted_at` means the trial's record stopped listing the
location at all. A site can be live while reading `WITHDRAWN`.

**Proven able to fail:** seven more mutations — filling a coordinate on a
disputed site, swapping lat and lon across every US site, putting a site off
the planet, keeping a longitude without its latitude, asserting RECRUITING
where no record says so, inventing a status value, leaving the columns
unpopulated. 7/7 red, 14/14 across both harnesses. **The swap case is the one
a range check misses** — most latitudes are also legal longitudes — and it
moves US orientation from 100.0% to 0.0%.

**One test OOM-killed the backend before it worked.** The obvious form of the
coordinate check is a correlated `EXISTS` per site, which re-expands all
142,777 location objects for each of 51,272 sites; pytest died with exit 137
and no readable error. Rewritten as a CTE joined once, the file runs in 15
seconds. **Against `jsonb_array_elements`, a correlated subquery is not a slow
query, it is a dead one.**

## 2026-09-03 — Follow-ups on unit 2b: the OOM had a survivor, and NULL got a guard

**The correlated-subquery problem was not a one-off.**
`test_no_organization_was_invented` was still the slowest test at 9.32s
against ~1.0s for its neighbours — the same shape, matching on `col->>'name'`.
It survived only because 6,207 organizations is small next to 51,272 sites; it
would have degraded quietly as the graph grew. Rewritten as a CTE, the file
went 26.7s → 15.3s.

The precise rule, which "avoid correlated subqueries" gets wrong:
**correlating on `s.nct_id` is fine** — that hits the primary key and expands
one trial's array. **Correlating on a value dug out of the JSON is what turns
linear into quadratic**, because there is no index to reach for.

**NULL got a guard before it got a consumer.** `recruitment_status` is NULL on
71.4% of live edges, and the tempting shortcut — `status == 'RECRUITING'` for
open, everything else closed — would report roughly 100,000 sites as shut that
the registry never described. `format_site_status()` and
`site_status_is_stated()` were added **while nothing consumes the column yet,
which is the cheapest moment to make the wrong thing hard to write.** Six free
tests, including one asserting a missing value never renders with any
closed-sounding word; the shortcut turns it red. `site_status_is_stated`
rejects whitespace rather than using `bool()`, which would call `"   "` a
stated status.

The UI consequences became requirements rather than discoveries
(`plan_explore_nodes.md` §4b): 1,666 sites cannot be placed on a map and the
page must say so rather than silently shrinking the result set; status filters
must offer "not reported" as its own option; site status renders as sentences,
not colour, **because grey would mean both "closed" and "unknown".**

## 2026-09-03 — `withdrawn_at` renamed to `delisted_at`

The column sat in `trial_sites` beside `recruitment_status`, whose CT.gov
vocabulary contains the literal value `WITHDRAWN`, meaning something entirely
different. A schema comment and a UI test were written to hold the
distinction; neither is worth much against a word that means two things in one
table, and the cost only grows — three files read the column then, many more
after the Explore page. **Renamed rather than documented.**

**The migration is the part worth recording.** `schema.sql` is idempotent and
every column is `ADD COLUMN IF NOT EXISTS`, so simply renaming the text of
those lines would have added a second, empty `delisted_at` beside a populated
`withdrawn_at` and quietly stranded 17 stamped edges. The rename runs first,
inside a guarded `DO $$` block firing only when the old column exists and the
new one does not — a no-op on a fresh database and on every later run.
Verified: 4 columns renamed, 0 leftovers, 17 stamps before and after, applied
twice to confirm idempotence.

The prose moved too. Leaving the output saying "withdrawn" would have
preserved exactly the collision the rename was for. **The general rule: check
the source vocabulary before naming a column** — CT.gov already used the best
word for a different fact.

## 2026-09-03 — The graph sync went live, and the first run exposed an inconsistency I had left

`monitor.yml` now runs `scripts/backfill_graph_entities.py` after the ingest.
Run #7 proved it end to end: the same job ingested new trials and wrote 8
organizations, 17 lead edges, 45 sites and 107 site edges untouched by anyone.

**And then the drift checks failed** — not from the sync, but from a gap only
a real rebuild could surface. When delisting was introduced,
`test_no_site_was_invented` was scoped to live edges and the organization and
intervention versions were not. The first rebuild that delisted anything
reported inventions that were nothing of the kind — a trial that changed its
lead sponsor, and two arms a trial dropped. All three had `live_edge=False,
delisted_edge=True`: the machinery worked exactly as designed and the
assertions had not been updated with it.

**The lesson is about how the earlier fix was made:** the sites test was
scoped because it was the one that happened to be red that day, rather than
because delisting had changed what "invented" means for **every** entity. **A
concept introduced in one place and applied in one place is a latent failure
everywhere else it belongs.**

Auditing for that found a fourth case: **investigators had no invention test
at all**, covered only in the losing direction, so a bad JSON path could have
put people into Explore who appear in no trial with the suite green. All four
entity types now assert the same invariant the same way, each mutation-checked
by inserting a fabricated entity *with a live edge* — the case scoping could
have blinded.

**A red CI run was the cheapest possible outcome here.** Dispatching the
workflow rather than trusting a local green is what surfaced it, for the third
time on this project.

## 2026-09-04 — Step 7c: ask what changed, not why it matters

The first batch that really ran (8 stored interpretations, $0.032) was read
row by row, and reading it found three faults.

**`why_matters` is gone.** It was ~48% of output tokens and carried every weak
line in the batch — "potentially affecting recruitment messaging and
stakeholder communication". The `summary` half stayed tethered to the diff and
could be checked against the source text; `why_matters` was speculation about
consequences stored beside it **with equal authority**, which is precisely the
§2 line between reporting a change and inventing its significance. The
audience argument is decisive: told that an adverse-event denominator moved to
all randomized patients, a clinical researcher does not need to be told that
is an ITT shift. The prompt now says "the reader is a clinical researcher who
will judge significance themselves". Output bills at 5x input, so the shorter
answer is also cheaper — but cost was the third reason, not the first.

**The no-change gate matched prose and lost to rephrasing.** It was
`summary.lower() != "no change"`, an exact comparison against a sentence the
model writes freely. The model wrote "No meaningful change—the criteria were
reformatted for clarity", and **a paid call announcing that nothing had
happened was stored as a finding.** The model now fills in
`MEANINGFUL: yes|no` and the gate reads that field.

Reading all 8 rows showed the problem was wider than the one obvious case.
Honest tally: **2 clearly valuable, 2 debatable, 4 reformatting.** The earlier
note that "7 of 8 are real" was written after reading only 4 and was wrong.

**Verified against the rows that broke the old gate**, not just fakes: four
real calls, gate agreeing with a human reading 4/4. Unit tests with a faked
client prove the gate reads the field; only real registry text proves the
model fills it in correctly.

**Billing is measured now, not multiplied.** `COST_ESTIMATE_PER_CALL` was the
recorded spend as well as the pre-flight guess, so the rolling ceiling added
up a constant rather than money. Cost now comes from `response.usage`. That
pairing fixed a third bug: spend had been added only when an interpretation
came back, **so every call returning "no change" was real money recorded as
$0.00** — invisible to the ceiling meant to bound it. Billing now keys on
`cost > 0` (a call happened) rather than on whether the result was worth
keeping.

**Real cost is ~$0.00125 per call, not $0.004** — measured over four calls,
range $0.00066–$0.00297, the spread being input length. The estimate is ~3x
high and left that way on purpose: it is the "may I spend more?" guard, and a
guard that over-estimates stops early while one that under-estimates walks
through the ceiling. It also means the $1.00 rolling ceiling buys roughly 800
calls, not the ~250 assumed when it was set.

## 2026-09-04 — Step 8: the graph becomes visible, and a count that lied

`GET /explore/{nct_id}` and `frontend/pages/4_Explore.py` exist. 191,864 edges
built over three days were reachable from nothing until now.

**The roadmap's order was wrong and was reversed.** Unit 3 (merging
near-duplicate entities) was next on paper, and was deferred: the merge exists
to fix "381 Madrid facility strings are 381 sites", and no page had ever shown
a site list, so there was no evidence the problem was real. **Building it
first would have been step 7 again — a layer measured against nothing.**

**A shared-condition count was written, measured, and thrown away the same
hour.** Run against real data it printed **0 shared conditions for RxPONDER
and its nearest neighbour — two breast cancer trials.** One tags morphology
("Invasive Breast Carcinoma"), the other AJCC stage. Nothing is merged here
either: 7,808 distinct condition strings across 32,701 rows, with `Breast
Cancer` (3,088), `Metastatic Breast Cancer` (325) and `Breast Neoplasms` (285)
as separate strings. **The count measured spelling, not subject matter** — a
false claim wearing arithmetic's costume, the same shape as step 7's filters
wearing a score's costume. Replaced by the neighbour's **own condition tags**,
shown as text: sec. 3 applied literally, source text plus interpretation,
never the conclusion alone.

**Neighbours are three lists, never one.** Sharing a hospital and sharing a
principal investigator are different claims of different strength. Fusing them
into a single "related trials" ranking would rebuild exactly the unexplainable
number `/rank` was deleted for.

**Site overlap partly measures hospital networks, and the page says so.**
RxPONDER's top neighbour shares 1,047 sites; both are NCI cooperative-group
trials in the same ~1,400 US hospitals. Not filtered out — that would drop
real overlaps silently and we could not say how many.

**Every capped list carries its real denominator** — 10 of 1,497 neighbours,
40 of 899 cities, 50 of 1,568 sites. A list reporting its own length as the
total is the step-4 under-reporting bug in new clothes. `count(*) OVER ()`
runs before `LIMIT`, so the denominator costs no extra round trip.

**An investigator table nearly written off.** Its top five names are `Pfizer
CT.gov Call Center` and `Call 1-877-CTLILLY…`, which read as junk. Counting
properly: 76 of 7,722 names carry desk words, 363 of 9,243 live edges look
desk-like (3.9%), and **5,325 names carry an MD or PhD**. The desks are top
precisely *because* a contact desk is reused across 102 trials while a real
investigator is on three. The table is fine; what it rules out is any "most
prolific investigators" ranking, which would be all call centres.

**The fake connection has a blind spot, and it is exactly the dangerous one.**
A planted mutation rewriting the site query to `coalesce(ts.recruitment_status,
'NOT_RECRUITING')` — turning registry silence into a claim a site is closed,
the single worst thing this page can do — **passed all 11 fake-connection
tests**, by design, since the fake ignores SQL. The honesty guarantee lives
entirely in the real-data suite. Nine mutations were planted across both
suites and all nine caught, but **five only by the real-data half.**

**Latency is architectural, not this query.** `/explore` takes ~4.4s; so does
`/watch` at 4.3s and `/changes` at 3.2s. The cost is **1.7s to open a Neon
connection plus ~300–580ms per round trip** from a laptop — a per-request
connection is deliberate, and the fix if it ever matters is colocating the API
with the database, not tuning SQL. Neighbours were folded into the same
endpoint rather than a second one for this reason: one connection, not two.

## 2026-09-04 — The seven interpretations become visible, and a canary for what CI cannot see

**Step 7c's prose interpretations are on screen.** They had been written by
the cron since 2026-09-03 and read by nothing — the same "built, paid for,
unreachable" state Explore was in, at 1/27,000th the size.

**A bug caught during the build, not after.** The first version rendered
interpretations only in the long-text branch. But `primary_outcomes` is a
STRUCTURED field, and **5 of the 7 stored readings are on it** — so most of
the feature would have shipped invisible, which is the exact failure being
fixed. All three branches render it now, and a page test fails if the
structured one stops.

**Attribution is in the element, not in a footnote.** This is the only thing
TrialLens displays that a model wrote rather than computed, so
`labels.render_interpretation` draws the label and the sentence in one block,
and the page test asserts they appear in the *same rendered element* — a
future edit cannot separate them while leaving both technically on the page.
It never replaces the diff: the exact words stay one click away (sec. 3).

**Absence of an interpretation means three different things** — wrong field,
predates 2026-09-03, or the model answered `MEANINGFUL: no` — and the stored
column cannot tell them apart. So the page never implies absence means nothing
important changed.

**A source-text canary for the gap between CI and the cron.** The mutation
that turned an unstated site status into `NOT_RECRUITING` was caught only by
the real-data suite — which needs credentials, so it runs in `monitor.yml` on
the cron and **skips entirely in `tests.yml` on every push.** Between a bad
push and the next cron, CI was green while the claim was wrong.
`tests/test_sql_honesty_guards.py` bans two things across `api/` and
`frontend/`: any `coalesce()` supplying a default for `recruitment_status`,
and the literal `NOT_RECRUITING`, which is not a value CT.gov publishes (a
lookbehind spares the real `NOT_YET_RECRUITING` and `ACTIVE_NOT_RECRUITING`).

**It is a weak kind of test and says so in its own docstring** — reading
source text, not behaviour. It is a canary, not the guarantee, and it asserts
that the real-data test it stands in for still exists by name, so deleting
that one cannot leave these green over nothing.

## 2026-09-04 — Step 8 unit 3: the merge, scoped by measurement and written as a pointer

Units 1-2 extracted everything unmerged on purpose so the registry's own words
survived and any later merge had a baseline. This is that merge.

**Measured before designing anything**, which cut the scope in half:

| table | groups | rows collapsed | of |
|---|---|---|---|
| sites | 2,395 | 3,033 | 51,317 (5.9%) |
| intervention_terms | 650 | 783 | 14,492 |
| investigators | 99 | 111 | 7,722 |
| **organizations** | **0** | **0** | already clean |

Organizations got no column. The symmetric design gives all four tables the
same treatment; the data says one has nothing to fix, and building it anyway
is a merge with no duplicates to merge.

**The "381 Madrid facility strings" that motivated this column are 381
different Madrid hospitals**, not 381 spellings of one. The real duplication
is smaller and dumber: 11 spellings of one Guangzhou cancer centre differing
only in hyphens and capitals.

**It writes a pointer, never a delete.** `canonical_id` is NULL for the ~94%
of rows that are their own canonical form and otherwise points at the row
chosen to represent the group. No row is removed, no edge rewritten, and
setting the column back to NULL restores the unmerged extraction exactly.
**Merging is a judgement about the data, and a judgement written
destructively cannot be revisited** (sec. 3, sec. 4). Same instinct as
`delisted_at`: stamp, never delete.

**The rule is deterministic and deliberately timid** — casefold, collapse
non-alphanumeric runs to one space, trim. No edit distance, no abbreviation
expansion, no model. That is what makes 3,033 merges safe to apply with nobody
reviewing them individually. It merges `Semaglutide` with `semaglutide` (90 +
12 = 102 trials) and correctly does NOT merge `Placebo semaglutide` or
`Semaglutide 2.4 mg` — a placebo arm is not the drug and a dose is not the
intervention.

**Identity boundaries are the dangerous part, so the script aborts rather
than trusting itself.** Sites merge on the (facility, city, country) triple; a
mutation dropping city and country was run and the guard caught it — **8,856
sites would have merged across a place boundary**, reporting trials as running
on other continents. Nothing was committed. Terms never merge across `type`
(`semaglutide` exists as DRUG, BIOLOGICAL and OTHER, and only the DRUG pair
may merge); investigators never merge across affiliation.

What it changed, through the endpoint: RxPONDER's site-neighbours **1,497 →
1,624** (127 trials were invisible purely because they spelled a shared
hospital differently), its intervention-neighbours 282 → 320, Letrozole's
reach 114 → 125, and NCT01740427's **299 sites for 292 real places** resolved
to 292. A collapsed site whose edges disagree about recruitment status
resolves to **NULL, not to one of them** — the same answer a disputed geoPoint
gets.

**A test that passed by luck, found by mutation.** The first endpoint-level
merge test used the busiest trial, which has no duplicate spellings at all —
so removing the canonical join from the API broke nothing and 16 tests stayed
green. The fixture now selects a trial where raw edges and canonical sites
genuinely differ. **This is the second time this session a green suite hid a
real regression, and both times the fixture was the problem rather than the
assertion.**

It runs in `monitor.yml` after the graph backfill, never before: the rows it
must consider are the ones the backfill just inserted. Idempotent — verified
by a second run changing 0 pointers.

## 2026-09-04 — Step 9, Investigate: deterministic analysis, and one number that was wrong by 20x

**The five capabilities are complete.** `GET /investigate` and
`GET /investigate/landscape`, `api/investigate.py`,
`frontend/pages/5_Investigate.py`, and Home's fifth card is live.

**The number that was wrong.** The step-7 removal argument leans on "this
product is deliberately low-volume (~17 changed trials a week)". Measured
against the live record: 2026-09-01 → 09-04 (3.5 days) saw **184 trials
amended, 322 content field changes → ~370 trials/week, ~1,600/month.** **Off
by roughly 20x.** It does not overturn the step-7 decision — that rested
mainly on four of five signals being filters wearing a score's costume — but
the "low volume" leg is not true and should not be cited again without
re-measuring.

**Why Investigate is deterministic.** Every question has exactly one correct
answer: `2027-05-31 → 2026-03-19` is 14 months, `RECRUITING →
ACTIVE_NOT_RECRUITING` happened 13 times, `400 → 163` missed target by 237. A
model computing these could only be slower, dearer, and occasionally wrong.

**External evidence agreed on the agent shape.** A three-agent pipeline
consumes ~29,000 tokens where a single agent uses ~10,000; a five-agent triage
system spent 80% of its tokens on agents describing their work to each other
and was better, 4x faster and a quarter the cost rebuilt as one agent with the
same tools. Multi-agent wins only when the task exceeds one context window or
needs genuinely adversarial roles, and the findings payload is a few KB.
**So: one specialist agent, weekly, reading pre-computed findings — not a
crew.** Costed at ~$0.145/run (a 10-turn loop re-sends its history, so the
$0.00125 measured for step 7c is a single-shot figure), ~$0.63/month against
the existing $1.00 ceiling. The naive per-changed-trial design would be
~$232/month.

**Outcome switching — the finding that came from outside evidence.** The first
feature in this project chosen from published literature rather than from what
the columns allowed. Changing a registered primary outcome after the data can
be seen is a named, measured problem: **31.7%** of registered CT.gov studies
have had one changed (PMC4032105); the change is associated with funding
source at **OR 1.82** (PMC5829948); among 389 trials, the 130 with a change
overstated effect size by **16%** (PMC6646984). An LLM approach reaches **0.97
sensitivity / 0.95 PPV** on detecting them (npj Digit Med 2026) — external
validation that language understanding earns its cost here specifically, which
step 7's ranking never had. The registry records every one of these and
surfaces none. In the record: **17 outcome changes, 5 after the trial's own
primary completion date.**

**The deterministic layer exists to stop false alarms, not raise them.**
NCT03674567 has results posted and changed its outcome after primary
completion — the strongest flag combination available — and the change is
`Safety and tolerability` → `Safety and Tolerability`. Reading real output
then found a second false positive of our own making: NCT05327608 renumbered
its only outcome and punctuation stripping alone left the bare `1` behind, so
it read as a different endpoint. `_LIST_MARKER` strips leading enumeration
first and requires a digit be followed by `.` or `)` **and** whitespace, so
`6-minute walk distance` and `30 day mortality` survive. That moved the split
from 9 substantive / 8 wording to **8 substantive / 9 wording**.

**Flags are listed, never summed.** No score, no confidence number — that is
the invisible ranking sec. 3 forbids and step 7 was removed for. And nothing
here is an accusation: a changed endpoint has innocent explanations and the
record cannot say which, so the page states what changed, when, relative to
the trial's own milestones, and that it **requires review** — sec. 2's
vocabulary, the same one used for eligibility.

**The landscape half, added mid-build.** Investigate initially answered only
"what changed", leaving "what has been done in breast cancer" unanswered
anywhere. Three honesty rules it exists to keep: **the unstated share stays in
the picture** (2,838 of 5,377 breast-cancer trials report `NA` or no phase —
52%; CT.gov's `NA` means the trial does not use phases at all, a real answer
but not a rung on the ladder, so it is counted with the unstated rather than
plotted beside PHASE3); **the current year is not a data point yet** (2025
started 899 trials, 2026 shows 756 in September — drawn at equal weight that
is a decline, and it is the calendar); and **a term's reach is measured
against trials that list any intervention** (4,938 of 5,377), never the slice.

**A self-join that looked like a working chart.** The first intervention query
joined `intervention_terms` to itself on `coalesce(canonical_id, id)`, which
cross-products the table — every term came back with the identical count
4,938. Two aliases is the correct canonical-merge form, and a test asserts the
counts are not all equal, which is the signature.

**Two bugs the tests caught that reading the code did not.**
`analyse_enrollment` reported `None` for the 8 of 20 target-became-actual
switches with no count row in their amendment while its docstring claimed
otherwise — and **the guard never fires on live data**, so it needed a
constructed test; a suite run only against production would have reported it
covered while never executing it. And the page said "No trial changed a
registered primary outcome" when changes existed but none could be *read* —
**an unreadable row is not an absent one**, and that sentence was false.

**One definition per concept.** `classify_date_move` calls
`describe_date_shift` rather than re-deriving its threshold, so the aggregate
and Understand's per-amendment view cannot disagree about whether the same row
moved. Testing the equivalence across the boundary is where the cut-off turned
out to be **>= 14 days counts as a move** — the code was right and the first
draft of the test was wrong.

**Benchmarks, and the denominator trap.** Findings are read against published
baselines: median delay **12.2 months** with ~1 in 5 finishing on time
(PMC9857498, 2,542 RCTs); **19%** of trials missing 85% of target and **55%**
of terminations being low accrual. Ours: 6.3 months median push, 6 of 20 (30%)
below 85%. **31.7% is deliberately NOT plotted** — "studies that ever changed
an outcome" and "changes seen in eight days" do not share an axis, and drawing
them together would manufacture a comparison neither source supports. It is
caption context, and the delay and accrual lines carry the same caveat stated
out loud: ours is a window of amendments, theirs a cohort of completed trials.

## 2026-09-04 — Investigate, read by a human: nine findings, and a chart that lied

Step 9 shipped and was then actually used. Everything below came from that
reading, not from a test — which is the point worth recording.

**The serious one: a chart reporting wrong numbers with full confidence.**
Vega-Lite thins axis labels it decides will not fit. On a numeric axis that is
harmless; on a **categorical** axis each surviving label lands against
whichever bar is nearest. Eight statuses, four labels:

    the chart said        the truth
    Terminated  78        Terminated is 237; 78 is Enrolling By Invitation
    Withdrawn   24        Withdrawn is 69;   24 is Suspended
    Recruiting  1,240     Recruiting is 2,053; 1,240 is Completed

Nothing on screen indicated it. `labelOverlap=False` on every categorical
axis, row height 40px, and `tests/test_charts.py` asserts it on the spec —
3/3 planted mutations caught. **The first fix was worse than the bug:**
`axis=None` on the value-label layer removed the shared axis outright and
produced a chart with no labels at all.

**Why it survived two rounds of looking.** The verification method was
rendering to PNG and inspecting. A PNG export lays out with default spacing;
only the live theme tightens it enough to trigger the thinning. **The
instrument was structurally incapable of showing the defect, so a clean result
from it was not weak evidence — it was none.** Rendering is necessary and not
sufficient; layout guarantees live in a spec assertion.

**A chart's form is a claim.** Enrolment bands drawn as horizontal bars sorted
by length read as a league table ("why is 1-49 winning?"). Nothing was winning
— it is a distribution, and ordered left-to-right columns say so.

**The worst reporting flaw was not the crowding.** "Enrolment against plan"
plotted absolute headcount on a 0-2,000 linear axis, so a trial that enrolled
**13 of 30** — a 57% shortfall — was an invisible dot at the origin beside one
that comfortably hit 2,000 of 1,960. **The most serious miss was the least
visible thing on screen.** The axis is percent of the trial's own target now,
with rules at 100% and 85%; absolute numbers stay on the label because a bare
percentage hides whether a miss was 6 people or 600.

**Six smaller ones, all from real use:** the window selector offered 30 and 90
days over a 7-day record; the growth curve cut the axis at 2010 and *dropped*
the 153 trials that started earlier, the oldest in 1989; its x labels collided
into "2010201120122013"; flagged trials named an NCT ID with no way to open
it; drug bars were a dead end; and Home's results sentence was circular, both
halves saying "posted results" when the distinction being drawn was status.

**The lifecycle chart was called inaccurate and hard to read, and both were
true for different reasons.** Inaccurate: the same label thinning. Hard to
read: bars labelled with semantic buckets ("Finished", "Closed to new
participants, still running") made the reader decode an abstraction first.
Bars are literal movements now — "Recruiting → Completed", 11 — and the
counts reconcile: 1 + 21 + 13 + 12 + 1 = 48, every status change in the record.

**A note on the test suite.** One full run showed 15 real-data errors that
were Neon closing pooled connections under load, not regressions — the failure
mode `api/database.py` already documents, surfacing as a flaky run rather than
a request error. They pass on retry.

## 2026-09-02 — README, CI, and the amendment grouping key

**A README, and CI that actually runs the suite, both added.** Before this
nothing ran the tests automatically. `tests.yml` runs on every push with no
secrets: 226 pass, 22 skip. Those 22 are the real-data and drift tests that
need `DATABASE_URL`; running them without it would either fail on a missing
secret or, worse, silently skip in a way nobody would notice. They run instead
inside `monitor.yml`, on the data's own schedule, immediately after the ingest
that could have introduced drift.

**The amendment grouping key is the trial's own `last_update_post_date`, never
`detected_at`.** A cron run writes one trial's whole diff inside a single
transaction and Postgres's `now()` is transaction-start time, so every row of
one amendment shares an exact `detected_at` — **but a run straddling a
wall-clock minute boundary can still make grouping BY MINUTE split one real
amendment into two.** `get_study_amendments` groups by the field CT.gov itself
moved, so the split cannot happen regardless of when the cron fired.
`api/investigate.py` calls the exact same grouping function rather than
re-deriving the threshold, so the per-trial page and the cross-trial one can
never disagree about how many amendments a trial had.

## 2026-09-02 — `git add -A` committed an installed skill and a 2.4 MB canvas

One `git add -A`, meant to stage that day's real changes, also staged
`.claude/skills/` (an installed skill meant to stay local) and a 2.4 MB
generated design canvas. Both landed in one commit before anyone read
`git status`.

Neither was secret or destructive, so the fix was a follow-up commit removing
them and adding them to `.gitignore` rather than a history rewrite — but the
near miss is why **`git add -A` (and `git add .`) is a standing "don't" for
this repo**: staging has to name files deliberately, and `git status` gets
read before every commit, not after something unexpected turns up in a diff.

## 2026-09-04 — Two cost-estimation numbers worth re-checking before quoting

- **This project's text runs at ~2.61 characters per token**, not the ~4.0
  rule of thumb. Assuming 4.0 understates a token-based cost projection by
  roughly 53%. Clinical trial text — eligibility criteria, outcome measures —
  tokenizes less efficiently than general prose; re-measure on real records.
- **A per-call cost estimate used as a safety ceiling should be measured high,
  not accurate.** Both `COST_ESTIMATE_PER_CALL` and
  `COST_ESTIMATE_PER_TURN_USD` intentionally sit several times above the real
  measured average — a guard that stops one call early because it
  over-estimated costs nothing; one that lets a call through because it
  under-estimated walks straight through the budget it exists to enforce. The
  real average is tracked separately from `response.usage` and is what gets
  billed against the rolling ceiling; the estimate only decides whether to
  attempt the next call.

## 2026-09-05 — Building the weekly synthesis agent: nine build decisions

Nine questions settled before writing code, each with a reason rather than a
pick:

1. **Runtime: a hand-rolled loop against the raw Anthropic Messages API, not
   the Claude Agent SDK.** Zero SDK dependency today,
   `api/prose_interpreter.py` is already a working reference for the
   cost-tracking and error-handling shape, and a 10-turn loop with four tools
   is small enough that a managed framework buys little.
2. **Model: claude-haiku-4-5**, same as step 7c. The $0.145/run costing only
   pencils out at haiku's rate, and the questions Investigate hands the agent
   are pattern-matching over a few KB of pre-computed structure, not
   open-ended reasoning — the same "language understanding earns its cost here
   specifically" bar step 7c passed and step 7's ranking did not.
3. **Trigger: a separate `synthesis.yml` on its own weekly cron**, not a
   day-of-week gate inside `monitor.yml`. That file already runs three
   unrelated jobs every 6 hours; folding in a weekly, budget-gated step means
   every run pays a conditional check for something that fires 1/28th as
   often, and a failure in the new step risks the run record `/watch` reads
   `last_checked_at` from.
4. **Multi-week comparison: both directions, as two tools.** `/investigate` is
   called 3-4 times walking `as_of` back a week at a time, and
   `/investigate/landscape` once for the corpus base rate. `as_of` was added
   for exactly this — a caller can now ask about a week that already ended.
   This mirrors how the human reading of Investigate actually judged the
   outcome-switching finding: against a published external rate, not a single
   window in isolation.
5. **Duplicate avoidance: a real `get_recent_proposals` tool.** The schema
   already commits to "never overwritten, a reviewer can see the agent changed
   its mind" — a good record, a bad reviewer experience if the same finding
   shows up as five unrelated-looking rows across five weeks. A cheap read
   lets the agent say "still true, third week running" instead.
6. **Zero-finding weeks: `synthesis_runs` alone is sufficient.**
   `proposals_created = 0` on a completed run is unambiguous. A synthetic
   "quiet" row in `review_queue` would need its own confidence, finding type
   and evidence to stay honest, and **inventing evidence of absence is exactly
   what §2 rules out.**
7. **Proposal emission: a `propose_finding` tool call per finding**, not one
   JSON blob parsed out of a closing message. Each call's arguments map
   directly onto a row, partial progress survives a run that dies mid-way, and
   "no more tool calls" is a natural stopping signal.
8. **Review queue UI: deferred.** This project's own pattern — Explore's page
   before the merge, Investigate before its evaluation — is build the layer,
   run it against real data, then design the surface once there is something
   real to look at. **A review-queue UI designed against zero real proposals
   is the step-7 mistake in new clothes.** (Built 2026-09-06, when the gap
   became concrete.)
9. **Guardrails: `SYNTHESIS_BUDGET_USD = 0.20`, `SYNTHESIS_MAX_TURNS = 10`**,
   checked against `rolling_budget_remaining()` before the run starts.

**The rolling ceiling became genuinely shared, not just conceptually shared.**
Both features draw from the SAME $1.00/30-day window — a researcher reading a
monthly bill does not care which feature spent the dollar, and **capping them
separately would let the two together spend $2.00 while each guard reported
itself under budget.** `PROSE_ROLLING_CEILING_USD` and
`rolling_budget_remaining()` moved into `api/cost_budget.py`, which sums
`monitor_runs.prose_spend_usd` and `synthesis_runs.spend_usd` in one query.

## 2026-09-05 — First real synthesis run: $0.1099, zero proposals, and why that's not bug #4

The first live run spent **$0.1099** and filed **zero** `review_queue` rows.
Given this project's history — step 7c silently dropped 100% of its writes
twice before anyone read the rows it should have produced — **a zero-row first
outcome does not get believed on the strength of "tests pass".** It gets
checked against what the agent actually saw.

The window was not quiet: 235 trials changed, 276 amendments, 433 field
changes, 8 substantive primary-outcome changes, and one flagged lifecycle
anomaly (NCT06904365, `COMPLETED` → `RECRUITING`). If the agent had nothing to
say about a week that active, that would be a fourth silent-write failure.

It isn't. Re-querying `/investigate` for `weeks_ago=2,3,4` — free, no model
call — returns **0/0/0/0** for every one. Real monitoring only started
2026-08-28, so the run had exactly one prior week of history, and the system
prompt is explicit: *"Compare the current window against at least 2-3 prior
weeks before calling anything a pattern."* An agent following that instruction
literally has nothing to call a trend yet — the corpus is too young. Zero
proposals here is the conservative branch of decision 6 working as designed.

**One loose thread, deliberately left open rather than resolved by
inference:** `propose_finding` allows a standalone `single_trial_flag`
independent of any trend, which is what the reopened-after-finishing anomaly
looks like. Whether the agent considered that trial and judged it not yet
worth attention, or never called `get_trial_amendments` on it, is not knowable
from the run record alone — only a turn-by-turn transcript would settle it,
and that costs another real call. Next week's scheduled run is free to wait
for.

## 2026-09-05 — Step 10 starts: hosting platform, cold-start budget, and the Neon rename finally lands

The roadmap's own candidate list named "Railway/Vercel". Checked rather than
assumed: **Vercel is a serverless-functions platform and Streamlit is a
stateful, long-lived WebSocket server** that needs a real running container —
ruled out before any deploy was attempted, not discovered after one failed.

The choice between Render and Railway took two passes because the first was
under-specified. Render's free tier is permanent but sleeps after ~15 min idle
(30-90s cold start, and worse here because a cold Streamlit waking a cold
FastAPI can stack to 1-2 min); Railway Hobby runs 24/7 for $5/mo base.

**The real constraint wasn't technical — it's a real budget**, and the fix
wasn't picking the cheaper paid tier. It was finding a genuinely free path to
the same reliability guarantee: an external UptimeRobot free monitor (5-minute
interval) pinging both services keeps them from ever sleeping, at $0/mo.
**Decided: Render free tier + UptimeRobot.** Why the two-step matters more
than the answer: the first framing (pay $5-8 vs pay $14) accepted "always-on
costs money" as a given and only asked how much. **The real fix was outside
that frame entirely.**

**The Neon branch rename, flagged since 2026-08-29 and deferred twice, was
done today rather than documented around again.** Old empty `production` →
`production-old-unused` first (avoiding a name collision), then the real live
branch `dev` → `production`. Connection strings are endpoint-based, not
name-based, so nothing else needed to change — verified live, the same
`DATABASE_URL` still connects to the same 11,561-row table post-rename.

**Tracked conditions moved off `config/tracked_conditions.json` into a real
`tracked_conditions` table.** `api/conditions.py` exposes
`list_tracked_conditions(conn)` as a plain function so `discover.py` and
`watch.py` can call it with their own already-open connection instead of
importing a route function outside a request. `scripts/run_monitor.py` reads
the table directly on the connection it already opens for run-record
bookkeeping — consistent with how that script splits its own writes from the
trial-data writes it sends through FastAPI. The JSON file was deleted, not
left stale.

Verified live, not just by test: schema applied to the real database, a
condition added over HTTP, `/discover` and `/watch` both picking it up
correctly, then the test row removed.

Moving `_is_comprehensively_tracked` from a file read to a DB query added one
query to two `/discover` branches, so every existing test that queues a
non-empty `local_rows` result had to queue a second result for it — the fake
DB pops queued results strictly in call order. `tests/conftest.py`'s `api`
fixture now also overrides `get_db`, not just `get_readonly_db`: the first
HTTP-level test in this suite for a write route other than `/studies/batch`.

`render.yaml` written: two web services, **no secret in the file** (sec. 2) —
`DATABASE_URL`, `DATABASE_URL_READONLY` and `API_BASE_URL` are all
`sync: false`, since `API_BASE_URL` cannot be known until Render assigns the
API service's hostname.

## 2026-09-05 — First deploy is live, and an error message put a live password on a public page

Both Render services are up, free tier, Oregon. The API was verified against
the real database from outside the network — `/health`, `/tracked-conditions`
and `/watch` (11,461 trials) all correct over HTTPS.

**Two false alarms, worth recording because the diagnosis method mattered more
than either outcome.** *"The frontend 404s despite Render saying Live"* — the
distinguishing evidence was a response header, not the status code: a 200
carried `x-render-origin-server: uvicorn` (the app answering) and the 404s
carried no such header at all (Render's router, with no instance to route to).
That separated "app is broken" from "no instance is up right now" without
guessing; it resolved on its own as the deploy settled, and repeat probes went
4/4 with a successful WebSocket upgrade on `/_stcore/stream`, which is what
actually has to work for Streamlit. And *"the backend disappeared from the
dashboard"* — it was filed under a project group the frontend wasn't.

**The real bug: `frontend/api_client.py` leaked a credential into user-visible
output.** `API_BASE_URL` on the frontend service was set to the Postgres
connection string instead of the API's URL. `requests` has no adapter for
`postgresql://`, so it raised — and the old error text interpolated *both*
`API_BASE_URL` and the raw exception (which carries the full request URL), so
**the live `neondb_owner` password rendered onto a publicly reachable page.**

The misconfiguration was human. The defect is this project's: **an error
message is user-visible output, and user-visible output must not carry a
credential** (sec. 2, which until now had been read as being about repo
files). Every ingredient was already present — the frontend is public by
default, env vars are pasted by hand, and `requests` puts URLs in exception
text — so this was waiting to happen rather than unlucky.

Fixed in three parts: `_safe_base_url()` reduces the address to
`scheme://host[:port]`, dropping the userinfo and query where secrets live;
`_redact()` scrubs the raw value out of exception text, **since sanitising our
own message is not enough when `requests` embeds the URL in its**; and
`_require_http_address()` refuses a non-HTTP address *before* any request,
with a message naming the variable to fix — converting this exact failure from
a confusing leak into a one-line instruction. **Proven able to fail** (sec. 7):
reverting `get()` failed 3 of its 5 tests. The `https://user:pass@host` case
is covered too — credentials in an `http://` URL are still credentials, so the
fix could not stop at "reject postgres://".

**`requirements.txt` had no version pins — found during this deploy, fixed the
same day.** One file of bare names produced **three different stacks**: this
repo's venv (Python 3.9, streamlit 1.50, pandas 2.3) where all 674 tests
actually run; GitHub Actions, re-resolving on every scheduled run; and
Render's first deploy, which resolved **Python 3.14** with streamlit 1.63,
pandas 3.0 and numpy 2.5. So the suite certified software that was not the
software running — and, worse than any single wrong version, **any rebuild
could change production with no commit to point at**, which is the hardest
class of bug to trace because `git log` shows nothing.

Not theoretical: pandas 2→3 and numpy 1→2 are major releases and the
chart-heavy pages are exactly where that lands. The `anthropic` SDK matters
most — the hand-rolled Messages API loops run against a specific response
shape, and that is the code that spends real money, so a silently-upgraded SDK
means a paid run that fails after billing.

Fixed by pinning the **full runtime closure** (63 packages), not the seven
direct ones — pandas and numpy arrive *through* streamlit, so a top-level pin
would have left the drift untouched. Python is pinned in `.python-version`
(3.9.6). `requirements-dev.txt` is pinned too, since a drifting dev stack is a
suite whose result means something different each week.

**The method mattered more than the diff.** A first pass classified
GitPython/gitdb/smmap as local git tooling and dropped them —
`pip install --dry-run` then showed **streamlit 1.50 requires gitpython**, so
they would have installed anyway but unpinned, quietly preserving the exact
drift being removed. **Classifying dependencies by what they look like is
guessing; the resolver knows.**

Deliberately deferred, with the honest cost stated: Python 3.9 is past
end-of-life, so "deployed == tested" was bought by freezing on an old runtime
rather than by modernising.

## 2026-09-06 — Step 11: the jobs nobody watches get watched

Two unattended processes hold a database credential, an API key and a budget.
Their entire health surface was `GET /watch`'s `last_checked_at` — one
timestamp from one of the two jobs — plus GitHub Actions logs, which expire
and which nobody reads on a good day.

**The gap that mattered is not "a job crashed".** A crash is loud: the
workflow goes red and GitHub emails. **The gap is a job that finishes green
while doing nothing**, and this project has been in that state twice — step 7c
storing zero interpretations for a day while spending $0.168 inside a broad
`except`, and the `LIKE '__%'` cleanup emptying `tracked_conditions`, which had
it gone unnoticed for one cycle would have produced a clean run record
checking zero trials. Neither is visible in a status column that only knows
'completed' and 'failed'.

**`monitor_runs.error` / `synthesis_runs.error` — the third state.** A run can
now say **"finished, but part of me broke"**: `status` stays 'completed' when
the ingest genuinely completed, the error sits beside it, and `/ops/status`
names the combination (`run_degraded`) rather than folding it into either.
`run_prose_interpretation()` returns `(spend, error)` instead of a bare float —
the same lesson as 2026-09-03, one step further: **the money surviving the
exception was not enough, the reason has to survive too.** The budget-skip
path deliberately writes **no** error: a ceiling refusing a call is the guard
working, and recording it as an error would report a degraded run every week
the budget did its job. One fact, one alert.

**`api/safe_errors.py` — the 2026-09-05 leak's second door.** That incident
went config → exception text → public page and was fixed for the frontend's
own HTTP errors. This step opens a different route to the same place: a cron
catches an exception, writes it to a database column, an endpoint reads it
back, and a page prints it — and the cron is exactly the process holding
`DATABASE_URL` and `ANTHROPIC_API_KEY`. `scrub()` is belt-and-braces on
purpose: exact replacement of the secret *values* this process holds (cannot
be defeated by an unexpected message format), plus redaction by *shape* — a
`user:password@host` userinfo block, an `sk-ant-` key — **which is what
catches the credential this process did not know it had.** Truncation last,
because an error column is not a log. Scrubbed again on the way out of
`/ops/status`, for rows written before the guard existed. Mutation-checked
both directions: removing the shape rules kills 3 of 12 tests, removing the
exact-value replacement kills 1.

**`GET /ops/status` — deterministic, and a list, never a score.** Every
question has one correct answer computable from two tables, so no AI (sec. 5).
And **the verdict is a list of named conditions each carrying its own
measurement, never a summed health index** (sec. 3) — "two alerts" is not
twice as bad as one, and a stale monitor and an exhausted budget are different
problems with different responses. `is_healthy` means "no critical alert", not
a threshold on a number.

Severity is split so the alarm keeps meaning something: a stale *monitor* is
critical (TrialLens's central claim has stopped being true), a stale
*synthesis agent* is a warning (a missed week of advisory output). Zero trials
checked is critical; **zero proposals filed is not a fault at all** — the
first real run filed zero because it had one week of history, and an agent
that finds nothing and says so is working.

**Every rule is an incident, not ops boilerplate:** `job_did_nothing` and
`no_tracked_conditions` from the wiped registry, `run_degraded` from step 7c,
`run_stuck` from `run_monitor.py` deliberately leaving a dying run's row as
'running', and `budget_exhausted` because a guard that silently stops guarding
looks exactly like a guard with nothing to do.

**The escalation is the workflow going red.** `scripts/check_ops_health.py`
runs as the last step of `monitor.yml`, reads `/ops/status` over HTTP (it
holds no database credential of its own), and **exits non-zero on a critical
alert** — GitHub's own failure notification is then the alarm: no email
provider, no account, no extra secret, nothing new that can itself break.
Step 12's Resend digest is a product feature for a researcher; **wiring an ops
alarm through it would make an outage depend on the notification system that
outage might have taken down.** Warnings do not fail the job — a red build for
something nobody must act on today is how red builds stop meaning anything.
An unreachable API *is* critical: a check that returns "fine, I couldn't
check" is a green tick attached to no evidence.

**What live data corrected.** The endpoint answered on the first call and
immediately corrected an assumption written into a comment ten minutes
earlier. The expectation was that GitHub's best-effort scheduler skips slots,
so runs would trail the schedule. The record says the opposite: **17 monitor
runs against 13 scheduled slots**, because `monitor_runs` cannot tell a
`schedule` run from a `workflow_dispatch` one and several were dispatched by
hand while debugging. The denominator needed the same honesty the capped lists
already have: measured from the job's **first run**, not the window's start.
The synthesis agent is one week old against a 28-day window, and dividing
window by cadence reported "1 of 4" — **a 75% miss rate invented entirely out
of history that never existed.**

**A test that was passing for the wrong reason.** Adding the error half of the
contract immediately caught one: `test_nothing_is_called_once_the_ceiling_is_
reached` was passing *through* the exception path. `StubConn` had no
`close()`, so the ceiling-refusal branch raised `AttributeError`, the broad
`except` swallowed it, and the old `== 0.0` assertion accepted the error
path's return value as proof the refusal worked. The claim happened to hold;
the code being exercised was not the code under test. **Once the function also
returns *why* it stopped, "returned 0.0" and "returned 0.0 because it crashed"
stop looking the same.**

**A mutation-testing gotcha.** Mutating a file and restoring it inside the
same shell command produced a run where the restored, correct code appeared to
fail — long enough to nearly "fix" working code. **Diff the restored file
against the backup before believing a post-restore result.**

Deliberately not here: no uptime pinging of the deployed services, no alert
history table, no paging. This step is about the jobs that write data and
spend money, which are the ones whose failures are silent.

## 2026-09-06 — Step 10's last item: the uptime monitor that reported a false outage

Keep-warm pings are live (UptimeRobot free tier, 5-minute interval, two
monitors, $0), closing step 10. The Neon `Default` flag was also moved off
`production-old-unused`, with the live database verified unaffected.

**The part worth recording.** The API monitor reported **Down for its entire
existence** while the service was demonstrably up and answering in 0.4s. Not
an outage and not a false alarm exactly — a protocol mismatch: UptimeRobot's
HTTP monitors send **HEAD** by default, FastAPI's `@app.get("/health")`
returns **405** to HEAD, and any non-2xx reads as down, so the monitor had
never once succeeded. Streamlit's `/_stcore/health` accepts HEAD, so the
frontend monitor was fine throughout — **a useful asymmetry that pointed at
the request method rather than at either service.**

Two premium-only fixes were dead ends on the free plan. The free fix is a
**keyword monitor**, which sends GET — and checking that the body contains
`ok` is a *stronger* check than HEAD anyway: a HEAD monitor only proves
something answered, while this proves the app answered correctly. An empty 200
or a Cloudflare error page would pass the first and fail the second.

**The keep-warm still worked the whole time it was reporting down.** A failed
HEAD request still reaches the container and resets its idle timer, so the
service never slept — the 0.4s response times prove it. The monitor's
*reporting* was broken; its actual job was not. **Worth separating those two
before treating a red dashboard as an outage.**

**Diagnostic note, general.** When a failure could come from any layer, find
what identifies *which layer produced it* — a header, an error format, a body
shape. A plain-text `Not Found` body versus FastAPI's JSON
`{"detail": "Not Found"}` separates a Starlette default from a real route the
same way the `x-render-origin-server` header separated the app from the
platform router.

## 2026-09-07 — The first clinician judgments of real TrialLens output

Since the ranking layer was removed this project has carried an unanswered
question: **no clinician had ever judged a real TrialLens output.** Every
claim that a flag is useful was second-hand — literature, reasoning, or the
agent's own say-so.

Four flags have now been read and judged by the user, a clinician, on live
deployed output: NCT05872620 **dismiss** (endpoint unchanged; entry fleshed
out when results were posted), NCT04315233 **dismiss** ("change in
terminology, with similar description"), NCT04276493 **significant**
("outcomes were merged, time frame extended"), NCT04570956 **significant**.
Two of four dismissed — on a sample of four that is not a false-positive rate
and must not be quoted as one.

**The most useful finding is a caveat the user attached unprompted, and it is
the thing most likely to be misapplied later.** On NCT04315233 they dismissed
the flag *and* immediately ruled out generalising it: *"i would dismiss but
not make it a pattern i.e. some changes in terminology are significant unlike
this one."* So **"terminology change → dismiss" is exactly the rule that must
NOT be written.** What made this instance dismissible was narrower: the **old
description already stated what the new title says.** The meaning was
recoverable from the record on both sides; only the label moved.

That points at a real defect: **the flag compares measure NAMES and ignores
descriptions**, and the description is where the meaning lives. A future
improvement is to compare the pair — and per the caveat, that can only ever
DE-escalate a specific case, never auto-dismiss a category.

**What the two "significant" calls have in common** is also informative, and
neither is a wording question: one merged two primary outcomes into one and
extended its window; the other replaced a purpose statement sitting in the
measure field with a specific Ki67 endpoint and moved the time frame from 48
months to 4 weeks. **Both changed the *shape* of what is measured, not its
label.**

**Method note.** Before these judgments the agent asserted that ~31% of
surviving flags matched the first dismissed case, from a heuristic written on
the spot. Reading the three cases it selected showed none of them was that
pattern. The claim was withdrawn before the user acted on it. Recorded because
it is the second time in two days a general claim was made ahead of the
evidence: **the heuristic produced a number, and a number reads as a
measurement even when it is a guess with arithmetic attached.**

## 2026-09-07 — All twelve substantive outcome flags, judged by a clinician

The user has now read and called **every substantive primary-outcome change on
file — 12 of 12.** (Corrected count: 22 changes total, 12 substantive, 10
reformatting-only. An earlier entry said "nine remain", which was wrong; the
page listed only 8 of the 12, so four had never been displayed to anyone.)

**Significant — 9:** NCT04276493 (two outcomes merged, window extended),
NCT04570956 (purpose statement replaced by a Ki67 endpoint, 48 months → 4
weeks), NCT03244722 (5 outcomes → 3, time frames stretched), NCT05864144
(title annotated "Part C was never initiated" — significant because *a
researcher needs to know a trial did not start something it said it would*),
NCT05756166 (title corrected to match its own description, but observation
window narrowed 2 years → 13 months **after results**), NCT05838417 (the
"reactions to mammography **harms**" outcome deleted while the "benefits" half
survived), NCT06400472 (drug renamed, cycle length 21 → "21 or 28" days,
windows 48 → 60 months, an outcome added), NCT05846789 ("tocilizumab" →
"tocilizumab **biosimilar**"), NCT05868226 (three outcomes gained scope
qualifiers restricting which arms they apply to).

**Dismissed — 3:** NCT05872620 (entry fleshed out at results posting),
NCT04315233 (terminology, description equivalent), NCT06803888 ("mean
percentage weight loss" → "mean percentage **total body** weight loss").

**9 of 12 were worth a researcher's attention. The flag is not noisy.** That
is the first measured answer to the question `verify_ranking_results.md` asked
and never got, and it argues against loosening the filter's bias.

**Two judgments corrected the agent's own reading**, which is the point of
having a clinician do this. On NCT05756166 the agent leaned toward dismissing
the narrowed window as registry housekeeping, reasoning that a DLT period is
protocol-defined and short; the user overruled — **narrowing an observation
window after results are known is concerning on its face, whatever the
protocol says.** On NCT05864144 the agent read "Part C was never initiated" as
a harmless annotation; the user read it as exactly what a researcher must
know, because it records that a planned arm never happened.

**Three blind spots in how the flag is computed**, all surfaced by these
readings rather than by tests:

1. **Time frames are ignored** — a trial that kept every endpoint name and
   halved its observation window would not be flagged at all. **A false
   negative, and the more serious kind: a false positive costs a reviewer
   seconds, a false negative is never seen.**
2. **Descriptions are ignored**, where the meaning often lives.
3. **The 10 reformatting-only changes are hidden from the page entirely**
   (`if change["wording_only"]: continue`), counted but not listable — so the
   filter is trusted rather than auditable, and nobody has ever read them.

**Agreed order of work, and why it is not the obvious one.** Time frames
first, descriptions second. Fixing descriptions first looks appealing — it
reduces false positives — but would have auto-dismissed NCT05756166, whose
descriptions are identical on both sides and which the user judged significant
precisely because of its time frame. **A description match may only ever
de-escalate when the time frame is also unchanged**, and never as a
categorical rule. The default bias stays timid.

**Also agreed: stop sending reformatting-only records to the weekly agent** —
the agent pays tokens to read changes the system has already decided are not
worth attention. Kept as a count rather than dropped, so the agent still knows
they happened without paying to read them, and does not silently inherit a
filter that has known blind spots.

## 2026-09-07 — Fixing the two gaps the clinician review found

Parts 1 and 2 of the agreed order. Part 3 is deliberately left for a later
session — it needs design, not a patch.

**1. Observation windows are now compared.** `outcome_windows()` reads
`time_frame` per outcome, keyed by the NORMALISED measure name so a window is
still compared across a pure re-capitalisation of its own measure.
`wording_only` becomes `not added and not removed and not window_changes` —
which is the whole correction: a trial that kept every endpoint name and
shortened its follow-up used to be filed as reformatting and then suppressed
from the page by that classification. Measured against the live record, the
reclassification is exactly the two cases the review found and nothing else:
**wording_only 10 → 8, substantive 12 → 14.**

**No direction is computed.** `before` and `after` are the registry's own
strings. "Week 39 → Week 33" is obvious to a reader and a guess to a parser —
CT.gov time frames are free text ("12 months", "up to 2 years", "Baseline,
6-months, and 10-months after the start of the study") — and deriving
"shortened by six weeks" from that would be a computed claim about a study
fact of exactly the kind sec. 3 rules out. The reviewer reads both values and
judges.

**2. The reformatting bucket is collapsed, not hidden.** The page's
`if change["wording_only"]: continue` was the reason four real changes were
invisible, so it is replaced by an expander listing them with their flags —
**the filter is now auditable rather than trusted.** The caption states the
remaining limitation in plain words, so the expander does not read as a
guarantee.

**Proven able to fail** (sec. 7): reverting the classification fails
`test_a_moved_window_under_an_unchanged_name_is_substantive`. Four new tests,
all built from real records rather than invented ones, including two guards
against over-correcting — capitalisation with an untouched window must still
de-escalate, and a window on a newly ADDED measure must not be reported as
"moved" when the addition is already reported.

**What this does not fix, stated so it is not mistaken for done.** The four
hidden changes were two windows (fixed here), one comparative endpoint
becoming descriptive, and one changed analysis method. **Both of the latter
live in descriptions and remain invisible.** They are at least listed in the
expander now, so a reader can reach them, but the page still cannot tell you
that anything moved inside them.

## 2026-09-07 — Descriptions, the third blind spot, and a cap that quietly undid a fix

**1. Endpoint descriptions are compared now.** `outcome_descriptions()` reads
`description` per outcome, keyed by the normalised measure name, the same
shape `outcome_windows()` already used. **A description is where an endpoint
is actually defined** — the measure name says *what* is counted, the
description says how it is measured, compared and analysed — and nothing had
ever read it. `describe_description_move()` returns which of three things
happened, read off the record rather than judged: **added** (the entry was
silent and now speaks), **edited** (both sides define it, differently), or
**removed**.

**2. Only an edit or a deletion escalates. An addition does not, and that is
the whole design decision.** Measured against the live record first, because
the naive rule is very wrong: treating *any* description difference as
substantive moves **8 reformatting changes down to 1**, which would gut the
filter. The `added` exclusion is not a convenience —

- The clinician dismissed exactly this pattern (NCT05872620, "entry fleshed
  out at results posting").
- It would invert this module's own worked example: NCT03674567 has results
  posted and is past primary completion — the strongest flag combination
  available — and its only real move is "tolerability" gaining a capital T.
  Escalating it turns the documented demonstration that the normalisation
  works into a flagged trial.
- And it is true rather than convenient: **you cannot diff against silence.**
  A description appearing where there was none says the registry entry is more
  complete, not that the endpoint moved.

An added description is still *listed*, with its text. **Not escalated is not
the same as not shown.**

**Measured effect: wording_only 8 → 3, substantive 14 → 19.** The honest
breakdown of those five is three-and-two, not five-for-five. Three are real —
NCT06635980 ("will **compare** grade 3+ RT adverse events... Arm 1 versus Arm
2" became "will **assess the occurrence of**", a between-arm comparison
becoming a single-arm observation), NCT07160530 (dropped "quantified using
MyPlate categories and"), NCT05327608 (the operational definition of adherence
replaced by a statistical one). Two are trivial: "(0-10)" → "(0-10 scale)" and
"We" → "The investigators".

**No deterministic rule separates them.** Both change real words, so
`is_formatting_only` cannot catch them; the only thing that would is a
threshold on how many words moved, **which is a tuned knob whose reasoning is
invisible — the thing sec. 3 forbids and step 7 was removed for.** Two extra
cards costing a reviewer seconds is the honest price, and the review's own
finding says which way to err. Stated here rather than tuned away.

**3. The weekly agent gets substantive changes only.** `GET /investigate`
takes `include_reformatting` (default true); `get_window` sends false. The
**counts are computed before the filter and are identical either way**, and
the payload carries `reformatting_listed` so nothing has to infer the filter
from a short list. The tool description tells the agent in words that
`wording_only` means "changes not shown to you", not "changes that did not
matter" — **the agent must not silently inherit a filter with known blind
spots.**

**Do not quote this as a cost saving without the caveat.** It removes 3 rows
of 11, saves nothing at all in a window with 8 or more substantive changes
because `NAMED_CAP` binds first, and the description text this same session
added is *heavier* than the rows removed. Net effect on the weekly bill is
roughly neutral. The real argument is quality: the agent no longer reads rows
the deterministic layer already judged to carry nothing, so it cannot build a
"pattern" out of capitalisation edits.

**4. A cap written for one section had silently undone a fix written for
another** — the more serious finding of the session. That morning's entry says
the reformatting bucket "is replaced by an expander listing them with their
flags". Against the real record it listed **nothing**. `changes` was capped at
`NAMED_CAP` (8) over a list sorted substantive-first, and the record holds
more than 8 substantive changes — so the reformatting rows fell off the end.
**The page printed "3 reformatting only" in a caption above an expander that
could not render, and the four changes a clinician had found hidden that
morning were hidden again by lunchtime, by a different mechanism.**

It passed every test because **both suites asserted on the classification,
never on what survived the cap.** The fix is a cap **per bucket** — each gets
its own room — plus the missing sentence: the page now says "Showing the first
8 of 19 substantive changes", which every other capped list already said and
this one did not.

**Proven able to fail** (sec. 7): seven mutations, all caught, each restore
diffed against its backup before the result was believed. 34 new tests. The
real-data half checks the properties that survive re-ingestion — every
reported diff is re-derivable from the stored values, no reformatting-filed
change carries an edit or a deletion, and the reformatting bucket actually
reaches the reader. **The page was additionally rendered against the real
`/investigate` payload, not only against fixtures, because fixtures are what
hid the cap fault.**

**Still not fixed, so it is not mistaken for done.** The comparison reads
three fields of a primary outcome — name, time frame, description. A change to
a secondary outcome, to which arm an endpoint applies to, or to anything else
in the record is invisible to it, and the page's expander now says so in those
words.

## 2026-09-07 — Three categories, and the agent stops reading case notes

**1. "Reformatting only" was a false label.** The morning's rule was binary:
an edited or deleted description escalates, an added one does not. The
reasoning still holds. **The label was wrong.** A change with a definition
filled in was filed under "reformatting only", and nothing about it was
reformatted: a fact appeared in the registry that was not there before. The
user's objection was sharper than "too strict" — *it can be important in some
cases* — and the binary rule had no way to say so, worst of all when a
definition appears **after results are known**, which is exactly when a reader
would want it, and which the old label actively hid.

Two buckets could not hold three cases, so there are three:

| Category | Meaning | Live |
|---|---|---:|
| `substantive` | a measure name, observation window, or surviving endpoint's definition **moved** | 19 |
| `entry_completed` | a definition was **filled in** where the entry was silent — a more complete record, not a moved endpoint | 2 |
| `reformatting` | capitalisation, punctuation, list numbering | 1 |

`OutcomeChange.wording_only` (bool) became `OutcomeChange.category` (str). **A
pair of booleans would have permitted an impossible both-true state; one field
cannot contradict itself.**

**Every category keeps its own milestone flags**, which is what makes this
sufficient rather than a rename. A definition filled in on a trial past its
own primary completion date, with results posted, says so on its own card —
and the reviewer judges. Facts listed, never summed (sec. 3).

**The rejected alternative, and why.** Escalating an added description
whenever a risky flag is present sounds better and fails on the data: both
live cases are past primary completion *and* have results posted, so that rule
flags both — including NCT03674567, which the user and the record agree is
genuinely nothing. **A flag cannot carry this distinction. A named category
can.**

**2. The agent was being handed case notes to answer a question about
totals.** "How can we genuinely reduce cost?" — so it was measured rather than
argued. One `GET /investigate` response is **39,972 characters, 12,707
tokens**: outcomes 10,228 (27.6%), dates 9,147 (24.7%), lifecycle 8,091
(21.8%), enrollment 6,002 (16.2%), scope_exits 3,196 (8.6%), **window 277
(0.7%)**. Everything except `window` is a capped list of individual trials,
built for a human to click. The agent's question is arithmetic over counts,
and its own prompt tells it to read 2-3 prior weeks — and **the Messages API
is stateless, so window 1 is re-sent on every turn after it: the loop paid for
those cards five or six times over.**

**`GET /investigate/summary`** returns every count, median and denominator
plus the bare NCT IDs behind each finding: **4,099 characters — 89.7%
smaller.** Detail comes from `get_trial_amendments`, which the agent already
had, for the one trial it actually wants to name. Modelled over a five-window
loop at this project's measured 2.61 chars/token, the conversation ends at
**10,288 tokens instead of 78,984** and the loop's input cost falls **$0.2443
→ $0.0382, 84%.** Treat the ratio as the finding and the absolutes as a
projection on today's record.

Two things this route deliberately does NOT do. **It does not re-derive
anything** — it calls the same `_analyse_window` the page does, so the two can
never disagree about a number. Extracting that helper was forced by a real
bug: the first draft called `investigate()` directly and got `Query(...)`
*objects* where the defaults should be, the same class of mistake sec. 7
records about testing a route by calling it. And **it does not add a cap** — a
first draft had `SUMMARY_ID_CAP = 20`, which can never bind because the lists
are already capped at 8 upstream: **a number in the code claiming to do
something it does not**, the same shape as the morning's cap fault and
harmless only by luck.

**3. Not buying a foregone conclusion.** The first live run cost $0.1099 and
filed zero proposals, correctly — the outcome was determined before any money
was spent, and "does the record hold two prior windows" is a database question
(sec. 5). `prior_windows_available()` now asks it before the budget is
committed. **`MIN_PRIOR_WINDOWS = 2` is read off the agent's own system
prompt** ("at least 2-3 prior weeks"), not picked, and a test asserts the
prompt still says so — otherwise this enforces a rule nobody stated.

**A failed lookup returns `None` and does NOT skip.** The dangerous failure
here is the inverse of the one being fixed: a transient API blip silently
skipping a week is precisely what step 11 was built to make visible. And a
skip writes `skipped_reason`, never a plain `completed` with zero proposals —
**that reads identically to a week the agent examined and found quiet**, which
is the one thing this record must never blur.

**4. The chart's third colour was computed, not chosen.** Three categories
needed a third fill. The obvious middle — the palette's amber — measured
**ΔE 13.7 against its neighbour for normal vision, under the floor of 15**:
full-colour readers would struggle to tell the segments apart. It looked fine.
The shipped alternative measures 33.6 normal and 24.7 on the worst CVD
simulation. **Adjacent-hue separation is computable, so it was computed.**

**Proven able to fail** (sec. 7): six mutations, each restore diffed against
its backup. **One of them lied the first time** — the runner passed two test
paths as a single quoted argument, so pytest never ran and the mutation read
as "caught nothing to report". Re-run correctly, it killed four tests. Same
lesson as 2026-09-06: **verify the mutation actually executed.**

**Considered and not done: prompt caching.** Real, and verified applicable —
but partly redundant once the payload shrank by 89.7%, and it carries a trap
worth recording: **Haiku 4.5 has the highest minimum cacheable prefix of any
current model, 4,096 tokens.** This agent's static prefix (system prompt plus
tool definitions) measures **1,918 tokens**, so a breakpoint placed there —
the obvious placement — would have cached *nothing*, silently, with no error
and a bigger bill. Deferred, not rejected.

## 2026-09-07 — Step 12: the digest, and the two things a researcher asked for

The last unbuilt step. Deterministic throughout (sec. 5): which changes
happened, how many, and what the record states about each all have exactly one
correct answer, and formatting a list of facts is not a language-understanding
problem.

**The external-service risk mostly evaporated, for a reason worth recording.**
Resend's docs say plainly that *"you must add and verify at least one domain
to send emails with Resend"* — which for a project with no domain reads as a
blocker. It is not: the shared `onboarding@resend.dev` sender needs no DNS at
all, and its one restriction is that it *"can only send emails to the email
address associated with your Resend account."* **For most products that
restriction is fatal. TrialLens is one researcher's tool and the digest goes
to that researcher, who is the account owner** — so the restriction is a
perfect fit rather than a limitation. If TrialLens ever mails a second person,
`DEFAULT_FROM` is the single line that changes, and it fails loudly with a 403
rather than silently not arriving.

**What leads, chosen by measuring.** Substantive primary-outcome changes,
named individually; everything else as counts. Two reasons, both numbers: it
is the finding outside evidence says matters and the only one a clinician has
scored (9 of 12 worth attention), and it is the only finding at a readable
volume — a weekday carries **65-136 changed trials**, which nobody will read,
against **0-5 substantive outcome changes**, which is a morning's worth.

**Two corrections from the user, mid-build.** *"Don't need empty email"* — a
mail that says nothing happened teaches the reader to skim, and then the one
that matters is skimmed too, the same argument `check_ops_health.py` already
makes about a workflow that goes red for nothing. An empty window closes the
run as **completed with a `skipped_reason`**, advancing the window because
there was genuinely nothing in it. Deliberately *not* defined as "no outcome
change": a window with 68 trials updated and 36 timeline moves has plenty to
say, it just has no endpoint change to lead with.

*"Sat-sun remove from email"* — weekends carry 1-7 changed trials against a
weekday's 65-136 and have never yet carried a primary-outcome change. **The
obvious implementation is wrong, and the trap is worth writing down: a rolling
"everything since the last digest" window cannot exclude the weekend, because
"since Friday 07:00" necessarily contains it** — and clipping the start to
Monday 00:00 would silently drop everything filed after Friday breakfast, a
whole working day. So the window is **one whole weekday**, not a rolling 24
hours: Tue-Fri report the previous calendar day, **Monday reports Friday**.

**The run record, because this is the third unattended job.** `digest_runs`
mirrors its two siblings and `/ops/status` gets a third `JobSpec`. Two
settings are not copied blindly: `stale_after_hours` is **96, not 48**,
because the Friday-to-Monday gap is 72 hours by design and a tighter threshold
would fire every Monday morning about a job that ran exactly as intended; and
`zero_work_is_a_fault` is **False**, because 5 of the record's first 10 days
had no substantive outcome change and counting that as a fault would alert on
half of all correct runs.

A failed run does **not** advance `covered_until`, so a failed Tuesday is
caught up by Wednesday rather than mailed to nobody. That recovery window can
span a weekend — the one place weekend rows are allowed through, because two
quiet days in a catch-up mail cost far less than a working day that reached no
inbox.

**Three details that are not incidental.** The per-trial link goes to
**ClinicalTrials.gov**, not to TrialLens: it is the source of every fact in
the mail (sec. 4), needs no login, and will outlive any URL of ours — the
TrialLens links are for the aggregate views CT.gov cannot show.
`2_Understand.py` now reads `nct_id` off the query string: three lines,
without which every mail could only say "go and search for this". And **no
SDK** — `requirements.txt` is a pinned 63-package closure and adding a
dependency for one JSON POST would mean re-pinning the whole thing.

**Sec. 2 applies at least as strictly here as on the page**, because an email
is read in an inbox, away from anything that explains itself. The subject line
is held to it too — "3 primary-outcome changes to review" states what is
waiting, where "3 trials changed their endpoints after results" would be an
accusation in a notification bar. Seven forbidden words are asserted absent
from subject, text and HTML.

**One real defect the live dry run found**, which no fixture would have:
NCT06400472 renamed its drug and touched every endpoint it registers,
producing **12 bullet lines** for what a reader would call one change. Capped
at 6 — with the remainder counted in the line that follows, never silently
truncated, because a silently shortened list is the cap fault found earlier
that day in a new place. Summarising the twelve into "the drug was renamed"
would be an interpretation of a study fact, which sec. 2 does not allow.

Composition is **52 free tests** — no network, no database, no Resend account,
no email sent — the same free-test-first rule sec. 7 states for paid model
calls, applied to an external service.

## 2026-09-07 — The weekly agent died on a real schedule, and took its receipts with it

Run #2 of `synthesis.yml` failed at 13:04 UTC. Two distinct bugs, neither
introduced that day. The second is much the worse.

**Bug 1 — an empty user message.** `messages.8: user messages must have
non-empty content`. The loop only builds `tool_results` when
`stop_reason == "tool_use"`, which should guarantee at least one `tool_use`
block. **On the sixth turn the model returned that stop reason with no
tool_use block**, so the list was empty and the request was rejected outright.
Fixed by refusing to send it: an empty tool-result list can never become valid
on a later turn, so the loop stops — **with an error, not quietly**, because a
run that ends here files nothing, which is otherwise indistinguishable from a
week the agent examined and correctly found quiet. The recorded message names
the content types that did come back, so a recurrence explains itself.

**Bug 2 — the spend went missing, and a comment said it could not.**
`ERROR after $0.0000 spent` — after five paid calls. The caller was:

```python
spend = 0.0
try:
    proposals, spend = run_synthesis(...)
except Exception as exc:
    # Whatever was spent before the failure must still reach the run record
    print(f"  ERROR after ${spend:.4f} spent: ...")
```

**The comment is right and the code cannot do it.** `proposals, spend = ...`
never binds when the callee raises, so `spend` is still its initialised `0.0`.
Real money — five Haiku calls over a growing conversation — was recorded as
zero against the rolling ceiling that exists to bound it.

This is the *same* accounting hole as 2026-09-03. It was written up, the
lesson was stated in a comment at the new site, and **the new site had it
anyway. A comment describing an invariant is not the invariant.** The tell in
the log was the number, not the exception: `$0.0000` after five calls is
arithmetically impossible.

Fixed by changing the contract: `run_synthesis()` now returns
`(proposals, spend, error)` and catches its own exception — the shape
`run_prose_interpretation()` already uses for the same reason, so both paid
paths now fail identically. The caller banks the spend, keeps any proposals
filed before the failure (discarding them would spend the money twice), and
*then* exits non-zero so GitHub's notification still fires. Five new tests,
including one asserting the literal string `"0.0000"` never appears as a
post-failure spend, because that number is what exposed this.

**What this says about the ops surface.** `/ops/status` would have shown the
failed run — the alarm worked. What it could not show was that the run had
*cost* something, because the row said $0.00. **A health surface that reads
its own job's self-report inherits that report's bugs**, and there is no
independent check on spend short of the provider's own billing.

## 2026-09-07 — Pushing it found two more things, both from watching it run

Step 12's first live send worked (Resend id `3ff01a1f`, `digest_runs` #1, 4
outcome changes named). The synthesis dispatch behaved exactly as designed —
skipped at $0.00 for insufficient history, clearing the critical alert from
that morning's failure. Then two problems that only appear once the thing is
actually running.

**1. Every Tuesday would have leaked the weekend back in.** The window logic
looked right in isolation and was tested that way. Feeding each run's
`covered_until` into the next — a week's simulation rather than one call —
showed this:

    Fri run: covers Thu -> Fri  (1d)
    Mon run: covers Fri -> Sat  (1d)
    Tue run: covers Sat -> Tue  (3d)   <== the weekend, back again
    Wed run: covers Tue -> Wed  (1d)

Monday's digest reports Friday, so it leaves `covered_until` at **Saturday
00:00** — always earlier than Tuesday's Monday 00:00 — and the catch-up test
`previous_until < since` therefore read the *deliberate* weekend gap as a
missed run, every single week. The comparison has to be against what a
**healthy predecessor** would have left, not against this window's own start.
Recovery still works: a genuinely missed Monday leaves `covered_until` at
Friday 00:00, which *is* earlier than that.

**The lesson is about the test, not the code.** Every window assertion passed,
because each was written against a single call with a hand-chosen previous
value. **Only feeding the output of one run into the next exposed it.**
Stateful cadences need a simulation, not a table of independent cases — there
is now a test that walks Fri→Fri and asserts no window is ever longer than a
day. A second guard came with it: a window already covered sends nothing,
because a manual dispatch or a double-fired cron would otherwise mail an
identical digest, **and a duplicate is worse than an empty one — the reader
cannot tell it from a day that genuinely repeated.**

**2. A correct skip was failing the build every six hours.** The history
precondition worked, and `work_skipped` fired at **CRITICAL**, which fails
`monitor.yml`. The agent had done the right thing and the alarm went off — for
a condition **no action can clear**. More prior weeks cannot be conjured; it
resolves with calendar time. `monitor.yml` would have run red four times a day
for a fortnight.

That is the exact failure `check_ops_health.py`'s own docstring warns about:
*"a workflow that goes red for something nobody needs to act on today is a
workflow people learn to ignore, and then the one real alarm is ignored too."*
The rule was written for the budget skip, where a human genuinely must decide
something, and inherited by a skip where nobody can. Severity now splits on
whether the skip is **actionable**: `SELF_RESOLVING_SKIPS = {history, empty,
duplicate}` are WARNING; **`budget` stays CRITICAL, and so does any prefix
nobody has classified — an allowlist, not a denylist, because an unconsidered
skip should be louder than a considered one, never quieter.** Quieter is not
hidden: the alert is still reported and still on the System page.

**What both have in common.** Neither was findable by reading the diff, and
neither was a coding error — both were correct code meeting reality. The first
needed a week simulated; the second needed the alarm actually to fire.
**Shipping is a test the test suite cannot run.**

## 2026-09-07 — Neon's transfer allowance, measured rather than blamed

Neon warned at 82% of the 5 GB monthly public-transfer allowance. Diagnosed by
measuring, and **the two obvious suspects were both wrong.** The 6-hourly
graph rebuild looks damning — `raw_json` is 96 MB and it runs four times a day
— but every one of its queries is `INSERT ... SELECT`, so the JSON is read and
written inside Postgres and never crosses the wire. And the ingest is
genuinely lean: the cheap filter pulls IDs and dates only, full records are
fetched for the ~91 of 11,466 that moved, and no `SELECT *` against `studies`
exists anywhere.

**The measured answer is the test suite, and mostly one session.**

| Suite | Tests | Bytes in | Time |
|---|---:|---:|---:|
| `-k "not real_data"` | 757 | **0.5 MB** | 38s |
| `-k "real_data"` | 121 | **56 MB** | 161s |

**86% of the coverage for 0.8% of the transfer.** Roughly ten full-suite runs
went through on 2026-09-07 alone — **~560 MB, about 14% of the monthly
allowance in one sitting.** Iterate on the free subset; run the full suite
once before committing. The real-data half is not optional at a commit — it is
the only thing that tests the SQL — it just should not run forty times while a
docstring is being edited.

**A second, smaller amplifier, not yet fixed at this point:** the frontend has
no caching at all, so each filter change re-issues the page's whole read set.
Left alone deliberately rather than patched, because **a blanket cache would
also cache `/tracked-conditions` immediately after the "+ Add" write, and a
monitoring tool that appears not to register a change the user just made is
worse than one that costs bandwidth.** Caching here has to be per-endpoint.

**What could not be established.** Neon's own per-source breakdown needs an
authenticated connector, so the remaining ~3.5 GB is not attributed. What is
measured is the per-run cost and this session's share of it; the rest is
stated as unknown rather than guessed.

## 2026-09-07 — The frontend finally remembers something, per endpoint

The bandwidth measurement named a second amplifier and deliberately left it:
the frontend had **no caching at all**, so Streamlit's script rerun on every
widget interaction re-issued that page's whole read set.

**What a rerun actually costs**, measured against the live API:

| Endpoint | Bytes | Read by |
|---|---:|---|
| `/investigate` | 37,711 | Investigate, every rerun |
| `/changes?limit=25` | 8,577 | Monitor, every rerun |
| `/discover/{nct}` | 4,395 | Understand, every rerun |
| `/investigate/landscape` | 3,604 | Investigate, every rerun |
| `/explore/{nct}` | 2,733 | Explore, every rerun |
| `/watch` | 2,500 | Home *and* Investigate |
| `/ops/status` | 2,217 | System, Review |
| `/tracked-conditions` | 27 | Monitor, Investigate |

**One Investigate rerun is 43,842 bytes**, all four calls unconditional —
Streamlit executes every tab body whether or not you are looking at it, and a
session is dozens of reruns.

**Why an allowlist and not `@st.cache_data` on `get`.** A blanket cache is one
line and it would have shipped a lie. Two endpoints exist precisely to say
what is true *now*: **`/ops/status`** is the health surface, where a
five-minute-old all-clear during an incident is the exact failure step 11
exists to prevent; and **`/discover`** (the search) has a live CT.gov
fallback, so a cached search could hide a trial registered minutes ago.
**`/synthesis/proposals`** is a work queue a human is actively changing and
measures 16 bytes — nothing to buy.

So `CACHEABLE_PATHS` is an explicit list of eleven patterns and anything
unclassified is **not** cached. **An endpoint added next month is slow by
default, never silently stale by default** — the same allowlist reasoning as
`SELF_RESOLVING_SKIPS`, for the same reason: the unconsidered case must not
inherit the quieter behaviour.

**A write clears everything, bluntly.** The finer alternative — a map from
each write path to the reads it invalidates — is one more table to forget an
entry in, and **a forgotten entry shows the user a page that ignored what they
just did.** Not hypothetical: Home's "+ Add" writes a tracked condition, and
Monitor and Investigate both read the list back. Writes are rare; one full
refetch is the cheap half of the trade.

**TTL 300s against a 6-hour cron** — 1/72nd of the cadence that changes the
underlying data. It cannot make a reader see a stale record; it covers one
person's session of filter changes.

**Evidence, at two levels.** 14 free tests hold the policy and five planted
mutations were all caught. The TTL test uses a 0.2s override rather than
reading the constant, because **a configured TTL that never fires looks
identical from the outside.** Then the part the unit tests structurally cannot
show, since every page test stubs `api_client.get` and so bypasses the cache:
**three real `AppTest` runs of Home.py with `requests.get` counted instead — 1
HTTP GET, not 3.** The cache does survive a Streamlit rerun, which is the only
claim that matters and the one thing "it's decorated, so it works" would not
have established.

**One dead rule, found and deleted.** `UNCACHED_ON_PURPOSE` first listed
`/health`, which no page reads — a rule that can never fire, the same shape as
the unreachable `SUMMARY_ID_CAP`. There is now a canary in both directions:
every path the pages read must appear in one of the two lists, and every entry
in those lists must match a path some page actually reads.

## 2026-09-08 — Removing a condition, and the 19% the record could not account for

"Can I remove a condition?" was a one-line answer — no, `/tracked-conditions`
had only GET and POST — and a much longer one underneath it, **because the
obvious implementation would have quietly stranded a fifth of the watch.**

**Three different costs, which had to be separated before anything could be
built.** *Ongoing cost: no* — nothing queries CT.gov for a condition that is
not on the registry, so its trials are never refetched, diffed, or sent to a
paid call; spend is per detected change on a watched trial, never per stored
row. *Storage: yes* — the database is **249 MB**, of which `studies` is **184
MB** (~16 KB/trial, `raw_json` about half); dropping one condition's exclusive
trials would leave roughly 60 MB of dead weight. *"All the trials associated
with it": not answerable from what was stored* — and that is the part that
mattered.

**The measurement that changed the design.** `study_conditions` holds CT.gov's
own condition strings, not the term TrialLens watches, and the only link
between them was a substring match. Against the live record:

    in-scope trials matching NEITHER tracked term:  2,173 of 11,453  (19%)
    commonest tags: 200 Breast Neoplasms · 135 Breast Carcinoma
                     47 Obese ·  31 Breast Neoplasm ·  29 Overweight

**CT.gov expands synonyms when it searches.** A trial arrives through the
"breast cancer" query tagged `Breast Neoplasms`, and the substring rule cannot
see it. A removal built on that rule would have left ~2,000 trials
`active_in_scope = true` with **no query left that returns them** — counted in
"11,453 trials watched" while nothing watched them. **That is the
finishes-green-while-doing-nothing state step 11 exists to catch, and it would
have been introduced by the feature rather than found by it.**

Worth recording: the same blind spot exists in the other direction. A `Breast
Neoplasms` trial that ages out of the recency window can never be flagged out
of scope, because the drop query cannot match it either. Not changed in this
pass — switching that query to attribution would move live rows on the next
run, and this project's rule is to measure before moving them.

**So attribution came first.** `study_tracked_conditions (nct_id, condition,
first_matched_at, last_matched_at, untracked_at)`, written by
`POST /studies/reconcile-scope` — which already receives exactly the pair
(condition, every nct_id that condition's query returned) once per condition
per monitor run. No new call, no new plumbing, and `INSERT ... SELECT` so
nothing crosses the wire and an id not yet written is skipped rather than
rejected by the foreign key. `untracked_at` is a stamp, not a delete — the
`delisted_at` precedent — and `ON CONFLICT ... SET untracked_at = NULL` means
re-adding a condition revives its attribution on the next run instead of
needing a repair script. **That is what makes removal reversible.**

**The removal itself: untrack, never delete.** `study_changes.nct_id` is a
foreign key into `studies`, and those 1,098 rows are the product's actual
output — the amendments, the 22 primary-outcome changes a clinician judged,
the digest history. Deleting trials makes last week's digest unreproducible
and overturns the settled 2026-08-28 decision. Disk is the one thing a delete
buys, and it is the cheapest of the three costs.

**Two refusals, both deliberate.** *The last condition on the list* — an empty
registry is a monitor that watches nothing while still reporting a healthy
watch, precisely what `/ops/status` raises `no_tracked_conditions` for. And
*before any attribution exists* — because that is the stranding case above.
The second check is **global** (does the table have any rows at all), not
per-condition, so a typo condition that genuinely matched nothing stays
removable — **otherwise the guard would create its own trap.**

**Evidence in the response, not just an outcome** (sec. 3):
`trials_untracked`, `trials_kept_for_another_condition`, and
`trials_unattributed` — the last being trials in scope that no watched
condition accounts for. It should be 0 after a full monitor run; anything else
is the record saying this answer is narrower than it looks.

**Verification, at three levels.** 10 free HTTP tests for the route. 6
real-data tests that **write and roll back** — which is the right shape for a
suite whose own subject is a delete endpoint in a table a `LIKE '__%'` cleanup
once emptied. The case they exist for is the overlap: **only 14 of 9,294
trials are brought in by both watched conditions**, and a wrong query would
drop them off the watch where no hand-check would notice. Then the part no
fake can show: the route run over HTTP against the live database — 404 for an
unknown condition, 409 with the honest reason for a real one, and the registry
still intact afterwards.

**What remains before the button works.** Attribution is written by the
deployed API, so the code has to ship and one monitor run has to complete —
until then the endpoint correctly refuses. **That is the honest order: the
record earns the right to be edited.**

## 2026-09-08 — The bandwidth postmortem blamed the wrong runner

The previous entry closed with "the measured answer is the test suite, and
mostly this session", and left ~3.5 GB unattributed. Half of that sentence was
wrong, and the question that found it was "will pushing use up the allowance?"

**Pushing costs nothing on the Neon meter.** `tests.yml` runs on every push
*deliberately without database credentials* — that is in its own header, and
it is why every real-data test skips there.

**The 6-hourly cron does.** `monitor.yml`'s drift-check step runs the **full**
suite **with** `DATABASE_URL_READONLY`, including the 121 real-data tests
measured at 56 MB:

    monitor runs since the step was added:  29
    29 x 56 MB = ~1.6 GB    ~224 MB/day, unattended

So a large part of the "unattributed" transfer was this job, and the entry
that went looking for the cause measured the runs it could see — the local
ones — and stopped. **The tell was that the suspect it cleared and the suspect
it convicted were both things a human types. An unattended job running the
same expensive thing four times a day was never in the lineup.**

**Fixed by cadence, not by deletion.** The drift checks are real: they assert
what CT.gov actually sends — every intervention type is one we know, every
stored age parses, changes still group into amendments the way the endpoint
assumes. They are also checking for something that does not happen on a
six-hour cycle; a thirteenth intervention type is a weekly-to-monthly event.
They now run on the **00:0x and 12:0x ticks only** (01 and 13 accepted, so a
late scheduler does not silently skip half a day) — 224 → 112 MB/day, ~3.4 GB
a month saved, at a cost of up to 12 hours of detection latency. The gating
condition was checked against every hour of the day for both event types
before shipping, **because a `case` pattern that quietly matches nothing would
turn this into "drift checks never run again"** — the same silence this
project keeps having to design against.

**And the escape hatch had the same bug in miniature.** The first cut ran
drift checks on *every* manual dispatch — but the usual reason to dispatch
this job is to make the ingest run now, so "force the checks" would have
charged 56 MB to every dispatch made for an unrelated reason. It is an
explicit `drift_checks` input now, default false. **A cost control that fires
when nobody asked for it is how the cost comes back.**

## 2026-09-08 — The transfer ledger, and a cadence that restores itself

The billing period turned out to run **26 Aug → 26 Sep**, which turns "we are
at 82%" into a deadline.

**The ledger, built from our own records rather than Neon's.** The Free plan
does not expose the consumption-history API, and even on a paid plan it breaks
down by time and branch, never by client. So attribution came from run counts
multiplied by measured per-run cost:

| Consumer | Runs since 26 Aug | Per run | Total |
|---|---:|---:|---:|
| `monitor.yml` drift checks | 29 | 56 MB | **~1.6 GB** |
| Local full-suite runs, 7 Sep alone | ~10 | 56 MB | **~560 MB** |
| `monitor.yml` ingest half | 47 | ~0.5-2 MB | ~25-95 MB |
| `tests.yml` | 35 | **0** — holds no DB credentials | 0 |
| UptimeRobot pings | ~3,700 | **0** — `/health` is a static dict | 0 |

~2.3 GB of 4.1 GB accounted for; the rest is most likely local full-suite runs
on the other twelve days, which nothing recorded — stated as unproven. **The
gain is not the estimate, it is that two suspects are now eliminated rather
than assumed.**

**Halving was not enough, and the arithmetic says so.** ~840 MB remaining over
18 days is a ~47 MB/day budget: twice daily (112 MB/day) exhausts it ~16 Sep,
once daily ~24 Sep, weekly (~16 MB/day) totals ~140 MB. **And running out is
not a slowdown: Neon's Free plan suspends the compute** until the next period.
The deployed site would have gone dark during the window it is being shown to
potential employers. A cost control that is merely an improvement is not a fix
when there is a deadline attached.

**So: weekly until the reset, twice daily after — decided by the code, not by
a comment.** The step reads `BILLING_RESET=2026-09-26` and picks its own
cadence around it. **Writing "remember to put this back" in a comment is how
it would quietly stay weekly for a year**; this project already has the rule
that a comment describing an invariant is not the invariant. The gate was
checked across dates, days and hours before shipping.

**Also worth watching, and not watched before now:** the Free plan allows
**0.5 GB of storage per project**, and the database measured **249 MB** —
about half — and Neon bills storage including branch history, so its figure
reads higher than `pg_database_size`. Transfer was the loud meter; that one is
quieter and nearer.

## 2026-09-08 — Wrap-up: what the public repo says, and the Corroborate question answered

The build is finished; this entry is about the documentation and one question
that had been open since 2026-08-26.

**The docs were describing a different project.** `README.md` still said "a
working local application, not a deployed product", "three of five
capabilities are built", "there is no model call in this system today" and
"248 tests" — against a deployed app, five live capabilities, two paid model
paths and **914 tests**. Every one of those was true when written; none had
been re-read since. **A status essay copied into three files goes stale in
three files**, which is the rule CLAUDE.md's own status section states and
which CLAUDE.md itself had stopped obeying at 315 lines.

So: `CLAUDE.md` cut to under 100 lines across four sections, keeping the `§2`
through `§7` numbering because **~30 code comments cite those section numbers
by name** and renumbering them would have quietly broken every citation. The
standing gotchas moved to `docs/gotchas.md` — they are the highest-value
content in the repo and could not fit — and `decisions.md` was compressed to
roughly a quarter of its length with **every dated heading kept verbatim**,
because those headings are cited by date from code, tests and the roadmap.
Also removed: the course-tracking material, which belongs outside a public
repo.

**Corroborate: still possible, but not in either app's current shape.** The
2026-08-26 entry deferred a literature Q&A integration as "a genuine,
non-forced idea" without ever recording the technical reason. Checked
directly: Corroborate is *one in-process Python program* — Streamlit calling
ingestion, SQLite and RAG functions directly, with a FastAPI layer that its
own README says "was scaffolded in Step 1 but never built, and was removed
rather than left as dead code". So **there is no door to knock on**: Streamlit
Community Cloud serves a websocket UI, not an HTTP API. Its storage is a local
SQLite file plus a Chroma directory, which does not survive a Community Cloud
restart and is not reachable from Render. Different runtimes (3.12 vs this
project's pinned 3.9.6), different databases.

Three options, cheapest first: **a link-out** (TrialLens links a trial's
intervention terms into Corroborate as a pre-filled query — no integration, no
shared state, and it needs Corroborate actually deployed, which its README
still lists as in progress); **a real integration** (Corroborate needs the
FastAPI door back, a hosted vector store — pgvector on the existing Neon
project would do — a deploy and an auth story); or **nothing**. Deferred
again, but now for a stated reason rather than a feeling. The §5 rule "no
vector store" stands: the second option is where that would change.
