"""Read-time refresh of *who owns what* (engine/nfl_rosters.py).

`tests/test_roster_freshness.py` covers the other half — what's true of a player.
This one covers league state: a drop, an add, a taxi move or a traded pick since
the last sync used to leave the app showing the old roster, because the stored
row only changes when the owner presses sync.

The interesting cases are all failure cases. Refreshing is easy; refreshing
without ever blanking a league when Sleeper is down, or silently reassigning
everyone's draft capital because we guessed the season wrong, is the part worth
pinning.
"""
from engine import nfl_rosters
from engine.sleeper_sync import carry_forward_gaps, infer_league_season


# --- fakes --------------------------------------------------------------------

class FakeQuery:
    def __init__(self, data):
        self._data = data

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def single(self):
        return self

    def execute(self):
        return type("R", (), {"data": self._data})()


class FakeSB:
    def __init__(self, rosters, league):
        self._rosters, self._league = rosters, league

    def table(self, name):
        return FakeQuery(self._rosters if name == "rosters" else self._league)


PLAYERS = {
    "1": {"full_name": "Kept Player", "position": "RB", "team": "KC", "age": 25,
          "years_exp": 3, "injury_status": None},
    "2": {"full_name": "Added Player", "position": "WR", "team": "BUF", "age": 24,
          "years_exp": 2, "injury_status": None},
    "3": {"full_name": "Dropped Player", "position": "TE", "team": "NYJ", "age": 30,
          "years_exp": 8, "injury_status": None},
}

STORED = [{
    "fantrax_team_id": "1",
    "team_name": "My Team",
    # Synced when the roster was players 1 and 3.
    "roster_items": [
        {"id": "1", "name": "Kept Player", "position": "RB", "team": "KC",
         "status": "starter", "injury_status": None, "age": 25, "years_exp": 3},
        {"id": "3", "name": "Dropped Player", "position": "TE", "team": "NYJ",
         "status": "bench", "injury_status": None, "age": 30, "years_exp": 8},
    ],
    "draft_picks": [{"season": 2027, "round": 1, "label": "2027 1st",
                     "original_roster_id": 1}],
}]

LEAGUE = {"sleeper_league_id": "L1",
          "rules": {"league_size": 2, "draft_rounds": 1, "season": 2026}}

# Live: player 3 was dropped, player 2 was added.
LIVE = [{"roster_id": 1, "players": ["1", "2"], "starters": ["1"],
         "taxi": [], "reserve": []}]


def run(monkeypatch, *, live=LIVE, players=PLAYERS, traded=(), stored=None,
        league=None, team_ids=None):
    monkeypatch.setattr(nfl_rosters, "get_players", lambda: players)
    monkeypatch.setattr(nfl_rosters, "get_rosters_cached", lambda lid: live)
    monkeypatch.setattr(nfl_rosters, "get_traded_picks_cached",
                        lambda lid: list(traded) if traded is not None else None)
    sb = FakeSB(stored if stored is not None else STORED,
                league if league is not None else LEAGUE)
    return nfl_rosters.load_rosters(sb, "lg", team_ids)


def ids(rows, i=0):
    return sorted(it["id"] for it in rows[i]["roster_items"])


# --- the reported gap ---------------------------------------------------------

def test_a_player_dropped_since_the_last_sync_is_gone(monkeypatch):
    assert "3" not in ids(run(monkeypatch))


def test_a_player_added_since_the_last_sync_is_there(monkeypatch):
    rows = run(monkeypatch)
    assert ids(rows) == ["1", "2"]
    added = next(it for it in rows[0]["roster_items"] if it["id"] == "2")
    assert added["name"] == "Added Player" and added["team"] == "BUF"


def test_starters_and_taxi_come_from_the_live_roster(monkeypatch):
    live = [{"roster_id": 1, "players": ["1", "2"], "starters": ["2"],
             "taxi": ["1"], "reserve": []}]
    by_id = {it["id"]: it for it in run(monkeypatch, live=live)[0]["roster_items"]}
    assert by_id["2"]["status"] == "starter"
    assert by_id["1"]["status"] == "taxi"


def test_metadata_is_current_on_the_rebuilt_roster(monkeypatch):
    """The rebuild reads the dump, so #138's fix holds through this path too."""
    players = {**PLAYERS, "1": {**PLAYERS["1"], "team": "WAS",
                                "injury_status": "Questionable"}}
    kept = next(it for it in run(monkeypatch, players=players)[0]["roster_items"]
                if it["id"] == "1")
    assert kept["team"] == "WAS"
    assert kept["injury_status"] == "Questionable"


# --- never blank a league -----------------------------------------------------

def test_sleeper_unreachable_keeps_the_synced_roster(monkeypatch):
    """Stale membership beats no membership. The metadata overlay still runs."""
    rows = run(monkeypatch, live=None)
    assert ids(rows) == ["1", "3"]


def test_an_empty_live_roster_is_ignored(monkeypatch):
    """A team Sleeper returns with no players is a bad response, not a team that
    cut everyone."""
    live = [{"roster_id": 1, "players": [], "starters": [], "taxi": [], "reserve": []}]
    assert ids(run(monkeypatch, live=live)) == ["1", "3"]


def test_a_team_missing_from_the_live_response_keeps_its_roster(monkeypatch):
    live = [{"roster_id": 99, "players": ["2"], "starters": ["2"]}]
    assert ids(run(monkeypatch, live=live)) == ["1", "3"]


