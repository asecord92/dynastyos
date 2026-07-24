"""Unit tests for engine/nfl_dynasty.py — the pure dynasty logic behind
POST /dashboard/nfl_roster. First test suite in the repo (CLAUDE.md's
"pure logic first" target)."""

from engine.nfl_dynasty import (
    age_band,
    build_payload,
    depth_flags,
    derive_fc_params,
    index_fc,
    roster_window,
    starting_slots,
)


def fc_player(sleeper_id, value, position="WR", name="Player", age=25, **extra):
    return {
        "player": {
            "sleeperId": sleeper_id, "position": position, "name": name,
            "maybeAge": age,
        },
        "value": value,
        "overallRank": extra.get("overall_rank", 10),
        "positionRank": extra.get("pos_rank", 5),
        "maybeTier": extra.get("tier", 2),
        "trend30Day": extra.get("trend", 0),
    }


def fc_pick(name, value):
    return {"player": {"position": "PICK", "name": name}, "value": value, "trend30Day": 0}


def item(pid, position="WR", age=25, status="bench", years_exp=3, name=None):
    return {
        "id": pid, "name": name or f"P{pid}", "position": position, "team": "KC",
        "status": status, "injury_status": None, "age": age, "years_exp": years_exp,
    }


# --- age_band ---------------------------------------------------------------

def test_age_band_rb_edges():
    assert age_band("RB", 22) == "ascending"
    assert age_band("RB", 23) == "prime"
    assert age_band("RB", 25) == "prime"
    assert age_band("RB", 26) == "aging"
    assert age_band("RB", 27) == "aging"
    assert age_band("RB", 28) == "cliff"


def test_age_band_other_positions():
    assert age_band("WR", 24) == "prime"
    assert age_band("WR", 31) == "cliff"
    assert age_band("TE", 30) == "aging"
    assert age_band("QB", 32) == "prime"
    assert age_band("QB", 36) == "cliff"


def test_age_band_no_curve_or_age():
    assert age_band("K", 30) is None
    assert age_band("DEF", 5) is None
    assert age_band("RB", None) is None
    assert age_band(None, 25) is None


# --- derive_fc_params -------------------------------------------------------

def test_params_superflex_slot_counts_as_2qb():
    rules = {"roster_positions": ["QB", "SUPER_FLEX", "WR", "BN"], "ppr": 1,
             "league_size": 12}
    assert derive_fc_params(rules) == {"num_qbs": 2, "ppr": 1, "num_teams": 12}


def test_params_true_2qb_league_without_superflex_flag():
    rules = {"roster_positions": ["QB", "QB", "WR"], "superflex": False, "ppr": 0.5}
    assert derive_fc_params(rules)["num_qbs"] == 2


def test_params_ppr_snapping():
    assert derive_fc_params({"ppr": 0})["ppr"] == 0
    assert derive_fc_params({"ppr": 0.25})["ppr"] == 0.5
    assert derive_fc_params({"ppr": 0.5})["ppr"] == 0.5
    assert derive_fc_params({"ppr": 0.75})["ppr"] == 1
    assert derive_fc_params({"ppr": 1.5})["ppr"] == 1
    assert derive_fc_params({"ppr": None})["ppr"] == 0


def test_params_defaults():
    assert derive_fc_params({}) == {"num_qbs": 1, "ppr": 0, "num_teams": 10}


# --- starting_slots / depth_flags ------------------------------------------

def test_starting_slots_excludes_bench_taxi_ir():
    slots = starting_slots(["QB", "RB", "RB", "FLEX", "BN", "BN", "TAXI", "IR"])
    assert slots == ["QB", "RB", "RB", "FLEX"]


def test_depth_flag_superflex_one_qb():
    rules = {"roster_positions": ["QB", "SUPER_FLEX", "WR", "BN"], "superflex": True}
    players = [item("1", "QB"), item("2", "WR"), item("3", "WR")]
    flags = depth_flags(players, rules)
    assert any("Superflex" in f["text"] for f in flags)
    assert flags[0]["level"] == "critical"


def test_depth_flag_cannot_fill_dedicated_slots():
    rules = {"roster_positions": ["QB", "RB", "RB", "WR", "BN"]}
    players = [item("1", "QB"), item("2", "RB"), item("3", "WR"), item("4", "WR")]
    flags = depth_flags(players, rules)
    assert any(f["level"] == "critical" and "RB" in f["text"] for f in flags)


def test_depth_flags_ignore_taxi_and_ir():
    rules = {"roster_positions": ["QB", "RB", "BN"]}
    players = [
        item("1", "QB"), item("2", "RB"),
        item("3", "RB", status="taxi"), item("4", "RB", status="ir"),
    ]
    flags = depth_flags(players, rules)
    # Only 1 startable RB for 1 slot -> zero-depth warn, not critical
    assert any(f["level"] == "warn" and "RB" in f["text"] for f in flags)


def test_depth_flags_capped_at_three_and_sorted():
    rules = {"roster_positions": ["QB", "RB", "WR", "TE", "K", "DEF"]}
    flags = depth_flags([], rules)
    assert len(flags) == 3
    assert all(f["level"] == "critical" for f in flags)


def test_depth_flags_healthy_roster_is_quiet():
    rules = {"roster_positions": ["QB", "RB", "WR", "BN", "BN", "BN"]}
    players = [
        item("1", "QB"), item("2", "QB"),
        item("3", "RB"), item("4", "RB"),
        item("5", "WR"), item("6", "WR"),
    ]
    assert depth_flags(players, rules) == []


