import asyncio
import httpx
from datetime import datetime, timedelta
from .supabase_client import get_supabase

MLB_STATS_BASE = "https://statsapi.mlb.com/api/v1"
STATS_TTL_HOURS = 24


def _splits(resp) -> list:
    """First stat group's splits, tolerating an empty (not just missing) 'stats' list.
    The API returns "stats": [] for players with no data for a group (e.g. a prospect's
    expectedStatistics), which would otherwise IndexError on [0]."""
    stats = resp.json().get("stats") or [{}]
    return stats[0].get("splits", [])


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


def get_cached_stats_bulk(mlb_ids: list[int]) -> dict[int, dict]:
    """Return fresh cached stats for many players in one round-trip per 100 ids,
    keyed by mlb_id. Stale or missing ids are simply absent from the result — the
    caller fetches those individually. Mirrors the freshness rule in
    get_cached_stats so a warm cache avoids ~one SELECT per player."""
    out: dict[int, dict] = {}
    if not mlb_ids:
        return out
    try:
        supabase = get_supabase()
        ids = list({int(m) for m in mlb_ids})
        for i in range(0, len(ids), 100):
            result = (
                supabase.table("player_stats")
                .select("*")
                .in_("mlb_id", ids[i:i + 100])
                .execute()
            )
            for row in (result.data or []):
                if not is_stale(row["refreshed_at"]):
                    out[row["mlb_id"]] = row
    except Exception as e:
        print(f"[stats] Supabase bulk read error: {e}")
    return out


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
        }, on_conflict="mlb_id").execute()
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

        splits = _splits(season_resp)
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

        splits = _splits(advanced_resp)
        if splits:
            s = splits[0]["stat"]
            stats.update({
                "k_rate": s.get("strikeoutsPerPlateAppearance"),
                "bb_rate": s.get("walksPerPlateAppearance"),
                "iso": s.get("iso"),
                "whiff_rate": s.get("swingAndMisses"),
            })

        splits = _splits(expected_resp)
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

        splits = _splits(season_resp)
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

        splits = _splits(advanced_resp)
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
        splits = _splits(resp)
        # Take the first split with sport id 1 (MLB only)
        for split in splits:
            if split.get("sport", {}).get("id") == 1:
                return split["stat"]
    except Exception as e:
        print(f"[stats] Error fetching recent stats for {mlb_id}: {e}")

    return {}


def fetch_roster_status(mlb_id: int) -> dict:
    """
    Fetches current MLB roster status + current team + age for a player.
    Returns {"roster_status": "Active"|"IL"|"Minors"|None, "il_type": "10-Day IL"|...|None,
             "mlb_team": str|None, "age": int|None}.
    Never raises.
    """
    try:
        resp = httpx.get(
            f"{MLB_STATS_BASE}/people/{mlb_id}",
            params={"hydrate": "rosterEntries(team),currentTeam"},
            timeout=10,
        )
        resp.raise_for_status()
        people = resp.json().get("people", [])
        if not people:
            return {"roster_status": None, "il_type": None, "mlb_team": None, "age": None}

        person = people[0]
        age = person.get("currentAge")

        # Prefer rosterEntries — find the active entry (no endDate)
        entries = person.get("rosterEntries", [])
        active_entry = next((e for e in entries if e.get("endDate") is None), None)
        if active_entry is None and entries:
            active_entry = entries[0]

        # Current team: the active roster entry's team is correct whether the player
        # is on the MLB club or optioned; fall back to the person's currentTeam.
        team_name = None
        if active_entry:
            team_name = active_entry.get("team", {}).get("name")
        if not team_name:
            team_name = person.get("currentTeam", {}).get("name")

        if active_entry:
            description = active_entry.get("status", {}).get("description", "")
        else:
            # Fall back to top-level status
            description = person.get("status", {}).get("description", "")

        d = description.lower()

        if "60-day" in d or "60 day" in d:
            roster_status, il_type = "IL", "60-Day IL"
        elif "15-day" in d or "15 day" in d:
            roster_status, il_type = "IL", "15-Day IL"
        elif "10-day" in d or "10 day" in d:
            roster_status, il_type = "IL", "10-Day IL"
        elif "injured" in d or "il" in d:
            roster_status, il_type = "IL", "IL"
        elif "minor" in d or "rehabilitation" in d:
            roster_status, il_type = "Minors", None
        elif "active" in d:
            roster_status, il_type = "Active", None
        else:
            roster_status, il_type = (description or None), None

        return {
            "roster_status": roster_status,
            "il_type": il_type,
            "mlb_team": team_name,
            "age": age if isinstance(age, int) else None,
        }

    except Exception as e:
        print(f"[roster_status] Error fetching status for mlb_id {mlb_id}: {e}")
        return {"roster_status": None, "il_type": None, "mlb_team": None, "age": None}


