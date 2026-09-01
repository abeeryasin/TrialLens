# What replaces the ranking layer

**Written 2026-09-01, revised the same day.** Supersedes the ranking layer
built in step 7 (`f9ccb45`), which is committed as a documented dead end.
This is roadmap **step 7b**, not step 8 — step 8 is the knowledge graph.

---

## Priority, decided 2026-09-01

A lateral-thinking pass over "what should a researcher see, given it must
cost near-nothing to run" produced ten stimuli. Every idea that landed was
about **time and continuity**; every idea that died had tried to attach to
**evaluating or sorting trials**. That is a diagnosis, not luck: the
evaluation axis is exhausted, which is why removing the score felt right.

**Three directions, agreed with the user, in order. None needs a model:**

1. **Amendment history.** A trial's changes are its headline, not a
   footnote — "amended three times, here is each one." A primary outcome
   rewritten 14 months after first posting is a story, and it is the one
   thing ClinicalTrials.gov structurally cannot show, because it holds
   only the current version. `study_changes` already has the data.
2. **The watch.** Lead with the watching, not with a search box:
   *"Watching 9,268 trials, last checked 2 hours ago."* And design the
   **quiet week as the primary screen** — most weeks nothing important
   happens, so that is the screen a researcher sees most often, and it
   currently reads as a broken app rather than a confident report.
3. **The watch record.** Elapsed time is the moat and nothing shows it:
   *"Watching since 26 August · 1,412 changes recorded."* A fresh clone of
   the repo has none of that. Its sharp edge: **if the cron stops, say so
   loudly** rather than serving a stale feed that looks fine.

**The relevance column below is fourth, not first.** It answers a real
problem — Discover shows trials merely tagged with a condition — but it is
the only part that costs money, and it sits on the evaluation axis the
lateral pass found exhausted. Build it after the three above, and only if
Discover's mis-tagging still bothers a real user.

---

## Why the relevance column, when it is built

Step 7 scored trials on eight signals. Measuring it against real data
showed four of the five scored signals were **filters wearing a score's
costume** — "is it recruiting?" is a yes/no the researcher already stated,
and turning it into 20 points that blend into a 0.87 is strictly worse than
filtering on it.

One signal survives that argument: **is this trial actually about the
condition, or merely tagged with it?** Measured on real trials it returned
match 9 / partial 9 / no_match 2 — only about half of "breast cancer"
results are primarily breast cancer trials. No SQL answers that.

But step 7 asked it the wrong way: bundled into the researcher's whole
interest, so the answer was filed under their exact sentence and thrown
away after one search. **It is a fact about the trial, not about the
search.** Ask it once, store it, and it is free forever.

---

## The shape

```
BEFORE (step 7)                  AFTER (step 8)
──────────────────              ──────────────────
type an interest                pick filters (recruiting, phase, age, type)
   ↓ 1 paid call                   ↓ free, instant, SQL
score 5,371 in code              filtered results
   ↓                                ↓
top 20                           read stored relevance for each
   ↓ 20 paid calls                  ↓ free — already on disk
a 0.87 with 8 signals            results, with mis-tagged trials flagged

$0.32 per search                 $0.00 per search
```

Classification happens **in the background, never in the request path**.

---

## What to build

### 1. `study_condition_relevance` — a new table

Keyed on **(nct_id, condition)**, not nct_id alone: a trial tagged with
both breast cancer and obesity needs a verdict for each.

```sql
CREATE TABLE IF NOT EXISTS study_condition_relevance (
    nct_id        TEXT NOT NULL,
    condition     TEXT NOT NULL,
    verdict       TEXT NOT NULL,   -- primary | secondary | incidental | unknown
    evidence      TEXT NOT NULL,   -- sec. 3: never a bare verdict
    model         TEXT NOT NULL,   -- which model said so
    classified_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (nct_id, condition)
);
```

**Do not put these columns on `study_conditions`.** That table is
`DELETE`d and re-inserted wholesale on every batch upsert
(`api/studies.py`), so any verdict stored there would be silently wiped
the next time the trial changed. This is exactly the class of gotcha
`docs/decisions.md` exists to record.

`verdict` deliberately keeps `unknown` distinct from `incidental` — "the
record is too thin to tell" and "this is not that kind of trial" are
different facts, and only the first might change (see the 2026-08-31 entry
on `not_applicable`).

### 2. A demand queue, so only what people see gets classified

```sql
CREATE TABLE IF NOT EXISTS relevance_queue (
    nct_id       TEXT NOT NULL,
    condition    TEXT NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (nct_id, condition)
);
```

When a read endpoint returns trials, it inserts any unclassified
(nct_id, condition) pairs here — a plain `INSERT ... ON CONFLICT DO
NOTHING`, no model call, no added latency. Cost is then bounded by
**distinct trials anyone has actually seen**, not by trials stored or
searches run. Realistically a few hundred, not 11,490.

