"""Football (Sleeper/NFL) trade analysis: points-based player value, draft-pick
valuation, and the context/prompt builders for /trade/analyze and /trade/finder.

Kept separate from the MLB ``trade_analyzer`` so each sport stays clean; the API
dispatches by the league's sport. Player metadata is already embedded in the
shared ``rosters`` table (from the Sleeper sync), and season fantasy points come
from Sleeper's in-process-cached season stats — so this module does no live
per-player fetches.
"""
import asyncio
from datetime import datetime, timezone
from typing import Any

from .supabase_client import get_supabase
from .sleeper_client import get_season_stats


async def _load_blocking(sb, league_id: str, team_ids: list | None = None) -> tuple[dict, dict, list]:
    """League row, season stats, and rosters — all blocking (sync Supabase +
    Sleeper's season-stats download on a cold cache), so off the event loop."""
    def load():
        league = _load_league(sb, league_id)
        stats = get_season_stats(stats_season())
        rosters = _load_rosters(sb, league_id, team_ids)
        return league, stats, rosters
    return await asyncio.to_thread(load)

STARTABLE = ["QB", "RB", "WR", "TE"]

# Rough rookie-pick values on the same 0-100 scale as player production percentile.
# Tunable; superflex / context nuances are left to the model.
_PICK_BASE = {1: 55.0, 2: 30.0, 3: 15.0, 4: 8.0}
_PICK_DECAY = 0.85  # per draft-year further out


def _nfl_today_line() -> str:
    now = datetime.now(timezone.utc)
    return (
        f"Today's date is {now.strftime('%A, %B %d, %Y')}. Evaluate players on their "
        f"current NFL situation and recent production, not prior-years narratives."
    )


def stats_season() -> int:
    """Most recent completed NFL season for valuation. In the offseason (before
    September) that's last year; from September on, the current year."""
    now = datetime.now(timezone.utc)
    return now.year if now.month >= 9 else now.year - 1


def _format_key(rules: dict) -> str:
    return f"pts_{(rules or {}).get('scoring_format') or 'half_ppr'}"


def _percentiles(values: list) -> list:
    """0-100 percentile rank (100 = most points) within the non-None values.
    Tied values share the mean position of their tie block, so equal points
    score equally instead of by arbitrary sort order (0-point non-players would
    otherwise spread 0/50/100)."""
    present = [(i, v) for i, v in enumerate(values) if v is not None]
    out: list = [None] * len(values)
    n = len(present)
    if n == 0:
        return out
    if n == 1:
        out[present[0][0]] = 50.0
        return out
    ordered = sorted(present, key=lambda iv: iv[1])  # worst -> best
    i = 0
    while i < n:
        j = i
        while j < n and ordered[j][1] == ordered[i][1]:
            j += 1
        avg_pos = (i + j - 1) / 2.0  # shared position for the whole tie block
        pct = round(100.0 * avg_pos / (n - 1), 1)
        for k in range(i, j):
            out[ordered[k][0]] = pct
        i = j
    return out


def pick_value(season: int, rnd: int, next_season: int) -> float:
    base = _PICK_BASE.get(rnd, 4.0)
    years_out = max(0, season - next_season)
    return round(base * (_PICK_DECAY ** years_out), 1)


def _value_players(players: list, stats: dict, fmt_key: str) -> None:
    """Attach `points` (season fantasy points), `gp`/`ppg`, `pos_rank` (Sleeper's
    league-wide positional rank for the scoring format), and `value` (percentile
    of points *within the player's position*) to each player dict. Within-position
    so a WR is compared to WRs, not to higher-scoring QBs — otherwise raw points
    rank every QB above every WR/TE regardless of quality. Mutates in place."""
    pos_rank_key = fmt_key.replace("pts_", "pos_rank_")
    for p in players:
        s = stats.get(p["id"]) or {}
        pts = s.get(fmt_key)
        p["points"] = round(float(pts), 1) if isinstance(pts, (int, float)) else None
        gp = s.get("gp")
        p["gp"] = int(gp) if isinstance(gp, (int, float)) and gp > 0 else None
        p["ppg"] = (
            round(p["points"] / p["gp"], 1)
            if p["points"] is not None and p["gp"] else None
        )
        rank = s.get(pos_rank_key)
        p["pos_rank"] = int(rank) if isinstance(rank, (int, float)) else None
    by_pos: dict[str, list] = {}
    for p in players:
        by_pos.setdefault(p.get("position") or "?", []).append(p)
    for group in by_pos.values():
        for p, v in zip(group, _percentiles([p["points"] for p in group])):
            p["value"] = v