# --- roster_window ----------------------------------------------------------

def _windowed(players, picks=(), slots=("QB", "RB", "WR")):
    return roster_window(players, list(picks), {"roster_positions": list(slots)})


def test_window_young_core_is_ascending():
    players = [
        dict(item("1", "WR", 22), value=9000, band="ascending"),
        dict(item("2", "RB", 22), value=8000, band="ascending"),
        dict(item("3", "WR", 25), value=7000, band="prime"),
    ]
    assert _windowed(players)["verdict"] == "Ascending"


def test_window_old_core_is_aging():
    players = [
        dict(item("1", "RB", 29), value=6000, band="cliff"),
        dict(item("2", "WR", 31), value=6000, band="cliff"),
        dict(item("3", "TE", 30), value=4000, band="aging"),
    ]
    assert _windowed(players)["verdict"] == "Aging — sell high"


def test_window_prime_core_pick_capital_splits_winnow_vs_balanced():
    players = [
        dict(item("1", "WR", 26), value=8000, band="prime"),
        dict(item("2", "RB", 24), value=7000, band="prime"),
        dict(item("3", "QB", 28), value=7000, band="prime"),
    ]
    assert _windowed(players)["verdict"] == "Win-now"
    picks = [{"label": "2027 1st", "value": 6000}]
    assert _windowed(players, picks)["verdict"] == "Balanced"


def test_window_detail_is_plain_english():
    """The detail line is shown to the user verbatim — it must read as a
    sentence, not leak the internal 0-3 stage score."""
    players = [
        dict(item("1", "WR", 26), value=8000, band="prime"),
        dict(item("2", "RB", 24), value=7000, band="prime"),
    ]
    for picks in ([], [{"label": "2027 1st", "value": 6000}]):
        detail = _windowed(players, picks)["detail"]
        assert detail.endswith(".")
        assert "life-stage" not in detail and "/3" not in detail


def test_window_no_values_degrades():
    players = [dict(item("1", "WR"), value=None, band="prime")]
    out = _windowed(players)
    assert out["verdict"] is None


def test_window_core_limited_to_starting_slots():
    # Chaff (many low-value old players) must not drag the verdict when the
    # core (top-N = 2 slots here) is young.
    players = [
        dict(item("1", "WR", 22), value=9000, band="ascending"),
        dict(item("2", "RB", 22), value=8000, band="ascending"),
    ] + [
        dict(item(str(10 + i), "RB", 30), value=100, band="cliff") for i in range(10)
    ]
    out = roster_window(players, [], {"roster_positions": ["QB", "RB"]})
    assert out["verdict"] == "Ascending"


# --- index_fc / build_payload ----------------------------------------------

RULES = {"sport": "NFL", "roster_positions": ["QB", "RB", "WR", "BN"],
         "superflex": False, "ppr": 1, "league_size": 12}


def test_index_fc_splits_players_and_picks():
    entries = [fc_player("123", 5000), fc_pick("2027 1st", 4000)]
    players, picks = index_fc(entries)
    assert "123" in players and "2027 1st" in picks


def test_build_payload_joins_and_groups():
    roster = [
        item("123", "WR", 24, status="starter"),
        item("456", "RB", 28, status="bench"),
        item("789", "QB", 23, status="taxi", years_exp=0),
    ]
    picks = [
        {"season": 2027, "round": 1, "label": "2027 1st", "original_roster_id": 3},
        {"season": 2029, "round": 2, "label": "2029 2nd", "original_roster_id": 3},
    ]
    entries = [fc_player("123", 5000), fc_pick("2027 1st", 4000)]
    out = build_payload(roster, picks, RULES, entries)

    assert out["fc_available"] is True
    starter = out["players"]["starter"][0]
    assert starter["value"] == 5000 and starter["band"] == "prime"
    # Unknown to FantasyCalc -> renders with value None
    assert out["players"]["bench"][0]["value"] is None
    assert out["players"]["taxi"][0]["rookie_tag"] == "Rookie"
    # Pick join is best-effort: 2029 class not in FC -> unvalued but present
    assert [p["value"] for p in out["picks"]] == [4000, None]
    assert out["pick_capital"] == {"total": 4000, "valued": 1, "unvalued": 1}


def test_build_payload_age_backfill_from_fc():
    roster = [item("123", "WR", age=None, status="starter")]
    entries = [fc_player("123", 5000, age=27)]
    out = build_payload(roster, [], RULES, entries)
    starter = out["players"]["starter"][0]
    assert starter["age"] == 27 and starter["band"] == "prime"


def test_build_payload_fc_down_degrades():
    roster = [item("123", "WR", 24, status="starter")]
    out = build_payload(roster, [{"season": 2027, "round": 1, "label": "2027 1st"}],
                        RULES, None)
    assert out["fc_available"] is False
    assert out["players"]["starter"][0]["band"] == "prime"  # curve still works
    assert out["window"]["verdict"] is None
    assert out["pick_capital"]["total"] == 0


def test_build_payload_unknown_status_lands_in_bench():
    roster = [item("123", "WR", 24, status="weird")]
    out = build_payload(roster, [], RULES, [])
    assert out["players"]["bench"][0]["id"] == "123"
