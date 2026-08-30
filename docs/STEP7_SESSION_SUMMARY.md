# Step 7 — AI ranking / evidence layer

**Last updated: 2026-08-31.** This replaces the 2026-08-30 version, which
described an architecture that no longer exists. If anything here disagrees
with the code, the code wins — check before trusting this.

---

## Start here — where the code actually is

**None of step 7 is on `main`.** It lives on the branch
**`step7-ranking-deterministic-split`** (2 commits ahead of `main`, which is
still at `35dae21`). If `api/ranking.py` appears to be missing, you are on
the wrong branch:

```bash
git checkout step7-ranking-deterministic-split
```

Merging to `main` was left to the user; don't merge unasked.

**Two things this work depends on are gitignored and do NOT travel with a
clone.** On the machine where the work was done, both are present:

| | Why it matters if absent |
|---|---|
| `.env.local` | Holds `ANTHROPIC_API_KEY` (rotated 2026-08-31) and the DB URLs. Without it the paid harness and `test_ranking_real_data.py` can't run — the latter skips cleanly, it does not fail. |
| `.ranking_cache/` | 44 recorded responses, covering all 48 requests the harness makes (four trial+interest pairs recur across scenarios). **Without it, re-running the eval harness costs real money instead of $0.00.** Check `ls .ranking_cache \| wc -l` before assuming a re-run is free. |

**Two-minute verification that the tree is sane** (all free, no API calls):

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/ -q \
  --ignore=tests/test_ranking_integration.py     # expect: 103 passed
PYTHONPATH=. .venv/bin/python tests/reachability_check.py | tail -1
                                                 # expect: "$0.0000" — proves the cache is intact
PYTHONPATH=. .venv/bin/python tests/test_ranking_integration.py --dry-run
                                                 # expect: 48 total model calls, no spend