### 3. A classifier in the scheduled job

`scripts/run_monitor.py` already wakes every 6 hours. Add a final step:
drain up to `RELEVANCE_BATCH_SIZE` queued pairs, classify each, write the
verdict, delete the queue row.

- **One question per call.** Trial title, official title, summary,
  conditions, interventions — and the condition being asked about. Nothing
  about any researcher's interest.
- **Model: `claude-haiku-4-5`** (~$0.004/call vs Opus's ~$0.019). Note
  `supports_effort()` already suppresses the `effort` parameter, which
  Haiku rejects.
- **Reuse the on-disk cache** in front of it, unchanged.

**Two hard caps, non-negotiable given this project's history:**
`RELEVANCE_BATCH_SIZE` (default 25) per run, and a refusal to start if a
running spend total exceeds `RELEVANCE_BUDGET_USD`. A background job that
can spend without a ceiling is the failure mode to design out, not to
monitor.

### 4. Filters replacing the score

`api/ranking_deterministic.py` already holds the logic; it becomes filter
predicates rather than scorers. Move it to `api/filters.py` and expose on
`GET /discover` and `GET /changes`:

| filter | source | notes |
|---|---|---|
| recruiting only | `overall_status` | 8 real values, already vocabularised |
| phase | `phase` | remember `PHASE1,PHASE2` and that 64% have none |
| age band | `minimum_age` / `maximum_age` | units are not all years |
| intervention type | `interventions[].type` | 11 real values, not 6 |

### 5. Display

Results show the stored verdict where one exists, and say nothing where
none does — never a guess, never a placeholder score.

```
NCT06139042  Adding Durvalumab to Standard Chemo Before Surgery
             Recruiting · Phase III · 1 site · 45 participants (target)

NCT05221100  Diabetes Management in Cancer Survivors
             ⚠ Tagged breast cancer, but the trial is about diabetes;
               breast cancer survivorship is the enrolled population.
```

An unclassified trial simply shows no line. Absence of a flag is not a
claim that the trial is relevant.

---

## What gets deleted

`git revert f9ccb45` removes: `api/ranking.py`, `api/ranking_schemas.py`,
`frontend/pages/4_Ranking.py`, `tests/test_ranking_endpoint.py`,
`scripts/rank_dry_run.py`, `scripts/cache_coverage.py`, and the ranking
test suites, and reverts `frontend/Home.py` to "planned".

Verified 2026-09-01 that this revert leaves the egress fix and all 50
`decisions.md` entries intact — that is why the branch was split into two
commits.

**Kept:** the deterministic scorers, `STUDY_DETAIL_COLUMNS`, the AST column
guard, `scripts/paid_preflight.py`, the response cache, and every dated
entry in `decisions.md`.

**One test must be deleted with the revert, not before:**
`test_every_type_the_parse_may_emit_is_a_real_ctgov_value` in
`tests/test_ranking_deterministic.py` asserts against
`INTEREST_PARSE_SCHEMA`, which the revert removes.

---

## Cost

| | step 7 | step 8 |
|---|---|---|
| per search | ~$0.32 | **$0.00** |
| per new trial seen | — | ~$0.004, once, ever |
| when out of credits | 503 | **works, minus the flags** |
| scales with | searches × visitors | distinct trials seen |

Nothing in the request path ever calls a model. The app is fully
functional with an empty account; classification resumes when credit
exists and never re-charges for a trial already done.

---

## Risks, honestly

- **One-time exposure.** A mis-tagged trial appears unflagged the first
  time it surfaces, and is flagged from the second. Accepted: cheaper than
  a page that costs money or blocks on a model.
- **Verdicts go stale.** If a trial's title or summary changes, its verdict
  should be invalidated. `study_changes` already knows when those fields
  move — delete the verdict row and re-queue.
- **Discover's long tail stays unclassified.** Only what surfaces gets
  classified. That is the point, but it means a rare trial's first viewer
  sees it unflagged.
- **The classifier is unvalidated.** Same gap as step 7:
  `docs/verify_ranking_results.md` must be run against real output before
  any claim that this works. It has never been run.

---

## Done when

1. A search returns filtered results with **zero model calls** — provable
   from `spend_note` and from the request never touching `anthropic`.
2. A known mis-tagged trial carries its flag on the second appearance.
3. The scheduled job classifies a bounded batch and stops at its cap —
   demonstrated by a run that hits the cap and refuses to continue.
4. With `ANTHROPIC_API_KEY` unset, every page still works; only the flags
   are absent.
5. `docs/verify_ranking_results.md` has been run once against real output,
   and its table is filled in.

Criterion 5 is the one step 7 never met. It is not optional this time.
