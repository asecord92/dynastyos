"""NFL roster metadata is re-read from the players dump on every read.

`build_roster_items` embeds NFL-world facts (team, injury, age) into the stored
roster row so the frontend needs no NFL map. Those facts change on the NFL's
schedule; the row they live in only changes when the owner runs a sync. The gap
between the two is how the app came to show Rachaad White on Tampa Bay weeks
after Washington signed him — and, worse, how the AI widgets came to web-search
the wrong depth chart and report back confidently.

`refresh_item_meta` closes the gap by treating the snapshot as a fallback. The
tests that matter here are the failure modes: it must never empty a roster when
the dump is unavailable, and it must distinguish "the dump says this player has
no team now" (news) from "the dump has no age for this player" (a hole).
"""
import inspect

from engine.sleeper_sync import (
    build_roster_items,
    refresh_item_meta,
    refresh_roster_rows,
)


def synced_item(**over):
    """A roster item as `build_roster_items` froze it at sync time."""
    item = {
        "id": "8136",
        "name": "Rachaad White",
        "position": "RB",
        "team": "TB",
        "status": "starter",
        "injury_status": None,
        "age": 26,
        "years_exp": 3,
    }
    item.update(over)
    return item


def dump(**over):
    meta = {
        "full_name": "Rachaad White",
        "position": "RB",
        "team": "WAS",
        "injury_status": None,
        "age": 27,
        "years_exp": 4,
    }
    meta.update(over)
    return {"8136": meta}


# --- the reported bug ---------------------------------------------------------

def test_traded_player_shows_his_current_team():
    (item,) = refresh_item_meta([synced_item()], dump())
    assert item["team"] == "WAS"


def test_league_wide_refresh_covers_every_row():
    rows = [
        {"fantrax_team_id": "1", "roster_items": [synced_item()]},
        {"fantrax_team_id": "2", "roster_items": [synced_item(id="9999")]},
    ]
    out = refresh_roster_rows(rows, dump())
    assert out[0]["roster_items"][0]["team"] == "WAS"
    # Unknown to the dump — left exactly as synced, not blanked.
    assert out[1]["roster_items"][0]["team"] == "TB"
    # Callers hold onto the original rows; refreshing must not mutate them.
    assert rows[0]["roster_items"][0]["team"] == "TB"


# --- absence as news vs absence as a hole -------------------------------------

def test_a_healed_player_loses_his_injury_status():
    """injury_status is authoritative: no entry in the dump means healthy now,
    not "keep yesterday's Questionable"."""
    (item,) = refresh_item_meta(
        [synced_item(injury_status="Questionable")], dump(injury_status=None)
    )
    assert item["injury_status"] is None


def test_a_cut_player_loses_his_team_rather_than_keeping_the_old_one():
    (item,) = refresh_item_meta([synced_item()], dump(team=None))
    assert item["team"] == ""


def test_a_missing_age_in_the_dump_does_not_wipe_the_synced_age():
    """Sleeper ages and experience go missing routinely (nfl_dynasty carries a
    maybeAge backfill for exactly this). A hole is not a fact."""
    (item,) = refresh_item_meta([synced_item()], dump(age=None, years_exp=None))
    assert item["age"] == 26
    assert item["years_exp"] == 3


def test_a_missing_name_or_position_does_not_blank_the_row():
    (item,) = refresh_item_meta(
        [synced_item()], dump(full_name="", position=None)
    )
    assert item["name"] == "Rachaad White"
    assert item["position"] == "RB"


# --- never make things worse than stale ---------------------------------------

def test_an_unavailable_dump_serves_the_synced_snapshot():
    """Stale beats empty: a Sleeper outage must not blank every roster in the
    app. Same stale-if-error shape as fantasycalc / mlb_market_values."""
    items = [synced_item()]
    assert refresh_item_meta(items, {}) == items
    assert refresh_item_meta(items, None) is not None
    rows = [{"fantrax_team_id": "1", "roster_items": items}]
    assert refresh_roster_rows(rows, {}) == rows


def test_empty_and_missing_rosters_are_handled():
    assert refresh_item_meta(None, dump()) == []
    assert refresh_item_meta([], dump()) == []
    assert refresh_roster_rows(None, dump()) == []


# --- league facts are not the dump's to change --------------------------------

def test_fantasy_league_fields_are_never_touched():
    """`id` and `status` (starter/bench/taxi/ir) come from the fantasy league.
    The NFL players dump has no opinion on them and must not overwrite them —
    only a sync can tell us a player moved to the taxi squad."""
    (item,) = refresh_item_meta(
        [synced_item(status="taxi")],
        {"8136": {**dump()["8136"], "status": "Active", "id": "nonsense"}},
    )
    assert item["status"] == "taxi"
    assert item["id"] == "8136"


def test_refresh_covers_every_field_build_roster_items_embeds():
    """If a new embedded field is added to `build_roster_items`, it must also be
    classified here — otherwise it silently joins the set of fields that go
    stale between syncs, which is the whole bug."""
    from engine.sleeper_sync import _AUTHORITATIVE_FIELDS, _BEST_EFFORT_FIELDS

    (embedded,) = build_roster_items(["8136"], ["8136"], dump())
    league_owned = {"id", "status"}  # set by the league, not the dump
    covered = set(_AUTHORITATIVE_FIELDS) | set(_BEST_EFFORT_FIELDS) | league_owned
    assert set(embedded) <= covered, set(embedded) - covered


# --- the read paths actually call it ------------------------------------------

def test_every_nfl_read_path_goes_through_the_loader():
    """The loader is only worth anything if the read boundaries use it. These are
    every place a synced NFL roster becomes something a user or the AI sees. A
    new read path that queries `rosters` directly is the way this bug comes
    back."""
    import api.main
    from engine import nfl_dashboard, nfl_trade, nfl_widgets

    assert "load_rosters" in inspect.getsource(nfl_widgets.my_roster)
    assert "load_rosters" in inspect.getsource(nfl_widgets.waiver_pool)
    assert "load_rosters" in inspect.getsource(nfl_trade._load_rosters)
    assert "load_rosters" in inspect.getsource(nfl_dashboard.build_nfl_dashboard)
    assert "load_nfl_rosters" in inspect.getsource(api.main.dashboard_nfl_roster)
    assert "load_nfl_rosters" in inspect.getsource(api.main.dashboard_trade_values)


def test_the_football_dashboard_stays_off_the_event_loop():
    """`build_nfl_dashboard` does blocking Supabase + Sleeper I/O (including the
    ~5MB players dump). It used to be declared `async` while awaiting nothing,
    so all of that ran on the loop. It must stay sync, and its caller must
    thread it."""
    import api.main
    from engine import nfl_dashboard

    assert not inspect.iscoroutinefunction(nfl_dashboard.build_nfl_dashboard)
    assert "to_thread(build_nfl_dashboard" in inspect.getsource(api.main.nfl_dashboard)
