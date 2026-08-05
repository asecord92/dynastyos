"""Unit tests for engine/trade_values.py — the pure pricing behind
POST /dashboard/trade_values.

Two behaviors carry most of the risk. First the name join: the value feed
exposes no MLB id, so players are matched on a normalized name and only
disambiguated by age — a wrong match silently misprices a trade. Second the
unpriced case: an asset we can't value must stay None, never 0, or a package
total quietly understates one side and the UI shows a confident verdict over a
number it shouldn't trust.
"""

from engine.trade_values import (
    build_values_payload,
    index_mlb_values,
    match_mlb,
    normalize_name,
    pick_key,
)


def hkb(name, value, age=25.0, rank=1, prospect=False, asset_type="PLAYER"):
    return {
        "id": name.lower().replace(" ", "-"), "name": name, "value": value,
        "rank": rank, "age": age, "prospect": prospect, "assetType": asset_type,
        "valueChange30Days": 12,
    }


def fc_player(sleeper_id, value, name="Player", age=25):
    return {
        "player": {"sleeperId": sleeper_id, "position": "WR", "name": name, "maybeAge": age},
        "value": value, "overallRank": 7, "positionRank": 3, "trend30Day": -4,
    }


def fc_pick(label, value):
    return {"player": {"position": "PICK", "name": label}, "value": value, "trend30Day": 0}


def roster(team_id, item_ids, picks=None):
    return {
        "fantrax_team_id": team_id,
        "roster_items": [{"id": i} for i in item_ids],
        "draft_picks": picks or [],
    }


def id_row(fantrax_id, full_name, age=25):
    return {"fantrax_id": fantrax_id, "full_name": full_name, "age": age}


# --- normalize_name ---------------------------------------------------------

def test_normalization_survives_accents_suffixes_and_case():
    assert normalize_name("Ronald Acuña Jr.") == "ronald acuna jr"
    assert normalize_name("Ronald Acuna Jr") == "ronald acuna jr"
    assert normalize_name("  JULIO   RODRÍGUEZ ") == "julio rodriguez"
    assert normalize_name("Michael Harris II") == "michael harris ii"


def test_normalization_of_empty_input_is_empty():
    assert normalize_name(None) == ""
    assert normalize_name("") == ""


# --- index / match ----------------------------------------------------------

def test_matches_across_an_accent_difference():
    index = index_mlb_values([hkb("Ronald Acuña Jr.", 6000, age=28.6)])
    assert match_mlb("Ronald Acuna Jr.", 28, index)["value"] == 6000


def test_picks_are_excluded_from_the_name_index():
    """This league drafts by auction — a pick is never a tradeable asset."""
    assert index_mlb_values([hkb("2027 Early 1st", 1437, asset_type="PICK")]) == {}


def test_duplicate_names_resolve_by_age():
    # The real feed carries ~3 of these (max muncy, fernando cruz, wilmer flores).
    index = index_mlb_values([hkb("Max Muncy", 1200, age=35.9), hkb("Max Muncy", 900, age=23.4)])
    assert match_mlb("Max Muncy", 36, index)["value"] == 1200
    assert match_mlb("Max Muncy", 23, index)["value"] == 900


def test_duplicate_names_without_an_age_decline_to_guess():
    index = index_mlb_values([hkb("Max Muncy", 1200, age=35.9), hkb("Max Muncy", 900, age=23.4)])
    assert match_mlb("Max Muncy", None, index) is None


def test_duplicate_names_of_similar_age_decline_to_guess():
    index = index_mlb_values([hkb("Fernando Cruz", 300, age=26.2), hkb("Fernando Cruz", 280, age=26.9)])
    assert match_mlb("Fernando Cruz", 26, index) is None


def test_unknown_player_is_unmatched():
    assert match_mlb("Nobody At All", 25, index_mlb_values([hkb("Shohei Ohtani", 10000)])) is None


def test_single_candidate_matches_even_with_no_age():
    index = index_mlb_values([hkb("Paul Skenes", 8000, age=24.1)])
    assert match_mlb("Paul Skenes", None, index)["value"] == 8000


# --- MLB payload ------------------------------------------------------------

def test_mlb_payload_prices_matched_players_and_counts_the_rest():
    rosters = [roster("t1", ["f1", "f2"]), roster("t2", ["f3"])]
    id_map = [
        id_row("f1", "Shohei Ohtani", 32),
        id_row("f2", "Bobby Witt Jr.", 26),
        id_row("f3", "Some Deep Minors Guy", 19),
    ]
    entries = [hkb("Shohei Ohtani", 10000, age=32.1), hkb("Bobby Witt Jr.", 9914, age=26.1, rank=2)]

    out = build_values_payload("MLB", rosters, id_map, entries, "2026-08-04T12:00:00Z")

    assert out["source"] == "HarryKnowsBall"
    assert out["available"] is True
    assert out["updated_at"] == "2026-08-04T12:00:00Z"
    assert out["values"]["f1"]["value"] == 10000
    assert out["values"]["f2"]["rank"] == 2
    assert out["matched"] == 2
    assert out["unmatched"] == 1


