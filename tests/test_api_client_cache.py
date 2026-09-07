"""frontend/api_client.py's read cache — what it saves, and what it must
never hide.

Why this exists. Streamlit re-runs the whole page script on every widget
interaction, and until 2026-09-07 the frontend cached nothing, so one filter
change on Investigate re-issued 43,842 measured bytes of reads (see the
allowlist's own note for the per-endpoint figures). Each of those is an API
request, and each API request is a query against Neon, which warned at 82% of
its 5 GB monthly transfer allowance that same day.

The saving is the easy half. The dangerous half is that a cache can make a
monitoring tool *lie*: show a stale watch, or appear not to register a
condition the user just added. So most of what follows asserts the limits
rather than the hits — a write clears everything, a failure is never sticky,
the health surface is never cached at all, and an endpoint nobody classified
gets no cache by default.

Free: no network (requests.get is stubbed), no database, no model.

Run: PYTHONPATH=frontend .venv/bin/python -m pytest tests/test_api_client_cache.py -v
"""
import importlib
import re
import sys
import time
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
if str(FRONTEND) not in sys.path:
    sys.path.insert(0, str(FRONTEND))

# Without streamlit there is no cache to test — api_client falls back to
# fetching every read, which is what the pre-2026-09-07 behaviour was.
pytest.importorskip("streamlit", reason="streamlit not installed")


class Response:
    """The smallest thing requests.get's callers here actually use."""

    ok = True
    status_code = 200
    text = ""

    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


@pytest.fixture
def client(monkeypatch):
    """A freshly reloaded api_client with requests.get counted, not made.

    Reloaded per test because st.cache_data is decorated at import time and
    caches across the whole process — a shared instance would leak one test's
    entries into the next, which is the bug class this module is about.
    """
    import api_client

    def _make(body=None, ttl=None):
        monkeypatch.setenv("API_BASE_URL", "http://127.0.0.1:8000")
        if ttl is not None:
            monkeypatch.setenv("FRONTEND_CACHE_TTL_SECONDS", str(ttl))
        module = importlib.reload(api_client)
        calls = []

        def record(url, params=None, timeout=None):
            calls.append((url, params))
            return Response({"body": body if body is not None else len(calls)})

        monkeypatch.setattr(module.requests, "get", record)
        module.clear_cache()
        return module, calls

    yield _make
    monkeypatch.delenv("API_BASE_URL", raising=False)
    monkeypatch.delenv("FRONTEND_CACHE_TTL_SECONDS", raising=False)
    import api_client as reset

    importlib.reload(reset).clear_cache()


class TestWhatTheCacheSaves:
    def test_a_cacheable_read_reaches_the_api_once(self, client):
        """The measured case: /investigate is 37,711 bytes and the page
        re-issues it on every rerun."""
        api, calls = client()
        first = api.get("/investigate")
        second = api.get("/investigate")
        assert len(calls) == 1
        assert first == second

    def test_params_order_and_none_values_do_not_split_the_cache(self, client):
        """Monitor builds its params dict conditionally, so the same view can
        arrive with the keys in a different order or with an unset filter
        present as None. requests drops a None param, so these are one
        request and must be one entry."""
        api, calls = client()
        api.get("/changes", {"limit": 25, "offset": 0})
        api.get("/changes", {"offset": 0, "limit": 25, "condition": None})
        assert len(calls) == 1

    def test_different_params_are_different_entries(self, client):
        """Paging must not serve page 1 for page 2."""
        api, calls = client()
        page_one = api.get("/changes", {"limit": 25, "offset": 0})
        page_two = api.get("/changes", {"limit": 25, "offset": 25})
        assert len(calls) == 2
        assert page_one != page_two
        api.get("/changes", {"limit": 25, "offset": 0})
        assert len(calls) == 2, "going back to page 1 should be free"

    def test_a_per_trial_read_is_cached_but_a_search_is_not(self, client):
        """/discover/NCT... is a stored record; /discover is a search with a
        live CT.gov fallback, which a cache could make hide a trial
        registered minutes ago."""
        api, calls = client()
        api.get("/discover/NCT04837586")
        api.get("/discover/NCT04837586")
        assert len(calls) == 1
        api.get("/discover", {"condition": "obesity"})
        api.get("/discover", {"condition": "obesity"})
        assert len(calls) == 3