```

If the first command reports fewer than 103, something is wrong — say so
rather than working around it.

---

## Where things actually stand

| Unit | State |
|---|---|
| 1 — Fit scoring schema | Done, then substantially revised (see below) |
| 2 — Evaluation harness | Done, then rewritten for the new architecture |
| 3 — Ranking endpoint | **Rebuilt 2026-08-31.** Original had 8 real bugs |
| 4 — Frontend | **NOT STARTED — this is the next task** |
| 5 — Real usage & iteration | Not started |
| 6 — Aesthetic redesign | Not started |

**103 free tests passing. $0.55 of the user's $5 API budget spent.**

> **Before building anything, read "Open questions the user has NOT decided"
> at the bottom.** Four decisions are deliberately still open — the ranking
> tie, what the eval suite should assert (it currently *cannot* pass), the
> paid prior-treatment case, and `sites_active` calibration. The user left
> these open on purpose. Don't resolve them unilaterally.

---

## The one hard constraint: budget

The user has **$5 total** for the Anthropic API and cannot spend more.
$0.55 is gone; roughly **$4.45 remains**. This shapes real decisions — not
a footnote.

Two mechanisms protect it, both already built:

1. **On-disk response cache** (`api/ranking.py`, `.ranking_cache/`,
   gitignored). Keyed on `sha256(model + effort + system + user_content)`.
   An identical request replays from disk for **$0.00** — demonstrated: a
   full 48-call eval suite re-ran at zero cost. Only a real prompt, model,
   or effort change forces new spend. **Iterating on weights, thresholds,
   scoring, or display is therefore free.** Disable with `RANKING_CACHE=0`.
2. **`MAX_TRIALS_PER_REQUEST = 50`** hard cap in the endpoint.

Measured cost: **~$0.006 per model call** at `effort=low` on `claude-opus-5`
with prompt caching active. A 20-trial search is roughly $0.13.

**Never wire the paid eval into CI.** The free tests are the CI half.

---

## Architecture as it now stands

**Deterministic first (CLAUDE.md §5).** Eight signals; five computed in
code, three judged by the model. `api/ranking_deterministic.py` does not
import `anthropic` at all.

| Signal | Weight | Where |
|---|---|---|
| `condition_is_subject` | 20% | model |
| `status_recruiting` | 20% | code |
| `phase_fit` | 15% | code |
| `prior_treatment_compatible` | 15% | model |
| `age_range_fit` | 10% | code |
| `approach_match` | 10% | model |
| `sites_active` | 5% | code |
| `enrollment_feasibility` | 5% | code |

**Call pattern:** `1 + N` per search of N trials — one interest parse for
the whole search, then one call per trial. Both use schema-constrained
output (`output_config.format`), not "please return JSON". There are **no
few-shot examples** anywhere; see below for why.

**Endpoint:** `POST /rank`, body `{researcher_interest, condition, limit}`.
Fetches full `StudyDetail` server-side. Returns `FitRankingResponse` with
`ranked_trials`, `preferences` (how the interest was read), `unspecified`
(questions that would close gaps), `unscored_weight`, `failures`,
`spend_note`.

---

## Eight bugs fixed on 2026-08-31 — do not reintroduce these

1. **`POST /rank` bound `researcher_interest` as a query param.** A bare
   `str` is a query parameter to FastAPI; only `trials` was the body. The
   old integration tests passed because they called the function directly,
   bypassing HTTP entirely.
2. **Per-trial exceptions silently swallowed.** A bare `except Exception:
   continue` meant a trial that failed to rank vanished from results with
   no indication the list was incomplete. Now reported in `failures`.
3. **`unknown` scored 0.0 while counting in the denominator.** This made
   "the researcher didn't ask" arithmetically identical to "the trial
   fails", capping scores near 0.65 for any plainly-worded interest. It was
   the cause of the recorded "0.60 when expecting 0.75+" symptom. `unknown`
   is now excluded from numerator *and* denominator.
4. **The prompt taught `CLOSED`, which is not a CT.gov status.** The eight
   real values are RECRUITING (3,982), COMPLETED (3,413),
   ACTIVE_NOT_RECRUITING (1,841), NOT_YET_RECRUITING (1,447), TERMINATED
   (385), ENROLLING_BY_INVITATION (233), WITHDRAWN (149), SUSPENDED (40).
5. **Only 2 of those 8 had any guidance** — ~20% of trials unguided.
6. **Phase format mismatch.** Stored as `PHASE2`, prompt showed `Phase 2`;
   multi-phase (`PHASE1,PHASE2`, 461 trials) unhandled.
7. **`eligibility_criteria` was never placed in the prompt payload**, while
   `prior_treatment_compatible` carried 15% weight. That signal could only
   ever return `unknown`. **A free payload test now guards this.**
8. **`source_field`/`source_value` were placeholder and empty string**,
   violating §3's evidence requirement.

Found later the same day: **observational studies scored `unknown` on
phase**, so they were excluded from scoring and could rank alongside genuine
Phase II trials for a researcher who explicitly asked for Phase II. Now
`no_match`, distinguished by `study_type`.

---

## Why there are no few-shot examples

The user spotted this, and it's worth preserving. The old prompt's three
examples filled `prior_treatment_compatible` and `age_range_fit` identically
in every one: `{"status": "unknown", "confidence": "low"}`. Read as a
pattern, that teaches the model which boxes to leave blank. **Whatever an
example holds constant, it teaches.**

Replaced with schema-constrained output. The API enforces shape, so no
example is needed to demonstrate it — and with none present, nothing can be
contaminated by them.

---

## Real data facts the code depends on

Measured against the live `dev` branch, 11,474 active trials, 2026-08-31.
Load-bearing — the code's vocabularies come from here, not CT.gov's docs.

- **Phase:** `NA` 4,869 + NULL 2,442 = **64% have no usable phase.** Splits
  almost perfectly by study type: 4,869 INTERVENTIONAL/`NA`, 2,440
  OBSERVATIONAL/NULL.
- **Age units are not all years:** Years, Months, Weeks, Days, Hours,
  Minutes. `1 Day` is a real `minimum_age` (12 trials). Reading it as 1 year
  is a 365x error.
- **50% have no `maximum_age`** (5,778). Absent means unbounded, not missing.
- **`enrollment_type`:** ESTIMATED 6,577 vs ACTUAL 4,905 — most report a
  target, not a headcount.
- **707 trials list zero sites.**
- **Intervention types:** DRUG 9,455, OTHER 3,967, **BEHAVIORAL 3,518**,
  PROCEDURE 2,042, DEVICE 1,045, DIETARY_SUPPLEMENT 767. Non-drug is over
  half — relevant because obesity is a tracked condition.
- **3,407 trials carry prior-therapy language** in `eligibility_criteria` —
  free fixtures for testing that signal.

---

## Tests: the free half and the paid half

**Free — run on every commit. 103 passing.**
```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/ -q \
  --ignore=tests/test_ranking_integration.py
