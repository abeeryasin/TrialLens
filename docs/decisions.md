# Decisions & Learning Log — TrialLens

Dated entries capturing real decisions and why. One `##` heading per decision;
headings are cited by date from code, tests and the roadmap, so they are
stable. Each entry states what was decided, what it beat, the numbers it was
decided on, and what verified it. The rules that came out of the painful ones
are collected in [`gotchas.md`](gotchas.md).

## 2026-08-25 — Domain considered and shelved: maternal-health / Three Delays

A WHO "Three Delays" maternal-mortality project. The GHO API works, but
PDHS/MICS microdata is gated behind manual registration and not
redistributable, and an assumption that de-identified Pakistani case narratives
are public was checked and found wrong. Shelved when TrialLens matched a
different set of unpracticed skills more directly. Logged as a future project.

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
"deterministic first, AI second, agents third", and "potential fit" instead of
"patient eligibility" — all adopted. Pushed back on three: its FastAPI layer
was speculative "for later" with no consumer (made load-bearing from day one
instead); its vector store would build retrieval infrastructure this project
doesn't need (sequenced for once a real cache exists); and its claim that
CT.gov maintains record versions was checked rather than accepted, since it
justified the whole monitoring feature. Its own later section warned against
building everything at once, immediately after sections describing exactly
that — **read a big AI-generated proposal's later caveats against its earlier
scope before adopting either.**

## 2026-08-26 — Database: Neon Postgres, chosen and verified (retroactively logged)

Chosen earlier but never logged — caught in a documentation audit. Verified
rather than assumed: a real permanent free tier (0.5 GB storage, 100 compute
hours/month, commercial use allowed), real Postgres, instant branching. Schema
work on a `dev` branch, `production` untouched until trusted. (What actually
happened to that plan: 2026-08-29 and 2026-09-05.)

## 2026-08-26 — Discover vs. Monitor: an untracked topic falls through to a live lookup

A plain read of our own database for a never-fetched area comes back empty,
**which looks identical to "no trials exist" — actively wrong, not just
incomplete.** So an ad-hoc question falls through to a one-time live CT.gov
call, while *deciding to track* an area is its own explicit action. Without the
split, a live search and a monitored topic collapse into the same broken thing.

## 2026-08-26 — Ingestion scope: filter by trial status, not just condition name

Checked real counts before assuming feasibility. "diabetes" alone matches
**24,289 studies** — ~410 MB for one topic; three such topics exceed the entire
0.5 GB free tier. Filtering to active statuses cuts it ~10x (**1,958**). 10-12
areas filtered to active trials fit; full historical registries do not.

## 2026-08-26 — Ingestion pipeline built and verified with real data

Ran against two topics chosen from verified current research interest: breast
cancer (6,545) and obesity (4,912) — **11,415 unique studies, 32,417 condition
tags**. Caught a bug before trusting v1: it wrapped the whole run in one
transaction, committing nothing until the end — progress invisible and
all-or-nothing on failure. Found by querying `pg_stat_activity` directly rather
than assuming a long runtime meant "fine" or "broken".

## 2026-08-26 — Future literature integration: logged, not built

Pulling supporting literature for a trial via a separate document-Q&A
capability is a genuine, non-forced idea. Deferred: the core capabilities don't
need it, and a cross-tool integration adds complexity before this project
stands on its own. (Technical reason finally recorded 2026-09-08.)

## 2026-08-27 — FastAPI built as the real only door to the database

`ingest.py` refactored to call `POST /studies/batch` over HTTP instead of
writing Postgres directly — **that is what made "only door" real today rather
than an intention for later**; the script no longer holds a database credential
at all. Read-only is enforced at the database layer: a `SELECT`-only role, with
a direct `UPDATE` through it rejected by Postgres itself while a `SELECT`
returned normally. **An app-layer check wouldn't survive a bug in the app code;
a missing grant can't be bypassed.**

## 2026-08-28 — Monitor: real cheap-filter/expensive-diff, a changelog table, and a no-delete guardrail

Verified live first that CT.gov v2 supports `fields=` and `filter.ids=`. Each
run fetches ID + last-updated for everything matching a tracked condition,
pulls full records only for what moved, and writes every real difference to
`study_changes` **before** overwriting — the bare `UPSERT` would have discarded
the previous value with no record, defeating the entire point of Monitor.

**The scheduler never issues a `DELETE`, full stop** — this project already has
an incident where a cleanup removed rows it shouldn't have, and CT.gov itself
never deletes a record either. A trial that stops matching gets flagged via
`POST /studies/reconcile-scope`, which **refuses to run against an empty ID
set**: an upstream fetch failure returning zero results would otherwise flag
every tracked study as dropped in one shot. Tested by corrupting one row's date
and enrollment and confirming the diff caught exactly those two fields.

## 2026-08-27 — Found and fixed: client-side connection pooling against Neon's pooled endpoint

A write succeeded at startup, then one ~20s later failed with `server closed
the connection unexpectedly`. `DATABASE_URL` points at Neon's `-pooler`
endpoint, already a PgBouncer pool that drops idle client-held connections, and
`psycopg2` only discovers this on the next query. Fixed by connecting fresh per
request: **Neon's own pooler is the pool.**

## 2026-08-27 — Caught and corrected: an overly broad test cleanup deleted 3 real studies

