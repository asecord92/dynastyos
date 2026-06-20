"""Football (Sleeper/NFL) dashboard data: real standings + points-for (from
Sleeper roster records), the manager's record, players currently out, and
positional strength (the manager's points by position vs the league)."""
import time

from .supabase_client import get_supabase
from .sleeper_client import get_rosters as sleeper_get_rosters
from .nfl_trade import STARTABLE, stats_season, _format_key
from .sleeper_client import get_season_stats

_OUT_STATUSES = {"Out", "IR", "Doubtful", "PUP", "Sus", "Suspended"}

_roster_cache: dict = {}  # sleeper_league_id -> (ts, rosters)


def _sleeper_rosters_cached(sleeper_lid: str, ttl: int = 600) -> list:
    now = time.time()
    hit = _roster_cache.get(sleeper_lid)
    if hit and now - hit[0] < ttl:
        return hit[1]
    data = sleeper_get_rosters(sleeper_lid)
    _roster_cache[sleeper_lid] = (now, data)
    return data


async def build_nfl_dashboard(league_id: str, my_team_id: str) -> dict:
    sb = get_supabase()
    league = (
        sb.table("leagues").select("sleeper_league_id, rules").eq("id", league_id).single().execute().data
        or {}
    )
    sleeper_lid = league.get("sleeper_league_id")
    fmt_key = _format_key(league.get("rules") or {})
    stats = get_season_stats(stats_season())

    roster_rows = (
        sb.table("rosters")
        .select("fantrax_team_id, team_name, roster_items")
        .eq("league_id", league_id)
        .execute()
        .data
        or []
    )
    by_team = {r["fantrax_team_id"]: r for r in roster_rows}

    # Live records (wins/losses/points-for) from Sleeper, cached briefly.
    live = _sleeper_rosters_cached(sleeper_lid) if sleeper_lid else []
    settings_by_rid = {str(r["roster_id"]): (r.get("settings") or {}) for r in live}

    # Standings
    standings = []
    for tid, r in by_team.items():
        s = settings_by_rid.get(tid, {})
        pf = (s.get("fpts") or 0) + (s.get("fpts_decimal") or 0) / 100
        standings.append({
            "team_id": tid,
            "team": r.get("team_name", ""),
            "wins": s.get("wins", 0),
            "losses": s.get("losses", 0),
            "ties": s.get("ties", 0),
            "points_for": round(pf, 1),
            "is_me": tid == my_team_id,
        })
    standings.sort(key=lambda x: (x["wins"], x["points_for"]), reverse=True)
    for i, st in enumerate(standings):
        st["rank"] = i + 1
    me = next((s for s in standings if s["is_me"]), None)

    # Positional strength: my points by position vs league average + my rank.
    def pos_points(items, pos):
        return round(sum(
            (stats.get(it["id"]) or {}).get(fmt_key, 0) or 0
            for it in items if it.get("position") == pos
        ), 1)

    n_teams = max(len(by_team), 1)
    my_items = by_team.get(my_team_id, {}).get("roster_items", [])
    positional = []
    for pos in STARTABLE:
        totals = sorted(
            ((tid, pos_points(r["roster_items"], pos)) for tid, r in by_team.items()),
            key=lambda x: x[1],
            reverse=True,
        )
        mine = pos_points(my_items, pos)
        league_avg = round(sum(t[1] for t in totals) / n_teams, 1)
        rank = next((i + 1 for i, (tid, _) in enumerate(totals) if tid == my_team_id), n_teams)
        positional.append({"position": pos, "my_points": mine, "league_avg": league_avg, "rank": rank})

    players_out = [
        it.get("name", it["id"]) for it in my_items if it.get("injury_status") in _OUT_STATUSES
    ]

    return {
        "record": (
            {
                "wins": me["wins"], "losses": me["losses"], "ties": me["ties"],
                "points_for": me["points_for"], "rank": me["rank"], "total": len(standings),
            }
            if me else None
        ),
        "players_out": players_out,
        "standings": standings,
        "positional_strength": positional,
    }
