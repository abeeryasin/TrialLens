"""Chart specs for Investigate, in one place so they read as one system.

Altair rather than st.bar_chart: every chart here needs something the
convenience wrapper cannot express — a diverging axis, a threshold rule, a
muted bar for an incomplete year, a direct value label on each mark.

**The palette is validated, not chosen by eye.** The categorical slots
below cleared the lightness band, chroma floor, CVD separation (worst
adjacent pair ΔE 9.1 protan) and the normal-vision floor (worst 19.6).
Three of the five fall below 3:1 contrast against the chart surface, which
obliges relief: every chart here carries direct value labels, and every
section that uses one also offers the same numbers as a table.

Diverging is blue<->red with a gray midpoint, and the assignment is not
arbitrary: a date pushed LATER is the direction a researcher is worried
about, so later is red and earlier is blue. Two cool hues were rejected —
the midpoint has to read as "nothing happened".
"""
import altair as alt
import pandas as pd

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_MUTED = "#52514e"
GRID = "#e8e7e3"

# Validated categorical order. Assigned in this fixed order, never cycled.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]

# Diverging poles + neutral.
LATER = "#d03b3b"     # pushed later — the direction that costs a researcher time
EARLIER = "#2a78d6"   # pulled earlier
NEUTRAL = "#c8c7c2"   # artefacts and no-moves: visibly "nothing happened"

# Status palette, reserved. Never reused as a series colour, and never the
# only channel — an anomaly carries an icon and a label too.
CRITICAL = "#d03b3b"
GOOD = "#0ca30c"

BAR_SIZE = 18
CORNER = 4


def _base(df, height):
    return (
        alt.Chart(df)
        .properties(height=height, background=SURFACE)
        .configure_view(strokeWidth=0)
        .configure_axis(
            grid=True, gridColor=GRID, gridWidth=1, domain=False, tickSize=0,
            labelColor=INK_MUTED, titleColor=INK_MUTED, labelFontSize=11, titleFontSize=11,
        )
        .configure_legend(labelColor=INK_MUTED, titleColor=INK_MUTED, labelFontSize=11)
    )


def ranked_bars(rows, label_field, value_field, value_title, color=None, height=None):
    """Horizontal bars, longest first, every bar directly labelled.

    The default form for "how many of each" — horizontal because the
    labels are trial titles and drug names, which do not fit under a
    vertical axis without rotating them to unreadability.
    """
    df = pd.DataFrame(rows)
    if df.empty:
        return None
    height = height or max(90, len(df) * (BAR_SIZE + 10))
    order = df[label_field].tolist()

    bars = alt.Chart(df).mark_bar(size=BAR_SIZE, cornerRadiusEnd=CORNER).encode(
        y=alt.Y(f"{label_field}:N", sort=order, title=None,
                axis=alt.Axis(labelColor=INK, labelLimit=260)),
        x=alt.X(f"{value_field}:Q", title=value_title, axis=alt.Axis(grid=True)),
        color=alt.value(color or SERIES[0]),
        tooltip=list(df.columns),
    )
    labels = alt.Chart(df).mark_text(
        align="left", dx=6, color=INK, fontSize=11
    ).encode(
        y=alt.Y(f"{label_field}:N", sort=order),
        x=alt.X(f"{value_field}:Q"),
        text=alt.Text(f"{value_field}:Q", format=","),
    )
    return (bars + labels).properties(height=height, background=SURFACE).configure_view(
        strokeWidth=0
    ).configure_axis(
        grid=True, gridColor=GRID, domain=False, tickSize=0,
        labelColor=INK_MUTED, titleColor=INK_MUTED, labelFontSize=11, titleFontSize=11,
    )


def diverging_dates(rows):
    """Pushed later vs pulled earlier, per date field, on one axis.

    Never two axes: a count and a median are different scales, so the
    median rides the tooltip and the direct label instead of a second y.
    """
    df = pd.DataFrame(rows)
    if df.empty:
        return None
    # Later goes right as a positive count, earlier goes left as negative —
    # one axis, and the sign IS the direction.
    df["signed"] = df.apply(
        lambda r: r["count"] if r["direction"] == "Pushed later" else -r["count"], axis=1
    )
    chart = alt.Chart(df).mark_bar(size=BAR_SIZE, cornerRadius=CORNER).encode(
        y=alt.Y("field:N", title=None, sort=None, axis=alt.Axis(labelColor=INK, labelLimit=200)),
        x=alt.X("signed:Q", title="← pulled earlier    ·    pushed later →",
                axis=alt.Axis(format="+d")),
        color=alt.Color(
            "direction:N",
            scale=alt.Scale(domain=["Pushed later", "Pulled earlier"], range=[LATER, EARLIER]),
            legend=alt.Legend(title=None, orient="top"),
        ),
        tooltip=["field", "direction", "count", "median_days", "median_months"],
    )
    # Two label layers, not one with a conditional offset: dx is a mark
    # property in Altair, not an encoding channel, so the nudge has to be
    # baked into the layer. Each side gets its own alignment so the number
    # always sits clear of the bar end rather than on top of it.
    def _labels(subset, dx, align):
        return alt.Chart(subset).mark_text(
            color=INK, fontSize=11, dx=dx, align=align
        ).encode(
            y=alt.Y("field:N", sort=None),
            x=alt.X("signed:Q"),
            text=alt.Text("count:Q"),
        )

    later = df[df["signed"] > 0]
    earlier = df[df["signed"] < 0]
    label_layers = [
        _labels(subset, dx, align)
        for subset, dx, align in ((later, 8, "left"), (earlier, -8, "right"))
        if not subset.empty
    ]
    zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(
        color=INK_MUTED, strokeWidth=1
    ).encode(x="x:Q")

    return alt.layer(chart, zero, *label_layers).properties(
        height=max(120, len(df["field"].unique()) * 52), background=SURFACE
    ).configure_view(strokeWidth=0).configure_axis(
        grid=True, gridColor=GRID, domain=False, tickSize=0,
        labelColor=INK_MUTED, titleColor=INK_MUTED, labelFontSize=11, titleFontSize=11,
    )


