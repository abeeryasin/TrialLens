"""Step 8 unit 3 — point near-duplicate entities at one canonical row.

Units 1-2 extracted everything unmerged on purpose, so the registry's own
words survived and any later merge had a baseline to be checked against.
This is that merge, and it does the smallest thing that works: it writes a
POINTER. No row is deleted, no edge is rewritten, and setting `canonical_id`
back to NULL undoes the whole thing. Merging is a judgement about the data,
and a judgement written destructively cannot be revisited.

**What counts as the same thing** is deterministic and timid: casefold,
collapse every non-alphanumeric run to one space, trim. Nothing else — no
edit distance, no abbreviation expansion, no model. That is not a shortcut,
it is the scope. Deterministic-first (CLAUDE.md sec. 5) means a merge rule
whose every decision can be re-derived by hand from two strings, which is
what makes the 5.9% it catches safe to apply without anyone reviewing it.

It therefore merges:
    'Sun Yat-Sen University Cancer Center' + 10 other spellings -> one site
    'Semaglutide' + 'semaglutide'                               -> one term
and deliberately does NOT merge:
    'Placebo semaglutide'    — a placebo arm is not the drug
    'Semaglutide 2.4 mg'     — a dose is not the same intervention
    'Mayo Clinic' in Rochester vs in Phoenix — different places

Organizations get no treatment at all: measured 2026-09-04, they have zero
duplicates under this rule. A merge with nothing to merge is not symmetry,
it is dead code.

Safe to re-run: idempotent, and every ingest adds new rows that need it, so
this runs in monitor.yml after the graph backfill.

One of sec. 5's administrative scripts, so it holds DATABASE_URL directly
rather than going through the API — the read-only role could not write this
column, and the API is not a migration tool.

Run:  python scripts/merge_entities.py [--dry-run]
"""
import argparse
import os
import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")
except ImportError:
    pass


def normalized(column):
    """The one definition of "the same string", as SQL.

    Casefold, every run of non-alphanumerics becomes a single space, trim.
    Used for grouping only — the stored value is never altered.
    """
    return f"btrim(regexp_replace(lower(coalesce({column}, '')), '[^a-z0-9]+', ' ', 'g'))"


# Each entity: the table, the columns that make up its identity, and the
# edge table whose row count decides which spelling wins.
#
# `identity` is what must MATCH before two rows are one thing. For sites it
# is the whole triple, never facility alone: the same hospital name really
# does recur in different cities, and merging on the name would move a trial
# to another country. For terms it includes `type`, because a DRUG called X
# is not the OTHER called X — the same reason the unique index has it.
ENTITIES = {
    "sites": {
        "table": "sites",
        "identity": ["facility", "city", "country"],
        "edge_table": "trial_sites",
        "edge_key": "site_id",
    },
    "interventions": {
        "table": "intervention_terms",
        "identity": ["name", "type"],
        "edge_table": "trial_interventions",
        "edge_key": "term_id",
    },
    "investigators": {
        "table": "investigators",
        "identity": ["name", "affiliation"],
        "edge_table": "trial_investigators",
        "edge_key": "investigator_id",
    },
}