def _pick_assets(draft_picks: list, next_season: int) -> list:
    assets = []
    for pk in draft_picks or []:
        try:
            season, rnd = int(pk["season"]), int(pk["round"])
        except (KeyError, TypeError, ValueError):
            continue
        assets.append({
            "id": f"pick:{season}:{rnd}:{pk.get('original_roster_id', '?')}",
            "name": pk.get("label") or f"{season} R{rnd}",
            "position": "PICK",
            "value": pick_value(season, rnd, next_season),
            "is_pick": True,
        })
    return assets


def _load_league(sb, league_id: str) -> dict:
    row = (
        sb.table("leagues")
        .select("name, rules, competitive_window, cap_philosophy, goals")
        .eq("id", league_id)
        .single()
        .execute()
    )
    return row.data or {}


def _load_rosters(sb, league_id: str, team_ids: list | None = None) -> list:
    q = sb.table("rosters").select(
        "fantrax_team_id, team_name, roster_items, draft_picks"
    ).eq("league_id", league_id)
    if team_ids:
        q = q.in_("fantrax_team_id", team_ids)
    return q.execute().data or []


def build_nfl_system_prompt(rules: dict) -> str:
    rules = rules or {}
    size = rules.get("league_size", 10)
    fmt = {"ppr": "full PPR", "half_ppr": "0.5 PPR (half)", "std": "standard (non-PPR)"}.get(
        rules.get("scoring_format") or "half_ppr", "0.5 PPR"
    )
    sf = (
        "superflex (a second QB can start, so QBs are premium)"
        if rules.get("superflex")
        else "single-QB"
    )
    return f"""You are a sharp, opinionated dynasty football trade advisor built into DynastyOS.
You give direct, defensible recommendations — not balanced summaries. You have a point of view and
you back it up with specifics. You never hedge without committing to a final answer.

IMPORTANT: Only reference player facts explicitly provided in this prompt — position, team, age,
injury status, fantasy production, and the value figures given. Do not use training knowledge to
invent injuries, depth-chart roles, or stats not provided; player situations change frequently.

Data grounding: rosters, ages, and injury designations below come from live Sleeper data and may
lag reality by up to ~24 hours. If a fact you need is not provided (and not confirmed by a web
search result when search is available), treat it as unknown — say so explicitly and tell the
manager what to verify, rather than guessing.

League format:
- {size}-team dynasty league, {fmt} scoring, {sf}
- No salary cap and no contracts — value is rest-of-career production plus positional scarcity
- Draft picks are tradeable assets; earlier rounds and nearer years are worth more
- Weigh roster construction, age / dynasty window, and bye weeks alongside raw production

Players carry age, injury status when listed, season fantasy points with games played and
points-per-game, and a positional rank (e.g. WR12 = 12th-best WR league-wide that season in this
scoring format). Each player's `value` is a 0-100 percentile of season fantasy points within the
trade pool; picks carry a comparable estimate. Use these to gauge balance, but adjust for
positional scarcity (QB in superflex, premium RB/WR) and dynasty age/upside — an aging RB's points
overstate his dynasty worth, a 22-year-old's understate it. Don't treat value as gospel."""


