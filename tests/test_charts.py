"""frontend/charts.py — the chart specs, checked as specs.

**Why this file exists.** On 2026-09-04 the status chart drew eight bars
and kept four axis labels: Vega-Lite thins labels it decides will not fit,
and on a CATEGORICAL axis a thinned label does not degrade gracefully — it
lies. "Terminated" sat against the bar for Enrolling By Invitation, so the
chart reported 78 terminated breast-cancer trials when the real number is
237. A reader has no way to tell.

It survived two rounds of looking because a PNG export renders every label;
only Streamlit's own theme tightens the spacing enough to trigger the
thinning. So the guarantee cannot live in "I looked at it" — it has to be
asserted on the spec, which is what these do.

Free: no database, no network, no browser.

Run: PYTHONPATH=frontend python3 -m pytest tests/test_charts.py -v
"""
import json
import sys
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
if str(FRONTEND) not in sys.path:
    sys.path.insert(0, str(FRONTEND))

charts = pytest.importorskip("charts", reason="altair/pandas not installed")

# Eight rows, because eight is what broke: the real status distribution.
STATUS_ROWS = [
    {"Status": label, "Trials": n}
    for label, n in [
        ("Recruiting", 2053), ("Completed", 1240), ("Active Not Recruiting", 962),
        ("Not Yet Recruiting", 714), ("Terminated", 237),
        ("Enrolling By Invitation", 78), ("Withdrawn", 69), ("Suspended", 24),
    ]
]


def spec_of(chart):
    return json.loads(chart.to_json())


def layers(spec):
    return spec.get("layer", [spec])


def categorical_axes(spec):
    """Every nominal axis that is actually drawn, with its config."""
    found = []
    for layer in layers(spec):
        for channel in ("x", "y"):
            encoding = layer.get("encoding", {}).get(channel, {})
            if encoding.get("type") != "nominal":
                continue
            if "axis" not in encoding:
                continue  # silent: the configured layer governs
            axis = encoding["axis"]
            if axis is None:
                continue  # explicitly axis-less: contributes nothing
            found.append((channel, axis))
    return found


ALL_BUILDERS = [
    pytest.param(
        lambda: charts.ranked_bars(STATUS_ROWS, "Status", "Trials", "Trials"),
        id="ranked_bars",
    ),
    pytest.param(
        lambda: charts.ranked_bars(
            STATUS_ROWS, "Status", "Trials", "Trials", select_field="Status"
        ),
        id="ranked_bars_selectable",
    ),
    pytest.param(
        lambda: charts.ordered_columns(STATUS_ROWS, "Status", "Trials", "Trials"),
        id="ordered_columns",
    ),
    pytest.param(
        lambda: charts.lifecycle_bars([
            {"movement": m, "count": c, "kind": "Ordinary", "examples": "—"}
            for m, c in [("Finished", 21), ("Closed", 13), ("Opened", 12),
                         ("Reopened", 1), ("Stopped", 3), ("Restarted", 2),
                         ("Other", 1), ("Unknown", 1)]
        ]),
        id="lifecycle_bars",
    ),
    pytest.param(
        lambda: charts.year_bars([
            {"year": str(y), "count": y - 2000, "kind": "Complete year",
             "detail": "a full calendar year"}
            for y in range(2010, 2027)
        ]),
        id="year_bars",
    ),
]


@pytest.mark.parametrize("build", ALL_BUILDERS)
def test_every_category_keeps_its_own_label(build):
    """The bug this file exists for.

    labelOverlap defaults to letting Vega-Lite drop labels. On a
    categorical axis that silently reassigns every remaining label to the
    wrong row, which is worse than an unreadable chart — it is a confident,
    wrong chart.
    """
    axes = categorical_axes(spec_of(build()))
    assert axes, "no categorical axis found — the chart shape changed"
    for channel, axis in axes:
        assert axis != "ABSENT", f"{channel} axis has no config at all"
        assert axis.get("labelOverlap") is False, (
            f"{channel} axis may thin its labels; a dropped categorical label "
            f"mislabels every row after it"
        )