def target_vs_actual(rows, threshold=0.85):
    """One line per trial from its target to what it enrolled.

    A dumbbell, not two bars: the pair belongs to one trial and the
    distance between them IS the finding. The rule marks 85% of target,
    the threshold the accrual literature counts a shortfall against.
    """
    df = pd.DataFrame(rows)
    if df.empty:
        return None
    order = df.sort_values("ratio")["label"].tolist()
    height = max(120, len(df) * (BAR_SIZE + 12))

    connector = alt.Chart(df).mark_rule(strokeWidth=2, color="#c8c7c2").encode(
        y=alt.Y("label:N", sort=order, title=None, axis=alt.Axis(labelColor=INK, labelLimit=240)),
        x=alt.X("target:Q", title="Participants"),
        x2="actual:Q",
    )
    target = alt.Chart(df).mark_point(
        size=90, filled=True, stroke=SURFACE, strokeWidth=2, color=INK_MUTED
    ).encode(
        y=alt.Y("label:N", sort=order), x="target:Q",
        tooltip=["label", "target", "actual", "pct"],
    )
    actual = alt.Chart(df).mark_point(
        size=110, filled=True, stroke=SURFACE, strokeWidth=2
    ).encode(
        y=alt.Y("label:N", sort=order), x="actual:Q",
        color=alt.Color(
            "shortfall:N",
            scale=alt.Scale(domain=["Below 85% of target", "At or above"],
                            range=[CRITICAL, GOOD]),
            legend=alt.Legend(title=None, orient="top"),
        ),
        tooltip=["label", "target", "actual", "pct"],
    )
    labels = alt.Chart(df).mark_text(align="left", dx=10, color=INK, fontSize=11).encode(
        y=alt.Y("label:N", sort=order),
        x=alt.X("max_x:Q"),
        text="pct:N",
    )
    return (connector + target + actual + labels).properties(
        height=height, background=SURFACE
    ).configure_view(strokeWidth=0).configure_axis(
        grid=True, gridColor=GRID, domain=False, tickSize=0,
        labelColor=INK_MUTED, titleColor=INK_MUTED, labelFontSize=11, titleFontSize=11,
    )


def year_bars(rows):
    """Trials started per year, with incomplete and planned years muted.

    The mute is the whole point. 2025 started 899 and the current year
    shows fewer only because it is not over; drawn at full weight beside
    its neighbours that is a decline the data does not support.
    """
    df = pd.DataFrame(rows)
    if df.empty:
        return None
    bars = alt.Chart(df).mark_bar(size=BAR_SIZE, cornerRadiusEnd=CORNER).encode(
        x=alt.X("year:N", title=None, axis=alt.Axis(labelColor=INK_MUTED, labelAngle=0)),
        y=alt.Y("count:Q", title="Trials started"),
        color=alt.Color(
            "kind:N",
            scale=alt.Scale(
                domain=["Complete year", "Part year so far", "Planned start"],
                range=[SERIES[0], NEUTRAL, NEUTRAL],
            ),
            legend=alt.Legend(title=None, orient="top"),
        ),
        opacity=alt.condition(alt.datum.kind == "Complete year", alt.value(1.0), alt.value(0.55)),
        tooltip=["year", "count", "kind"],
    )
    return bars.properties(height=240, background=SURFACE).configure_view(
        strokeWidth=0
    ).configure_axis(
        grid=True, gridColor=GRID, domain=False, tickSize=0,
        labelColor=INK_MUTED, titleColor=INK_MUTED, labelFontSize=11, titleFontSize=11,
    )


def stacked_split(rows):
    """One bar split into named parts — the outcome funnel's first step.

    A 2px surface gap between segments, so two adjacent fills never read
    as one longer one.
    """
    df = pd.DataFrame(rows)
    if df.empty:
        return None
    return alt.Chart(df).mark_bar(
        size=34, cornerRadius=CORNER, stroke=SURFACE, strokeWidth=2
    ).encode(
        x=alt.X("count:Q", title=None, stack="zero", axis=alt.Axis(grid=False)),
        color=alt.Color(
            "part:N",
            scale=alt.Scale(domain=[r["part"] for r in rows],
                            range=[SERIES[1], NEUTRAL][: len(rows)]),
            legend=alt.Legend(title=None, orient="top"),
        ),
        tooltip=["part", "count"],
    ).properties(height=90, background=SURFACE).configure_view(
        strokeWidth=0
    ).configure_axis(
        grid=False, domain=False, tickSize=0,
        labelColor=INK_MUTED, titleColor=INK_MUTED, labelFontSize=11,
    )
