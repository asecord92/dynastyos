"""Unit tests for engine/nfl_trade.py valuation — the numbers that decide
whether the AI thinks a football trade is balanced."""

from engine.nfl_trade import (
    _detect_weak_position,
    _fmt_asset,
    _fmt_val,
    _pick_assets,
    _value_players,
)


def fc_entry(sleeper_id, value, position="WR", name="Player", overall=10):
    return {
        "player": {"sleeperId": sleeper_id, "position": position, "name": name},
        "value": value,
        "overallRank": overall,
        "positionRank": 1,
        "trend30Day": 0,
    }


def item(pid, position="WR", name=None, age=25):
    return {"id": pid, "name": name or f"P{pid}", "position": position,
            "team": "KC", "age": age, "status": "starter"}


STATS_KEY = "pts_ppr"


def stats_for(**by_id):
    return {pid: {STATS_KEY: pts, "gp": 17, "pos_rank_ppr": 1}
            for pid, pts in by_id.items()}


# --- the bug this module exists to prevent ---------------------------------

def test_top_rb_is_not_equal_to_a_mid_wr():
    """Regression: `value` was a points percentile WITHIN a position, so the best
    WR in a pool and the best RB in a pool both scored 100 and the AI proposed
    straight swaps like Olave-for-Bijan. Market value must keep them far apart
    even when the WR outscores nobody but his own positional group."""
    players = [item("olave", "WR", "Chris Olave"), item("bijan", "RB", "Bijan Robinson")]
    fc_players = {
        "olave": fc_entry("olave", 3898, "WR", "Chris Olave", overall=47),
        "bijan": fc_entry("bijan", 10191, "RB", "Bijan Robinson", overall=2),
    }
    # Olave is the only WR in the pool — under the old percentile logic that
    # alone made him a 100, level with the best RB.
    _value_players(players, stats_for(olave=210.4, bijan=320.5), STATS_KEY, fc_players)
    olave, bijan = players
    assert olave["value"] == 3898 and bijan["value"] == 10191
    assert bijan["value"] > olave["value"] * 2
    # And the market rank travels through, so the prompt can show "#2 overall".
    assert bijan["market_rank"] == 2


def test_value_is_independent_of_pool_composition():
    """Absolute values, not pool-relative: the same player must price the same
    whether he's alone or surrounded by superstars."""
    fc_players = {
        "a": fc_entry("a", 4000), "b": fc_entry("b", 9000), "c": fc_entry("c", 8000),
    }
    alone = [item("a")]
    crowded = [item("a"), item("b"), item("c")]
    _value_players(alone, {}, STATS_KEY, fc_players)
    _value_players(crowded, {}, STATS_KEY, fc_players)
    assert alone[0]["value"] == crowded[0]["value"] == 4000


# --- production stays, as description --------------------------------------

def test_production_still_attached():
    players = [item("a")]
    _value_players(players, stats_for(a=210.4), STATS_KEY, {"a": fc_entry("a", 4000)})
    p = players[0]
    assert p["points"] == 210.4 and p["gp"] == 17 and p["ppg"] == 12.4
    assert p["pos_rank"] == 1


def test_unpriced_player_is_none_not_zero():
    """An unpriced deep-bench player is unknown, not worthless — coercing to 0
    would let the model treat him as a free throw-in."""
    players = [item("ghost")]
    _value_players(players, stats_for(ghost=12.0), STATS_KEY, {})
    assert players[0]["value"] is None
    assert players[0]["points"] == 12.0  # production still known


# --- picks on the same scale -----------------------------------------------

def test_picks_priced_on_the_player_scale():
    fc_picks = {"2027 1st": {"value": 2909}, "2028 2nd": {"value": 1275}}
    picks = _pick_assets(
        [
            {"season": 2027, "round": 1, "label": "2027 1st", "original_roster_id": 4},
            {"season": 2028, "round": 2, "label": "2028 2nd", "original_roster_id": 4},
            {"season": 2029, "round": 1, "label": "2029 1st", "original_roster_id": 4},
        ],
        fc_picks,
    )
    assert [p["value"] for p in picks] == [2909, 1275, None]
    assert picks[0]["id"] == "pick:2027:1:4" and picks[0]["is_pick"] is True


def test_pick_assets_skips_malformed_rows():
    assert _pick_assets([{"label": "nonsense"}, None or {}], {}) == []


# --- rendering --------------------------------------------------------------

def test_unpriced_renders_as_words_not_none():
    assert _fmt_val(None) == "unpriced"
    assert _fmt_val(10191) == "10,191"
    line = _fmt_asset({"name": "Ghost", "position": "WR", "team": "KC", "value": None})
    assert "unpriced" in line and "None" not in line


def test_asset_line_shows_market_rank():
    line = _fmt_asset({"name": "Bijan Robinson", "position": "RB", "team": "ATL",
                       "age": 24, "value": 10191, "market_rank": 2, "points": 320.5,
                       "gp": 17, "ppg": 18.9, "pos_rank": 1})
    assert "value 10,191" in line and "#2 overall" in line


# --- weak-position detection ------------------------------------------------

def test_weak_position_uses_value_not_points():
    """My RBs are cheap relative to the league even though they scored fine —
    the dynasty hole is RB."""
    me = [dict(item("a", "WR"), value=9000), dict(item("b", "RB"), value=500)]
    rival = [dict(item("c", "WR"), value=1000), dict(item("d", "RB"), value=9000)]
    by_team = {"1": me, "2": rival}
    assert _detect_weak_position(me, by_team) == "RB"


def test_weak_position_defaults_without_values():
    by_team = {"1": [item("a", "WR")], "2": [item("b", "RB")]}
    assert _detect_weak_position(by_team["1"], by_team) in ("QB", "RB", "WR", "TE")