def _fmt_asset(a: dict) -> str:
    if a.get("is_pick"):
        return f"{a['name']} (pick) | value {a.get('value', '?')}"
    pts = a.get("points")
    if pts is not None:
        extras = []
        if a.get("gp"):
            extras.append(f"{a['gp']} gp")
        if a.get("ppg") is not None:
            extras.append(f"{a['ppg']} ppg")
        if a.get("pos_rank"):
            extras.append(f"{a.get('position', '')}{a['pos_rank']}")
        pts_str = f"{pts} pts" + (f" ({', '.join(extras)})" if extras else "")
    else:
        pts_str = "no recent pts"
    age = f"{a['age']}yo" if a.get("age") else "age ?"
    inj = f" | INJ: {a['injury_status']}" if a.get("injury_status") else ""
    return (
        f"{a['name']} | {a.get('position', '?')} {a.get('team', '')} | {age}{inj} | "
        f"{pts_str} | value {a.get('value', '?')}"
    )


# ---------------------------------------------------------------------------
# Trade analyze
# ---------------------------------------------------------------------------
async def build_nfl_trade_context(
    league_id: str,
    my_team_id: str,
    opponent_team_id: str,
    offering_ids: list[str],
    receiving_ids: list[str],
) -> dict[str, Any]:
    sb = get_supabase()
    league, stats, rosters = await _load_blocking(sb, league_id, [my_team_id, opponent_team_id])
    rules = league.get("rules") or {}
    fmt_key = _format_key(rules)
    season = stats_season()
    next_season = datetime.now(timezone.utc).year + 1
    my = next((r for r in rosters if r["fantrax_team_id"] == my_team_id), None)
    opp = next((r for r in rosters if r["fantrax_team_id"] == opponent_team_id), None)
    if not my or not opp:
        raise ValueError("Could not load both rosters.")

    my_players = [dict(it) for it in (my.get("roster_items") or [])]
    opp_players = [dict(it) for it in (opp.get("roster_items") or [])]
    _value_players(my_players + opp_players, stats, fmt_key)  # shared-pool percentile
    my_picks = _pick_assets(my.get("draft_picks"), next_season)
    opp_picks = _pick_assets(opp.get("draft_picks"), next_season)

    by_id = {a["id"]: a for a in (my_players + opp_players + my_picks + opp_picks)}
    return {
        "sport": "NFL",
        "league": league,
        "rules": rules,
        "stats_season": season,
        "my_team_name": my.get("team_name", "Your team"),
        "opp_team_name": opp.get("team_name", "Opponent"),
        "my_players": my_players,
        "opp_players": opp_players,
        "my_picks": my_picks,
        "opp_picks": opp_picks,
        "by_id": by_id,
        "offering_ids": offering_ids,
        "receiving_ids": receiving_ids,
    }


