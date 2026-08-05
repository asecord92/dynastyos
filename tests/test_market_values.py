"""Unit tests for engine/mlb_market_values.py — the HarryKnowsBall parse and
its stale-if-error contract.

The parse is the fragile part: there is no documented API, so a page-shape
change upstream is a question of when, not if. These tests pin the two things
that keep that from becoming an outage — that a bad page *raises* rather than
returning an empty list (an empty value map would read as "every player is
unpriced"), and that a raise falls through to the previously cached values.

No network: every test drives the module with a fixture and a stubbed httpx.
"""

import json

import pytest

from engine import mlb_market_values as mv


def page(players, last_updated="2026-08-04T12:00:00Z", players_error=None, tag=mv._TAG):
    """A minimal stand-in for /rankings — the real page is the same JSON blob
    inside the same script tag, with ~1,750 entries and a lot more markup."""
    body = json.dumps({
        "props": {"pageProps": {
            "players": players,
            "lastUpdated": last_updated,
            "playersError": players_error,
        }},
        "page": "/rankings",
    })
    return f"<html><head><title>Rankings</title></head><body><div id=root></div>{tag}{body}</script></body></html>"


def player(name, value, rank=1, age=25.0, prospect=False, **extra):
    return {
        "id": extra.get("id", name.lower().replace(" ", "-")),
        "name": name, "value": value, "rank": rank, "age": age,
        "team": extra.get("team", "LAD"), "positions": extra.get("positions", ["OF"]),
        "level": extra.get("level", "MLB"), "prospect": prospect, "fypd": False,
        "assetType": extra.get("asset_type", "PLAYER"),
        "valueChange30Days": extra.get("trend", 0),
    }


@pytest.fixture(autouse=True)
def _clear_cache():
    """The cache is module state — a leak between tests would let one test's
    values satisfy another's stale-if-error assertion."""
    mv._cache = None
    yield
    mv._cache = None


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


def stub_get(monkeypatch, *responses):
    """Queue up successive httpx.get results; a callable raises instead."""
    calls = {"n": 0}

    def fake_get(url, **kwargs):
        i = min(calls["n"], len(responses) - 1)
        calls["n"] += 1
        r = responses[i]
        if isinstance(r, Exception):
            raise r
        return FakeResponse(r)

    monkeypatch.setattr(mv.httpx, "get", fake_get)
    return calls


# --- parse_rankings ---------------------------------------------------------

def test_parses_players_and_source_timestamp():
    entries, last_updated = mv.parse_rankings(
        page([player("Shohei Ohtani", 10000), player("Bobby Witt Jr.", 9914, rank=2)])
    )
    assert [e["name"] for e in entries] == ["Shohei Ohtani", "Bobby Witt Jr."]
    assert last_updated == "2026-08-04T12:00:00Z"


def test_missing_script_tag_raises():
    with pytest.raises(ValueError):
        mv.parse_rankings("<html><body>we redesigned the site</body></html>")


def test_empty_player_list_raises():
    # Would otherwise price the whole league at None and look like a data gap.
    with pytest.raises(ValueError):
        mv.parse_rankings(page([]))


def test_sites_own_error_flag_raises():
    with pytest.raises(ValueError):
        mv.parse_rankings(page([player("Shohei Ohtani", 10000)], players_error="upstream down"))


def test_absent_timestamp_is_none_not_a_crash():
    entries, last_updated = mv.parse_rankings(page([player("A", 1)], last_updated=None))
    assert entries and last_updated is None


# --- get_values -------------------------------------------------------------

def test_fetch_populates_cache_and_prefers_source_timestamp(monkeypatch):
    stub_get(monkeypatch, page([player("Shohei Ohtani", 10000)]))
    got = mv.get_values()
    assert [e["name"] for e in got["entries"]] == ["Shohei Ohtani"]
    assert got["fetched_at"] == "2026-08-04T12:00:00Z"


def test_second_call_is_served_from_cache(monkeypatch):
    calls = stub_get(monkeypatch, page([player("Shohei Ohtani", 10000)]))
    mv.get_values()
    mv.get_values()
    assert calls["n"] == 1, "TTL cache should not refetch a free hobby site per request"


def test_force_refetches(monkeypatch):
    calls = stub_get(
        monkeypatch,
        page([player("Shohei Ohtani", 10000)]),
        page([player("Shohei Ohtani", 9800)], last_updated="2026-08-05T12:00:00Z"),
    )
    mv.get_values()
    got = mv.get_values(force=True)
    assert calls["n"] == 2
    assert got["entries"][0]["value"] == 9800


def test_transport_failure_serves_stale_values(monkeypatch):
    stub_get(monkeypatch, page([player("Shohei Ohtani", 10000)]))
    mv.get_values()
    monkeypatch.setattr(mv.httpx, "get", lambda url, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    got = mv.get_values(force=True)
    assert got["entries"][0]["value"] == 10000
    assert got["fetched_at"] == "2026-08-04T12:00:00Z", "stale data must report its real age"


def test_page_shape_change_serves_stale_values(monkeypatch):
    """The failure mode this module exists to survive."""
    stub_get(monkeypatch, page([player("Shohei Ohtani", 10000)]), "<html>brand new site</html>")
    mv.get_values()
    got = mv.get_values(force=True)
    assert got["entries"][0]["name"] == "Shohei Ohtani"


def test_cold_failure_returns_none_not_an_exception(monkeypatch):
    stub_get(monkeypatch, RuntimeError("network down"))
    assert mv.get_values() == {"entries": None, "fetched_at": None}
