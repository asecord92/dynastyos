import json
import os
import time
from typing import Any

import httpx

FANTRAX_BASE = "https://www.fantrax.com/fxea/general"
PLAYER_ID_CACHE_PATH = ".fantrax_player_id_cache.json"
PLAYER_ID_CACHE_TTL = 60 * 60 * 24  # 24 hours


def get_leagues(user_secret_id: str) -> list[dict]:
    """
    Returns the list of leagues for a user, including leagueId, teamId, and sport.
    """
    url = f"{FANTRAX_BASE}/getLeagues"
    resp = httpx.get(url, params={"userSecretId": user_secret_id}, timeout=10)
    resp.raise_for_status()
    return resp.json().get("leagues", [])


def get_team_rosters(league_id: str) -> dict[str, Any]:
    """
    Returns all team rosters for a league keyed by teamId.
    Each value has teamName, rosterItems, and salaryCap.
    """
    url = f"{FANTRAX_BASE}/getTeamRosters"
    resp = httpx.get(url, params={"leagueId": league_id}, timeout=10)
    resp.raise_for_status()
    return resp.json().get("rosters", {})


def get_player_ids(sport: str) -> dict[str, str]:
    """
    Returns a dict mapping Fantrax player ID -> player name for the given sport.
    Results are cached to disk for 24 hours.
    """
    # Return from cache if still valid
    if os.path.exists(PLAYER_ID_CACHE_PATH):
        with open(PLAYER_ID_CACHE_PATH, "r") as f:
            cache = json.load(f)
        if (
            cache.get("sport") == sport
            and time.time() - cache.get("fetched_at", 0) < PLAYER_ID_CACHE_TTL
        ):
            return cache["players"]

    # Fetch fresh
    url = f"{FANTRAX_BASE}/getPlayerIds"
    resp = httpx.get(url, params={"sport": sport}, timeout=30)
    resp.raise_for_status()
    raw = resp.json()

    # Response is { playerId: { name, team, position, ... }, ... }
    players = {
    pid: {"name": info.get("name", ""), "team": info.get("team", "")}
    for pid, info in raw.items()
}

    # Write cache
    with open(PLAYER_ID_CACHE_PATH, "w") as f:
        json.dump({"sport": sport, "fetched_at": time.time(), "players": players}, f)

    return players