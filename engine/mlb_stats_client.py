import asyncio
import httpx
from datetime import datetime, timedelta
from .supabase_client import get_supabase

MLB_STATS_BASE = "https://statsapi.mlb.com/api/v1"
STATS_TTL_HOURS = 24


def is_stale(refreshed_at: str) -> bool:
    """Check if cached stats are older than TTL."""
    try:
        refreshed = datetime.fromisoformat(refreshed_at.replace("Z", "+00:00"))
        return datetime.now(refreshed.tzinfo) - refreshed > timedelta(hours=STATS_TTL_HOURS)
    except Exception:
        return True


def get_cached_stats(mlb_id: int) -> dict | None:
    """Return cached stats from Supabase if they exist and are fresh."""
    try:
        supabase = get_supabase()
        result = supabase.table("player_stats").select("*").eq("mlb_id", mlb_id).execute()
        if result.data:
            row = result.data[0]
            if not is_stale(row["refreshed_at"]):
                return row
    except Exception as e:
        print(f"[stats] Supabase read error for mlb_id {mlb_id}: {e}")
    return None


def save_stats(mlb_id: int, season: int, player_type: str, season_stats: dict, recent_stats: dict) -> None:
    """Persist stats to Supabase."""
    try:
        supabase = get_supabase()
        supabase.table("player_stats").upsert({
            "mlb_id": mlb_id,
            "season": season,
            "player_type": player_type,
            "season_stats": season_stats,
            "recent_stats": recent_stats,
            "refreshed_at": datetime.utcnow().isoformat(),
        }, on_conflict="mlb_id,season").execute()
    except Exception as e:
        print(f"[stats] Supabase write error for mlb_id {mlb_id}: {e}")


async def fetch_hitting_stats(mlb_id: int, season: int) -> dict:
    """Fetch season + advanced + expected hitting stats from MLB Stats API."""
    stats = {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            season_resp, advanced_resp, expected_resp = await asyncio.gather(
                client.get(
                    f"{MLB_STATS_BASE}/people/{mlb_id}/stats",
                    params={"stats": "season", "group": "hitting", "season": season},
                ),
                client.get(
                    f"{MLB_STATS_BASE}/people/{mlb_id}/stats",
                    params={"stats": "seasonAdvanced", "group": "hitting", "season": season},
                ),
                client.get(
                    f"{MLB_STATS_BASE}/people/{mlb_id}/stats",
                    params={"stats": "expectedStatistics", "group": "hitting", "season": season},
                ),
            )

        splits = season_resp.json().get("stats", [{}])[0].get("splits", [])
        if splits:
            s = splits[0]["stat"]
            stats.update({
                "games_played": s.get("gamesPlayed"),
                "plate_appearances": s.get("plateAppearances"),
                "runs": s.get("runs"),
                "home_runs": s.get("homeRuns"),
                "rbi": s.get("rbi"),
                "stolen_bases": s.get("stolenBases"),
                "obp": s.get("obp"),
                "avg": s.get("avg"),
                "slg": s.get("slg"),
                "ops": s.get("ops"),
            })

        splits = advanced_resp.json().get("stats", [{}])[0].get("splits", [])
        if splits:
            s = splits[0]["stat"]
            stats.update({
                "k_rate": s.get("strikeoutsPerPlateAppearance"),
                "bb_rate": s.get("walksPerPlateAppearance"),
                "iso": s.get("iso"),
                "whiff_rate": s.get("swingAndMisses"),
            })

        splits = expected_resp.json().get("stats", [{}])[0].get("splits", [])
        if splits:
            s = splits[0]["stat"]
            stats.update({
                "xwoba": s.get("woba"),
                "xavg": s.get("avg"),
                "xslg": s.get("slg"),
            })

    except Exception as e:
        print(f"[stats] Error fetching hitting stats for {mlb_id}: {e}")

    return stats


async def fetch_pitching_stats(mlb_id: int, season: int) -> dict:
    """Fetch season + advanced pitching stats from MLB Stats API."""
    stats = {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            season_resp, advanced_resp = await asyncio.gather(
                client.get(
                    f"{MLB_STATS_BASE}/people/{mlb_id}/stats",
                    params={"stats": "season", "group": "pitching", "season": season},
                ),
                client.get(
                    f"{MLB_STATS_BASE}/people/{mlb_id}/stats",
                    params={"stats": "seasonAdvanced", "group": "pitching", "season": season},
                ),
            )

        splits = season_resp.json().get("stats", [{}])[0].get("splits", [])
        if splits:
            s = splits[0]["stat"]
            stats.update({
                "era": s.get("era"),
                "whip": s.get("whip"),
                "strikeouts": s.get("strikeOuts"),
                "saves": s.get("saves"),
                "innings_pitched": s.get("inningsPitched"),
                "wins": s.get("wins"),
                "games_started": s.get("gamesStarted"),
                "k_per_9": s.get("strikeoutsPer9Inn"),
                "bb_per_9": s.get("walksPer9Inn"),
            })

        splits = advanced_resp.json().get("stats", [{}])[0].get("splits", [])
        if splits:
            s = splits[0]["stat"]
            stats.update({
                "quality_starts": s.get("qualityStarts"),
                "whiff_rate": s.get("whiffPercentage"),
                "k_rate": s.get("strikeoutsPerPlateAppearance"),
                "bb_rate": s.get("walksPerPlateAppearance"),
            })

    except Exception as e:
        print(f"[stats] Error fetching pitching stats for {mlb_id}: {e}")

    return stats


async def fetch_recent_stats(mlb_id: int, season: int, player_type: str) -> dict:
    """Fetch last 30 days of stats."""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    group = "hitting" if player_type == "hitter" else "pitching"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{MLB_STATS_BASE}/people/{mlb_id}/stats",
                params={
                    "stats": "byDateRange",
                    "group": group,
                    "season": season,
                    "startDate": start_date.strftime("%m/%d/%Y"),
                    "endDate": end_date.strftime("%m/%d/%Y"),
                },
            )
        splits = resp.json().get("stats", [{}])[0].get("splits", [])
        # Take the first split with sport id 1 (MLB only)
        for split in splits:
            if split.get("sport", {}).get("id") == 1:
                return split["stat"]
    except Exception as e:
        print(f"[stats] Error fetching recent stats for {mlb_id}: {e}")

    return {}


async def get_player_stats(mlb_id: int, player_type: str) -> dict | None:
    """
    Main entry point. Returns stats for a player, using cache if fresh.
    Fetches from MLB Stats API and stores in Supabase if stale or missing.
    """
    # Check cache first
    cached = get_cached_stats(mlb_id)
    if cached:
        return cached

    # Determine current season
    season = datetime.now().year

    # Fetch stats based on player type
    if player_type == "hitter":
        season_stats = await fetch_hitting_stats(mlb_id, season)
    else:
        season_stats = await fetch_pitching_stats(mlb_id, season)

    recent_stats = await fetch_recent_stats(mlb_id, season, player_type)

    # Store in Supabase
    save_stats(mlb_id, season, player_type, season_stats, recent_stats)

    return {
        "mlb_id": mlb_id,
        "season": season,
        "player_type": player_type,
        "season_stats": season_stats,
        "recent_stats": recent_stats,
    }
