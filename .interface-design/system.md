# TrialLens — interface system

Decisions, not preferences. Each one has a reason and most have a bug
behind them. Values live in `frontend/charts.py`; this file says why.

## Direction

**Who** — a clinical researcher tracking a therapeutic area over months.
They open this between other work, scanning for what moved, and they are
accountable for what they repeat. **Feel** — a clinical record, not a
dashboard: quiet, dense with fact, nothing decorative competing with a
number. Closer to a lab report than a BI tool.

**Signature** — the arrow (`Recruiting → Completed`) and the visible
denominator. Every figure on the page states what it is measured against;
no count appears without its total. That is the product's whole argument,
so it is also its visual identity.

## Depth strategy: none

Flat surfaces, no shadows, no card elevation. Chosen because the page is a
long single-column read of findings, not a set of manipulable objects —
lifting a finding off the page implies interactivity it does not have.
Structure comes from whitespace and `st.divider()` only.

## Charts

The palette is **validated, never chosen by eye** — run
`scripts/validate_palette.js` from the dataviz skill before changing a
hue. Current categorical set clears CVD ΔE 9.1 (protan) and normal-vision
ΔE 19.6. Three slots fall below 3:1 contrast, which obliges relief: every
bar is directly labelled and every chart has a table or drill-down.

| Token | Value | Why |
|---|---|---|
| `ROW_HEIGHT` | 40px | 34 read as a wall; the row needs more air than mark |
| `BAR_SIZE` | 13px | thin. A bar's job is comparison, not presence |
| `CORNER` | 4px | data-end only, anchored to the baseline |
| category label | 11px / `INK_MUTED` / 12px pad | secondary — the number leads |
| value label | 12px / 600 / `INK` | the focal element on every bar |
| `LATER` / `EARLIER` | red / blue, gray midpoint | later = the direction that costs a researcher time |

**Horizontal bars carry no axis.** Every bar prints its own value, so the
x scale, ticks and gridlines restate the same fact — and at counts of
0–13 that is fourteen vertical rules behind eight bars. That was most of
what "crowded" meant. Vertical charts (`ordered_columns`, `year_bars`)
keep a y grid, because height cannot be read without one.

**`labelOverlap=False` on every categorical axis, always.** Vega-Lite
thins labels it thinks will not fit, and on a categorical axis a thinned
label does not degrade — it lies. The status chart reported 78 terminated
trials when the real figure was 237. Guarded by `tests/test_charts.py`;
3/3 planted mutations caught.

**Never `axis=None` on a value-label layer** to stop it competing — that
removes the shared axis outright and leaves a chart with no labels. The
label layer stays silent and the bar layer's config governs.

**A legend only when it earns the row.** Two categories, one of size 1,
cost a whole row of chrome above an eight-row chart. The anomaly carries
`(unusual)` in its own label instead — identity is never colour alone.
Use a word, not a glyph: `⚠` falls back to an emoji font and that row
renders in a different typeface from its neighbours.

**Selectable charts must be single-view.** Streamlit refuses selections on
layered charts. Rather than drop value labels to gain the click, the value
moves into the category label (`Paclitaxel (Drug) · 163`).

## Honesty rules that are visual, not editorial

- A capped list states what it was capped from.
- An incomplete period is muted and labelled, never drawn at full weight
  beside complete ones — the current year at 756 next to last year's 899
  reads as a decline that is only the calendar.
- A rolled-up bucket names its real range (`Before 2010`, earliest 1989),
  so an axis cut never implies the field began there.
- The unstated share stays in the picture. 52% of breast-cancer trials
  report no usable phase; a phase chart without them describes a tidier
  field than the one that exists.
- Zero is a finding, stated in words. An empty chart area reads as a bug,
  so a builder returns `None` and the page says the sentence instead.

## Before changing a chart

Render it to PNG and look at it — `vl-convert-python` is in
`requirements-dev.txt` for exactly this. Two real bugs on 2026-09-04
(colliding year labels, a distribution drawn as a ranking) were only
visible in the image. But note the export renders every label even when
Streamlit's theme would thin them, so **looking is necessary and not
sufficient**: the spec-level guarantees live in `tests/test_charts.py`.