def merge_sql(spec):
    """One statement that assigns every row in a duplicate group to a winner.

    The winner is the spelling carrying the most LIVE edges, tie-broken by
    lowest id. Most-used rather than longest or first-seen: the variant the
    registry writes most often is the one a researcher is most likely to
    recognise, and it is a fact about the data rather than an aesthetic
    preference. The tie-break makes the whole thing deterministic, so two
    runs over unchanged data produce identical output.

    The winner's own canonical_id is set to NULL, not to itself. NULL means
    "this row IS the canonical form", which keeps `coalesce(canonical_id,
    id)` correct for the ~94% of rows that were never in a group at all, and
    means a row can never point at itself.
    """
    table, edge_table, edge_key = spec["table"], spec["edge_table"], spec["edge_key"]
    keys = ", ".join(normalized(c) for c in spec["identity"])
    key_cols = ", ".join(f"{normalized(c)} AS k{i}" for i, c in enumerate(spec["identity"]))
    group_by = ", ".join(f"k{i}" for i in range(len(spec["identity"])))

    return f"""
        WITH keyed AS (
            SELECT e.id, {key_cols},
                   (SELECT count(*) FROM {edge_table} x
                     WHERE x.{edge_key} = e.id AND x.delisted_at IS NULL) AS live_edges
            FROM {table} e
        ),
        winners AS (
            SELECT DISTINCT ON ({group_by}) {group_by}, id AS canonical
            FROM keyed
            ORDER BY {group_by}, live_edges DESC, id
        ),
        assignment AS (
            SELECT k.id, w.canonical
            FROM keyed k JOIN winners w USING ({group_by})
        )
        UPDATE {table} t
           SET canonical_id = CASE WHEN a.canonical = t.id THEN NULL ELSE a.canonical END
          FROM assignment a
         WHERE a.id = t.id
           AND t.canonical_id IS DISTINCT FROM
               (CASE WHEN a.canonical = t.id THEN NULL ELSE a.canonical END)
    """.replace("{keys}", keys)


def report(cur, spec, label):
    table = spec["table"]
    cur.execute(f"""
        SELECT count(*) AS rows,
               count(canonical_id) AS pointed,
               count(DISTINCT canonical_id) AS groups
        FROM {table}
    """)
    total, pointed, groups = cur.fetchone()
    print(
        f"  {label:14} {total:>7,} rows · {pointed:>6,} now point at a canonical "
        f"({groups:,} groups) · {total - pointed:,} stand alone",
        flush=True,
    )
    return pointed


def check_no_cross_place_merge(cur):
    """The one merge that would be a lie about a trial.

    Two sites may only merge when city AND country match after
    normalisation. If this ever finds a row, a trial is being reported as
    running somewhere it does not (CLAUDE.md sec. 2), so it aborts the
    transaction rather than reporting success.
    """
    cur.execute(f"""
        SELECT count(*) FROM sites s JOIN sites c ON c.id = s.canonical_id
        WHERE {normalized('s.city')}    IS DISTINCT FROM {normalized('c.city')}
           OR {normalized('s.country')} IS DISTINCT FROM {normalized('c.country')}
    """)
    crossed = cur.fetchone()[0]
    if crossed:
        raise SystemExit(
            f"ABORT: {crossed} site(s) were merged across a city or country "
            "boundary. Nothing has been committed."
        )


def check_no_chains(cur):
    """A canonical row must never itself point somewhere else.

    Otherwise `coalesce(canonical_id, id)` resolves to a row that is not
    canonical and identity depends on how many times you follow the
    pointer. One hop, always.
    """
    for spec in ENTITIES.values():
        table = spec["table"]
        cur.execute(f"""
            SELECT count(*) FROM {table} a JOIN {table} b ON b.id = a.canonical_id
            WHERE b.canonical_id IS NOT NULL
        """)
        chained = cur.fetchone()[0]
        if chained:
            raise SystemExit(f"ABORT: {chained} chained pointer(s) in {table}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="compute and report, then roll back without writing",
    )
    args = parser.parse_args()

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        with conn.cursor() as cur:
            print("Merging near-duplicate entities (deterministic, pointer-only):", flush=True)
            for label, spec in ENTITIES.items():
                cur.execute(merge_sql(spec))
                print(f"  {label:14} {cur.rowcount:,} pointer(s) changed", flush=True)

            check_no_cross_place_merge(cur)
            check_no_chains(cur)

            print("\nAfter:", flush=True)
            for label, spec in ENTITIES.items():
                report(cur, spec, label)

        if args.dry_run:
            conn.rollback()
            print("\n--dry-run: rolled back, nothing written.", flush=True)
        else:
            conn.commit()
            print("\nCommitted.", flush=True)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