def build_nfl_trade_prompt(context: dict[str, Any]) -> str:
    by_id = context["by_id"]
    league = context["league"]
    giving = [by_id[i] for i in context["offering_ids"] if i in by_id]
    getting = [by_id[i] for i in context["receiving_ids"] if i in by_id]
    give_val = sum(a.get("value") or 0 for a in giving)
    get_val = sum(a.get("value") or 0 for a in getting)

    def roster_block(label, players, picks):
        lines = [f"\n{label}:"]
        for p in sorted(players, key=lambda x: (x.get("value") or 0), reverse=True):
            lines.append(f"  {_fmt_asset(p)}")
        if picks:
            lines.append("  Picks: " + ", ".join(f"{p['name']} (v{p.get('value')})" for p in picks))
        return "\n".join(lines)

    stats_year = context.get("stats_season") or stats_season()
    return "\n".join([
        _nfl_today_line(),
        "",
        f"Manager's team: {context['my_team_name']} | "
        f"Window: {league.get('competitive_window') or 'Not set'} | "
        f"Goals: {league.get('goals') or 'Not set'}",
        "",
        f"Fantasy points below are {stats_year} regular-season totals in this league's scoring "
        "format (gp = games played, ppg = points per game, and e.g. WR12 = league-wide positional "
        "rank that season).",
        "",
        "Proposed trade:",
        f"  Manager GIVES: {', '.join(_fmt_asset(a) for a in giving) or '(nothing)'}",
        f"  Manager GETS:  {', '.join(_fmt_asset(a) for a in getting) or '(nothing)'}",
        f"  Value sent: {round(give_val, 1)} | value received: {round(get_val, 1)}",
        roster_block(f"Manager's roster ({context['my_team_name']})", context["my_players"], context["my_picks"]),
        roster_block(f"Opponent's roster ({context['opp_team_name']})", context["opp_players"], context["opp_picks"]),
        "",
        """Before finalizing your verdict, use web search (a few targeted searches at most) to verify
the current situation of the key players in this trade — injuries, depth-chart or role changes,
team changes, and holdouts from roughly the last two weeks. Incorporate only facts you actually
confirmed and note the date of any news you cite. If search turns up nothing new, proceed
confidently with the data above. Never let unverified memory of a player override the data
provided here.

Respond in exactly this format, beginning immediately with the VERDICT heading on its own
line. Do not narrate your process — no preamble before the verdict; any searching happens
silently first.

VERDICT
ACCEPT, DECLINE, or COUNTER — one punchy sentence on why.

ANALYSIS
3-5 paragraphs. Name the players and picks, cite the points/ppg/positional ranks and ages, and
argue the call. Cover positional scarcity (QB in superflex), dynasty age/window (weigh each
player's age against the manager's competitive window), injury flags, per-game production vs raw
totals (a high total on 17 games is different from the same total on 12), depth impact, and pick
value. Make the case.

COUNTER OFFER
If COUNTER, propose a specific tweak (swap/add/remove a player or pick) that stays within this deal
and is fair or tilts slightly to the manager. Otherwise note whether a tweak is worth exploring.""",
    ])


# ---------------------------------------------------------------------------
# Trade finder (position-need first)
# ---------------------------------------------------------------------------
def _detect_weak_position(my_players: list, all_players_by_team: dict, stats: dict, fmt_key: str) -> str:
    """The startable position where the manager's points are weakest relative to
    the league average for that position."""
    def team_pos_points(players, pos):
        return sum(
            (stats.get(p["id"]) or {}).get(fmt_key, 0) or 0
            for p in players if p.get("position") == pos
        )

    best_pos, best_deficit = "RB", float("-inf")
    n_teams = max(len(all_players_by_team), 1)
    for pos in STARTABLE:
        league_total = sum(team_pos_points(pl, pos) for pl in all_players_by_team.values())
        avg = league_total / n_teams
        mine = team_pos_points(my_players, pos)
        deficit = avg - mine
        if deficit > best_deficit:
            best_deficit, best_pos = deficit, pos
    return best_pos


async def build_nfl_finder_context(
    league_id: str,
    my_team_id: str,
    target_position: str | None = None,
) -> dict[str, Any]:
    sb = get_supabase()
    league, stats, rosters = await _load_blocking(sb, league_id)
    rules = league.get("rules") or {}
    fmt_key = _format_key(rules)
    season = stats_season()
    next_season = datetime.now(timezone.utc).year + 1
    my = next((r for r in rosters if r["fantrax_team_id"] == my_team_id), None)
    if not my:
        raise ValueError("Could not load your roster.")
    opp_rosters = [r for r in rosters if r["fantrax_team_id"] != my_team_id]

    by_team = {r["fantrax_team_id"]: [dict(it) for it in (r.get("roster_items") or [])] for r in rosters}
    my_players = by_team[my_team_id]

    if not target_position:
        target_position = _detect_weak_position(my_players, by_team, stats, fmt_key)
    target_position = target_position.upper()

    # Candidate pool: opponents' players at the target position, ranked by points.
    candidates = []
    for r in opp_rosters:
        for it in by_team[r["fantrax_team_id"]]:
            if it.get("position") != target_position:
                continue
            candidates.append({**it, "owner_team_id": r["fantrax_team_id"], "owner_team_name": r.get("team_name", "")})

    # Value candidates + my players on a shared pool; my assets also include picks.
    _value_players(candidates + my_players, stats, fmt_key)
    candidates = [c for c in candidates if c.get("points") is not None]
    candidates.sort(key=lambda c: c["points"], reverse=True)
    candidates = candidates[:12]

    my_picks = _pick_assets(my.get("draft_picks"), next_season)
    my_assets = my_players + my_picks

    return {
        "sport": "NFL",
        "league": league,
        "rules": rules,
        "stats_season": season,
        "target_position": target_position,
        "candidates": candidates,
        "my_assets": my_assets,
    }