@pytest.mark.parametrize("build", ALL_BUILDERS)
def test_exactly_one_layer_configures_the_axis(build):
    """A value-label layer must not contribute a competing axis config, or
    whichever Vega-Lite resolves decides the thinning — and it may not be
    the one carrying labelOverlap.

    It must also not set axis=None to achieve that: doing so removed the
    shared axis outright and produced a chart with no labels at all, which
    is worse than the thinning. The label layer stays silent instead.
    """
    spec = spec_of(build())
    configured = categorical_axes(spec)
    assert len(configured) == 1, (
        f"expected exactly one configured categorical axis, got {len(configured)}"
    )
    # And the axis genuinely renders: no layer may suppress it.
    suppressed = [
        channel
        for layer in layers(spec)
        for channel in ("x", "y")
        if layer.get("encoding", {}).get(channel, {}).get("type") == "nominal"
        and layer["encoding"][channel].get("axis", "ABSENT") is None
    ]
    assert not suppressed, f"axis=None on {suppressed} deletes the labels entirely"


def test_horizontal_bars_leave_real_room_per_row():
    """28px per row was tight enough for the theme to start thinning.
    The height must scale with the row count, not be a fixed box."""
    short = spec_of(charts.ranked_bars(STATUS_ROWS[:2], "Status", "Trials", "T"))
    tall = spec_of(charts.ranked_bars(STATUS_ROWS, "Status", "Trials", "T"))
    assert tall["height"] > short["height"]
    assert tall["height"] >= len(STATUS_ROWS) * 30


def test_a_selectable_chart_is_single_view_and_keeps_its_numbers():
    """Streamlit refuses selections on layered charts. Rather than drop the
    value labels to gain the click, the value moves into the category label
    — so the chart must be unlayered AND still show its figures."""
    spec = spec_of(
        charts.ranked_bars(STATUS_ROWS, "Status", "Trials", "T", select_field="Status")
    )
    assert "layer" not in spec, "a layered chart cannot carry a Streamlit selection"
    assert [p["name"] for p in spec.get("params", [])] == ["pick"]
    rendered = json.dumps(spec)
    assert "2,053" in rendered, "the value must survive in the label"


def test_the_selection_carries_the_real_field_not_the_display_label():
    """The page looks up the picked term by its original name; a selection
    on the decorated label would never match."""
    spec = spec_of(
        charts.ranked_bars(STATUS_ROWS, "Status", "Trials", "T", select_field="Status")
    )
    (param,) = spec["params"]
    assert param["select"]["fields"] == ["Status"]


def test_diverging_dates_uses_two_hues_and_one_axis():
    """Never a dual axis, and the midpoint must read as 'nothing'."""
    spec = spec_of(charts.diverging_dates([
        {"field": "Primary completion", "direction": "Pushed later", "count": 54,
         "median_days": 193, "median_months": 6.3},
        {"field": "Primary completion", "direction": "Pulled earlier", "count": 18,
         "median_days": 342, "median_months": 11.2},
    ]))
    colours = [
        layer["encoding"]["color"]["scale"]["range"]
        for layer in layers(spec)
        if "scale" in layer.get("encoding", {}).get("color", {})
    ]
    assert colours and colours[0] == [charts.LATER, charts.EARLIER]
    assert charts.LATER != charts.EARLIER


def test_an_empty_chart_is_none_not_an_empty_picture():
    """A caller must be able to say 'nothing happened' in words instead of
    rendering an empty axis, which reads as a broken query."""
    assert charts.ranked_bars([], "a", "b", "c") is None
    assert charts.ordered_columns([], "a", "b", "c") is None
    assert charts.lifecycle_bars([]) is None
    assert charts.year_bars([]) is None
    assert charts.diverging_dates([]) is None