class TestWhatTheCacheMustNeverHide:
    def test_a_write_clears_every_cached_read(self, client):
        """The shape this had to be safe against before it could ship: add a
        condition on Home, then read the list back. A tool that appears not to
        register what someone just did is worse than one that costs
        bandwidth."""
        api, calls = client()

        api.get("/tracked-conditions")
        api.get("/tracked-conditions")
        assert len(calls) == 1

        posted = []

        class Created(Response):
            status_code = 201

        def record_post(url, params=None, data=None, json=None, timeout=None):
            posted.append(json)
            return Created({"condition": "glioblastoma"})

        api.requests.post = record_post
        api.post("/tracked-conditions", json_data={"condition": "glioblastoma"})
        assert posted, "the write itself must still happen"

        api.get("/tracked-conditions")
        assert len(calls) == 2, "the read after a write must reach the API"

    def test_a_failed_read_is_not_cached(self, client):
        """An API blip must not be sticky for five minutes. st.cache_data
        stores return values, not exceptions — this holds that, because the
        alternative is a page that stays broken after the API recovers."""
        api, calls = client()

        def boom(url, params=None, timeout=None):
            calls.append((url, params))
            raise api.requests.RequestException("connection refused")

        api.requests.get = boom
        with pytest.raises(api.ApiError):
            api.get("/watch")

        def recovered(url, params=None, timeout=None):
            calls.append((url, params))
            return Response({"is_healthy": True})

        api.requests.get = recovered
        assert api.get("/watch") == {"is_healthy": True}
        assert len(calls) == 2

    def test_the_health_surface_is_never_cached(self, client):
        """/ops/status exists to answer "are the unattended jobs alive right
        now". A five-minute-old all-clear during an incident is the exact
        failure step 11 was built against."""
        api, calls = client()
        api.get("/ops/status")
        api.get("/ops/status")
        assert len(calls) == 2

    def test_an_unclassified_endpoint_is_not_cached(self, client):
        """Slow by default, never silently stale by default — the same
        allowlist reasoning as SELF_RESOLVING_SKIPS in
        scripts/check_ops_health.py."""
        api, calls = client()
        api.get("/some/endpoint/added/later")
        api.get("/some/endpoint/added/later")
        assert len(calls) == 2

    def test_a_caller_mutating_a_result_cannot_poison_the_cache(self, client):
        """Pages do mutate payloads. st.cache_data hands each caller its own
        copy; if that ever stopped being true, one page's edit would become
        every later reader's data."""
        api, calls = client()
        first = api.get("/watch")
        first["trials_watched"] = "tampered"
        second = api.get("/watch")
        assert len(calls) == 1
        assert "trials_watched" not in second

    def test_the_ttl_actually_expires(self, client):
        """The claim the whole design rests on is "five minutes, not
        forever". Asserted with a 0.2s TTL rather than by reading the
        constant, because a configured TTL that never fires would look
        identical from the outside."""
        api, calls = client(ttl=0.2)
        api.get("/investigate")
        api.get("/investigate")
        assert len(calls) == 1
        time.sleep(0.3)
        api.get("/investigate")
        assert len(calls) == 2


class TestEveryPathThePagesReadIsClassified:
    """A canary. The risk is not a wrong TTL, it is a page added in six
    months whose read nobody classified — cached when it should be live, or
    left out of the saving with no one noticing. Every GET path in the
    frontend must appear in exactly one of the two lists."""

    @staticmethod
    def paths():
        found = set()
        for source in sorted(FRONTEND.glob("*.py")) + sorted(FRONTEND.glob("pages/*.py")):
            if source.name == "api_client.py":
                continue
            text = source.read_text()
            for raw in re.findall(r"[^_\w]get\(\s*\n?\s*f?\"(/[^\"]*)\"", text):
                # f-string interpolations are always the trial id.
                found.add(re.sub(r"\{[^}]+\}", "NCT00000000", raw))
        return found

    def test_the_scan_found_the_pages_reads(self):
        """If the regex silently matches nothing, every assertion below
        passes for the wrong reason."""
        paths = self.paths()
        assert "/investigate" in paths and "/watch" in paths, paths
        assert len(paths) >= 10, paths

    def test_every_read_is_either_cached_or_deliberately_not(self):
        import api_client

        classified = api_client.CACHEABLE_PATHS + api_client.UNCACHED_ON_PURPOSE
        for path in sorted(self.paths()):
            assert any(re.fullmatch(p, path) for p in classified), (
                f"{path} is read by a page but appears in neither "
                "CACHEABLE_PATHS nor UNCACHED_ON_PURPOSE — decide which, "
                "in frontend/api_client.py"
            )

    def test_no_classified_path_is_dead(self):
        """The other direction, and this one found a real entry: /health was
        listed as deliberately uncached, and no page reads it. A rule that
        cannot fire is a lie in the code (CLAUDE.md's standing gotcha on the
        unreachable cap), so it was deleted rather than kept as decoration."""
        import api_client

        paths = self.paths()
        dead = [
            entry
            for entry in api_client.CACHEABLE_PATHS + api_client.UNCACHED_ON_PURPOSE
            if not any(re.fullmatch(entry, path) for path in paths)
        ]
        assert not dead, (
            f"no page reads {dead} — delete the entry, or the list stops "
            "describing the frontend it claims to classify"
        )

    def test_nothing_is_in_both_lists(self):
        import api_client

        overlap = set(api_client.CACHEABLE_PATHS) & set(api_client.UNCACHED_ON_PURPOSE)
        assert not overlap, overlap