def build_nfl_finder_prompt(context: dict[str, Any]) -> str:
    pos = context["target_position"]
    candidates = context["candidates"]
    my_assets = context["my_assets"]
    league = context["league"]

    stats_year = context.get("stats_season") or stats_season()
    lines = [
        _nfl_today_line(),
        "",
        f"The manager needs help at {pos}. Below are the best {pos} targets across the league, "
        f"ranked by {stats_year} regular-season fantasy points in this league's scoring format "
        "(gp = games played, ppg = points per game, WR12-style = league-wide positional rank). "
        "Each carries a 0-100 value (points percentile); your tradeable assets — players and "
        "draft picks — carry comparable values. Weigh age and injury flags against the manager's "
        "window, and per-game production against raw totals.",
        "",
        f"Manager's team: {league.get('name', 'Unknown')} | "
        f"Window: {league.get('competitive_window') or 'Not set'}",
        "",
        f"Acquisition targets at {pos} (id | player | pos team | age | points | value | owner):",
    ]
    for c in candidates:
        lines.append(f"  {c['id']} | {_fmt_asset(c)} | {c['owner_team_name']}")
    lines += ["", "Your tradeable assets (id | asset | value):"]
    for a in sorted(my_assets, key=lambda x: (x.get("value") or 0), reverse=True):
        lines.append(f"  {a['id']} | {_fmt_asset(a)}")

    lines += [
        "",
        f"Recommend the 2-3 most realistic {pos} targets and why. For EACH, construct a specific, "
        "fair offer using ONLY ids from 'Your tradeable assets' (players and/or picks) — name them. "
        "Aim for total value sent within ~15% of the target's value; favor packaging depth + a pick "
        "to land a clear upgrade rather than a straight swap. Never invent players, ids, or stats.",
        "",
        "Write 2-4 short paragraphs, then end with a fenced ```json block (nothing after it) using the "
        "ids above, in exactly this schema:",
        "```json",
        '[{"target_ids": ["<target id>"], "offer_ids": ["<your asset id>", "..."], '
        '"rationale": "<one sentence>"}]',
        "```",
        "Only include offers you actually recommend.",
    ]
    return "\n".join(lines)


# --- Add/Drop analyzer (football) --------------------------------------------
# "I'm adding these players and already dropping these — who else do I cut?"
# Ranks the manager's most expendable players. No salary/contract in this NFL
# setup, so expendability is production (within-position value) + positional
# depth relative to who's coming in.


