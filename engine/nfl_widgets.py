"""Football dashboard AI widgets (start/sit, news, waiver): roster context and
prompts built from synced Sleeper rosters + the players dump / season stats."""
from .sleeper_client import get_players, get_season_stats
from .nfl_trade import STARTABLE, stats_season, _nfl_today_line


def my_roster(sb, league_id: str, my_team_id: str):
    rows = (
        sb.table("rosters")
        .select("team_name, roster_items")
        .eq("league_id", league_id)
        .eq("fantrax_team_id", my_team_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        return None, []
    return rows[0].get("team_name", "Your Team"), (rows[0].get("roster_items") or [])


def _lines(items: list) -> str:
    out = []
    for it in items:
        line = f"- {it.get('name')} | {it.get('position')} | {it.get('team', '')}"
        if it.get("injury_status"):
            line += f" | {it['injury_status']}"
        out.append(line)
    return "\n".join(out)


def start_sit_prompt(team_name: str, items: list) -> str:
    return f"""You are a fantasy football analyst.
{_nfl_today_line()}

Team: {team_name}
Roster (player | pos | team | injury):
{_lines(items)}

Use web search (2-3 searches max) to check current status. For the upcoming NFL week, give each
startable player (QB/RB/WR/TE) a start/sit call considering matchup, recent role/usage, injuries, and
bye weeks. If it is the NFL offseason (no games scheduled), say so briefly and base calls on dynasty
outlook instead.

Return ONLY a ```json block — no other text:
{{"players":[{{"name":"Player","position":"RB","team":"DET","recommendation":"start","reason":"one sentence"}}],
  "alerts":[{{"name":"Player","status":"Out","detail":"one sentence"}}]}}
Rules: recommendation must be exactly start, monitor, or sit. Include every startable player."""


def news_prompt(team_name: str, items: list) -> str:
    return f"""You are a fantasy football analyst. Use web search for the latest news on these players.
{_nfl_today_line()}

Team: {team_name}
Roster:
{_lines(items)}

Summarize recent news (last 2 weeks) per player: injuries, depth-chart/role changes, signings,
suspensions, anything affecting fantasy value. Skip players with nothing to report. Format as a
bulleted list with the player name in bold. No preamble — start with the first bullet."""


def waiver_pool(sb, league_id: str, fmt_key: str, top: int = 40) -> list:
    """Top unrostered free agents by last-season points (startable positions)."""
    rosters = (
        sb.table("rosters").select("roster_items").eq("league_id", league_id).execute().data or []
    )
    claimed = {it["id"] for r in rosters for it in (r.get("roster_items") or [])}
    players = get_players()
    stats = get_season_stats(stats_season())
    fas = []
    for pid, s in stats.items():
        if pid in claimed:
            continue
        meta = players.get(pid) or {}
        pos = meta.get("position")
        pts = s.get(fmt_key)
        if pos not in STARTABLE or not pts:
            continue
        fas.append((round(float(pts), 1), meta.get("full_name") or pid, pos, meta.get("team", "")))
    fas.sort(reverse=True)
    return fas[:top]


def waiver_prompt(team_name: str, fas: list) -> str:
    pool = "\n".join(f"- {n} | {pos} | {tm} | {pts} pts last season" for pts, n, pos, tm in fas)
    return f"""You are a fantasy football analyst. Recommend the best waiver / free-agent pickups.
{_nfl_today_line()}

Team: {team_name}
Available pool (unrostered, ranked by last-season fantasy points):
{pool}

Use web search to check current role and news. Identify the best 4-5 targets to add right now. For
each: name, position, team, why they're worth adding, and a win-now vs dynasty read. No preamble."""