```
- `test_ranking_deterministic.py` — the five code signals
- `test_ranking_scoring.py` — score arithmetic, confidence, elicitation, spend
- `test_ranking_prompt_payload.py` — **what actually reaches the model.**
  This is the half that would have caught bug #7 for $0.
- `test_ranking_real_data.py` — all five deterministic scorers against all
  11,474 real trials. Read-only; skips without `DATABASE_URL_READONLY`.

**Paid — by hand, at decision points only.**
```bash
PYTHONPATH=. .venv/bin/python tests/test_ranking_integration.py --dry-run      # free: call count
PYTHONPATH=. .venv/bin/python tests/test_ranking_integration.py --effort low
PYTHONPATH=. .venv/bin/python tests/test_ranking_integration.py --sweep-effort # low vs high
```
Reads `ANTHROPIC_API_KEY` from `.env.local` (gitignored). 48 calls per pass —
**but free on re-run if prompts haven't changed.**

---

## What the eval proves, and what it doesn't

Last paid run (2026-08-31, effort=low, $0.29): ordering correct 15/15,
`0/15` on score ranges.

**Read both numbers skeptically.**

- **The suite cannot pass. `0/15` is uninterpretable, not a quality signal.**
  Checked from cache at $0.00 (`--reachability` analysis, 2026-08-31):
  - **`confidence: "high"` is unreachable in 0/15 scenarios.** The rule needs
    `evaluated_fraction >= 0.80`, but **70% of signal weight is
    preference-gated** — status (20), phase (15), prior treatment (15), age
    (10), approach (10) — leaving only 30% always evaluated
    (`condition_is_subject`, `sites_active`, `enrollment_feasibility`).
    Reaching 0.80 needs the researcher to state 50 of those 70 points. The
    best any test interest manages is **65%**; the rest are 30-55%.
  - **The score ranges are unreachable too.** A trial matching everything the
    researcher asked about scores **exactly 1.00**, because unknowns are
    excluded and nothing remains to lose points on. The fixtures designed
    their top-1 trial to match everything. Four of five return 1.00 against
    an expected ceiling of 0.95; case 5 returns 0.94 against a ceiling of
    0.75.
  - The ranges were calibrated to the old buggy denominator — the old
    arithmetic reproduces each boundary exactly.
  - **The harness never asserts confidence at all**
    (`passed = order_correct and in_range`). So
    `TEST_CASE_3_CONFIDENCE_CALIBRATION`, whose stated purpose is confidence
    calibration, does not check confidence — and its target would be
    unreachable if it did.

  Recalibrating the numbers is the shallow fix. The deeper one: top-1 score
  is now a weak assertion, because "matched everything asked" always equals
  1.00 regardless of how little was asked. Assert on the **score gap between
  #1 and #2** (does the system discriminate?) and on **coverage** instead.
- The **15/15 is partly an artifact.** Five scenarios had the top two trials
  tied on score *and* coverage; Python's stable sort resolved them by
  fixture order, which happened to match the expected answer. Proven by
  reversing the fixture list — those five flipped to FAIL with identical
  scores. **Honest count: 10 genuinely correct, 5 undetermined.**
- Published trial-matching systems report precision/recall ~0.32-0.45
  (recorded in `step7_implementation_guide.md`). Scoring 1.00 means the eval
  is far easier than reality, not that this system beats the field: 2-3
  trials per scenario, caricature fixtures with no near-misses, fully
  populated where real data is 64% missing phase, and zero human relevance
  judgments.

**No researcher has judged a single real output.** That is the missing
baseline, and the user (MBBS) is the domain expert for it. The agreed shape:
rank ~20 real trials (~$0.13), user reads top 10 and bottom 10, answers two
questions — is anything at the top obviously wrong, is anything at the
bottom obviously good.

---

## Next: Unit 4 — the frontend

Nothing renders any of this. Scores, coverage, evidence and the elicitation
questions exist only as JSON.

Two design decisions already made with the user — build to these:

**1. Score never appears without its coverage.** A `1.00` assessed on 30% of
criteria reads as "perfect fit" and isn't. Adjacent, not a footnote:
`0.95 · assessed on 55% of your criteria`.

**2. Elicit, don't penalise.** When signals go unscored because the
researcher didn't specify something, show the questions — never an error,
never a silent deduction. `find_unspecified()` already returns them ordered
by how much coverage each answer recovers. For "I track breast cancer
trials": 70% unscored, 5 questions. For a fully-specified interest: zero.

Sketch agreed with the user:
```
  Ranked 20 breast cancer trials · scored on 30% of fit criteria

  ⓘ  Five things you didn't specify are unscored:
     [+ recruiting only?]      would score 20% more
     [+ which phases?]         would score 15% more
     [+ prior treatment?]      would score 15% more
     [+ age range?]            would score 10% more
     [+ mechanism/modality?]   would score 10% more