async def build_nfl_add_drop_context(
    league_id: str,
    my_team_id: str,
    incoming: list[dict],       # [{"id": <sleeper id> | None, "name": <str>}]
    outgoing_ids: list[str],
) -> dict[str, Any]:
    sb = get_supabase()
    league, stats, rosters = await _load_blocking(sb, league_id)
    rules = league.get("rules") or {}
    fmt_key = _format_key(rules)
    my = next((r for r in rosters if r["fantrax_team_id"] == my_team_id), None)
    if not my:
        raise ValueError("Could not load your roster. Sync your league first.")
    my_items = [dict(it) for it in (my.get("roster_items") or [])]

    item_by_id = {
        it["id"]: it
        for r in rosters for it in (r.get("roster_items") or [])
        if it.get("id")
    }

    incoming_ids = [inc["id"] for inc in incoming if inc.get("id")]
    exclude = set(outgoing_ids) | set(incoming_ids)
    drop_items = [it for it in my_items if it.get("id") not in exclude]

    # Value the drop candidates within position (points percentile per position).
    _value_players(drop_items, stats, fmt_key)

    incoming_resolved = []
    for inc in incoming:
        fid = inc.get("id")
        if fid:
            it = item_by_id.get(fid, {})
            incoming_resolved.append({
                "name": it.get("name") or inc.get("name") or f"Unknown ({fid})",
                "position": it.get("position", "?"),
                "team": it.get("team", ""),
            })
        else:
            incoming_resolved.append({
                "name": (inc.get("name") or "Unknown").strip(),
                "position": "?",
                "team": "",
            })

    outgoing_named = [
        (item_by_id.get(oid, {}).get("name") or f"Unknown ({oid})")
        for oid in outgoing_ids
    ]

    return {
        "league": league,
        "rules": rules,
        "sport": "NFL",
        "team_name": my.get("team_name") or "Your Team",
        "drop_assets": drop_items,
        "incoming": incoming_resolved,
        "outgoing": outgoing_named,
        "spots_needed": max(0, len(incoming) - len(outgoing_ids)),
    }


def build_nfl_add_drop_prompt(context: dict[str, Any]) -> str:
    drops = context["drop_assets"]
    incoming = context["incoming"]
    outgoing = context["outgoing"]
    spots = context["spots_needed"]

    incoming_lines = "\n".join(
        f"  {p['name']} | {p['position']} {p.get('team', '')}".rstrip() for p in incoming
    ) or "  (none)"

    drop_lines = []
    for p in sorted(drops, key=lambda x: (x.get("value") is not None, x.get("value") or 0)):
        inj = f" | {p['injury_status']}" if p.get("injury_status") else ""
        age = f"{p['age']}yo" if p.get("age") else "age ?"
        drop_lines.append(
            f"  {p['id']} | {p['name']} | {p.get('position', '?')} {p.get('team', '')} | {age} | "
            f"{p.get('status', '')}{inj} | {p.get('points', '?')} pts | value {p.get('value', '?')}"
        )
    roster_block = "\n".join(drop_lines) or "  (none)"

    if spots > 0:
        ask = f"Recommend exactly which {spots} player(s) to drop"
        spots_line = f"You need to clear {spots} roster spot(s) to make this work."
    else:
        ask = "Recommend who is most expendable"
        spots_line = (
            "No drop is strictly required (the players already leaving cover the additions), "
            "but identify who is most expendable if the manager wants to open a spot."
        )

    return "\n".join([
        _nfl_today_line(),
        "",
        f"The manager is making room on their roster ({context['team_name']}).",
        f"Adding:\n{incoming_lines}",
        f"Already dropping/trading away: {', '.join(outgoing) or 'none'}",
        spots_line,
        "",
        "Each drop candidate carries last season's fantasy points and a 0-100 value (points "
        "percentile WITHIN their position, so compare like-for-like). Lower value = more "
        "expendable at that position, all else equal.",
        "",
        "Drop candidates (id | player | pos team | age | status | points | value):",
        roster_block,
        "",
        f"{ask} to make this work. Rank them from most to least droppable. For EACH, give a "
        "one-line rationale weighing: production/value, positional depth RELATIVE TO who's coming "
        "in (never drop your only startable player at a position the incoming players don't "
        "cover), positional scarcity (QB in superflex, premium RB/WR), and dynasty age/upside. "
        "Prefer dropping injured/bench depth and redundant players first. There's no salary or "
        "contracts in this league — value is rest-of-career production plus positional scarcity.",
        "",
        "Format: one short summary sentence, then a numbered list — "
        "'1. **Player Name** (pos, team) — rationale'. Recommend ONLY players from the drop "
        "candidates list above; never invent players or stats.",
    ])
