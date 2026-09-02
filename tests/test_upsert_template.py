"""The batch upsert's three moving parts must agree, and nothing else checks
that they do.

On 2026-09-02 `has_results` was added to `UPSERT_STUDIES`' column list and to
the `study_rows` tuple. The `template` string of hand-typed `%s` was not
extended, so every row carried 24 values into 23 placeholders and psycopg2
raised `TypeError: not all arguments converted during string formatting`.

Nothing caught it:
  - The suite was green. No test writes a real batch through this path; the
    fake connection in conftest ignores SQL and never calls `mogrify`.
  - The live cron was green for three consecutive runs. `write_batch` returns
    before reaching the upsert when nothing changed, so the bug only fires on
    a run that actually has a record to write — it waited for the first busy
    run and then took the scheduled job down.

That is a `#41` fire alarm and a `#33` green-test-measuring-nothing at the
same time: the failure was invisible to the tests AND intermittent in
production, which is the combination that stays broken longest.

The template is now derived from the row, so the specific bug cannot recur.
These tests guard the wider invariant — that the column list, the row tuple,
and the placeholder row still describe the same number of things — because
the next column to be added is the one nobody will re-check.

Free: pure source inspection, no database, no network.
"""
import ast
import re
from pathlib import Path

import pytest

from api.studies import (
    INSERT_CHANGES,
    UPSERT_SQL_LITERAL_COLUMNS,
    UPSERT_STUDIES,
    values_template,
)

SOURCE = Path(__file__).resolve().parent.parent / "api" / "studies.py"


def insert_columns():
    """The column names UPSERT_STUDIES inserts into."""
    body = re.search(r"INSERT INTO studies\s*\((.*?)\)\s*VALUES", UPSERT_STUDIES, re.S)
    assert body, "UPSERT_STUDIES no longer starts with INSERT INTO studies (...)"
    return [c.strip() for c in body.group(1).split(",") if c.strip()]


def study_row_width():
    """How many values one row of `study_rows` carries, read from the real
    source rather than reconstructed — building a fake record here would just
    be a second implementation to keep in sync."""
    tree = ast.parse(SOURCE.read_text())
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and any(getattr(t, "id", None) == "study_rows" for t in node.targets)
            and isinstance(node.value, ast.ListComp)
            and isinstance(node.value.elt, ast.Tuple)
        ):
            return len(node.value.elt.elts)
    pytest.fail("could not find `study_rows = [( ... ) for r in records]`")


def test_the_column_list_matches_the_row_tuple():
    """The exact drift that broke the cron. A column added to the INSERT
    without a matching value in the tuple (or the reverse) fails here, at
    import speed, instead of six hours later on the first busy run."""
    columns = insert_columns()
    width = study_row_width()
    assert len(columns) == width + len(UPSERT_SQL_LITERAL_COLUMNS), (
        f"UPSERT_STUDIES inserts {len(columns)} columns and study_rows carries "
        f"{width} values plus {len(UPSERT_SQL_LITERAL_COLUMNS)} SQL literals "
        f"({', '.join(UPSERT_SQL_LITERAL_COLUMNS)}) — they have drifted apart"
    )


def test_the_sql_literal_columns_are_the_last_three():
    """values_template() appends `now(),true,now()` positionally, so those
    three columns must be last and in that order. Reordering the column list
    would silently write now() into the wrong column."""
    assert insert_columns()[-len(UPSERT_SQL_LITERAL_COLUMNS):] == list(
        UPSERT_SQL_LITERAL_COLUMNS
    )


def test_the_template_has_one_placeholder_per_value():
    width = study_row_width()
    template = values_template(width)
    assert template.count("%s") == width
    assert template.endswith(",now(),true,now())")


@pytest.mark.parametrize("width", [1, 5, 24, 40])
def test_values_template_is_well_formed_at_any_width(width):
    """Guards the off-by-one directly: a template built with a stray leading
    or trailing comma parses as an extra column and fails only against a real
    database."""
    template = values_template(width)
    assert template.startswith("(") and template.endswith(")")
    placeholders = template[1:-1].split(",")
    assert placeholders[:width] == ["%s"] * width
    assert placeholders[width:] == ["now()", "true", "now()"]


def test_change_rows_match_their_insert():
    """The same class of bug, one statement over. INSERT_CHANGES takes no
    explicit template, so psycopg2 builds one from the tuple — but the column
    list still has to match the tuple's width."""
    body = re.search(r"INSERT INTO study_changes\s*\((.*?)\)\s*VALUES", INSERT_CHANGES, re.S)
    assert body
    columns = [c.strip() for c in body.group(1).split(",") if c.strip()]

    tree = ast.parse(SOURCE.read_text())
    widths = {
        len(node.args[0].elts)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "append"
        and getattr(node.func.value, "id", None) == "change_rows"
        and node.args
        and isinstance(node.args[0], ast.Tuple)
    }
    assert widths, "could not find change_rows.append((...))"
    assert widths == {len(columns)}, (
        f"INSERT_CHANGES has {len(columns)} columns but change_rows appends "
        f"tuples of width {widths}"
    )
