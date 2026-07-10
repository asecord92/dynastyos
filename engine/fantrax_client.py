from datetime import datetime, timezone, timedelta
from typing import Any

import httpx

FANTRAX_BASE = "https://www.fantrax.com/fxea/general"


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
    Checks Supabase cache first; falls back to a fresh Fantrax fetch and syncs to Supabase.
    """
    from .supabase_client import get_supabase

    # Check Supabase cache
    try:
        sb = get_supabase()
        latest = (
            sb.table("fantrax_players")
            .select("updated_at")
            .eq("sport", sport)
            .order("updated_at", desc=True)
            .limit(1)
            .execute()
        )
        if latest.data:
            updated_at_str = latest.data[0]["updated_at"]
            updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - updated_at < timedelta(hours=24):
                all_rows = (
                    sb.table("fantrax_players")
                    .select("fantrax_id, name")
                    .eq("sport", sport)
                    .limit(11000)
                    .execute()
                )
                print(f"[player_ids] Returning {len(all_rows.data)} players from Supabase cache")
                return {row["fantrax_id"]: {"name": row["name"], "team": ""} for row in all_rows.data}
    except Exception as e:
        print(f"[player_ids] Supabase cache check failed (non-fatal): {e}")

    # Fetch fresh from Fantrax
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

    # Sync to Supabase fantrax_players table
    try:
        sb = get_supabase()
        upserts = [
            {"fantrax_id": pid, "name": data["name"], "sport": sport}
            for pid, data in players.items()
            if data.get("name")
        ]
        chunk_size = 500
        for i in range(0, len(upserts), chunk_size):
            chunk = upserts[i:i + chunk_size]
            sb.table("fantrax_players").upsert(chunk, on_conflict="fantrax_id").execute()
        print(f"[player_ids] Synced {len(upserts)} players to Supabase")
    except Exception as e:
        print(f"[player_ids] Supabase sync failed (non-fatal): {e}")

    return players


def get_standings(league_id: str) -> list[dict]:
    """
    Returns flat array of team standings objects.
    Each item: {teamId, teamName, points ("W-L-T"), rank, gamesBack, winPercentage}
    Find your team by teamId, parse points.split("-") → [wins, losses, ties].
    len(result) gives total teams in league.
    """
    url = f"{FANTRAX_BASE}/getStandings"
    resp = httpx.get(url, params={"leagueId": league_id}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_league_info(league_id: str) -> dict:
    """
    Returns full league info including team names/IDs, scoring system,
    roster constraints, draft settings, and season dates.
    """
    url = f"{FANTRAX_BASE}/getLeagueInfo"
    resp = httpx.get(url, params={"leagueId": league_id}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_draft_picks(league_id: str) -> list[dict]:
    """
    Returns the league's future draft picks. Each item:
    {year, round, currentOwnerTeamId, originalOwnerTeamId}. A pick whose
    currentOwner differs from originalOwner has been traded.
    """
    url = f"{FANTRAX_BASE}/getDraftPicks"
    resp = httpx.get(url, params={"leagueId": league_id}, timeout=15)
    resp.raise_for_status()
    return resp.json().get("futureDraftPicks", [])
