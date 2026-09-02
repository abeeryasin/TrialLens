# Design sources — "The Watch"

Three artboards for step 7b direction 2, drawn 2026-09-02 before any of it
was built. They are the argument for what the watch screen should say, not
a preview of what exists.

**Built the same day.** `frontend/Home.py` is now the watch, and
`GET /watch` feeds it. These files are kept as the record of the argument,
not as a spec to keep in sync — see "What the build changed" below.

| file | what it is |
|---|---|
| `Main.dc.html` | **The quiet week** — the primary screen, and the whole point |
| `NewsWeek.dc.html` | A week with real news, led by a trial publishing its results |
| `Alarm.dc.html` | The scheduled check has died |
| `canvas.json` | Layout, annotations, and which view opens first |

## Why these three

Most weeks nothing happens. 29 and 30 August 2026 had **zero** amendments
across all 11,427 watched trials — that is real recorded data, not a
hypothetical — and today that renders as an empty table, which reads as a
broken app rather than a working watch. The quiet week is therefore the
screen a researcher sees most often and the one worth designing first.

These originally claimed "every number is real, including the zeros".
**Building the screen proved four of them were not**, and they have been
corrected here (2026-09-02):

| was | is | why it was wrong |
|---|---|---|
| 751 completed w/ results | **747** | drifted overnight |
| 1,056 with results | **1,050** | drifted overnight |
| Alarm: 13 checks missed | **12** | 76 elapsed hours ÷ 6-hour slots is 12; the figure was written by hand |
| NewsWeek: 3 scientific / 59 other | **14 / 49** | estimated before anyone queried it |

And one element is not a number at all but an unobserved state, now
labelled on the artboard: **the "results posted" card depicts an amendment
that has never happened.** `has_results` was added and backfilled on
2026-09-02, and backfilled values are deliberately not written to
`study_changes`, so no false → true transition has ever been recorded.
NCT05599334 is a real watched trial that really does have results; what has
not occurred is TrialLens watching them appear. The treatment is designed
for the first real one.

That is the same failure `docs/decisions.md` names twice in two days —
**when a true statement feels unsatisfying, the fix is a better true
statement or silence, never a plausible one** — committed here in a design
file instead of in copy. A drawn number has no test.

No number on the built page is hardcoded, which is the durable version of
"every number is real", and the reason a designed screen gets built rather
than maintained as a drawing.

Two decisions worth keeping:

- **The alarm replaces the page** rather than sitting above it. A stale
  feed under a small warning still reads as current, and that is the
  failure being designed out.
- **The quiet screen offers something to do.** An absence stated and then
  left there is still a dead end; it points at the 751 completed trials
  with posted results, because a quiet week is when there is time to read
  them.

## Deliberately Streamlit

These match the app's real vocabulary — Source Sans, `#31333F` text,
`#F0F2F6` surfaces, `#E6EAF1` rules — rather than proposing an identity
Streamlit cannot render. Decided 2026-09-02: the watch ships as a Streamlit
page, so a design it cannot build is a design that does not ship.

**Resolved 2026-09-02:** the dots won. `frontend/labels.py` now owns them
(`ASPECT_DOTS`, `render_aspect_caption`) and both Home and Understand read
from there, so the two screens cannot disagree about what "Scientific"
looks like. The emoji carried meanings that fought the label — a microscope
is not what "Scientific" means here; the whole trial is science.

## What the build changed

The artboards were followed closely. Three deliberate departures:

- **"Checks run: 21" is not on the page.** Nothing records that a scheduled
  run happened — that is direction 3 — so the footer shows "Last check",
  inferred from `max(studies.last_matched_at)`, and says out loud that it
  is inferred. A drawn number is allowed to assume a table that does not
  exist; a shipped one is not. This is the one figure above left uncorrected,
  because it is the design target for direction 3 rather than a claim about
  now.
- **The news headline counts trials, not amendments touching results.**
  `results_posted` is a subset of `scientific`, so the page subtracts —
  "one published its results, thirteen others changed something scientific"
  — rather than reporting one amendment in two places.
- **The quiet-day invitation only appears on a quiet day.** "A quiet week is
  when there is time to read them" is a non-sequitur beside real news; the
  results count itself stays, because it is a standing fact.

## Rebuilding the canvas

The published page (`triallens-the-watch.html`, ~2.5 MB) is a build
artifact and is gitignored — it embeds a whole editor. Re-seed it from
these sources with the `design` skill's helper, then publish that file to
the same artifact URL to keep the link stable.