```

Notes for building it:
- `frontend/api_client.py` now has `post()`; use it, never `requests`
  directly (CLAUDE.md §5 — FastAPI is the only door).
- There is no ranking page. An earlier `frontend/pages/4_Ranking.py` was
  written against the old API shape (expected a `studies` key from
  `/studies`, which returns `results`; posted the old
  `{researcher_interest, trials}` body) and was **deleted** rather than
  committed broken. Build it fresh against the shape documented above.
- `Home.py` lists Ranking with `status: "planned"`. Flip it to `"live"` and
  set `page` only once a working page exists — Home's own docstring forbids
  implying a capability is live when it isn't, and `POST /rank` working is
  not the same as the capability being usable.
- Elicitation is per-search. A per-trial version ("this trial's phase is
  unrecorded") is a different thing, probably belonging in the detail view.

---

## Open questions the user has NOT decided

1. **The ranking tie.** When a researcher doesn't state a preference, a
   recruiting and a completed trial can score identically. Options
   discussed: (a) leave tied — purist §2 reading; (b) weak defaults —
   infers intent; (c) score stays conditional, rank applies a *disclosed*
   tiebreak. The user leaned toward elicitation dissolving the problem
   instead — all five observed ties were on vague interests. Don't pick
   unilaterally.
2. **Recalibrating the expected ranges — and what the suite should assert
   instead.** Explicitly deferred; free to iterate on thanks to the cache.
   Note the suite currently *cannot* pass (see above), so don't read its
   pass rate as a quality signal or a regression baseline until this is
   settled. Two things to decide together:
   - Top-1 score is a weak assertion now, since "matched everything asked"
     is always 1.00. Prefer asserting the **#1-to-#2 score gap** and
     **coverage**.
   - **Is the `>= 0.80` coverage threshold for `confidence: "high"` right?**
     Realistic queries reach 30-65%, so `high` is currently unreachable in
     production, not just in tests — the three-level scale is effectively
     two-level. That may be correct (high confidence *should* be rare) or
     miscalibrated. It was inherited, never decided.
3. **The paid prior-treatment eval case.** Designed, not built. Would use
   real criteria text from the 3,407 trials that have it. ~$0.05, best
   folded into a run that's happening anyway.
4. **`sites_active` calibration.** Returns `partial` for 64% of all trials —
   a signal that says the same thing about two-thirds of everything isn't
   discriminating. The `>1 site` threshold is probably too blunt. Noted, not
   tuned, because tuning it blind produces a number that looks better
   without meaning more.

---

## Housekeeping

- `api/ranking_mock.py` was **deleted** (user-approved). It silently
  returned fabricated fit scores when no API key was set — dangerous under
  §2, since a researcher could see invented scores without knowing. The
  endpoint now raises 503 explaining why it can't score.
- The API key lives in `.env.local` (gitignored; verified never committed
  via `git log -S`). An earlier key was briefly present in the previous
  version of *this file*, which was untracked but **not** gitignored — one
  `git add .` from being public. That key was **rotated by the user on
  2026-08-31** and the old value no longer appears anywhere in the tree.
  Keep keys out of `docs/`: this file is not gitignored.
- Nothing committed this session. `git status` shows the full change set.
