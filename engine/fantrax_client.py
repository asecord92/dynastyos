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


def get_player_ids(sport: str) -> dict[str, dict]:
    """
    Returns a dict mapping Fantrax player ID -> {name, team} for the given sport.
    Results are cached to disk for 24 hours and synced to Supabase.
    """
    # Return from cache if still valid
    if os.path.exists(PLAYER_ID_CACHE_PATH):
        try:
            with open(PLAYER_ID_CACHE_PATH, "r") as f:
                cache = json.load(f)
            if (
                cache.get("sport") == sport
                and time.time() - cache.get("fetched_at", 0) < PLAYER_ID_CACHE_TTL
                and cache.get("players")
            ):
                return cache["players"]
        except Exception as e:
            print(f"[player_ids] Cache read failed: {e}")

    # Fetch fresh
    url = f"{FANTRAX_BASE}/getPlayerIds"
    resp = httpx.get(url, params={"sport": sport}, timeout=30)
    resp.raise_for_status()
    raw = resp.json()

    if not raw:
        raise RuntimeError(f"getPlayerIds returned empty response for sport={sport}")

    players = {
        pid: {"name": info.get("name", ""), "team": info.get("team", "")}
        for pid, info in raw.items()
        if isinstance(info, dict)
    }

    if not players:
        raise RuntimeError(f"getPlayerIds parsed to empty dict for sport={sport}")

    print(f"[player_ids] Fetched {len(players)} players for {sport}")

    # Write disk cache
    try:
        with open(PLAYER_ID_CACHE_PATH, "w") as f:
            json.dump({"sport": sport, "fetched_at": time.time(), "players": players}, f)
    except Exception as e:
        print(f"[player_ids] Cache write failed (non-fatal): {e}")

    # Sync to Supabase fantrax_players table
    try:
        from .supabase_client import get_supabase
        sb = get_supabase()
        upserts = [
            {"fantrax_id": pid, "name": data["name"], "sport": sport}
            for pid, data in players.items()
            if data.get("name")
        ]
        # Batch in chunks of 500 to avoid payload limits
        chunk_size = 500
        for i in range(0, len(upserts), chunk_size):
            chunk = upserts[i:i + chunk_size]
            sb.table("fantrax_players").upsert(chunk, on_conflict="fantrax_id").execute()
        print(f"[player_ids] Synced {len(upserts)} players to Supabase")
    except Exception as e:
        print(f"[player_ids] Supabase sync failed (non-fatal): {e}")

    return players
def get_league_info(league_id: str) -> dict:
    """
    Returns full league info including team names/IDs, scoring system,
    roster constraints, draft settings, and season dates.
    """
    url = f"{FANTRAX_BASE}/getLeagueInfo"
    resp = httpx.get(url, params={"leagueId": league_id}, timeout=15)
    resp.raise_for_status()
    return resp.json()