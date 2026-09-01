# Verifying a ranking run — the researcher-judgment protocol

**Status: NOT YET DONE. This is the missing baseline.**

No clinical researcher has judged a single real TrialLens ranking output.
Every quality number the project has so far comes from synthetic fixtures
that score 1.00 because they were built to. Until this protocol has been
run once, "the ranking works" is an assumption.

You (MBBS) are the domain expert this is waiting on. It takes about
fifteen minutes and costs nothing beyond a ranking run you've already paid
for.

---

## Why judge criteria, not trials

"Is this a good trial?" is vague, slow, and impossible to be consistent
about across ten trials. "Is this sentence true of this trial?" is fast
and factual.

This is how TrialGPT (NIH/NLM, *Nature Communications* 2024) was
validated: hand-judging **1,015 patient-criterion pairs**, not whole
trials. They report 87.8% of explanations correct and criterion-level
accuracy of 0.873 against human experts at 0.887-0.900. Those are the
numbers this protocol reproduces on your own data.

---

## Before you start — two rules that decide whether this is worth anything

1. **Blind yourself to the scores.** If you see `0.92` first you will
   rationalise it, and your judgement stops being independent evidence.
   Judge the trial, write your mark, *then* reveal the score.
2. **Write the marks down**, in the table at the bottom of this file. A
   baseline you cannot re-run after a prompt change is not a baseline.

---

## The run

```bash
# 1. The gate: refuses if the free suite is red, and lists what else is
#    waiting on a paid answer so you ask everything in one run.
PYTHONPATH=. .venv/bin/python scripts/paid_preflight.py

# 2. Start the API, then rank. ~$0.13 for 20 trials.
.venv/bin/uvicorn api.main:app --port 8000
```

Then in the Ranking page, or via `POST /rank` directly. Save the JSON —
you will want to diff against it after the next prompt change.

---

## Part A — the top 10 (precision)

For each of the ten, **three marks**. Look at the trial on
ClinicalTrials.gov if the record in front of you isn't enough.

| # | question | scale |
|---|---|---|
| 1 | **Is `condition_is_subject` right?** Is breast cancer what this trial is actually *about*, or is it incidental — a comorbidity, an exclusion, a sub-population? | correct / partly / wrong |
| 2 | **Is the evidence sentence factually true** of the trial record? Not "is it a good reason" — is the *statement itself* accurate? | correct / partly / wrong |
| 3 | **Would you put this in your top 10** for the interest as stated? | yes / no / borderline |

Question 2 is the one that reproduces TrialGPT's 87.8%. It is also the one
that catches an LLM stating a study fact that isn't in the record —
the thing CLAUDE.md §2 forbids outright.

**precision@10** = (count of "yes" in Q3) / 10.

## Part B — the bottom 10 (recall)

One question, scanning the ten lowest-ranked:

> **Is anything here obviously good?**

Missed positives are invisible in the top 10 by construction — if the
system buried a trial you'd have wanted, only this half finds it. Note the
NCT ID of anything that should have ranked higher.

## Part C — the two structural checks

- **Does any `unknown` look like it should have been answerable?** That is
  usually a plumbing bug, not a model failure — bug #7 and bug #10 were
  both exactly this, a weighted signal whose input never reached the model.
- **Does any `not_applicable` look like a real data gap?** Those two labels
  are deliberately separate; confusing them was TrialGPT's second-largest
  error class (26.9%).

---

## Record it here

Run date: ____________  ·  interest used: ______________________________
Condition: ____________  ·  pool size: ______  ·  cost: $______

### Top 10

| # | NCT ID | Q1 subject | Q2 evidence true | Q3 belongs in top 10 | note |
|---|--------|-----------|------------------|----------------------|------|
| 1 |        |           |                  |                      |      |
| 2 |        |           |                  |                      |      |
| 3 |        |           |                  |                      |      |
| 4 |        |           |                  |                      |      |
| 5 |        |           |                  |                      |      |
| 6 |        |           |                  |                      |      |
| 7 |        |           |                  |                      |      |
| 8 |        |           |                  |                      |      |
| 9 |        |           |                  |                      |      |
| 10|        |           |                  |                      |      |

**precision@10 = ____ / 10**
**explanation accuracy = ____ / 10 correct, ____ partly, ____ wrong**

### Bottom 10

Anything that should have ranked higher? ________________________________

### Structural

Suspicious `unknown`s: ___________________________________________________
Suspicious `not_applicable`s: ____________________________________________

---

## What the result means

- **precision@10 around 0.67** would put this level with TrialGPT's
  reported P@10 of 0.6724 — on an easier task (surveillance, not
  patient-level eligibility), so treat parity as the floor, not a win.
- **Explanation accuracy is the more honest number.** It measures whether
  the system is telling the truth about the record, which is what §3 is
  for. A high precision with wrong explanations is worse than the reverse.
- **A precision far above 0.9 means the test was too easy**, not that the
  system is excellent — the same lesson the synthetic harness taught when
  it returned 1.00.
