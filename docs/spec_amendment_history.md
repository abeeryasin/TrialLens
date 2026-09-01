# Spec — amendment history (step 7b, direction 1)

**Written 2026-09-01.** The first of the three directions in
`docs/plan_after_ranking.md`. No model, no new API cost, no new external
dependency. Every number below was queried from the live `dev` database on
2026-09-01, not assumed (CLAUDE.md §6).

---

## What it is

ClinicalTrials.gov holds only a trial's **current** version. It will tell
you what a trial says today; it will not tell you that the primary outcome
was rewritten, that the completion date slipped a year, or that enrollment
was quietly revised down. TrialLens has been recording exactly that since
2026-08-28, and currently shows it as an undifferentiated list of field
changes.

Amendment history turns that list into the trial's story: **"amended twice
since we started watching — here is each one, and what moved."**

---

## What the data actually says

Queried 2026-09-01 against `study_changes` (498 rows, 262 trials,
2026-08-28 → 2026-09-01).

### 1. `detected_at` is not a run identifier — do not group by it

One cron run writes its rows over several seconds, and those seconds cross
minute boundaries:

```
2026-08-28 12:55:52.606   ← same run
2026-08-28 12:56:00.655   ←
2026-08-29 00:01:58.694   ← next run, 11 hours later
```

`date_trunc('minute', detected_at)` splits that single run in two and would
report one amendment as two. Gaps *within* a run are under 9 seconds; gaps
*between* runs are never less than 11 hours — so a gap rule would work, but
it is a heuristic about our scheduler, and there is a better key that is a
fact about the trial.

### 2. The amendment key is the trial's own `last_update_post_date`

`last_update_post_date` is itself a tracked field (212 changes across 171
trials), and its `new_value` is **the registry's own version stamp** — the
date ClinicalTrials.gov says the record was amended. Three properties were
verified, not assumed:

| check | result |
|---|---|
| content changes with no accompanying `last_update_post_date` move | **0 of 195** |
| a trial getting two `last_update_post_date` moves in one run | **0** |
| `active_in_scope` events co-occurring with an amendment | **0 of 91** — always standalone |

So every content change belongs to exactly one amendment, identified by the
`new_value` of that trial's `last_update_post_date` change in the same run.
That is CT.gov's date, not ours — which is the honest one to show, and the
one that survives a change in how often the cron runs.

**These three properties must become tests.** They are load-bearing, and if
CT.gov ever violates one, the grouping silently mis-reports rather than
failing.

### 3. Nearly half of all amendments are invisible to us

Of 212 amendments, **99 (47%) moved `last_update_post_date` and nothing
else we store.** CT.gov amended a field TrialLens does not track.

This is the spec's central honesty problem. The system knows three
genuinely different things and must never conflate them:

| reality | what the UI must say |
|---|---|
| No amendment posted | "No amendments since we started watching" |
| Amended, and we can show what moved | the amendment, with its fields |
| Amended, but the change was in a field we don't store | **"Amended on 1 Sept — the change was in a field TrialLens doesn't track"** |

Rendering the third case as "no changes" would be a false statement about a
study fact (CLAUDE.md §2). It is the same class of error as the `unknown`
vs `not_applicable` conflation recorded on 2026-08-31.

### 4. The history is five days old, and must say so

First recorded change is 2026-08-28 (tracking began 2026-08-26; the first
ingest had nothing to diff against). Every count is therefore **"since we
started watching,"** never "since the trial was registered." A trial
amended eleven times in 2024 shows zero amendments here, and the UI must
make that unmistakable rather than implying a quiet trial.

### 5. Volume, for sizing

| | |
|---|---|
| trials with any change | 262 of 11,469 (2.3%) |
| trials with 1 change | 152 |
| most changes on one trial | 6 |
| most common changed fields | `last_update_post_date` (212), `active_in_scope` (91), `completion_date` (25), `primary_completion_date` (25), `overall_status` (24) |

Small. This is a low-volume product by design, and the feature does not
need pagination or a cache.

### A real example, already in the data

`NCT02954874`, exactly as it would render:

```
Amended twice since we started watching, 28 August

  31 August 2026
    Completion date      2026-08-31  →  2027-08-27   (slipped ~1 year)
    Enrollment           1,155       →  1,195
    Enrollment type      ESTIMATED   →  ACTUAL
    Primary completion   2026-08-31  →  2026-08-03

  28 August 2026
    Amended, but the change was in a field TrialLens doesn't track.
```

That top amendment is a story — the trial finished enrolling, reported a
real headcount, and pushed completion out a year — and it is precisely what
ClinicalTrials.gov cannot show you.

---

## What gets built

### 1. `GET /studies/{nct_id}/amendments`

Groups that trial's `study_changes` rows into amendments. Not a new table —
no schema change, no backfill, no migration. The grouping is a query.

- One amendment per `last_update_post_date` change, dated by its
  `new_value` (the registry's date), ordered newest first.
- Each amendment carries the content changes detected in the same run.
- `active_in_scope` and other tracking fields are **excluded** — they are
  our bookkeeping, not the sponsor's amendment. The category split in
  `api/tracking.py` already draws this line; reuse it rather than
  re-deciding it.
- An amendment with no accompanying content change is returned explicitly,
  flagged, never omitted.
- Response carries `watching_since` so the page can state the window rather
  than leaving the reader to assume it means "ever."

### 2. Understand page — amendment history as the headline

`frontend/pages/2_Understand.py` currently shows a flat change list. It
becomes the grouped history above, moved up the page. Reuses
`summarize_text_change` / `render_text_diff` from `frontend/labels.py`
unchanged.

### 3. Tests, since none of this code has any

The suite has no API, database, or frontend coverage at all — every
surviving test covers the deterministic scorers. This unit ships with:

- **The three verified properties** from §2 above, as real-data tests
  against the live database, in the shape of `tests/test_ranking_real_data.py`
  (skips cleanly with no credentials).
- **HTTP-level endpoint tests** — not calls to the endpoint function.
  CLAUDE.md §7: request binding and response validation are FastAPI's job,
  and only an HTTP call exercises them. This is bug #9's lesson, which cost
  $0.13 to learn.
- **`is_formatting_only` unit tests.** Its docstring claims four specific
  cases "were checked and correctly return False" — a BMI cutoff moving
  35→45, an eGFR threshold moving <60→<30, a dropped "no". Nothing checks
  them. Amendment history depends on this function to decide whether to
  tell a researcher the wording changed, so the claim gets a test.
  (`_ACTIVE_WORK.md` says this function has no callers; it does —
  `labels.py:176` and `:194`, reached from both Monitor and Understand.)

---

## Done when

1. `GET /studies/NCT02954874/amendments` returns two amendments, the
   31 August one carrying its four field changes, the 28 August one flagged
   as amended-but-untracked — verified over HTTP, not by calling the
   function.
2. The Understand page renders that trial's history as its headline, and
   states the watching window on the same screen.
3. A trial with no amendments says "none since we started watching," and a
   trial amended only in untracked fields never renders as "no changes."
4. The three grouping properties are enforced by tests against the live
   database, so a change in CT.gov's behaviour fails loudly.
5. No model is called anywhere in the path — provable by the code never
   importing `anthropic`.

## Explicitly not in this unit

- Backfilling history from before 2026-08-28. CT.gov does not serve prior
  versions through the v2 API; there is nothing to backfill from, and
  inventing one would violate §2.
- Regrouping the cross-trial Monitor feed by amendment (a 5-field amendment
  currently floods it as 5 rows). Same grouping logic would apply and it is
  a real improvement — but it is the watch's problem, direction 2.
