# What replaces the ranking layer — step 7b

**Written 2026-09-01, split the same day.** Supersedes the ranking layer
built in step 7, which was measured, disproved, and deleted on 2026-09-01.
This is roadmap **step 7b**, not step 8 — step 8 is the knowledge graph.

The removal itself is done and does not need re-planning: what was deleted,
what survived, and the three things the removal plan got wrong are recorded
in `docs/decisions.md` (2026-09-01). `f9ccb45` stays in history as the
documented dead end.

The paid relevance classifier that used to occupy 83% of this file now
lives in `docs/plan_relevance_column.md`, deferred — it needs credits the
account does not have, and a real complaint about mis-tagging that no user
has made.

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

**Why amendment history is first, and stayed first when the order was
questioned (2026-09-01):** it is a build problem, not a design problem.
`study_changes` already holds every row it needs, so it requires no new
judgment call about what a screen should say — and after a dead end, the
right next thing is one with a known shape. The watch is genuinely a design
problem (what *should* a quiet week look like?) and deserves to be second
rather than to block the first shippable thing. The watch record needs a
new table and its value accrues with wall-clock time, which argues for
building it early; that argument lost to "ship something visible first,"
deliberately, and it should be built directly after the watch rather than
drifting.
