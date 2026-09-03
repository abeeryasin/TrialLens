# Which nodes should Explore actually lead with?

**Decided 2026-09-03.** Written after the step 8 unit 2 extraction, in
response to one question: *do researchers care about collaborations?*

The honest starting position: **nobody had asked.** The graph got sponsors,
sites, investigators and interventions because those are the entities
CT.gov reports, not because any researcher said they were useful. That is
the same failure mode as step 7 — a ranking layer built, measured and
removed once someone asked what it was for, after scoring 15/15 against
fixtures no clinician ever read. This document is the check that was skipped
then.

---

## 1. Collaborator is a weak node, and the reason is definitional

ClinicalTrials.gov's own data-element definition settles it:

> "A collaborator is any other organizations (as applicable) that are
> providing support. Support may include **funding**, design,
> implementation, data analysis or reporting."

Registration guidance is blunter — the field is "where you should list any
external **funders, granting institutions (such as NIH institutions)**, and
other universities or organizations working on the project with you."

So the field *deliberately merges funding with scientific work*, and offers
no sub-field to separate them. This is not a data-quality problem that
cleaning fixes. It is the schema.

The stored data behaves exactly as the definition predicts:

| Top collaborator | Trials |
|---|---|
| National Cancer Institute (NCI) | 480 |
| National Institute of Diabetes and Digestive and Kidney Diseases | 264 |
| National Institutes of Health (NIH) | 91 |
| National Heart, Lung, and Blood Institute (NHLBI) | 86 |

An oncology researcher's reaction to "Mayo Clinic collaborates with NCI, 14
trials" is *yes, obviously*. It is a **funding label wearing a
relationship's costume** — structurally the same error as step 7's "four of
five scored signals were filters wearing a score's costume."

Coverage is weak too, and degree is weaker:

- **37.4%** of trials (4,314 of 11,528) have any collaborator at all.
- Of those, **63%** (2,740) have exactly one. A network whose modal node has
  degree 1 is not much of a network.

And one line of the registration guidance removes the main use case
outright: **"Collaborators should not include individuals; this field is for
institutions or organizations only, not PIs."** So "who else works in this
space?" — where *who* means a person — is a question this field is
definitionally incapable of answering.

## 2. What the field research says researchers actually do

An interview study covering 34 real trials in the Nordic countries gives the
most direct evidence, including one finding that is uncomfortable here:

- **ClinicalTrials.gov was used for site identification in only 3 of 34
  trials.** Commercial products (Citeline, DrugDev, GlobalData) dominate.
  Worth sitting with rather than explaining away — though those same
  products are described elsewhere as "secondary datasets that build off the
  clinicaltrials.gov database," which is precisely what TrialLens is.
- What actually drove site selection was **"previous collaboration between
  the trial sponsor and the trial sites" — 23 of 34 trials.** Note the
  shape: sponsor↔**site** history. `trial_sites` joined to
  `trial_organizations` computes that. The collaborator field cannot.

For finding *people*, CT.gov is a named primary source, but via
investigators: "KOLs often serve as principal investigators," and Tier 1
KOLs include "major clinical trial investigators." That is
`overallOfficials` — the investigators table.

The sharpest pain point comes from the oncology literature. A community
oncologist searches, finds candidate trials, and then must **"call the site
to ask whether the trial is still open."** Separately, a study of 8,893
cancer patients found **55.6% had no available trial at their treating
facility**. Both are location questions.

## 3. The ranking

| # | Node | Coverage | Why |
|---|---|---|---|
| 1 | **Sites** (+ per-site status, geo) | 93.8% | Highest reach; answers the phone-call question from stored data; combines with `delisted_at` so a dropped or suspended site becomes a monitoring signal |
| 2 | **Investigators** | 66.4% | The only way to answer the people-shaped reading of "who else works here," since the collaborator field bans individuals |
| 3 | **Interventions + phase + status** | — | Where landscape and pipeline questions actually live |
| 4 | **Collaborator** | 37.4% | **Keep, do not traverse.** Demote to an attribute — "NIH-funded", "industry-partnered" — a filter, not a network |