def test_unpriced_assets_are_absent_rather_than_zero():
    """A 0 would make a real player look worthless and skew a package total."""
    out = build_values_payload("MLB", [roster("t1", ["f1"])], [id_row("f1", "Unknown Guy")], [hkb("Other", 500)], None)
    assert "f1" not in out["values"]
    assert out["values"] == {}
    assert out["unmatched"] == 1


def test_player_missing_from_the_id_map_is_unmatched_not_a_crash():
    out = build_values_payload("MLB", [roster("t1", ["f1"])], [], [hkb("Shohei Ohtani", 10000)], None)
    assert out["matched"] == 0 and out["unmatched"] == 1


def test_feed_outage_prices_nothing_and_says_so():
    out = build_values_payload("MLB", [roster("t1", ["f1", "f2"])], [id_row("f1", "A")], None, None)
    assert out["available"] is False
    assert out["values"] == {}
    assert out["unmatched"] == 2


def test_prospect_and_trend_ride_along():
    entries = [hkb("Konnor Griffin", 5000, age=20.1, prospect=True)]
    out = build_values_payload("MLB", [roster("t1", ["f1"])], [id_row("f1", "Konnor Griffin", 20)], entries, None)
    assert out["values"]["f1"]["prospect"] is True
    assert out["values"]["f1"]["trend"] == 12


# --- NFL payload ------------------------------------------------------------

def test_nfl_payload_prices_players_by_sleeper_id_and_picks_by_label():
    picks = [{"season": 2027, "round": 1, "original_roster_id": 4, "label": "2027 1st"}]
    rosters = [roster("t1", ["4034", "9999"], picks)]
    entries = [fc_player("4034", 8000, name="Star WR"), fc_pick("2027 1st", 1500)]

    out = build_values_payload("NFL", rosters, [], entries, "2026-08-04T00:00:00Z")

    assert out["source"] == "FantasyCalc"
    assert out["values"]["4034"]["value"] == 8000
    assert out["values"]["4034"]["trend"] == -4
    assert out["values"]["pick:2027:1:4"]["value"] == 1500
    assert "9999" not in out["values"], "an unpriced player must not be invented"
    assert out["matched"] == 2
    assert out["unmatched"] == 1


def test_pick_key_matches_the_frontends_synthetic_id():
    """buildPlayerOptions in web/app/(app)/trade/page.tsx builds this exact
    string — if the two drift, every NFL pick silently shows as unpriced."""
    assert pick_key({"season": 2027, "round": 2, "original_roster_id": 11}) == "pick:2027:2:11"


def test_unmatched_pick_class_is_counted_not_priced():
    picks = [{"season": 2026, "round": 1, "original_roster_id": 3, "label": "2026 Pick 1.05"}]
    out = build_values_payload("NFL", [roster("t1", [], picks)], [], [fc_pick("2027 1st", 1500)], None)
    assert out["values"] == {}
    assert out["unmatched"] == 1


def test_sport_defaults_to_baseball():
    assert build_values_payload("", [], [], [], None)["source"] == "HarryKnowsBall"


# --- the same values, handed to the paid analysis ---------------------------

def test_market_block_totals_each_side_and_labels_unpriced_players():
    """The AI escalation must see the same numbers the free check showed, and
    must not read a partial total as a whole one."""
    from engine.trade_analyzer import _market_value_block

    id_map = {"a": {"name": "Shohei Ohtani"}, "b": {"name": "Paul Skenes"},
              "c": {"name": "Deep Minors Guy"}}
    values = {
        "a": {"value": 10000, "rank": 1, "valueChange30Days": 0},
        "b": {"value": 7500, "rank": 9, "valueChange30Days": -250},
    }

    block = _market_value_block(values, id_map, ["a"], ["b", "c"])

    assert "Shohei Ohtani: 10000 (overall #1)" in block
    assert "Paul Skenes: 7500 (overall #9, -250 over 30d)" in block
    assert "Total: 10000" in block and "Total: 7500" in block
    assert "Deep Minors Guy" in block and "exclude them" in block


def test_market_block_is_omitted_when_the_feed_is_down():
    from engine.trade_analyzer import _market_value_block

    assert _market_value_block({}, {"a": {"name": "X"}}, ["a"], ["b"]) == ""
