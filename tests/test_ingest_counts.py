"""What a monitor run records as "changes detected" must be the writer's
own count, and it must survive batching.

Why this exists. `monitor_runs.changes_detected` used to be re-derived after
the fact: `SELECT count(*) FROM study_changes WHERE detected_at >= started_at`.
Close, but not true — that window also catches rows written by anything else
running at the same time (a manual ingest, a backfill) and files them under
this run's id. The number now comes from POST /studies/batch, which reports
what it actually wrote, summed by `sync_group` across its batches.

That sum is the fragile part. `sync_group` flushes at REFETCH_CHUNK_SIZE-
sized boundaries (200 records) and then once more for the remainder, which
is the classic place to drop a trailing batch or double-count the last one.
Nothing else in the suite touches `scripts/ingest.py` at all — before this
file, the whole module had zero coverage.

No network and no database: every boundary of `sync_group` is replaced, so
this runs in CI without credentials.

Proven able to fail (CLAUDE.md sec. 7; concepts #41) — three mutations, all
caught:
  - dropping the trailing `if batch:` flush   -> changes 900 != 500, ids 450 != 400
  - `total_changed = result[...]` (= not +=)  -> changes 900 != 100
  - returning `len(all_nct_ids)` as the count -> changes 900 != 450
"""
import pytest

import scripts.ingest as ingest


def make_study(n):
    """Only the field `sync_group` reads off a record: nothing. It passes
    each one to extract_fields and appends the result, so the shape here
    just has to be distinguishable."""
    return {"nct_id": f"NCT{n:08d}"}


@pytest.fixture
def captured_batches(monkeypatch):
    """Replace every I/O boundary of sync_group. Returns the list that
    records the size of each batch handed to write_batch."""
    sizes = []

    def fake_write_batch(records):
        sizes.append(len(records))
        # Two field changes per study written — deliberately not 1, so a
        # test asserting on the count cannot pass by accidentally counting
        # studies instead of changes.
        return {
            "studies_written": len(records),
            "condition_tags_written": 0,
            "changes_detected": len(records) * 2,
        }

    monkeypatch.setattr(ingest, "write_batch", fake_write_batch)
    monkeypatch.setattr(ingest, "extract_fields", lambda study: study)
    monkeypatch.setattr(ingest, "get_known_dates", lambda nct_ids: {})
    return sizes


def stub_remote(monkeypatch, count):
    """The cheap filter matched `count` trials, all of them new or changed
    (get_known_dates returns {}, so every one gets refetched)."""
    nct_ids = [f"NCT{n:08d}" for n in range(count)]
    monkeypatch.setattr(
        ingest,
        "cheap_fetch_dates",
        lambda *a, **kw: {nct_id: "2026-01-01" for nct_id in nct_ids},
    )
    monkeypatch.setattr(
        ingest,
        "expensive_fetch_full",
        lambda ids: (make_study(n) for n in range(len(ids))),
    )
    return nct_ids


def test_sync_group_sums_changes_across_batches(monkeypatch, captured_batches):
    """450 records is 200 + 200 + 50: two mid-loop flushes and a remainder.

    The remainder is the whole point. A version that forgets the trailing
    `if batch:` still writes 400 records and still returns a plausible
    number — it just silently loses the last 50, which on a real run is a
    quiet undercount nobody would ever notice.
    """
    nct_ids = stub_remote(monkeypatch, 450)

    result = ingest.sync_group("breast cancer", ingest.ACTIVE_STATUSES)

    assert captured_batches == [200, 200, 50], (
        "batching changed shape — the count below is only meaningful if "
        "every record actually reached write_batch"
    )
    assert result.changes == 900, "450 records x 2 changes each"
    assert result.nct_ids == set(nct_ids)


def test_sync_group_counts_an_exact_multiple_of_the_batch_size(
    monkeypatch, captured_batches
):
    """400 records is exactly 200 + 200, with nothing left over. The trailing
    flush must not fire on an empty list and add a phantom batch."""
    stub_remote(monkeypatch, 400)

    result = ingest.sync_group("breast cancer", ingest.ACTIVE_STATUSES)

    assert captured_batches == [200, 200]
    assert result.changes == 800


def test_sync_group_reports_zero_when_the_cheap_filter_matches_nothing(
    monkeypatch, captured_batches
):
    """The early return. It must still be an IngestResult, not a bare set —
    run_monitor.py reads `.changes` off it unconditionally."""
    monkeypatch.setattr(ingest, "cheap_fetch_dates", lambda *a, **kw: {})

    result = ingest.sync_group("nothing matches this", ingest.ACTIVE_STATUSES)

    assert result.nct_ids == set()
    assert result.changes == 0
    assert captured_batches == []


def test_run_ingest_adds_up_both_status_groups(monkeypatch):
    """One condition is two searches — active trials and recently-closed
    ones. A run's recorded total is both, not whichever ran last."""
    groups = iter(
        [
            ingest.IngestResult({"NCT00000001", "NCT00000002"}, 7),
            ingest.IngestResult({"NCT00000002", "NCT00000003"}, 5),
        ]
    )
    monkeypatch.setattr(ingest, "sync_group", lambda *a, **kw: next(groups))
    monkeypatch.setattr(ingest, "reconcile_scope", lambda condition, ids: None)

    result = ingest.run_ingest("breast cancer")

    assert result.changes == 12, "7 active + 5 recently-closed"
    assert result.nct_ids == {"NCT00000001", "NCT00000002", "NCT00000003"}, (
        "the id sets are unioned — NCT00000002 appears in both groups and is "
        "one trial, not two"
    )


def test_run_ingest_reconciles_scope_with_the_union(monkeypatch):
    """Scope reconciliation flags anything it does NOT hear about as dropped.
    Handing it one group's ids instead of the union would flag every trial in
    the other group as out of scope — on live data.
    """
    seen = {}
    groups = iter(
        [
            ingest.IngestResult({"NCT00000001"}, 0),
            ingest.IngestResult({"NCT00000002"}, 0),
        ]
    )
    monkeypatch.setattr(ingest, "sync_group", lambda *a, **kw: next(groups))
    monkeypatch.setattr(
        ingest, "reconcile_scope", lambda condition, ids: seen.update(ids=ids)
    )

    ingest.run_ingest("breast cancer")

    assert seen["ids"] == {"NCT00000001", "NCT00000002"}