Ingested a test condition, then deleted it by matching on the condition tag.
CT.gov's search does synonym expansion, and 3 of the 56 studies returned were
already part of the real dataset — so deleting by `nct_id` removed their whole
row. **Real data loss**, caught by comparing row count against the known
baseline (11,415) rather than assuming a cleanup did only what it was meant to.
**Lesson:** a cleanup against a real dataset must record exactly what it added,
by ID, up front — never reconstruct it from a tag that can also match
pre-existing rows. (Same class as 2026-09-05's `LIKE '__%'`.)

## 2026-08-28 — Discover live-fallback built: `GET /discover`

Checks our DB first; only a genuinely empty local match falls through to one
live, unpersisted CT.gov call. **A live result is never written to the DB** —
tracking a topic stays an explicit action, not a side effect of asking a
question. `ctgov_client.py` was extracted so both `ingest.py` and
`api/discover.py` share identical parsing; it lives outside both `scripts/` and
`api/` on purpose, since it never touches the database.

## 2026-08-28 — Found and deferred: `/discover` can silently under-report an untracked condition

The local-vs-live check is a plain "did the DB return anything", but an
untracked condition can still have incidental local rows (a breast-cancer trial
listing melanoma as a comorbidity), which get returned as if they were the
complete picture. **"Found something" is not "found everything", and the
response doesn't say which.**

## 2026-08-29 — `/discover` gap fixed: per-result source, merged local+live

Built at the start of step 5 rather than deferred again, since the frontend was
about to display these results. Three branches: nothing stored → live only;
local rows **and** an exact tracked match → local only; an incidental match →
both, merged de-duplicated, each result carrying its own `source`. Verified
against real data, including `psoriasis` returning a real mix of 2 live + 3
tracked. Added a degraded path: a failed live call returns the local rows with
a note rather than a hard 502 — those rows are still real data.

## 2026-08-29 — Streamlit frontend built: Discover + Understand

Every page reads through `api_client.py` over HTTP, never Postgres, extending
"only door" to a second real consumer. Eligibility is shown as source text with
a standing caption that TrialLens never determines whether a real person
qualifies — **the first UI surface where sec. 2 has a concrete implementation
rather than being only a written rule.** Verified in a real headless browser
including, with FastAPI killed, Home showing the "could not reach the API"
message instead of failing silently.

## 2026-08-29 — Understand extended to live-only trials; UI copy de-jargoned

Clicking "View" on a live Discover result led to a 404. Fixed with the same
tracked-or-live split. Two bugs found while verifying: **CT.gov returns 404 for
a well-formed nonexistent NCT ID but 400 for a malformed one**, and the code
only treated 404 as "not found"; and `request_with_retry` was retrying 4xx,
which can never succeed. Also removed a permanent green "Connected to the API"
banner — **confirmation noise, when every other surface only speaks up when
something is wrong.**

## 2026-08-29 — Discover's results table rebuilt on st.dataframe, not hand-rolled columns

Short values wrapped onto two lines even in wide layout: the table was seven
manually ratio'd `st.columns()`, fixed widths that don't reflow. Replaced with
`st.dataframe`, which auto-sizes to content. **A real testing gotcha:**
Streamlit's dataframe renders to an HTML canvas, so a click at plausible pixel
coordinates registers nothing — an overlay intercepts pointer events and the
component listens for real `pointerdown`/`pointerup`, not a synthesized
`click`.

## 2026-08-29 — Narrative/design fields added: what a trial is, not just who's eligible

Understand showed eligibility but never *why the trial exists*. Checked against
research rather than guessing: brief summary and intervention are the two most
helpful result fields after title and condition. Two things caught before
shipping: **~23% of CT.gov date structs are month-only**, so a `DATE` column
would have rejected them or forced fabricating a day (sec. 2) — changed to
`TEXT` before any data was written; and `ALTER COLUMN ... TYPE TEXT` hit
`DiskFull` on a 181 MB database, because **a type change rewrites the whole
table even for an all-NULL column.**

Backfilled 11,490 rows from stored `raw_json`, writing to Postgres directly
rather than through the batch endpoint **deliberately** — its diff logic would
log a "changed" entry for all ~11k rows, which is not a Monitor-detected
change. A bulk `UPDATE ... FROM (VALUES ...)` cut it from ~90 minutes to under
3. Added an honest fallback: when the only change is `last_update_post_date`,
the page says CT.gov marked the record updated but no field we track moved.

## 2026-08-29 — Small UI fixes + honest, interactive Home page

`st.metric` truncates long values instead of wrapping; `st.write()` on a bare
integer renders an inline `<code>` chip. Home rebuilt around a live stats row
(via `GET /tracked-conditions`, keeping the frontend reading through FastAPI
rather than a config file) and an honest capability grid, with Explore and
Investigate labelled "Not built yet" rather than hidden.

## 2026-08-29 — Monitor gets its own roadmap step, separate from the digest email

Monitor's output was reachable only per-trial, so "what changed across
everything this week" was unanswerable without already knowing the NCT ID —
exactly the question the persona asks. Built as its own step, not merged with
the digest: **a page you pull up and an email that pushes are genuinely
different things.**

## 2026-08-29 — Monitor page built: `GET /changes` + `frontend/pages/3_Monitor.py`

Lives at `/changes` as its own top-level router, **not** under `/studies`:
`/studies/changes` would collide with `/studies/{nct_id}`, needing permanent
registration-order discipline — too fragile. Added
`idx_study_changes_detected_at`, since the per-trial index doesn't help a query
scanning across every trial. `FIELD_LABELS` moved into a shared `labels.py`,
the same drift risk `ctgov_client.py` was extracted for.

## 2026-08-29 — Monitor page: real pagination, filters, inline detail, a real dedup fix, and honest formatting

The dataframe's widget `key` is suffixed by page number — without that a stale
selection carries into differently-ordered rows. `GET /changes/fields` returns
only field names that actually have a change on record, so the dropdown can
never offer an option that filters to nothing.

**A real duplicate-row bug.** `reconcile-scope`'s drop query joins
`study_conditions` and matches `condition ILIKE '%obesity%'`; a trial with two
matching tags produced two rows, and the following `SELECT` — **no `DISTINCT`**
— carried the duplicate into `study_changes`.

**Correction, same day — that cleanup was incomplete and its verification was
wrong.** The check queried only `obesity`, then reported the data clean.
`NCT04835597` appeared **19 times**, because it carries 19 tags all containing
"breast cancer". **22 excess rows removed (141 → 119)**, with
`COUNT(DISTINCT (nct_id, field_name, detected_at))` asserted unchanged before
and after. **Lesson, worth more than the bug: verifying a fix against one
sample of a filtered dataset is not verifying the fix.** The first check looked
rigorous — read-only, row counts, real data — but sampled one of two
conditions.

Also: a `distinct_trials` count, so the caption doesn't conflate "many changes
to one trial" with "many trials changing once"; and honest formatting, since
`study_changes` stores everything as `TEXT`. One gotcha: an imported module
like `labels.py` stays cached in `sys.modules` for the process lifetime —
editing it does nothing until the server restarts.

## 2026-08-29 — Found: the `dev`→`production` cutover never happened; added a real `sandbox` branch

The 2026-08-26 decision described two phases. Phase 1 happened. **Phase 2 never
happened, and was never tracked anywhere as a remaining step** — so `dev`
became the permanent real database by inertia rather than by decision.
Confirmed from Neon's metadata: `dev` at 226 MB with 736 MB transferred,
`production` at 32 MB with zero. Decided **not** to migrate just to make names
match intent — re-pointing everything risks breaking a working unattended job
to fix a label. Added `sandbox` as the real disposable copy, and proved
isolation rather than trusting it. (The rename landed 2026-09-05.)

## 2026-08-30 — Monitor honesty pass: labels, drop reasons, change categories, enrollment type

Each item a case where the UI was technically accurate but practically
misleading. "Active in tracking scope: Tracked → Dropped" was a field name
*asserting* the trial is active beside a value saying the opposite.

**A dropped trial now says why, deterministically** — fully derivable from
stored data. Tested against all 14 real dropped trials, every one explained. It
returns `None` rather than a guess when the facts don't explain the drop, and
the UI says "we can't tell from the data we've stored" — **sec. 2 forbids
presenting an inference as a source fact, and this is exactly where that
temptation lives.** `CLOSED_STATUSES` and `RECENCY_DAYS` moved into
`ctgov_client.py` so the explanation imports the same constants the fetcher
uses; a second copy could quietly start lying.

**Enrollment was ambiguous** — "Enrollment: 34" gave no indication whether 34
people enrolled or 34 is the target, and CT.gov reports exactly that, which the
parser was discarding. **6,577 ESTIMATED vs 4,905 ACTUAL**, so the majority of
bare counts were targets read as headcounts.

**Test residue was sitting in the real change log.** `NCT00260585` carried the
first three change rows ever written — artifacts of 2026-08-28 drift testing
(an injected `enrollment_count` of 999999, a corrupted date). The tests were
documented; the rows they created never were. **A feed row claiming enrollment
changed from 999,999 is a fact CT.gov never reported.**

## 2026-08-30 — Long text changes: a real word-level diff, and honest "formatting only" labelling

An `eligibility_criteria` change rendered both versions in full — **8,400
characters** to communicate a handful of edited words. Checked the case first:
94.8% similar by word and, after normalising punctuation and casing,
**identical** — the sponsor had reformatted one criterion into a list.

**Deterministic, not an agent.** A text diff has exactly one correct answer, so
this is `difflib`. An LLM summarising eligibility criteria would risk
paraphrasing clinical text, which sec. 2 forbids outright. The inline diff was
chosen over side-by-side, which for 4,000 characters reproduces the original
problem.

**The formatting-only check is deliberately biased toward saying "no."** Only
non-alphanumeric differences are ignored. **Missing a cosmetic edit is
harmless; telling a researcher nothing changed when it did is a false claim
about a study fact.** Verified against `BMI 27.0 to 35.0` → `45.0` and `eGFR <
60` → `< 30`, which correctly return False. The diff earned its place
immediately, surfacing airway-difficulty criteria replaced outright by `BMI
>28kg/m2`. CT.gov's markdown escaping is left showing through: **stripping
characters from stored study text would be editing the source rather than
displaying it.**

## 2026-08-30 — Age shown as a real bracket, not a lower bound

`minimum_age` alone can only render "18 Years and older". CT.gov does report
`maximumAge` — **5,712 of 11,490** trials have one — and the parser was
discarding it. `TEXT`, not numeric: the unit really does vary ("18 Years", "18
Months"), so parsing to a number means losing it or inventing a conversion.
Roughly half of trials specify no upper bound, **which is a fact about the
trial, not missing data.** Verified the write path on `sandbox` first, since
adding a column means the INSERT list, the `ON CONFLICT` set, the row tuple and
the `execute_values` template must all stay aligned — **a mismatch surfaces as
silently shifted column values, or as a failure on the next cron run.**

## 2026-08-31 — Ranking: five of eight signals moved out of the model

Four of seven fit signals were field comparisons with exactly one correct
answer, and a fifth became one once the preference was parsed. Routing those
through a model lets them drift on identical input, **which makes an evaluation
harness unable to attribute a score change to a code change.** Cost fell ~$0.03
→ ~$0.006 per call, but the reason was reproducibility.

**Every threshold came from querying the live database, not the CT.gov docs,
and the two disagreed.** The replaced prompt named `CLOSED`, which is not a
CT.gov status at all, and covered two of eight real values — leaving ~20% of
trials unguided. It showed `"Phase 2"` where the column stores `PHASE2`. Age
parsing needs the unit: `1 Day` is real on 12 trials, and reading it as 1 year
is a 365x error.

## 2026-08-31 — "Unknown" excluded from the score denominator

A signal never asked about scored 0.0 while its weight stayed in the
denominator, **making "we can't tell" arithmetically identical to "this trial
fails"** — capping the score near 0.65 however well the trial matched.
`unknown` is now excluded from both; `no_match` stays at 0.0, being real
evidence against. `evaluated_weight_fraction` rides alongside, because **a 1.00
assessed on 30% of criteria and a 1.00 assessed on all of them are different
claims, and the score alone cannot distinguish them.**

## 2026-08-31 — Missing preferences are elicited, not scored

Excluding unknown signals is honest but silently narrows what the score means.
`POST /rank` now returns the preferences not stated, the weight each costs, and
the question that would close it — no extra model call. It only asks about gaps
an answer can fix: a signal unscored because the trial records no phase (**64%
of trials**) is not recoverable by anything the researcher can say.

## 2026-08-31 — Observational studies cannot match a phase request

`phase_fit` returned `unknown` whenever no phase was recorded, so an
observational cohort could rank alongside genuine Phase II trials for someone
who asked for Phase II. The cases separate by `study_type`: 2,440 OBSERVATIONAL
with NULL, 4,869 INTERVENTIONAL with `NA`. An observational study has no phase
**by definition** — a fact, not an ambiguity — so it scores `no_match`.

## 2026-08-31 — Condition matching split, because the filter already answered it

`/rank` selects with `condition ILIKE`, so a 30%-weighted `condition_match`
signal asked the model something already established and always got yes —
granting 30% to every trial automatically. **A signal that nearly always
returns the same value carries no information regardless of its weight.**
Replaced with `condition_is_subject` (is the condition the trial's subject, or
a comorbidity or exclusion criterion) and `approach_match`.

## 2026-08-31 — Few-shot examples removed in favour of schema-constrained output

Three worked examples filled two fields identically as `unknown`/`low`. Read as
a pattern rather than three judgments, that teaches which fields to leave blank
— **whatever an example holds constant, it teaches.** A JSON schema now
enforces shape. This also removed a real failure path: the old code told the
model to emit JSON then called `json.loads`, where a malformed reply raised into
a bare `except` and **silently dropped the trial from the results.**

## 2026-08-31 — Two test tiers, split by whether they cost money

An LLM feature fails two ways that look identical from outside: the data never
reached the model, or the model reasoned badly. The bug that occurred was the
first — a signal carrying 15% of the weight whose input was never placed in the
payload. **No amount of running the paid harness distinguishes that from honest
uncertainty, because the output string is the same.** A free payload test
asserts on the constructed payload, and that the five deterministic fields stay
*out* of it so the model cannot re-judge settled facts.

## 2026-08-31 — On-disk response cache for the evaluation harness

Most iteration is on weights and presentation, which need no fresh judgment.
Responses cache keyed on `sha256(model + effort + prompt + content)`, so only a
genuine change forces spend. Verified by re-running a 48-call suite for **$0.00**
right after a paid run. Each entry stores the question that produced it, so a
cached answer can be audited.

## 2026-08-31 — What the ranking evaluation does and does not establish

The harness reported correct ordering 15 of 15. **Five had the top two trials
tied on score and coverage**, resolved by stable sort in fixture order, which
happened to match — reversing the list flipped them to failures with identical
scores. Honest count: **10 correct, 5 undetermined**. The fixtures also don't
resemble stored data: 2-3 trials per scenario, no eligibility text, every field
populated where real data is 64% missing phase. **The missing-data paths most
of the design addresses are the ones the fixtures never exercise.**

## 2026-08-31 — The ranking evaluation suite cannot pass; its rate is not a signal

The declared target is unreachable for both halves. `high` confidence needs 80%
coverage, but 70% of the weight is preference-gated, so it requires stating 50
of those 70 points — the most any test interest unlocks is 65%, so `high` is
unreachable in **0 of 15** scenarios. And because `unknown` is excluded from
the denominator, a trial matching everything asked scores exactly 1.00, which
the fixtures were designed to produce. The harness also **never asserts
confidence at all.** Recorded rather than patched: **top-1 score is a weak
assertion, because "matched everything asked" equals 1.00 however little was
asked.**

## 2026-08-31 — `SELECT *` was spending the Neon transfer budget on a column nothing reads

Neon warned at **84% (4.2 GB) of 5 GB monthly transfer**, and nothing about the
app's traffic explained it. The cause was `SELECT *`: `raw_json` is ~22 KB per
row on the wire and **nothing has ever read it** — `StudyDetail` has no such
field, so Pydantic dropped it on arrival. The real-data test reads every active
row on every run: **315 MB per full-table run before, 16 MB after.** Fourteen
free-suite runs is 4.4 GB — the entire allowance, on a column discarded the
moment it arrived.

`STUDY_DETAIL_COLUMNS` derives from `StudyDetail.model_fields` so it cannot
drift. The narrowing creates a trap — an unfetched column arrives as `None`, so
a scorer reading one would be tested against nothing while passing — so a guard
walks the module's **AST** for every `trial.<field>` access. The first version
grepped a hand-written list; replaced because **a hand-written list only catches
the mistakes whoever wrote it already anticipated, and the entire risk is the
field nobody thought of.** The free suite's wall time fell 79s → 10s.

## 2026-08-31 — `raw_json` stays; the storage tradeoff is real but not due yet

Questioned since it is 52% of the table against a 0.5 GB cap and no query reads
it. An earlier note called it a column "nothing reads" — wrong in the way that
matters. It has earned its keep three times, each a backfill with **no CT.gov
re-fetch**. Speed is the weaker argument. The real one: **a re-fetch is not a
re-read** — CT.gov's record today is not the record that was stored, so
backfilling from one would mix current values into historical rows and make the
diff history a lie. Keep it; the wall arrives around ~28,000 trials, and the
option then is to *move* it, not drop it.

## 2026-08-31 — Feature order for post-Step-7 work

Filtering first (deterministic over data already stored), then a curated
summary — building the summary first means writing it twice. **Per-user
accounts deferred**: auth demonstrates none of the skills this project was
chosen to practise, and a reviewer forced to sign up before seeing anything
usually leaves. Grounding: four days of Monitor produced **123 changes across
100 trials** — the substantive signal is real and already on disk.

## 2026-08-31 — Unit 4 verified; two more bugs, one fixed and one open

Everything below came from *running* the page, not reading it — it had compiled
for an hour first. Found free: a `SyntaxError` (Python 3.9 forbids a backslash
inside an f-string expression — the file had never been executed).

**Bug #9 — `POST /rank` had never once returned successfully over HTTP.** The
endpoint returned the wrong type for its `response_model`, and FastAPI
validates the *outgoing* response — so every request raised a 500 **after all
21 model calls had been billed.** Found by spending $0.13 on a run that threw
the result away. The tests all called scoring functions directly. **A test that
calls the endpoint function directly is not testing the endpoint.** The cache
made the re-run $0.0000, so the bug cost $0.13 once, not twice.

**Bug #10 — `approach_match` cannot ever score. Found, NOT fixed.** It returned
`unknown` 20/20 with "Researcher named no specific approach" — for an interest
naming immunotherapy explicitly, because `raw_interest` reached the model only
as a fallback. **This is bug #7 exactly, recurring inside the very function
whose docstring describes bug #7.** The system contradicted itself: elicitation
correctly did *not* ask about approach, so it knew one was named while the
signal said it wasn't.

## 2026-08-31 — Researched against the literature: what TrialGPT settles

**Validates:** TrialGPT's Retrieval → Matching → Ranking shape recalls >90% of
relevant trials using <6% of the collection — the same two-stage design arrived
at here independently. **Corrects the label set:** it keeps "not enough
information" and "not applicable" separate where TrialLens collapses both into
`unknown`, and **26.9% of its residual errors were exactly this confusion.**
**Corrects the benchmark:** the step-7 guide's precision/recall ~0.32-0.45 is
not the state of the art (NDCG@10 0.7275) — the conclusion still stands on its
own evidence but must not be argued from that number.

Also: generate the rationale *first*, then classify, or the model commits then
rationalises. Explanations are the measurable part (87.8% rated correct), and
that is per-criterion, not per-trial. Verbosity bias matters here because
`confidence` and `evidence` are both model-generated — **length must not become
a proxy for certainty.** And the local evidence beat the citation on whether
the LLM is needed at all: `condition_is_subject` returned match 9 / partial 9 /
no_match 2, real variance on the one question a `condition ILIKE` tag provably
cannot answer.

## 2026-08-31 — The three process fixes, implemented as code not intentions

**No paid call until a free test of the same path passes**, and **batch the
paid questions** — both enforced by `scripts/paid_preflight.py`, which exits
non-zero if the free suite is red and otherwise prints every question still
waiting on a paid answer. Also written into CLAUDE.md, **since a rule that
lives only in a script is a rule nobody reads first.** Third: a guard asserting
elicitation and the payload can never again disagree about whether an approach
was named — that disagreement *was* bug #10.

## 2026-08-31 — Intervention category: the free half of the approach question

CT.gov records `interventionType` as structured data, so a category conflict is
a fact. It cannot tell a GLP-1 from an SGLT2 (both DRUG), so it narrows what
needs the paid call rather than replacing it. **Querying the real distribution
first changed the design twice:** there are **11 intervention types, not the 6
proposed** (the missing five cover 2,022 interventions), and **985 of 11,420
trials record no interventions at all** with OTHER on 3,939 — both must defer
to the model, never return `no_match`, since absent data is not evidence
against a trial. Measured on the real breast-cancer pool: surgical ruled out
3,373 (63%), immunotherapy 1,507 (28%), all for $0. **The AST guard demanded
the new column automatically the moment a scorer read it.**

## 2026-08-31 — `not_applicable` added, but it belongs to the model, not the code

**A negative finding worth recording, because it stops this being
cargo-culted:** there is no clean use for it in any *deterministic* scorer.
TrialGPT's label applies to individual criteria within a trial; TrialLens's
signals are trial-level preferences that always apply, so "the trial doesn't
record it" is a data gap — `unknown` by definition. It has a real use in the
model-judged signals, with an explicit tie-break: *if unsure which applies, use
`unknown`, because calling a question meaningless is a stronger claim than
admitting you cannot answer it.*

## 2026-08-31 — Evidence before status in the output schema

The schema emitted `status` before `evidence`, and JSON is generated in order —
so **the model committed to a verdict then wrote a justification for it, making
the evidence decoration rather than reasoning**, which quietly undercuts sec. 3.
Reordered to evidence → status → confidence.

## 2026-09-01 — Two honesty repairs found by re-reading what the UI claims

**A deterministic verdict resting on an inferred input must disclose it.**
`score_approach_category` rules out up to 63% of trials and claimed its
categories were "read from the registry, not inferred" — half true: the
*trial's* types are registry fact, the *researcher's* come from a model reading
prose. Now both sides are named, and the mapping is surfaced in the page's "how
your interest was read" panel, the only place a bad mapping could be caught.

**The page was inferring a cause it had not checked.** An `unknown` signal
means either "you didn't say" or "the record doesn't carry it", and the first
fix wrote *"the trial's record doesn't carry it"* — **an assertion about the
record the page never inspected.** Corrected to what is known: *"answering
below would recover it"* versus *"nothing you could add would change it"*.
Inventing a cause to sound helpful is inventing a study fact, one level down.

## 2026-09-01 — Credits exhausted mid-batch; what was learned before they ran out

Bug #10 is fixed, verified on real output: `approach_match` went from `unknown`
20/20 to **`match` 5/5 at high confidence** with correct evidence.

**The $0.006-per-call figure was wrong, and every projection on it was wrong.**
Measured: **$0.1142 for 6 calls ≈ $0.019/call**. The old number came from this
repo's own notes, measured against **synthetic fixtures**; real records carry
up to 2,500 characters of eligibility criteria. A 20-trial search is ~$0.32,
not $0.13.

**Caught before spending, by reading the API reference rather than assuming:**
`output_config.effort` is Opus-tier and **rejected on Haiku 4.5** — every call
in the planned comparison would have failed. And two graceful-failure fixes: a
parse error returns **503** rather than a 500 stack trace, and **every trial
failing is an outage, not a ranking with no results** — 503 rather than a 200
with an empty list, which would render as "no trials matched" and is a false
statement about the data.

## 2026-09-01 — Step 7's two working docs deleted; what they held

Both checked for unique content first rather than assumed redundant. The
implementation guide already carried a STALE banner naming six of its own
claims wrong, and said it was retained for the precision/recall figure **the
TrialGPT entry corrects** — so its only stated reason to exist was itself the
error. Two open questions recorded here so deleting the file doesn't erase
them: the ranking tie (moot, the score is being removed) and the paid
prior-treatment eval case (moot, the signal is being cut — it carried 15% of
the weight while being relevant to 28% of breast cancer and 1% of obesity
trials). Both closed, not outstanding.

## 2026-09-01 — The ranking layer removed; what the removal plan got wrong

Ten files gone; `/rank` no longer exists. **A removal plan's file list is not
the same as the dependency graph** — the plan named one test, and three more
breakages were visible only by reading the survivors' imports. **Grep for what
the deleted files export, not just for their module names:** a module search
finds `import api.ranking`, it does not find `SIGNAL_WEIGHTS`, and that is the
reference that breaks a keeper.

**Deleting a test that guards a vocabulary needs a replacement, not just a
deletion.** The one test the plan named was the only thing holding
`INTERVENTION_TYPES` to anything — and it compared that list to a hand-written
enum in the prompt schema: **two hand-written lists agreeing with each other,
neither checked against the data.** Its replacement asks the live database and
passes against all 11,469 active trials — strictly better, and it exists only
because the deletion prompted "what was this actually protecting?"

**Home lost the Ranking card entirely rather than reverting to "planned"**,
which is what the plan said to do. "Planned" would be a false statement about
the roadmap: the capability is rejected with reasons recorded, and a card
saying "not built yet" invites someone to build it.

## 2026-09-02 — Where a model earns its place, decided by querying first

Before writing the change-interpreter prompt, the change-sets were queried —
**§6 applies to a prompt as much as to SQL**, which is the lesson step 7 paid
for. Four findings moved the design more than the plan did. **Most amendments
are not interpretable:** of 212, **99 (47%)** changed nothing TrialLens stores,
38 moved one structured field, and only 75 contain anything a model could add
to. **The category half is a lookup, not a judgement** — 14 content fields, all
mapping statically; a model asked for that verdict is step 7's error repeated.
**One amendment carries 252,041 characters of `locations` JSON**, where the
honest summary is "5 sites added, 5 removed". And **dates cannot be subtracted
naively** — ~23% are month-only, so "slipped 361 days" about a date given as
"2027-06" invents precision the registry never stated.

`describe_effect` returns `None` for every prose field permanently, and a test
fails if that changes. **Shipping the deterministic layer first creates a
control**: "does a model's prose add anything over this?" is now answerable,
where step 7's equivalent question never was. Rejected: running it on a local
3-4B model — the task is interpreting clinical prose where inventing a fact is
the cardinal sin, and **fluent, confident and wrong is the exact failure §2
exists to prevent.**

## 2026-09-02 — Why an amendment was invisible: we were not looking at the field

The diff compares 21 normalized columns, and the most consequential thing in
the raw record was never read: **`hasResults` sits at the TOP level of the
response, not inside `protocolSection`**, so a parser walking every module one
level down never saw it. **1,056 of 11,518 stored trials already have results
posted** — the single most consequential amendment a researcher can receive,
and every one had been rendering as "amended, but we can't see what."

Recovered for all 11,518 trials straight out of stored `raw_json` — a field
nobody thought to normalize in August, recoverable in September for free.
**Backfilled values are deliberately NOT written to `study_changes`:** that
would log 1,056 "results were posted" amendments dated today for trials that
published months ago — a false claim about *when* something happened.

**The generalisable lesson is the same one as 2026-08-31: the shape of the real
payload is not the shape the code assumes.** That time it was values inside a
field; this time a field one level up from where every other field lived.

## 2026-09-02 — The invisible amendment was over-weighted, and its copy guessed

Caught by reading the rendered page. An amendment TrialLens *cannot see* had
more visual weight than the one above it carrying four real field changes.
Worse, the copy named the untouched fields as "contacts, oversight and sponsor
administrative details" — **we do not know that.** The system knows only that a
date moved and no stored field did. This is the *same* error as the entry
above, by the same reasoning: the honest line felt too thin, so plausible
detail got added. **When a true statement feels unsatisfying, the fix is a
better true statement or silence, never a plausible one.**

## 2026-09-02 — The watch leads the page, and "last checked" is a proxy that says so

`Home.py` was a capability grid — a brochure. The thing TrialLens has that a
fresh clone does not is **elapsed time**, so the page leads with the watch.
`GET /watch` is one endpoint rather than five reads, because the numbers only
mean anything together.

**The screen has three states and the least eventful one mattered most.** Two
days had zero amendments across 11,427 trials — real data — and that rendered
as an empty table, which reads as a broken app rather than a working watch. The
quiet week is what a researcher sees most often, so empty days are drawn as
zeros: **a zero is evidence the watch ran and found nothing, the opposite of
missing data.** The day strip is built from `generate_series`, not `GROUP BY`,
which has no rows for a quiet day and would delete the only proof it was
watched. **The alarm replaces the page rather than sitting above it**, because
a stale feed under a small warning still reads as current — and since it only
appears after 12 hours of a dead cron, exactly when nobody is looking, all
three states are asserted through `AppTest`.

The headline "last checked" was a labelled proxy, `max(last_matched_at)`. The
obvious alternative, `max(detected_at)`, is **wrong in exactly the case this
screen exists for**: on a quiet week nothing is detected, so it would fire the
alarm on the primary screen. **A proxy that fails on the common case is not a
proxy.**

**Counted by what it means, not by how many rows moved.** `results_posted` is a
subset of `scientific`, and a live test asserts `results_posted ≤ scientific ≤
amendments` — if that containment broke the page would state a negative number
of trials as fact. **The amendment, not the changed row, is the unit.**

**The artboards claimed "every number is real". Four were not**, and one wasn't
a number: the lead card showed a trial publishing results — a transition that
**has never been recorded**, because backfilled values are deliberately not
written to `study_changes`. That is the third instance in two days of the same
pattern, and worse in one way: **a drawn number has no test.**

## 2026-09-02 — Step 7b direction 3: the watch record, un-deferred by backfilling

Direction 3 was deferred on the reasoning that an empty run table reads as "no
check has ever run" and fires the alarm on a healthy watch. Sound reasoning,
wrong conclusion: the proxy it replaces is not merely *correlated* with a run —
`reconcile-scope` stamps it at the end of every run, so it **is** a real
completion time, which makes it backfillable. **The blocker was a gap of one
row, not a gap of two weeks.** `changes_detected` on that seeded row is NULL
rather than 0, because 0 would claim it found none.

**The test that has to survive this** was rewritten against `monitor_runs`
rather than deleted: the same silent failure exists in the new shape. **A guard
that moves when the mechanism moves is the point**; deleting it because its
subject was replaced would retire the invariant along with the implementation.

## 2026-09-02 — Record the writer's own count, not a timestamp window

`changes_detected` was first re-derived after the run by a timestamp window,
which also catches rows written by anything else active at the same time. **A
number that is usually correct, in a column nothing reads yet, is the easiest
kind of wrong to ship.** The exact number already existed upstream and was
being discarded. **Before deriving a value, check whether something upstream
already knows it exactly** — re-derivation is how an approximation gets into a
table later displayed as fact. Urgency came from the column being *unread*, not
despite it: every run writes another approximate row, and once a screen shows
the number the wrong history cannot be recomputed.

## 2026-09-02 — Step 8 unit 1: the Explore graph is tables, not a graph database

**No Neo4j.** The graph already exists — `lead_sponsor` holding "Mayo Clinic"
on 134 rows *is* 134 edges. Index-free adjacency pays off when traversals are
deep and the graph is large; here it is 11,518 trials and 2-3 hops. The
operational half is decisive on its own: **a second database is a second sync
path and a second thing that can be stale**, and sec. 5 says FastAPI is the
only door.

**Controlled vs. free text is a property of a FIELD, not an entity.**
`lead_sponsor` has 3,173 distinct values and zero case-duplicates; location
`facility` has 42,842 collapsing to 41,710. **Madrid alone carries 381 distinct
facility strings** — a city does not have 381 trial sites. So sponsors and
countries get identity upfront; facility, intervention and investigator
identity has to emerge from the values.

**Merge only when the difference is *naming*, never when it is *substance***.
55 names begin with "semaglutide" (dose and route arms, where the difference IS
the study) and 159 with "placebo" — merging those builds the densest node in
the graph out of a thing that is by definition nothing. Merging never
overwrites: **a merge that destroys the source text is the Procrustean cut** —
the problem is not the inference, it is that a researcher cannot disagree with
it.

## 2026-09-03 — Step 8 unit 2: extraction, and the edges a trial takes back

**6,207 organizations, 51,272 sites, 7,717 investigators, 14,468 intervention
terms, 191,864 edges**, all from records already on file — no CT.gov call, the
third time §4's keep-the-raw-record rule paid for itself. Nothing merged on
purpose: that unmerged extraction is the baseline any later merge is checked
against.

**Reconciliation failed twice, each for a different real reason.** First
staleness — a monitor run ingested 70 trials mid-extraction. Second, the graph
had **more** rows than the source: **the extraction is insert-only, so when a
trial drops a site the edge outlives the record that justified it.** Explore
would have gone on saying a trial runs at a location it had removed.

**Decision: stamp `delisted_at`, never delete.** Deleting fixes the false claim
and destroys the finding — "this trial quietly dropped three sites" is a
result, not a row to tidy away. It is deliberately *not* the date the trial
made the change; nothing on file says that.

## 2026-09-03 — Two monitor bugs that could only exist on the schedule

Both found by dispatching the workflow rather than waiting. **`KeyError:
'DATABASE_URL'`** — the workflow passed only `API_BASE_URL`, invisible locally
because `load_dotenv` reads `.env.local`. **So the watch record added the day
before had never once been written by a real run**, and every "successful" cron
since recorded nothing. And **`UPDATE ... ORDER BY ... LIMIT` is MySQL** —
Postgres rejects it, and an except clause swallowed it, so
`prose_interpretation` had **zero rows**: step 7c's $0.168 bought
interpretations that were computed and then dropped. Matching on `(nct_id,
field_name)` was independently wrong — a trial amending the same field twice in
one window would get the older interpretation on the newer row.

## 2026-09-03 — Site enrichment: the fields the parser dropped, and the evidence that asked for them

Prompted by a question that should have come earlier: *do researchers care
about collaborations?* **Collaborator is weak by definition, not by accident** —
CT.gov defines it as any organization "providing support", covering funders and
co-designers in one field with no way to separate them, reaching **37.4% of
trials with 63% of those at degree 1.** Kept but demoted from a network to an
attribute. **Sites reach 93.8%** and answer a documented question: the oncology
literature describes phoning the site to ask whether it is still open, and a
study of 8,893 patients found **55.6% had no trial at their treating facility.**

**The `has_results` pattern, third recurrence.** Across 142,777 stored
locations, geoPoint (98.3%), zip, state and per-site status were all sitting
unread in `raw_json`. Backfilled with no network call: **49,606 of 51,272 sites
now carry coordinates.** Status is an edge property; place is a site property —
2,616 site identities report more than one status, because a hospital
recruiting for one trial and closed for another is one place in two states.

**Where the registry contradicts itself, store nothing.** 109 sites are
reported at more than one geoPoint, **the largest 52 degrees apart** — the same
facility on different continents. All left NULL and counted. **A guessed
coordinate on a "trials near me" map sends someone to the wrong country.** And
**NULL means "not stated", never "not recruiting"** — only 28.6% of live edges
carry a status.

**One test OOM-killed the backend before it worked.** A correlated `EXISTS` per
site re-expands all 142,777 location objects for each of 51,272 sites; pytest
died at exit 137 with no readable error. **Against `jsonb_array_elements`, a
correlated subquery is not a slow query, it is a dead one.**

## 2026-09-03 — Follow-ups on unit 2b: the OOM had a survivor, and NULL got a guard

The same shape survived elsewhere, slow rather than dead only because 6,207
organizations is small next to 51,272 sites. The precise rule, which "avoid
correlated subqueries" gets wrong: **correlating on `s.nct_id` is fine — it
hits the primary key. Correlating on a value dug out of the JSON is what turns
linear into quadratic**, because there is no index to reach for.

**NULL got a guard before it got a consumer.** The tempting shortcut —
`status == 'RECRUITING'` for open, everything else closed — would report
~100,000 sites as shut that the registry never described. The formatter was
added **while nothing consumes the column yet, which is the cheapest moment to
make the wrong thing hard to write.** Site status renders as sentences, not
colour, **because grey would mean both "closed" and "unknown".**

## 2026-09-03 — `withdrawn_at` renamed to `delisted_at`

The column sat beside `recruitment_status`, whose CT.gov vocabulary contains
the literal value `WITHDRAWN` meaning something else entirely. A schema comment
was written to hold the distinction; **neither is worth much against a word
that means two things in one table**, and the cost only grows with readers.

**The migration is the part worth recording.** `schema.sql` is idempotent with
`ADD COLUMN IF NOT EXISTS`, so renaming the text of those lines would have
added a second, empty column beside the populated one and **quietly stranded 17
stamped edges.** The rename runs first inside a guarded `DO $$` block firing
only when the old column exists and the new does not. **Check the source
vocabulary before naming a column** — CT.gov already used the best word for a
different fact.

## 2026-09-03 — The graph sync went live, and the first run exposed an inconsistency I had left

The sync ran end to end untouched — **and then the drift checks failed**, from a
gap only a real rebuild could surface. When delisting was introduced, the sites
invention-test was scoped to live edges and the organization and intervention
versions were not, so the first rebuild that delisted anything reported
inventions that were nothing of the kind.

**The lesson is about how the earlier fix was made:** the sites test was scoped
because it was the one that happened to be red that day, rather than because
delisting had changed what "invented" means for **every** entity. **A concept
introduced in one place and applied in one place is a latent failure everywhere
else it belongs.** Auditing found a fourth case — investigators had no
invention test at all. **A red CI run was the cheapest possible outcome here.**

## 2026-09-04 — Step 7c: ask what changed, not why it matters

The first batch that really ran was read row by row, and found three faults.
**`why_matters` is gone** — ~48% of output tokens and the home of every weak
line ("potentially affecting recruitment messaging"). `summary` stayed tethered
to the diff and checkable; `why_matters` was speculation stored beside it
**with equal authority**, which is precisely the §2 line between reporting a
change and inventing its significance. The prompt now says the reader is a
clinical researcher who will judge significance themselves.

**The no-change gate matched prose and lost to rephrasing.** It compared
against the literal string "no change"; the model wrote "No meaningful
change—the criteria were reformatted", and **a paid call announcing that
nothing had happened was stored as a finding.** Now a structured
`MEANINGFUL: yes|no` field. Honest tally of the batch: **2 clearly valuable, 2
debatable, 4 reformatting** — an earlier note saying "7 of 8 are real" was
written after reading only 4.

**Billing is measured now, not multiplied.** The estimate was also the recorded
spend, so the ceiling added up a constant rather than money. That fixed a third
bug: spend was added only when an interpretation came back, **so every call
returning "no change" was real money recorded as $0.00.** Real cost is
**~$0.00125/call, not $0.004** — and the estimate is left ~3x high on purpose,
because **a guard that over-estimates stops early while one that
under-estimates walks through the ceiling.**

## 2026-09-04 — Step 8: the graph becomes visible, and a count that lied

**The roadmap's order was wrong and was reversed.** The merge was next on
paper, but it exists to fix "381 Madrid strings are 381 sites" and no page had
ever shown a site list — **building it first would have been step 7 again, a
layer measured against nothing.**

**A shared-condition count was written, measured, and thrown away the same
hour.** It printed **0 shared conditions for two breast cancer trials** — one
tags morphology, the other AJCC stage, and nothing is merged there either
(7,808 condition strings over 32,701 rows). **The count measured spelling, not
subject matter** — a false claim wearing arithmetic's costume. Replaced by the
neighbour's own tags as text.

**Neighbours are three lists, never one.** Sharing a hospital and sharing a
principal investigator are different claims of different strength; fusing them
would rebuild the unexplainable number `/rank` was deleted for. **Every capped
list carries its real denominator** — a list reporting its own length as the
total is the step-4 under-reporting bug in new clothes.

**An investigator table nearly written off:** its top names are call centres,
which read as junk. Counting properly, 76 of 7,722 names carry desk words and
**5,325 carry an MD or PhD** — the desks are top precisely *because* a contact
desk is reused across 102 trials while a real investigator is on three. What it
rules out is any "most prolific investigators" ranking.

**The fake connection has a blind spot, and it is exactly the dangerous one.** A
mutation turning registry silence into a claim a site is closed **passed all 11
fake-connection tests** by design, since the fake ignores SQL. Nine mutations
were planted and all caught, but **five only by the real-data half.** Latency
(~4.4s) is architectural — 1.7s to open a Neon connection — not this query.

## 2026-09-04 — The seven interpretations become visible, and a canary for what CI cannot see

The prose interpretations had been written by the cron and read by nothing.
**A bug caught during the build, not after:** the first version rendered them
only in the long-text branch, but `primary_outcomes` is STRUCTURED and **5 of
the 7 stored readings are on it** — most of the feature would have shipped
invisible, the exact failure being fixed.

**Attribution is in the element, not in a footnote.** This is the only thing
TrialLens displays that a model wrote, so the page test asserts label and
sentence appear in the *same rendered element* — a future edit cannot separate
them while leaving both technically on the page. **Absence of an interpretation
means three different things** and the column cannot tell them apart, so the
page never implies absence means nothing important changed.

**A source-text canary for the gap between CI and the cron.** The real-data
suite needs credentials, so it runs on the 6-hour cron and **skips entirely on
every push** — between a bad push and the next cron, CI was green while the
claim was wrong. The canary bans `coalesce()` on `recruitment_status` and the
literal `NOT_RECRUITING`, a value CT.gov does not publish. **It is a weak kind
of test and says so in its own docstring** — it asserts the real-data test it
stands in for still exists by name, so deleting that cannot leave it green over
nothing.

## 2026-09-04 — Step 8 unit 3: the merge, scoped by measurement and written as a pointer

**Measured before designing anything**, which cut the scope in half: 2,395 site
groups, 650 term groups, 99 investigator groups, and **0 for organizations,
which therefore got no column** — the symmetric design would have built a merge
with no duplicates to merge. **The "381 Madrid facility strings" that motivated
this are 381 different Madrid hospitals**; the real duplication is smaller and
dumber, 11 spellings of one Guangzhou centre.

**It writes a pointer, never a delete.** Setting `canonical_id` back to NULL
restores the unmerged extraction exactly, because **a judgement written
destructively cannot be revisited.** The rule is deterministic and deliberately
timid — casefold, collapse punctuation, trim; no edit distance, no model —
which is what makes 3,033 merges safe to apply unreviewed. It merges
`Semaglutide` with `semaglutide` and correctly does not merge `Placebo
semaglutide` or `Semaglutide 2.4 mg`.

**Identity boundaries are the dangerous part, so the script aborts rather than
trusting itself:** a mutation dropping city and country was caught at **8,856
cross-place merges**, nothing committed. Visible effect: RxPONDER's
site-neighbours **1,497 → 1,624**, and NCT01740427's 299 sites resolved to the
292 real places they are.

**A test that passed by luck, found by mutation.** The first merge test used
the busiest trial, which has no duplicate spellings — so removing the canonical
join broke nothing and 16 tests stayed green. **The second time this session a
green suite hid a real regression, and both times the fixture was the problem
rather than the assertion.**

## 2026-09-04 — Step 9, Investigate: deterministic analysis, and one number that was wrong by 20x

**The number that was wrong.** The step-7 removal argument leans on "this
product is deliberately low-volume (~17 changed trials a week)". Measured:
**~370 trials/week, ~1,600/month — off by roughly 20x.** It does not overturn
the decision, which rested on four of five signals being filters wearing a
score's costume, but the "low volume" leg is not true and must not be cited
again without re-measuring.

**Why Investigate is deterministic:** every question has one correct answer —
14 months is subtraction, 13 transitions is counting. **External evidence
agreed on the agent shape:** a three-agent pipeline costs ~29,000 tokens where
one agent uses ~10,000, and a five-agent system spent 80% of its tokens on
agents describing work to each other. **One specialist agent, weekly, reading
pre-computed findings — not a crew**, at ~$0.63/month against the naive
per-trial design's ~$232.

**Outcome switching — the first feature chosen from published literature rather
than from what the columns allowed.** Changing a registered primary outcome
after the data can be seen is a named, measured problem: **31.7%** of studies
have had one changed, associated with funding source at **OR 1.82**, and the
130 of 389 trials with a change overstated effect size by **16%**. The registry
records every one and surfaces none.

**The deterministic layer exists to stop false alarms, not raise them:** the
strongest flag combination available turned out to be `Safety and tolerability`
→ `Safety and Tolerability`. **Flags are listed, never summed** — no score, no
confidence number, which is the invisible ranking step 7 was removed for. And
nothing is an accusation: the page states what changed and that it **requires
review**, sec. 2's vocabulary.

Three honesty rules in the landscape half: **the unstated share stays in the
picture** (52% of trials report `NA` or no phase, counted with the unstated
rather than plotted beside PHASE3); **the current year is not a data point
yet** (drawn at equal weight a part-year reads as a decline, and it is the
calendar); and a term's reach is measured against trials listing any
intervention. **A self-join that looked like a working chart** cross-producted
the table so every term returned the identical count.

**Benchmarks, and the denominator trap.** Read against published baselines
(median delay 12.2 months, 19% missing 85% of target). **31.7% is deliberately
NOT plotted** — "studies that ever changed an outcome" and "changes seen in
eight days" do not share an axis, and drawing them together would manufacture a
comparison neither source supports.

## 2026-09-04 — Investigate, read by a human: nine findings, and a chart that lied

Everything below came from that reading, not from a test.

**The serious one: a chart reporting wrong numbers with full confidence.**
Vega-Lite thins axis labels it decides will not fit — harmless on a numeric
axis, but on a **categorical** one each surviving label lands against whichever
bar is nearest. The chart said Terminated 78; Terminated is 237, and 78 is
Enrolling By Invitation. Nothing on screen indicated it.

**Why it survived two rounds of looking.** Verification was rendering to PNG
and inspecting — but a PNG export lays out with default spacing, and only the
live theme tightens it enough to trigger the thinning. **The instrument was
structurally incapable of showing the defect, so a clean result from it was not
weak evidence — it was none.**

**A chart's form is a claim:** enrolment bands as bars sorted by length read as
a league table when it is a distribution. **And the worst reporting flaw was
not the crowding** — "enrolment against plan" on an absolute 0-2,000 axis made
a trial enrolling **13 of 30** an invisible dot at the origin. **The most
serious miss was the least visible thing on screen.**

Six smaller ones from real use, including a growth curve that cut its axis at
2010 and *dropped* the 153 trials that started earlier. **A note on the
suite:** one run showed 15 real-data errors that were Neon closing pooled
connections under load, not regressions — they pass on retry.

## 2026-09-02 — README, CI, and the amendment grouping key

Before this nothing ran the tests automatically. `tests.yml` runs on every push
with no secrets; the real-data tests run instead inside `monitor.yml`,
immediately after the ingest that could have introduced drift.

**The amendment grouping key is the trial's own `last_update_post_date`, never
`detected_at`.** Postgres's `now()` is transaction-start time so every row of
one amendment shares a timestamp — **but a run straddling a wall-clock minute
boundary can still split one real amendment into two.** The aggregate view
calls the same grouping function as the per-trial page, so the two can never
disagree about how many amendments a trial had.

## 2026-09-02 — `git add -A` committed an installed skill and a 2.4 MB canvas

One `git add -A` staged an installed skill and a generated design canvas before
anyone read `git status`. Neither was secret, so the fix was a follow-up commit
and a `.gitignore` entry rather than a history rewrite — but **`git add -A` is
now a standing "don't" for this repo**: staging names files deliberately, and
`git status` gets read before every commit, not after something unexpected
turns up in a diff.

## 2026-09-04 — Two cost-estimation numbers worth re-checking before quoting

**This project's text runs at ~2.61 characters per token**, not the ~4.0 rule
of thumb — assuming 4.0 understates a projection by roughly 53%, because
clinical trial text tokenizes less efficiently than general prose. And **a
per-call estimate used as a safety ceiling should be measured high, not
accurate**: a guard that stops one call early costs nothing; one that lets a
call through walks straight through the budget it exists to enforce. The real
average is tracked separately from `response.usage`.

## 2026-09-05 — Building the weekly synthesis agent: nine build decisions

**A hand-rolled loop against the raw Messages API, not the Agent SDK** — zero
SDK dependency today and `prose_interpreter.py` is already a working reference
for the cost-tracking shape. **claude-haiku-4-5**, since the costing only
pencils out at that rate and the questions are pattern-matching over a few KB
of pre-computed structure. **A separate weekly cron, not a day-of-week gate
inside `monitor.yml`** — otherwise every 6-hour run pays a conditional check
for something firing 1/28th as often, and a failure risks the run record
`/watch` reads from. **A real dedup tool**, so the same finding across five
weeks doesn't read as five unrelated rows. **Zero-finding weeks need no
synthetic row** — `proposals_created = 0` is unambiguous, and inventing
evidence of absence is what §2 rules out. **One tool call per finding**, not a
JSON blob, so partial progress survives a run that dies. **The review UI
deferred** — a UI designed against zero real proposals is the step-7 mistake in
new clothes.

**The rolling ceiling became genuinely shared, not just conceptually shared.**
Both paid features draw from the same $1.00/30-day window, because **capping
them separately would let the two together spend $2.00 while each guard
reported itself under budget.**

## 2026-09-05 — First real synthesis run: $0.1099, zero proposals, and why that's not bug #4

Given this project's history — step 7c silently dropped 100% of its writes
twice — **a zero-row first outcome does not get believed on the strength of
"tests pass".** The window was not quiet: 235 trials changed, 276 amendments, 8
substantive outcome changes.

It isn't a bug. Re-querying for `weeks_ago=2,3,4` — free, no model call —
returns **0/0/0/0**. Monitoring started eight days earlier, and the system
prompt is explicit that 2-3 prior weeks are needed before calling anything a
pattern. **An agent following that instruction literally has nothing to call a
trend yet.** One loose thread left open rather than resolved by inference:
whether it considered the one flagged anomaly and declined, or never looked, is
not knowable from the run record — and next week's run is free to wait for.

## 2026-09-05 — Step 10 starts: hosting platform, cold-start budget, and the Neon rename finally lands

**Vercel ruled out by research, not by a failed deploy** — it is a
serverless-functions platform and Streamlit is a stateful WebSocket server.
Render vs Railway took two passes because the first was under-specified: **the
real constraint wasn't technical, it was a real budget**, and the fix wasn't
the cheaper paid tier but a free UptimeRobot monitor keeping both services
awake at $0/mo. **Why the two-step matters more than the answer:** the first
framing accepted "always-on costs money" as a given and only asked how much.
The real fix was outside that frame entirely.

**The Neon rename, flagged since 2026-08-29 and deferred twice, was done rather
than documented around again.** Connection strings are endpoint-based, so
nothing else changed — verified live post-rename. **Tracked conditions moved
off a JSON file into a real table**, with the file deleted rather than left
stale, and `render.yaml` written with **no secret in it**.

## 2026-09-05 — First deploy is live, and an error message put a live password on a public page

**Two false alarms, worth recording because the diagnosis method mattered more
than either outcome.** A 200 carried `x-render-origin-server: uvicorn` (the app
answering) and the 404s carried no such header (Render's router, with no
instance to route to) — **that separated "app is broken" from "no instance is
up" without guessing.**

**The real bug: the frontend leaked a credential into user-visible output.**
`API_BASE_URL` was set to the Postgres connection string; `requests` has no
adapter for it, so it raised — and the error text interpolated both the env var
and the raw exception, **so the live database password rendered onto a publicly
reachable page.** The misconfiguration was human; the defect is this project's:
**an error message is user-visible output, and user-visible output must not
carry a credential** — sec. 2, which until then had been read as being about
repo files. Fixed three ways, including scrubbing the raw value out of
exception text, **since sanitising our own message is not enough when
`requests` embeds the URL in its.**

**`requirements.txt` had no version pins.** One file of bare names produced
**three different stacks** — the repo venv on Python 3.9, GitHub Actions
re-resolving every run, and Render's first deploy landing on **Python 3.14**
with pandas 3.0. So the suite certified software that was not the software
running, and worse, **any rebuild could change production with no commit to
point at**, the hardest class of bug to trace. Fixed by pinning the **full
63-package closure**, not the seven direct ones — pandas arrives *through*
streamlit. **The method mattered more than the diff:** a first pass dropped
GitPython as local tooling, and `pip install --dry-run` showed streamlit
*requires* it. **Classifying dependencies by what they look like is guessing;
the resolver knows.**

## 2026-09-06 — Step 11: the jobs nobody watches get watched

Two unattended processes hold a database credential, an API key and a budget,
and their entire health surface was one timestamp. **The gap that mattered is
not "a job crashed"** — a crash is loud. **It is a job that finishes green
while doing nothing**, and this project has been in that state twice.

**A third state:** a run can now say "finished, but part of me broke". The
prose call returns `(spend, error)` — **the money surviving the exception was
not enough, the reason has to survive too.** The budget-skip path deliberately
writes no error: a ceiling refusing a call is the guard working.

**`safe_errors.py` closes the credential leak's second door** — cron catches an
exception, writes it to a column, an endpoint reads it back, a page prints it.
`scrub()` is belt-and-braces: exact replacement of the values this process
holds, plus redaction by *shape*, **which is what catches the credential this
process did not know it had.**

**`/ops/status` is a list of named conditions each carrying its own
measurement, never a summed health index** — "two alerts" is not twice as bad
as one. Severity is split so the alarm keeps meaning something: a stale monitor
is critical, a stale agent a warning, and **zero proposals filed is not a fault
at all.** Every rule is a real incident, not ops boilerplate.

**The escalation is the workflow going red** — GitHub's own notification, so no
email provider and nothing new that can itself break. Wiring an ops alarm
through the digest **would make an outage depend on the notification system
that outage might have taken down.** Warnings do not fail the job.

**Live data corrected an assumption within ten minutes**: the record showed
**17 monitor runs against 13 scheduled slots**, not the expected under-run,
because the table cannot tell a dispatch from a schedule. And the denominator
had to be measured from each job's **first run** — dividing a 28-day window by
a weekly cadence **invented a 75% miss rate out of history that never
existed.** It also caught a test passing *through* an exception path: once the
function returns *why* it stopped, "returned 0.0" and "returned 0.0 because it
crashed" stop looking the same.

## 2026-09-06 — Step 10's last item: the uptime monitor that reported a false outage

The API monitor reported **Down for its entire existence** while the service
answered in 0.4s — a protocol mismatch: UptimeRobot's HTTP monitors send
**HEAD**, FastAPI's `/health` returns **405** to HEAD, and any non-2xx reads as
down. Streamlit's health endpoint accepts HEAD, so only one of the two was red
— **a useful asymmetry that pointed at the request method rather than at either
service.** The free fix is a **keyword monitor**, which sends GET and
additionally asserts the body says `ok` — **a stronger check than HEAD anyway**,
since an empty 200 or an error page would pass the first and fail the second.

**The keep-warm still worked the whole time it was reporting down** — a failed
HEAD still resets the idle timer. The monitor's *reporting* was broken; its job
was not. **Worth separating those two before treating a red dashboard as an
outage.**

## 2026-09-07 — The first clinician judgments of real TrialLens output

Since the ranking layer was removed this project had carried an unanswered
question: **no clinician had ever judged a real TrialLens output.** Four flags
were read and called — two dismissed, two significant. On a sample of four that
is not a false-positive rate and must not be quoted as one.

**The clinician is the author of this project**, which is the limit on what
these judgments establish. Domain expertise in the person building the thing
is worth something — it caught three real defects the tests did not — but it
is not independent review, and nothing here should be quoted as if it were.
An outside researcher reading this output remains the missing evidence.

**The most useful finding is a caveat the user attached unprompted, and it is
the thing most likely to be misapplied later.** They dismissed a terminology
change *and* immediately ruled out generalising it: *"some changes in
terminology are significant unlike this one."* So **"terminology change →
dismiss" is exactly the rule that must NOT be written.** What made this
instance dismissible was narrower: **the old description already stated what
the new title says.** That points at a real defect — the flag compares measure
NAMES and ignores descriptions, where the meaning lives.

**Method note.** Before these judgments the agent asserted that ~31% of
surviving flags matched the dismissed case, from a heuristic written on the
spot; reading the cases it selected showed none of them was that pattern. The
claim was withdrawn before the user acted on it. **The heuristic produced a
number, and a number reads as a measurement even when it is a guess with
arithmetic attached.**

## 2026-09-07 — All twelve substantive outcome flags, judged by a clinician

All 12 read and called: **9 significant, 3 dismissed.** (Corrected count: 22
changes total, 12 substantive. An earlier entry said "nine remain", which was
wrong — the page listed only 8 of the 12, so four had never been displayed to
anyone.) **9 of 12 worth a researcher's attention: the flag is not noisy.** That
is the first measured answer to the question `verify_ranking_results.md` asked
and never got, and it argues against loosening the filter's bias.

**Two judgments corrected the agent's own reading**, which is the point of
having a clinician do this. The agent leaned toward dismissing a narrowed
observation window as registry housekeeping; the user overruled — **narrowing
an observation window after results are known is concerning on its face,
whatever the protocol says.** And it read "Part C was never initiated" as a
harmless annotation, where the user read it as exactly what a researcher must
know.

**Three blind spots:** time frames ignored, descriptions ignored, and the 10
reformatting-only changes hidden from the page entirely — counted but not
listable, **so the filter is trusted rather than auditable.** Time frames were
fixed first, and **not the obvious order**: fixing descriptions first would
have auto-dismissed a case whose descriptions are identical on both sides and
which the user judged significant on its time frame. **A false positive costs a
reviewer seconds; a false negative is never seen.**

## 2026-09-07 — Fixing the two gaps the clinician review found

**Observation windows are compared**, keyed by the normalised measure name so a
window is still compared across a re-capitalisation. Live effect: **wording_only
10 → 8, substantive 12 → 14.** **No direction is computed** — CT.gov time
frames are free text ("up to 2 years"), so deriving "shortened by six weeks"
would be a computed claim about a study fact. The reviewer reads both values.

**The reformatting bucket is collapsed, not hidden** — the `continue` that made
four real changes invisible is replaced by an expander, so **the filter is
auditable rather than trusted.** Four new tests built from real records, two of
them guards against over-correcting.

## 2026-09-07 — Descriptions, the third blind spot, and a cap that quietly undid a fix

**Endpoint descriptions are compared now** — the measure name says *what* is
counted, the description says how it is measured, and nothing had ever read it.
**Only an edit or a deletion escalates. An addition does not, and that is the
whole design decision:** measured first, because treating *any* description
difference as substantive moves **8 reformatting changes down to 1**, gutting
the filter. The clinician dismissed exactly that pattern twice, and **you
cannot diff against silence** — a description appearing where there was none
says the entry is more complete, not that the endpoint moved. An added
description is still *listed*: **not escalated is not the same as not shown.**

**Effect: wording_only 8 → 3, substantive 14 → 19** — honestly three real and
two trivial ("(0-10)" → "(0-10 scale)"). **No deterministic rule separates
them**; the only thing that would is a threshold on words moved, **a tuned knob
whose reasoning is invisible.** Two extra cards costing seconds is the honest
price, stated rather than tuned away.

**A cap written for one section had silently undone a fix written for
another** — the more serious finding. The morning's expander listed **nothing**
against the real record: one `NAMED_CAP` of 8 over a substantive-first sort
pushed the whole reformatting bucket off the end. **The page printed "3
reformatting only" above an expander that could not render, and the four
changes a clinician had found hidden that morning were hidden again by
lunchtime, by a different mechanism.** It passed every test because **both
suites asserted on the classification, never on what survived the cap.** Fixed
with a cap per bucket plus "showing the first 8 of 19", which every other
capped list already said. **The page is now rendered against the real payload,
not only fixtures, because fixtures are what hid this.**

## 2026-09-07 — Three categories, and the agent stops reading case notes

**"Reformatting only" was a false label.** A change with a definition filled in
was filed under it, and nothing about it was reformatted — a fact appeared in
the registry that was not there before. The binary rule had no way to say so,
worst of all when a definition appears **after results are known**, which is
exactly when a reader would want it. Three categories now: `substantive` (19),
`entry_completed` (2), `reformatting` (1). One `category` string rather than a
pair of booleans, because **a pair would permit an impossible both-true
state.** Every category keeps its own milestone flags, which is what makes this
sufficient rather than a rename. **A flag cannot carry this distinction. A
named category can.**

**The agent was being handed case notes to answer a question about totals.**
One `/investigate` response is **39,972 characters**, of which **277 (0.7%)**
are the numbers it reasons with; the rest is per-trial cards built for a human
to click — **and the Messages API is stateless, so the loop paid for those
cards five or six times over.** `GET /investigate/summary` returns the counts
plus bare NCT IDs at **4,099 characters, 89.7% smaller**, cutting the loop's
input cost **84%**. It **does not re-derive anything** (same helper as the
page) and **does not add a cap** — a first draft had one that could never bind,
the same shape as the morning's cap fault and harmless only by luck.

**Not buying a foregone conclusion.** The first run's outcome was determined
before any money was spent, and "does the record hold two prior windows" is a
database question. **`MIN_PRIOR_WINDOWS = 2` is read off the agent's own system
prompt**, not picked, and a test asserts the prompt still says so — otherwise
this enforces a rule nobody stated. **A failed lookup returns `None` and does
NOT skip**, because a transient blip silently skipping a week is what step 11
exists to make visible, and a skip writes a reason rather than a plain
`completed` with zero proposals.

**The chart's third colour was computed, not chosen** — the obvious middle
measured **ΔE 13.7, under the floor of 15**. It looked fine. **Considered and
not done: prompt caching** — **Haiku 4.5 has the highest minimum cacheable
prefix of any current model, 4,096 tokens**, and this agent's static prefix is
**1,918**, so the obvious breakpoint would have cached *nothing*, silently,
with a bigger bill.

## 2026-09-07 — Step 12: the digest, and the two things a researcher asked for

**The external-service risk mostly evaporated.** Resend's docs say you must
verify a domain, which for a project with no domain reads as a blocker. It is
not: the shared sender needs no DNS, and its one restriction — it delivers only
to the account owner's own address — **is exactly this product's shape.**

**What leads, chosen by measuring:** substantive outcome changes named
individually, everything else as counts. A weekday carries **65-136 changed
trials**, which nobody will read, against **0-5 substantive outcome changes**.

**Two corrections from the user.** *No empty email* — a mail that says nothing
happened teaches the reader to skim, and then the one that matters is skimmed
too. *Drop weekends* — and **the obvious implementation is wrong: a rolling
"everything since the last digest" window cannot exclude the weekend**, because
"since Friday 07:00" necessarily contains it, and clipping the start to Monday
would silently drop a whole working day. So the window is **one whole weekday**;
Monday reports Friday.

Two settings are not copied blindly from the sibling jobs: `stale_after_hours`
is **96, not 48**, because the Friday-to-Monday gap is 72 hours by design; and
zero work is **not** a fault, because 5 of the first 10 days had no substantive
change and alerting would fire on half of all correct runs.

**The per-trial link goes to ClinicalTrials.gov, not TrialLens** — it is the
source of every fact in the mail, needs no login, and will outlive any URL of
ours. **Sec. 2 applies at least as strictly here as on the page**, because an
email is read in an inbox away from anything that explains itself; the subject
line is held to it too. **One real defect the live dry run found**, which no
fixture would have: one trial renamed its drug and produced **12 bullet lines**
for what a reader would call one change — capped at 6, with the remainder
counted, never silently truncated.

## 2026-09-07 — The weekly agent died on a real schedule, and took its receipts with it

**Bug 1 — an empty user message.** The loop builds tool results only when
`stop_reason == "tool_use"`, which should guarantee a tool_use block; **on the
sixth turn the model returned that stop reason with none.** It stops with an
**error**, not quietly, because a run that files nothing is otherwise
indistinguishable from a week correctly found quiet.

**Bug 2 — the spend went missing, and a comment said it could not.**
`proposals, spend = run_synthesis(...)` inside a `try`, with an accurate
comment above it saying whatever was spent must still reach the run record.
**The comment is right and the code cannot do it** — the tuple never binds when
the callee raises, so five paid calls were recorded as `$0.0000`. This is the
*same* accounting hole as 2026-09-03, written up once, restated in a comment at
the new site, and reopened there anyway. **A comment describing an invariant is
not the invariant.** The tell was the number, not the exception. Fixed by
changing the contract to return `(proposals, spend, error)`.

**What this says about the ops surface:** `/ops/status` showed the failed run —
the alarm worked. What it could not show was that the run had *cost* something.
**A health surface that reads its own job's self-report inherits that report's
bugs.**

## 2026-09-07 — Pushing it found two more things, both from watching it run

**Every Tuesday would have leaked the weekend back in.** Monday's digest
reports Friday, so it leaves `covered_until` at Saturday — always earlier than
Tuesday's Monday, so the catch-up test read the *deliberate* gap as a missed
run, every week. The comparison has to be against what a **healthy
predecessor** would have left. **The lesson is about the test, not the code:**
every window assertion passed, because each was written against a single call
with a hand-chosen previous value. **Stateful cadences need a simulation, not a
table of independent cases.** A second guard: an already-covered window sends
nothing, because **a duplicate is worse than an empty one — the reader cannot
tell it from a day that genuinely repeated.**

**A correct skip was failing the build every six hours.** The history skip
fired CRITICAL for a condition **no action can clear** — it resolves with
calendar time — and would have run `monitor.yml` red four times a day for a
fortnight. That is the exact failure `check_ops_health.py`'s own docstring
warns about. Severity now splits on whether a skip is **actionable**:
self-resolving ones are WARNING, **budget stays CRITICAL, and so does any
prefix nobody has classified — an allowlist, because an unconsidered skip
should be louder than a considered one, never quieter.**

**What both have in common.** Neither was findable by reading the diff, and
neither was a coding error — both were correct code meeting reality. **Shipping
is a test the test suite cannot run.**

## 2026-09-07 — Neon's transfer allowance, measured rather than blamed

Neon warned at 82% of 5 GB, and **the two obvious suspects were both wrong.**
The 6-hourly graph rebuild looks damning, but every query is `INSERT ...
SELECT`, so the JSON never crosses the wire; and the ingest is genuinely lean.

**The measured answer is the test suite:** the free 757 tests cost **0.5 MB and
38s**, the 121 real-data tests **56 MB and 161s** — **86% of the coverage for
0.8% of the transfer.** Roughly ten full-suite runs in one session is ~560 MB,
about 14% of the monthly allowance. The real-data half is not optional at a
commit — it is the only thing that tests the SQL — it just should not run forty
times while a docstring is being edited.

A second amplifier was named and deliberately left: **a blanket frontend cache
would also cache the tracked-conditions list immediately after the "+ Add"
write, and a monitoring tool that appears not to register a change the user
just made is worse than one that costs bandwidth.**

## 2026-09-07 — The frontend finally remembers something, per endpoint

**One Investigate rerun is 43,842 measured bytes**, all four calls
unconditional — Streamlit executes every tab body whether or not you are
looking at it.

**Why an allowlist and not `@st.cache_data` on `get`.** A blanket cache is one
line and would have shipped a lie: **`/ops/status` exists to say what is true
*now***, where a five-minute-old all-clear during an incident is the exact
failure step 11 prevents, and **`/discover`'s live CT.gov fallback could hide a
trial registered minutes ago.** So `CACHEABLE_PATHS` is explicit and anything
unclassified is not cached — **an endpoint added next month is slow by default,
never silently stale by default.**

**A write clears everything, bluntly.** The finer alternative is one more table
to forget an entry in, and **a forgotten entry shows the user a page that
ignored what they just did.** TTL is 300s against a 6-hour cron, so it cannot
make a reader see a stale record.

**The part the unit tests structurally cannot show**, since every page test
stubs the client and bypasses the cache: three real `AppTest` runs with
`requests.get` counted — **1 HTTP GET, not 3.** That is the only claim that
matters and the one thing "it's decorated, so it works" would not have
established. **One dead rule found and deleted** — a `/health` entry no page
reads — plus a canary in both directions.

## 2026-09-08 — Removing a condition, and the 19% the record could not account for

A one-line answer with a much longer one underneath, **because the obvious
implementation would have quietly stranded a fifth of the watch.**

Three costs had to be separated. *Ongoing cost: no* — nothing queries CT.gov
for an unregistered condition, so spend is per detected change, never per
stored row. *Storage: yes* — ~60 MB of dead weight. *"All the trials associated
with it": not answerable from what was stored*, and that is what mattered.

**The measurement that changed the design.** The only link between a watched
term and its trials was a substring match, and **2,173 of 11,453 in-scope
trials (19%) match no tracked term at all**, because CT.gov expands synonyms
when it searches (`Breast Neoplasms`, `Obese`). A removal built on that rule
would have left ~2,000 trials `active_in_scope = true` **with no query left
that returns them** — counted in the watch headline while nothing watched them.
**That is the finishes-green-while-doing-nothing state step 11 exists to catch,
and it would have been introduced by the feature rather than found by it.** The
same blind spot still exists in the other direction: a synonym-tagged trial can
never age out of scope. Measured and recorded, not changed, because switching
that query would move live rows.

**So attribution came first.** `study_tracked_conditions` is written by the
reconcile endpoint, which already receives exactly that pair once per condition
per run. `untracked_at` is a stamp, not a delete, and re-adding a condition
revives its attribution on the next run — **that is what makes removal
reversible.**

**The removal itself: untrack, never delete.** Those change rows are the
product's actual output — the amendments, the 22 outcome changes a clinician
judged, the digest history. **Deleting trials makes last week's digest
unreproducible**, and disk is the cheapest of the three costs.

**Two refusals, both deliberate:** the last condition on the list, and any
removal before attribution exists. The second check is **global**, not
per-condition, so a typo condition that genuinely matched nothing stays
removable — **otherwise the guard would create its own trap.** The response
carries `trials_unattributed` rather than just an outcome: **anything non-zero
is the record saying this answer is narrower than it looks.**

Verified at three levels, including 6 real-data tests that **write and roll
back** — the right shape for a suite whose subject is a delete endpoint in a
table a `LIKE '__%'` cleanup once emptied. The case they exist for is the
overlap: **only 14 of 9,294 trials are brought in by both conditions**, and a
wrong query would drop them where no hand-check would notice. **The record
earns the right to be edited.**

## 2026-09-08 — The bandwidth postmortem blamed the wrong runner

The previous entry closed with "mostly this session", and left ~3.5 GB
unattributed. Half of that was wrong, and the question that found it was "will
pushing use up the allowance?"

**Pushing costs nothing** — `tests.yml` runs deliberately without database
credentials. **The 6-hourly cron does:** its drift-check step ran the full
suite *with* credentials, **29 runs × 56 MB ≈ 1.6 GB, ~224 MB/day,
unattended.** The entry that went looking for the cause measured the runs it
could see — the local ones — and stopped. **The tell was that the suspect it
cleared and the suspect it convicted were both things a human types. An
unattended job running the same expensive thing four times a day was never in
the lineup.**

**Fixed by cadence, not deletion** — the drift checks are real, they just check
for something that does not happen on a six-hour cycle. Moved to two ticks a
day, with the gating condition checked against every hour for both event types
first, **because a `case` pattern that quietly matches nothing would turn this
into "drift checks never run again"** — the same silence this project keeps
having to design against. **And the escape hatch had the same bug in
miniature:** running checks on *every* manual dispatch would charge 56 MB to
dispatches made for an unrelated reason. **A cost control that fires when
nobody asked for it is how the cost comes back.**

## 2026-09-08 — The transfer ledger, and a cadence that restores itself

The billing period runs **26 Aug → 26 Sep**, which turns "we are at 82%" into a
deadline. The Free plan does not expose the consumption API, so attribution
came from run counts × measured per-run cost: ~2.3 GB of 4.1 GB accounted for,
the rest most likely unrecorded local runs. **The gain is not the estimate, it
is that two suspects are now eliminated rather than assumed** — a push costs
nothing, and the 5-minute uptime pings cost nothing since `/health` never
touches Postgres.

**Halving was not enough, and the arithmetic says so:** ~840 MB over 18 days is
a ~47 MB/day budget, and twice-daily checks exhaust it ~16 Sep. **And running
out is not a slowdown: Neon's Free plan suspends the compute**, so the deployed
site would go dark during the window it is being shown to employers. **A cost
control that is merely an improvement is not a fix when there is a deadline
attached.**

**So: weekly until the reset, twice daily after — decided by the code, not by a
comment.** The step reads `BILLING_RESET=2026-09-26` and picks its own cadence.
**Writing "remember to put this back" in a comment is how it would quietly stay
weekly for a year**, and this project already has the rule that a comment
describing an invariant is not the invariant. Also newly watched: storage is
**249 MB of 0.5 GB** — transfer was the loud meter, that one is quieter and
nearer.

## 2026-09-08 — Wrap-up: what the public repo says, and the Corroborate question answered

**The docs were describing a different project.** The README still said "not a
deployed product", "three of five capabilities", "no model call in this system
today" and "248 tests" — against a deployed app, five live capabilities, two
paid model paths and **914 tests**. Every one was true when written; none had
been re-read since. **A status essay copied into three files goes stale in
three files** — the rule CLAUDE.md's own status section states, and which
CLAUDE.md itself had stopped obeying at 315 lines.

So CLAUDE.md is under 100 lines across four sections, keeping the `§2`-`§7`
numbering because **~30 code comments cite those section numbers by name**; the
standing gotchas moved to `docs/gotchas.md`; and this file was compressed with
**every dated heading kept verbatim**, because they are cited by date from
code, tests and the roadmap. The course-tracking material is out of the repo.

**Corroborate: still possible, but not in either app's current shape.** The
2026-08-26 entry deferred a literature Q&A integration without recording the
technical reason. Checked directly: Corroborate is *one in-process Python
program* — Streamlit calling ingestion, SQLite and RAG functions directly, with
a FastAPI layer its own README says was "scaffolded in Step 1 but never built,
and was removed rather than left as dead code". **So there is no door to knock
on:** Streamlit Community Cloud serves a websocket UI, not an HTTP API, and its
storage is a local SQLite file plus a Chroma directory that does not survive a
restart and is not reachable from Render. Different runtimes, different
databases.

Cheapest option is a **link-out** (a pre-filled query, no shared state), which
needs Corroborate actually deployed — its README still says in progress. The
real integration needs the FastAPI door back, a hosted vector store (pgvector
on the existing Neon project), a deploy and an auth story. Deferred again, but
now for a stated reason rather than a feeling. **§5's "no vector store" stands;
that second option is where it would change.**
