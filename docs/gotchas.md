# Standing gotchas

Rules that exist because breaking one produced a real bug, real data loss,
or a real bill. Each carries the date of its postmortem in
[`decisions.md`](decisions.md) — read the entry if you need the whole story,
but the rule alone is enough to avoid repeating it.

Ordered by what you are most likely to be doing.

## SQL and the database

- **A `JOIN` against `study_conditions` needs `DISTINCT` before feeding a
  write.** That table is wiped and re-inserted wholesale every batch upsert.
  One trial with 19 "breast cancer" AJCC stage tags logged 19 copies of the
  same change. → 2026-08-30
- **Never `SELECT *` against `studies`.** `raw_json` is 52% of the table.
  Use `STUDY_DETAIL_COLUMNS`. → 2026-08-31
- **Delete test rows by explicit list, never by pattern.** `_` is a wildcard
  in SQL `LIKE`, so `LIKE '__%'` means "2+ characters", not "starts with two
  underscores" — that wiped the whole `tracked_conditions` registry while
  cleaning up one probe row. Use `WHERE x IN (...)`. → 2026-09-05, and the
  same class as 2026-08-27
- **Stored values rarely match the API docs.** Phase is `PHASE2`, not
  "Phase 2"; 64% of trials have no usable phase; `hasResults` sits above
  `protocolSection`. Query the real distribution before writing a query
  **or a prompt**. → 2026-08-31
- **A substring link between two vocabularies is not attribution.**
  `study_conditions.condition ILIKE '%breast cancer%'` missed **2,173 of
  11,453 in-scope trials (19%)**, because CT.gov expands synonyms when it
  searches (`Breast Neoplasms`, `Breast Carcinoma`, `Obese`, `Overweight`).
  `study_tracked_conditions` records the real pair at ingest instead. The
  same blind spot still means a synonym-tagged trial can never age out of
  scope — measured, recorded, not yet changed. → 2026-09-08

## Testing

- **Iterate on `pytest -k "not real_data"`; run the full suite once, before
  committing.** Measured: the free tests cost **0.5 MB and 38s**, the
  real-data tests **56 MB and 161s** — 86% of the coverage for 0.8% of the
  bytes. The real-data half is not optional before a commit (it is the only
  thing that tests the SQL), it is just not the thing to run forty times
  while editing a docstring. → 2026-09-07
- **Check what runs the suite unattended, too.** `monitor.yml` was running
  the full suite on all four daily ticks — 29 runs, ~1.6 GB — missed by a
  postmortem that only considered things a human types. → 2026-09-08
- **A test that calls an endpoint function directly is not testing the
  endpoint.** Request binding and response validation are FastAPI's job;
  only an HTTP-level call exercises them. → 2026-09-03
- **When mutation-testing, diff the restored file against the backup before
  believing the result.** Mutating and restoring inside one shell command
  produced a run where correct, restored code appeared to fail — long enough
  to nearly "fix" working code. → 2026-09-06
- **`pkill -f <pattern>` matches your own command line too.**
  `pkill -f "port 8011"` killed the backgrounded shell running the test
  suite, because that shell's command string also contained the pattern; the
  run died at exit 144 with no output and read as a test failure. Match on
  something only the target has, or kill by PID. → 2026-09-06

## Correctness traps

- **A comment describing an invariant is not the invariant.** An accurate
  comment — "whatever was spent before the failure must still reach the run
  record" — sat above code that could not do it: `proposals, spend = f()`
  never binds when `f` raises, so a run that made five paid calls recorded
  `$0.0000`. **The tell was the number, not the exception.** Where a value
  must survive an exception, return it. → 2026-09-07
- **A cap in one place can silently undo a fix in another.** The
  reformatting bucket was made listable so a human could check the filter;
  hours later the page listed 8 changes of which **zero** were reformatting,
  because one `NAMED_CAP` over a substantive-first sort pushed the whole
  bucket off the end. Every test passed — both suites asserted on the
  *classification*, never on what survived the cap. Cap per bucket, assert on
  what the reader actually receives, and print "showing the first N of M".
  → 2026-09-07
- **A number that can never bind is a lie in the code.** `SUMMARY_ID_CAP =
  20` sat over lists already capped at 8 upstream — unreachable, and harmless
  only by luck. If a limit cannot fire, delete it and document the one that
  does. → 2026-09-07
- **A stateful cadence needs a simulation, not a table of cases.** Every
  digest window assertion passed, each written against one call with a
  hand-picked previous value. Feeding each run's output into the next showed
  every Tuesday pulling the weekend back in. Compare against what a *healthy
  predecessor* would have left, and walk a whole week in a test.
  → 2026-09-07
- **A rolling window cannot exclude a weekend.** "Everything since the last
  run" necessarily spans Saturday and Sunday on a Monday, and clipping its
  start to Monday 00:00 silently drops everything filed after Friday
  breakfast. If a cadence skips days, the window must be whole days, not
  elapsed time. → 2026-09-07

## Operations and cost

- **Neon's free tier suspends the compute when transfer runs out** — the
  deployed site goes dark until the period resets (the 26th here). 5 GB/month
  of public network transfer; storage is the quieter meter at 0.5 GB allowed,
  249 MB used. Drift checks are weekly until 2026-09-26 and twice daily
  after, decided by a date in the workflow rather than a comment promising to
  restore it. `tests.yml` deliberately holds no database credentials, so
  pushing costs nothing on that meter. → 2026-09-07, 2026-09-08
- **A cache on a monitoring tool has to be classified per endpoint.** One
  Investigate interaction re-issued 43,842 measured bytes on every rerun. The
  fix is an allowlist (`CACHEABLE_PATHS` in `frontend/api_client.py`), not
  `@st.cache_data` on `get`: `/ops/status` exists to say what is true *now*,
  and `/discover`'s live CT.gov fallback could hide a trial registered
  minutes ago. **Any write clears every cached read.** Unclassified paths are
  never cached, and a canary fails if a page reads a path in neither list.
  → 2026-09-07
- **An alarm nobody can act on trains people to ignore the ones they can.**
  The synthesis history-skip fired CRITICAL and would have failed
  `monitor.yml` every six hours for a fortnight over a condition that
  resolves itself with calendar time. `SELF_RESOLVING_SKIPS` are WARNING,
  `budget` stays CRITICAL, and an unclassified prefix stays CRITICAL — an
  allowlist, so an unconsidered skip is never quieter than a considered one.
  → 2026-09-07
- **This project's real text runs ~2.61 chars/token, not ~4.0.** Re-measure
  any cost estimate rather than trusting an old one. → 2026-09-04
- **`requirements.txt` is pinned, and must stay pinned** (with
  `.python-version`, 3.9.6). Bare names let Render's first deploy resolve
  Python 3.14 + streamlit 1.63 + pandas 3.0 while the suite passed on
  3.9 + 1.50 + 2.3 — a green suite certifying software nobody was running.
  Pin the whole closure, not the direct deps: pandas/numpy arrive through
  streamlit. Classify by resolver (`pip install --dry-run`), never by eye —
  streamlit requires GitPython, which "obviously dev tooling" got wrong.
  → 2026-09-05

## Git

- **`git add -A` is not safe here.** It has committed an installed skill and
  a 2.4 MB design canvas in one session. Stage deliberately. → 2026-09-02

## What doesn't travel with a clone

All gitignored, all rebuildable or personal: `.env.local` (database URLs —
real-data tests skip cleanly without it), `.ranking_cache/` (orphaned since
step 7's removal), `.claude/skills/` and `.claude/hooks/`, and
`design/triallens-the-watch.html` (rebuild from `design/*.dc.html`).
