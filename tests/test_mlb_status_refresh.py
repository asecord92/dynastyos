"""Bulk MLB status refresh (engine/mlb_stats_client + player_resolver).

`player_id_map` holds each MLB player's current team, roster status, IL type and
age. They were written at resolution and refreshed only by a full sync, so
between syncs the trade and waiver prompts argued from a player's old team and a
healed player stayed on the IL — the MLB half of the staleness the NFL side
fixes on read.

There's no single MLB dump to overlay, so this is a scheduled refresh instead.
What makes it affordable is `/people?personIds=`: same hydrate, same person
shape, ~300 players in 3 requests instead of 300. The two things worth pinning
are that the bulk and single paths can't drift (they share `_parse_person`), and
that a total outage writes *nothing* rather than blanking every team and IL flag
in the league.
"""
import engine.mlb_stats_client as msc
import engine.player_resolver as pr
from engine.mlb_stats_client import _parse_person, fetch_roster_statuses_bulk


def person(pid, *, team="Los Angeles Dodgers", status="Active", age=30):
    return {
        "id": pid,
        "currentAge": age,
        "rosterEntries": [
            {"endDate": None, "team": {"name": team},
             "status": {"description": status}}
        ],
        "currentTeam": {"name": team},
    }


class FakeResp:
    def __init__(self, people):
        self._people = people

    def raise_for_status(self):
        pass

    def json(self):
        return {"people": self._people}


# --- parsing ------------------------------------------------------------------

def test_status_descriptions_map_to_roster_status_and_il_type():
    cases = {
        "Active": ("Active", None),
        "Injured 10-Day": ("IL", "10-Day IL"),
        "Injured 15-Day": ("IL", "15-Day IL"),
        "Injured 60-Day": ("IL", "60-Day IL"),
        "Minors": ("Minors", None),
    }
    for description, expected in cases.items():
        got = _parse_person(person(1, status=description))
        assert (got["roster_status"], got["il_type"]) == expected, description


def test_team_comes_from_the_active_roster_entry_not_current_team():
    """An optioned player's active entry is his AAA club; currentTeam still says
    the parent. The entry is the truthful one."""
    p = person(1, team="Oklahoma City Comets")
    p["currentTeam"] = {"name": "Los Angeles Dodgers"}
    assert _parse_person(p)["mlb_team"] == "Oklahoma City Comets"


def test_current_team_is_the_fallback_when_there_are_no_entries():
    p = {"id": 1, "currentAge": 30, "rosterEntries": [],
         "currentTeam": {"name": "New York Yankees"}, "status": {"description": "Active"}}
    assert _parse_person(p)["mlb_team"] == "New York Yankees"


def test_single_and_bulk_agree(monkeypatch):
    """Both paths go through `_parse_person`, so a change to the status mapping
    can't land on one and not the other."""
    p = person(660271, team="Los Angeles Dodgers", status="Injured 15-Day", age=32)
    monkeypatch.setattr(msc.httpx, "get", lambda *a, **k: FakeResp([p]))
    assert msc.fetch_roster_status(660271) == fetch_roster_statuses_bulk([660271])[660271]


# --- batching -----------------------------------------------------------------

def test_players_are_fetched_in_batches_not_one_at_a_time(monkeypatch):
    calls = []

    def fake_get(url, params=None, **k):
        ids = params["personIds"].split(",")
        calls.append(len(ids))
        return FakeResp([person(int(i)) for i in ids])

    monkeypatch.setattr(msc.httpx, "get", fake_get)
    out = fetch_roster_statuses_bulk(list(range(1, 251)))
    assert len(out) == 250
    assert len(calls) == 3 and max(calls) <= msc._STATUS_BATCH


def test_duplicate_ids_are_fetched_once(monkeypatch):
    """The same player is rostered in several leagues; player_id_map is global."""
    seen = []

    def fake_get(url, params=None, **k):
        ids = params["personIds"].split(",")
        seen.extend(ids)
        return FakeResp([person(int(i)) for i in ids])

    monkeypatch.setattr(msc.httpx, "get", fake_get)
    fetch_roster_statuses_bulk([5, 5, 5, 7])
    assert sorted(seen) == ["5", "7"]