Organizations keep their table regardless: `lead_sponsor` has 100% coverage
and answers "who runs trials in this space." The one-table decision (lead
sponsors and collaborators together, 887 names being both) still holds. What
is demoted is *traversing collaborator edges as if they were a research
network*.

## 4. What this changed, and what it did not

**Built 2026-09-03** (see `docs/decisions.md` same date): site enrichment.
`geoPoint`, `zip`, `state` and per-location `status` had been dropped by the
parser and were sitting unread in `raw_json` — the third recurrence of the
`has_results` pattern. Backfilled with no network call. 49,606 of 51,272
sites now carry coordinates; 40,011 live edges carry a recruitment status,
31,442 of them RECRUITING.

**Not built:** nothing was removed. The collaborator edges stay extracted and
correct; they simply should not be what Explore leads with.

## 4b. What unit 3 and the Explore page must handle

Consequences of the decisions above, written down now so they are
requirements rather than bugs discovered later.

**1,666 sites have no coordinates** (51,272 total, 49,606 mapped). 109 of
those are NULL because the registry contradicts itself; the rest never
reported a geoPoint. A distance filter or map silently drops all of them.
The page must say how many sites it could not place, the same way the watch
states a quiet week rather than showing an empty list. "3 sites near you"
computed from a set that excluded 1,666 unplaceable ones is the step-4
under-reporting bug in a new costume.

**Never filter on `recruitment_status = 'RECRUITING'` alone.** That buckets
the 71.4% of live edges with no stated status in with the closed ones.
`frontend/labels.site_status_is_stated()` exists to make the three-way
distinction — stated-and-open, stated-and-closed, not stated — the easy
thing to write. Filters should offer "recruiting", "not recruiting" and
"not reported" as separate options, not a checkbox.

**Do not colour-code site status.** A green/grey dot is a conclusion with
its evidence deleted, and grey would be doing double duty for "closed" and
"unknown". `SITE_STATUS_LABELS` renders sentences for the same reason the
tracking drop reasons do (§3).

**Delisted edges are a feature of the page, not noise.** `delisted_at`
exists so "this trial dropped three sites since June" is answerable. Default
to live edges, but do not make the withdrawn ones unreachable.

## 5. What would overturn this

Stated so the decision can be reopened honestly, per the standing rule:

- A researcher saying they use collaborator lists to spot an industry
  partner before writing a grant, or to see whether a competitor is
  co-running a trial. Both are plausible; neither can be invented on their
  behalf.
- The per-site `status` proving too sparse in practice. It covers only
  **28.6%** of live edges, because CT.gov mostly supplies it for actively
  recruiting studies. It is a strong signal *where present*, not a universal
  one — and NULL means "not stated", never "not recruiting". Any UI that
  blurs those two repeats the step-4 under-reporting bug, where a handful of
  incidental local rows were presented as the complete picture.
- Any evidence about *this* researcher. Everything above is about clinical
  researchers in general. No clinician has looked at TrialLens. That gap is
  still open, and `docs/verify_ranking_results.md` is still unanswered.

## Sources

- [The Sponsors and Collaborators Module — CU Anschutz](https://research.cuanschutz.edu/crs/clinical-research-support/clinical-research-administration/clinicaltrials.gov-support/tips-of-the-week-archive/tip-of-the-week-april-2-2020/the-sponsors-and-collaborators-module)
- [Clinical trial site identification practices and the use of EHRs in feasibility evaluations: an interview study in the Nordic countries](https://pmc.ncbi.nlm.nih.gov/articles/PMC8592101/)
- [How to avoid common problems when using ClinicalTrials.gov in research: 10 issues to consider](https://pmc.ncbi.nlm.nih.gov/articles/PMC5968400/)
- [Decentralized Clinical Trials in Oncology (JCO)](https://ascopubs.org/doi/full/10.1200/JCO.22.00358)
- [Oncologist-Reported Barriers and Facilitators to Offering Cancer Clinical Trials](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11202609/)
- [KOL Research & Mapping Guide — IntuitionLabs](https://intuitionlabs.ai/articles/kol-research-mapping-guide)

Not relied on: *An Analysis of Sponsors/Collaborators of 69,160 Drug Trials
Registered with ClinicalTrials.gov* — the full text was CAPTCHA-blocked and
only the title was reachable, so nothing here rests on it.
