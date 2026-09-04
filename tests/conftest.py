"""Shared HTTP-test scaffolding.

CLAUDE.md sec. 7: "A test that calls an endpoint function directly is not
testing the endpoint — request binding and response validation are
FastAPI's job, and only an HTTP-level call exercises them." So every API
test goes through TestClient, with the database dependency replaced.

The fake connection is deliberately dumb: it returns queued results in
order and ignores the SQL entirely. A fake that interpreted SQL would be a
second, worse Postgres, and passing against it would say nothing about the
real query. What these tests cover is routing, request binding, the
assembly code between the query and the response, and the response model.
Whether the SQL is *correct* is what the real-data tests are for, and those
run against the live database.
"""
import pytest
from fastapi.testclient import TestClient

from api.database import get_db, get_readonly_db
from api.main import app


class FakeCursor:
    def __init__(self, results):
        self._results = list(results)
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def _next(self):
        assert self._results, (
            "the route ran more queries than the fake was given results for — "
            "add one, or the route changed shape"
        )
        return self._results.pop(0)

    def fetchone(self):
        rows = self._next()
        return rows[0] if rows else None

    def fetchall(self):
        return self._next()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, results):
        self.cursor_obj = FakeCursor(results)

    def cursor(self, **kwargs):
        return self.cursor_obj


@pytest.fixture
def api():
    """A TestClient whose database returns whatever the test queues.

    Usage:
        client = api(results)                 # results: list of row-lists
        client = api(results, keep=holder)    # to inspect the SQL sent
    """
    def _make(results, keep=None):
        fake = FakeConnection(results)
        if keep is not None:
            keep.append(fake)
        app.dependency_overrides[get_readonly_db] = lambda: fake
        # Same fake, same queued-results ordering as get_readonly_db — the
        # fake ignores SQL either way, so a route using the write connection
        # (get_db, e.g. POST /tracked-conditions) draws from the same list.
        app.dependency_overrides[get_db] = lambda: fake
        return TestClient(app)

    yield _make
    app.dependency_overrides.clear()