def test_no_ids_means_no_requests(monkeypatch):
    monkeypatch.setattr(msc.httpx, "get", lambda *a, **k: 1 / 0)
    assert fetch_roster_statuses_bulk([]) == {}


# --- outages ------------------------------------------------------------------

def test_a_total_outage_returns_none_rather_than_empty(monkeypatch):
    """None is the signal "write nothing". An empty dict would read as "no
    player has a team", and the writer would blank the league."""
    def boom(*a, **k):
        raise RuntimeError("statsapi down")

    monkeypatch.setattr(msc.httpx, "get", boom)
    assert fetch_roster_statuses_bulk([1, 2, 3]) is None


def test_a_partial_outage_returns_what_it_got(monkeypatch):
    state = {"n": 0}

    def flaky(url, params=None, **k):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("one batch failed")
        ids = params["personIds"].split(",")
        return FakeResp([person(int(i)) for i in ids])

    monkeypatch.setattr(msc.httpx, "get", flaky)
    out = fetch_roster_statuses_bulk(list(range(1, 151)))
    assert out is not None and len(out) == 50


def test_a_player_the_api_omits_is_absent_rather_than_blank(monkeypatch):
    monkeypatch.setattr(msc.httpx, "get",
                        lambda url, params=None, **k: FakeResp([person(1)]))
    out = fetch_roster_statuses_bulk([1, 2])
    assert 1 in out and 2 not in out


# --- the writer ---------------------------------------------------------------

class FakeTable:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def execute(self):
        return type("R", (), {"data": self.rows})()


def test_an_outage_writes_nothing(monkeypatch):
    """Same rule as the stat fetches: never persist an outage. A blanked
    mlb_team would then feed the trade prompts as fact."""
    writes = []
    monkeypatch.setattr(pr, "get_supabase",
                        lambda: type("SB", (), {"table": lambda s, n: FakeTable(
                            [{"fantrax_id": "a", "mlb_id": 1}])})())
    monkeypatch.setattr(pr, "fetch_roster_statuses_bulk", lambda ids: None)
    monkeypatch.setattr(pr, "_update_id_map", lambda *a, **k: writes.append(a))
    pr.refresh_roster_statuses(["a"])
    assert writes == []


def test_a_player_missing_from_the_response_is_not_overwritten(monkeypatch):
    writes = []
    rows = [{"fantrax_id": "a", "mlb_id": 1}, {"fantrax_id": "b", "mlb_id": 2}]
    monkeypatch.setattr(pr, "get_supabase",
                        lambda: type("SB", (), {"table": lambda s, n: FakeTable(rows)})())
    monkeypatch.setattr(pr, "fetch_roster_statuses_bulk", lambda ids: {
        1: {"roster_status": "Active", "il_type": None,
            "mlb_team": "New York Mets", "age": 28}
    })
    monkeypatch.setattr(pr, "_update_id_map",
                        lambda sb, fid, update: writes.append((fid, update)))
    pr.refresh_roster_statuses(["a", "b"])
    assert [w[0] for w in writes] == ["a"]
    assert writes[0][1]["mlb_team"] == "New York Mets"


def test_a_blank_team_or_age_does_not_clobber_a_known_one(monkeypatch):
    """The MLB API returns no team for some minor-league entries; that's a hole,
    not a release."""
    writes = []
    monkeypatch.setattr(pr, "get_supabase",
                        lambda: type("SB", (), {"table": lambda s, n: FakeTable(
                            [{"fantrax_id": "a", "mlb_id": 1}])})())
    monkeypatch.setattr(pr, "fetch_roster_statuses_bulk", lambda ids: {
        1: {"roster_status": "Active", "il_type": None, "mlb_team": None, "age": None}
    })
    monkeypatch.setattr(pr, "_update_id_map",
                        lambda sb, fid, update: writes.append(update))
    pr.refresh_roster_statuses(["a"])
    assert "mlb_team" not in writes[0] and "age" not in writes[0]
    assert writes[0]["roster_status"] == "Active"


def test_the_refresh_uses_the_bulk_endpoint():
    """A regression to one-request-per-player would be invisible except in the
    MLB API's logs and the sync's wall time."""
    import inspect

    src = inspect.getsource(pr.refresh_roster_statuses)
    assert "fetch_roster_statuses_bulk" in src
    assert "fetch_roster_status(" not in src
