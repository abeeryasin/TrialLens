# Design sources — "The Watch"

Three artboards for step 7b direction 2, drawn 2026-09-02 before any of it
was built. They are the argument for what the watch screen should say, not
a preview of what exists — `frontend/Home.py` is still the old capability
grid at time of writing.

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

Every number on these artboards is real, including the zeros.

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

One known inconsistency: these use small colored dots for the aspect
markers, while `frontend/pages/2_Understand.py` currently uses 🔬 ⚙️ 📝.
If these are adopted, that page should change to match — the two screens
should not disagree about what "Scientific" looks like.

## Rebuilding the canvas

The published page (`triallens-the-watch.html`, ~2.5 MB) is a build
artifact and is gitignored — it embeds a whole editor. Re-seed it from
these sources with the `design` skill's helper, then publish that file to
the same artifact URL to keep the link stable.
