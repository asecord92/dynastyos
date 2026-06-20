"""Read-only client for Sleeper's public API (no auth key required).

The large public dumps (the ~5MB players metadata and per-season stats) are
cached in-process for a day, so per-request handlers never re-download them.
"""
import time

import httpx

SLEEPER_BASE = "https://api.sleeper.app/v1"

_DUMP_TTL = 24 * 3600  # seconds
_players_cache: dict = {"data": None, "ts": 0.0}
_stats_cache: dict[str, dict] = {}  # season -> {"data": ..., "ts": ...}


def _get(url: str, timeout: float = 30) -> dict | list:
    resp = httpx.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def get_user(username: str) -> dict:
    """Resolve a username (or user_id) to the user object, incl. user_id."""
    return _get(f"{SLEEPER_BASE}/user/{username}")


def get_user_leagues(user_id: str, season: str | int) -> list:
    """The user's NFL leagues for a season."""
    return _get(f"{SLEEPER_BASE}/user/{user_id}/leagues/nfl/{season}") or []


def get_league(league_id: str) -> dict:
    """League detail: settings, scoring_settings, roster_positions, total_rosters."""
    return _get(f"{SLEEPER_BASE}/league/{league_id}")


def get_rosters(league_id: str) -> list:
    """Per-team rosters: roster_id, owner_id, players[], starters[], settings."""
    return _get(f"{SLEEPER_BASE}/league/{league_id}/rosters") or []


def get_users(league_id: str) -> list:
    """League members: user_id -> display_name, metadata.team_name."""
    return _get(f"{SLEEPER_BASE}/league/{league_id}/users") or []


def get_traded_picks(league_id: str) -> list:
    """Traded draft picks: {round, season, roster_id (original), owner_id (current)}."""
    return _get(f"{SLEEPER_BASE}/league/{league_id}/traded_picks") or []


def get_players() -> dict:
    """Full NFL player dump (player_id -> metadata). ~5MB; cached a day in-process.
    A transient empty/invalid response is never cached, so a bad fetch can't
    poison the 24h window."""
    now = time.time()
    if _players_cache["data"] is not None and now - _players_cache["ts"] <= _DUMP_TTL:
        return _players_cache["data"]
    data = _get(f"{SLEEPER_BASE}/players/nfl", timeout=60)
    if isinstance(data, dict) and data:
        _players_cache["data"] = data
        _players_cache["ts"] = now
        return data
    return _players_cache["data"] or {}


def get_season_stats(season: str | int) -> dict:
    """Per-player regular-season fantasy stats for a season (player_id -> stats incl.
    pts_half_ppr / pts_ppr / pts_std and pos_rank_*). Cached a day in-process; an
    empty/invalid response is never cached."""
    season = str(season)
    hit = _stats_cache.get(season)
    now = time.time()
    if hit and now - hit["ts"] <= _DUMP_TTL:
        return hit["data"]
    data = _get(f"{SLEEPER_BASE}/stats/nfl/regular/{season}", timeout=40)
    if isinstance(data, dict) and data:
        _stats_cache[season] = {"data": data, "ts": now}
        return data
    return (hit or {}).get("data", {})