def test_no_players_dump_means_no_rebuild(monkeypatch):
    """Rebuilding without the dump would name everyone by their Sleeper id."""
    assert ids(run(monkeypatch, players={})) == ["1", "3"]


def test_a_league_with_no_sleeper_id_still_gets_metadata(monkeypatch):
    league = {"sleeper_league_id": None, "rules": {}}
    rows = run(monkeypatch, league=league)
    assert ids(rows) == ["1", "3"]  # membership untouched
    assert all(it.get("team") for it in rows[0]["roster_items"])


def test_an_age_the_dump_has_lost_survives_the_rebuild(monkeypatch):
    """`build_roster_items` takes every field from the dump, so without
    carry-forward a player the dump has no age for would lose the age we had."""
    players = {**PLAYERS, "1": {**PLAYERS["1"], "age": None, "years_exp": None}}
    kept = next(it for it in run(monkeypatch, players=players)[0]["roster_items"]
                if it["id"] == "1")
    assert kept["age"] == 25 and kept["years_exp"] == 3


# --- picks --------------------------------------------------------------------

def test_a_traded_pick_moves_to_its_new_owner(monkeypatch):
    stored = STORED + [{"fantrax_team_id": "2", "team_name": "Them",
                        "roster_items": [], "draft_picks": []}]
    live = LIVE + [{"roster_id": 2, "players": ["3"], "starters": ["3"]}]
    traded = [{"season": "2027", "round": 1, "roster_id": 1, "owner_id": 2}]
    rows = run(monkeypatch, stored=stored, live=live, traded=traded)
    by_team = {r["fantrax_team_id"]: {p["label"] for p in r["draft_picks"]}
               for r in rows}
    # Inventory covers the next three classes; only the traded one moves.
    assert "2027 1st" not in by_team["1"]
    assert by_team["1"] == {"2028 1st", "2029 1st"}
    assert "2027 1st" in by_team["2"]


def test_unreachable_traded_picks_keep_the_stored_inventory(monkeypatch):
    rows = run(monkeypatch, traded=None)
    assert rows[0]["draft_picks"] == STORED[0]["draft_picks"]


def test_an_unknowable_season_keeps_the_stored_inventory(monkeypatch):
    """Guessing the year would reassign everyone's draft capital to the wrong
    classes — strictly worse than being a sync behind."""
    league = {"sleeper_league_id": "L1", "rules": {"league_size": 2, "draft_rounds": 1}}
    stored = [{**STORED[0], "draft_picks": []}]  # nothing to infer the season from
    rows = run(monkeypatch, league=league, stored=stored)
    assert rows[0]["draft_picks"] == []


def test_season_is_inferred_from_stored_picks_when_rules_predate_it():
    """Leagues synced before `season` was recorded still refresh picks: the
    stored classes are season+1..+3, so the earliest is season+1."""
    rows = [{"draft_picks": [{"season": 2028}, {"season": 2027}, {"season": 2029}]}]
    assert infer_league_season({}, rows) == 2026
    assert infer_league_season({"season": 2026}, []) == 2026
    assert infer_league_season({}, [{"draft_picks": []}]) is None


# --- scoping ------------------------------------------------------------------

def test_team_ids_narrows_the_result_but_not_the_pick_math(monkeypatch):
    """Pick ownership is league-wide, so the whole league is read even when the
    caller wants two teams — otherwise a pick traded away looks untraded."""
    stored = STORED + [{"fantrax_team_id": "2", "team_name": "Them",
                        "roster_items": [], "draft_picks": []}]
    live = LIVE + [{"roster_id": 2, "players": ["3"], "starters": ["3"]}]
    traded = [{"season": "2027", "round": 1, "roster_id": 1, "owner_id": 2}]
    rows = run(monkeypatch, stored=stored, live=live, traded=traded, team_ids=["1"])
    assert [r["fantrax_team_id"] for r in rows] == ["1"]
    assert "2027 1st" not in {p["label"] for p in rows[0]["draft_picks"]}


def test_rows_are_not_mutated_in_place(monkeypatch):
    stored = [dict(STORED[0])]
    original = list(stored[0]["roster_items"])
    run(monkeypatch, stored=stored)
    assert stored[0]["roster_items"] == original


# --- carry_forward_gaps, directly ---------------------------------------------

def test_carry_forward_leaves_authoritative_fields_alone():
    """team and injury_status must NOT be carried forward — a cleared value there
    is the news (#138)."""
    new = [{"id": "1", "team": "", "injury_status": None, "age": None}]
    old = [{"id": "1", "team": "TB", "injury_status": "Out", "age": 25}]
    (out,) = carry_forward_gaps(new, old)
    assert out["team"] == "" and out["injury_status"] is None
    assert out["age"] == 25


def test_picks_are_not_refreshed_when_sleeper_cannot_confirm_the_league(monkeypatch):
    """A wrong or stale sleeper_league_id returns 200/null for traded picks,
    which reads as "nobody traded a pick" and would hand every team back its
    default inventory. Only trust that answer for a league whose rosters Sleeper
    just confirmed."""
    rows = run(monkeypatch, live=None, traded=[])
    assert rows[0]["draft_picks"] == STORED[0]["draft_picks"]