# MiLB sport IDs, highest level first.
MILB_SPORT_IDS = [(11, "AAA"), (12, "AA"), (13, "A+"), (14, "A")]


def _to_float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


async def _fetch_milb_level_splits(
    client: httpx.AsyncClient, mlb_id: int, group: str, season: int, sport_id: int, **extra
) -> list:
    """Fetch stat splits for one MiLB level; returns [] on any error. The API
    accepts only a single sportId per call (comma-joined values return nothing)."""
    try:
        resp = await client.get(
            f"{MLB_STATS_BASE}/people/{mlb_id}/stats",
            params={"group": group, "season": season, "sportId": sport_id, **extra},
        )
        return _splits(resp)
    except Exception:
        return []


async def get_milb_player_summary(mlb_id: int, player_type: str) -> dict | None:
    """
    Returns current-season MiLB stats for a prospect at the level they've played
    most, plus a stats-grounded trend (recent ~30 days vs season). Never raises.
    Returns None if the player has no MiLB stats this season.

    Shape: {"level": "AA", "stat_line": "...", "trend": "up"|"down"|"steady"}
    """
    season = datetime.now().year
    group = "hitting" if player_type == "hitter" else "pitching"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # One season call per level; pick the level with the most games.
            level_results = await asyncio.gather(*[
                _fetch_milb_level_splits(client, mlb_id, group, season, sid, stats="season")
                for sid, _ in MILB_SPORT_IDS
            ])

            best = None  # (sport_id, label, stat)
            for (sid, label), splits in zip(MILB_SPORT_IDS, level_results):
                if not splits:
                    continue
                stat = splits[0].get("stat", {})
                games = stat.get("gamesPlayed") or stat.get("gamesStarted") or 0
                if best is None or games > (best[2].get("gamesPlayed") or best[2].get("gamesStarted") or 0):
                    best = (sid, label, stat)

            if best is None:
                return None
            sport_id, level, season_stat = best

            # Recent form at the same level (last 30 days) for the trend signal.
            end = datetime.now()
            start = end - timedelta(days=30)
            recent_splits = await _fetch_milb_level_splits(
                client, mlb_id, group, season, sport_id,
                stats="byDateRange",
                startDate=start.strftime("%m/%d/%Y"),
                endDate=end.strftime("%m/%d/%Y"),
            )
        recent_stat = next(
            (s.get("stat", {}) for s in recent_splits if s.get("sport", {}).get("id") == sport_id),
            {},
        )
    except Exception as e:
        print(f"[milb] Error building summary for mlb_id {mlb_id}: {e}")
        return None

    if player_type == "hitter":
        stat_line = (
            f"{season_stat.get('gamesPlayed','?')}G "
            f"{season_stat.get('homeRuns','?')}HR {season_stat.get('runs','?')}R "
            f"{season_stat.get('rbi','?')}RBI {season_stat.get('stolenBases','?')}SB "
            f"{season_stat.get('avg','?')}/{season_stat.get('obp','?')}/{season_stat.get('slg','?')}"
        )
        season_ops = _to_float(season_stat.get("ops"))
        recent_ops = _to_float(recent_stat.get("ops"))
        trend = _trend_from(recent_ops, season_ops, threshold=0.060, higher_is_better=True)
    else:
        stat_line = (
            f"{season_stat.get('gamesStarted','?')}GS "
            f"{season_stat.get('inningsPitched','?')}IP {season_stat.get('era','?')}ERA "
            f"{season_stat.get('whip','?')}WHIP {season_stat.get('strikeOuts','?')}K"
        )
        season_era = _to_float(season_stat.get("era"))
        recent_era = _to_float(recent_stat.get("era"))
        trend = _trend_from(recent_era, season_era, threshold=0.75, higher_is_better=False)

    return {"level": level, "stat_line": stat_line, "trend": trend}


def _trend_from(recent, season, threshold: float, higher_is_better: bool) -> str:
    """Compare recent vs season; 'up' means trending better, grounded in the gap."""
    if recent is None or season is None:
        return "steady"
    delta = recent - season
    if not higher_is_better:
        delta = -delta
    if delta >= threshold:
        return "up"
    if delta <= -threshold:
        return "down"
    return "steady"


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
