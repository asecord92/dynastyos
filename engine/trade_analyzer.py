import asyncio
from typing import Any
from .supabase_client import get_supabase
from .mlb_stats_client import get_player_stats


SCORING_CATEGORIES = {
    "hitting": ["R", "HR", "RBI", "SB", "OBP"],
    "pitching": ["QS", "SV", "K", "ERA", "WHIP"],
}

SYSTEM_PROMPT = """You are a sharp, opinionated dynasty baseball trade advisor built into DynastyOS.
You give direct, defensible recommendations — not balanced summaries. You have a point of view and
you back it up with specifics. You never hedge without committing to a final answer. You are not a
journalist presenting both sides — you are a trusted advisor telling the manager what to do and why.

IMPORTANT: Only reference player facts explicitly provided in this prompt — current team, stats,
contract, and salary. Do not use your training knowledge to fill in details about any player.
Player situations change frequently and your training data may be wrong.

League format:
- 10-team head-to-head category scoring (weekly matchups)
- Hitting categories: R, HR, RBI, SB, OBP
- Pitching categories: QS, SV, K, ERA, WHIP
- In-season salary cap: $450
- Offseason auction budget: $335

Dynasty contract rules:
- 1st and 2nd year contracts: salary does not change from draft price
- 3rd year is the decision point:
  - EXTEND: salary increases by $4 (floor of $15). Player stays on your roster long-term.
  - OPTION: salary increases by $1. Player is dropped to the auction pool at end of season — you lose them entirely.
  - CUT: available at any time, any contract year. Player goes to free agency immediately.
- 4th year and beyond (extended players only): salary increases by $4 every year, maximum $70.
- No limit on contract years as long as you keep extending.

Extension trajectory examples:
- Player drafted at $5, extended in year 3 → $15 (floor), year 4 → $19, year 5 → $23 (+$4/year, max $70).
- Player drafted at $12, extended in year 3 → $15 (floor), year 4 → $19, year 5 → $23.
- Player drafted at $20, extended in year 3 → $24, year 4 → $28, year 5 → $32.
Any player drafted under $15 follows the same floor trajectory once extended. +$4/year applies from year 4 onward.

Contract valuation framework — this is critical:
- 1st and 2nd year players are at their draft price. Their future cost is unknown until the 3rd year decision.
- A player's salary on a 4th+ year contract reflects cumulative $4 raises since their extension point.
- The core dynasty question on any trade: is this player's current salary above or below what they would
  realistically go for at auction? If you can cut a $35 player and re-sign them for $20, you've gained
  $15 in cap space — but you risk losing them entirely or paying more. Contract assets (cheap, locked-in
  players on long extensions) are extremely valuable. Overpaid aging players on late contracts are liabilities.
- Always consider: would you rather have this player at this salary, or take your chances at auction?"""


def get_player_name(fantrax_id: str, player_id_map: dict) -> str:
    return player_id_map.get(fantrax_id, {}).get("name", f"Unknown ({fantrax_id})")


def format_roster_for_prompt(
    roster_items: list,
    player_id_map: dict,
    label: str,
    highlight_ids: list[str] | None = None,
) -> str:
    lines = [f"\n{label}:"]
    for item in roster_items:
        fid = item.get("id", "")
        name = get_player_name(fid, player_id_map)
        salary = item.get("salary", 0)
        contract = item.get("contract", {}).get("name", "?")
        position = item.get("position", "?")
        status = item.get("status", "")
        highlight = " ◄ IN THIS TRADE" if highlight_ids and fid in highlight_ids else ""
        lines.append(f"  {name} | {position} | ${salary} | {contract} year | {status}{highlight}")
    return "\n".join(lines)


def format_stats_for_prompt(player_stats: dict, name: str, player_type: str, mlb_team: str = "") -> str:
    if not player_stats:
        team_str = f" ({mlb_team})" if mlb_team else ""
        return f"  {name}{team_str}: No 2026 stats yet (prospect or no MLB appearances)"

    season = player_stats.get("season_stats", {})
    recent = player_stats.get("recent_stats", {})

    if player_type == "hitter":
        season_line = (
            f"R:{season.get('runs','?')} HR:{season.get('home_runs','?')} "
            f"RBI:{season.get('rbi','?')} SB:{season.get('stolen_bases','?')} "
            f"OBP:{season.get('obp','?')} AVG:{season.get('avg','?')} "
            f"PA:{season.get('plate_appearances','?')}"
        )
        recent_line = (
            f"R:{recent.get('runs','?')} HR:{recent.get('homeRuns','?')} "
            f"RBI:{recent.get('rbi','?')} SB:{recent.get('stolenBases','?')} "
            f"OBP:{recent.get('obp','?')}"
        )
    else:
        season_line = (
            f"ERA:{season.get('era','?')} WHIP:{season.get('whip','?')} "
            f"K:{season.get('strikeouts','?')} QS:{season.get('quality_starts','?')} "
            f"SV:{season.get('saves','?')} IP:{season.get('innings_pitched','?')}"
        )
        recent_line = (
            f"ERA:{recent.get('era','?')} WHIP:{recent.get('whip','?')} "
            f"K:{recent.get('strikeOuts','?')}"
        )

    return f"  {name} (2026 season): {season_line} | Last 30 days: {recent_line}"


async def build_trade_context(
    league_id: str,
    my_team_id: str,
    opponent_team_id: str,
    offering_ids: list[str],
    receiving_ids: list[str],
) -> dict[str, Any]:
    sb = get_supabase()

    # Load league profile
    league_row = sb.table("leagues").select(
        "name, competitive_window, cap_philosophy, team_weaknesses, goals, sport"
    ).eq("id", league_id).single().execute()
    league = league_row.data

    # Load both rosters
    roster_rows = sb.table("rosters").select(
        "fantrax_team_id, team_name, roster_items, salary_cap"
    ).eq("league_id", league_id).in_(
        "fantrax_team_id", [my_team_id, opponent_team_id]
    ).execute()

    my_roster_row = next((r for r in roster_rows.data if r["fantrax_team_id"] == my_team_id), None)
    opp_roster_row = next((r for r in roster_rows.data if r["fantrax_team_id"] == opponent_team_id), None)

    if not my_roster_row or not opp_roster_row:
        raise ValueError("Could not load one or both rosters from Supabase.")

    # Collect all fantrax IDs across both rosters
    all_fantrax_ids = (
        [item["id"] for item in my_roster_row["roster_items"]] +
        [item["id"] for item in opp_roster_row["roster_items"]]
    )

    # Load resolved mappings from player_id_map table
    id_map_rows = sb.table("player_id_map").select(
        "fantrax_id, full_name, player_type, mlb_id, mlb_team"
    ).in_("fantrax_id", all_fantrax_ids).execute()

    # Build resolved lookup
    player_id_map = {
        row["fantrax_id"]: {
            "name": row["full_name"],
            "player_type": row["player_type"],
            "mlb_team": row.get("mlb_team") or "",
        }
        for row in id_map_rows.data
    }
    fantrax_to_mlb = {
        row["fantrax_id"]: row["mlb_id"]
        for row in id_map_rows.data
        if row.get("mlb_id")
    }

    # Fill in any unresolved players using the Fantrax getPlayerIds cache
    sport = league.get("sport", "MLB")
    unresolved_ids = [fid for fid in all_fantrax_ids if fid not in player_id_map]
    if unresolved_ids:
        from .fantrax_client import get_player_ids
        fantrax_name_map = get_player_ids(sport)
        for fid in unresolved_ids:
            player_data = fantrax_name_map.get(fid, {})
            name = player_data.get("name", f"Unknown ({fid})")
            if name:
                player_id_map[fid] = {
                    "name": name,
                    "player_type": "hitter",  # default, no position data available
                }

    # Fetch stats for all trade participants concurrently
    trade_ids = offering_ids + receiving_ids

    async def fetch_stat(fid):
        mlb_id = fantrax_to_mlb.get(fid)
        player_info = player_id_map.get(fid, {})
        player_type = player_info.get("player_type", "hitter")
        if mlb_id:
            return fid, await get_player_stats(mlb_id, player_type)
        return fid, None

    results = await asyncio.gather(*[fetch_stat(fid) for fid in trade_ids])
    trade_stats = dict(results)

    # Load category ranks from dashboard_cache
    category_ranks = {}
    try:
        import json as _json
        ranks_result = (
            sb.table("dashboard_cache")
            .select("content")
            .eq("league_id", league_id)
            .eq("widget", "category_ranks")
            .limit(1)
            .execute()
        )
        if ranks_result.data:
            category_ranks = _json.loads(ranks_result.data[0]["content"])
    except Exception:
        pass

    return {
        "league": league,
        "my_roster": my_roster_row,
        "opp_roster": opp_roster_row,
        "player_id_map": player_id_map,
        "fantrax_to_mlb": fantrax_to_mlb,
        "trade_stats": trade_stats,
        "offering_ids": offering_ids,
        "receiving_ids": receiving_ids,
        "category_ranks": category_ranks,
    }


def build_trade_prompt(context: dict[str, Any]) -> str:
    """
    Format the full context into a prompt string for Claude.
    """
    league = context["league"]
    my_roster = context["my_roster"]
    opp_roster = context["opp_roster"]
    player_id_map = context["player_id_map"]
    trade_stats = context["trade_stats"]
    offering_ids = context["offering_ids"]
    receiving_ids = context["receiving_ids"]

    my_items = my_roster["roster_items"]
    opp_items = opp_roster["roster_items"]

    # Team philosophy block
    category_ranks = context.get("category_ranks", {})
    if category_ranks:
        ranks_str = ", ".join(f"{cat}:{rank}" for cat, rank in category_ranks.items())
        num_teams = 10  # standard league size; ranks are absolute positions
        weak_cats = [cat for cat, rank in category_ranks.items() if isinstance(rank, int) and rank >= 7]
        category_context = f"Category ranks (1=best, {num_teams}=worst): {ranks_str}"
        if weak_cats:
            category_context += f"\n  Weakest categories: {', '.join(weak_cats)}"
    else:
        weak = league.get('team_weaknesses') or []
        category_context = f"Category weaknesses: {', '.join(weak) or 'Not set'}"

    philosophy = f"""
Manager's team philosophy:
  League: {league.get('name', 'Unknown')}
  Competitive window: {league.get('competitive_window') or 'Not set'}
  {category_context}
  Cap philosophy: {league.get('cap_philosophy') or 'Not set'}
  Season goals: {league.get('goals') or 'Not set'}
  Current salary cap: ${my_roster.get('salary_cap', 450)}"""

    # Proposed trade block
    offering_names = [
        get_player_name(fid, player_id_map) for fid in offering_ids
    ]
    receiving_names = [
        get_player_name(fid, player_id_map) for fid in receiving_ids
    ]

    trade_block = f"""
Proposed trade:
  Manager gives up: {', '.join(offering_names)}
  Manager receives: {', '.join(receiving_names)}"""

    # Stats block for trade participants
    stats_lines = ["\nStats for players in this trade:"]
    for fid in offering_ids + receiving_ids:
        name = get_player_name(fid, player_id_map)
        player_type = player_id_map.get(fid, {}).get("player_type", "hitter")
        stats = trade_stats.get(fid)
        mlb_team = player_id_map.get(fid, {}).get("mlb_team", "")
        stats_lines.append(format_stats_for_prompt(stats, name, player_type, mlb_team))

    stats_block = "\n".join(stats_lines)

    # Full rosters
    my_roster_block = format_roster_for_prompt(
        my_items, player_id_map,
        f"Manager's roster ({my_roster['team_name']})",
        highlight_ids=offering_ids,
    )
    opp_roster_block = format_roster_for_prompt(
        opp_items, player_id_map,
        f"Opponent's roster ({opp_roster['team_name']})",
        highlight_ids=receiving_ids,
    )

    # Cap impact
    giving_salary = sum(
        item["salary"] for item in my_items if item["id"] in offering_ids
    )
    receiving_salary = sum(
        item["salary"] for item in opp_items if item["id"] in receiving_ids
    )
    cap_delta = receiving_salary - giving_salary
    cap_impact = f"\nCap impact: {'saves' if cap_delta < 0 else 'costs'} ${abs(cap_delta)} (giving ${giving_salary}, receiving ${receiving_salary})"

    # Output format instructions
    format_instructions = """
Respond in exactly this format:

VERDICT
ACCEPT, DECLINE, or COUNTER — followed by one punchy sentence explaining why.

ANALYSIS
3-5 paragraphs. Be specific — name the players, cite the numbers, argue your recommendation.
Cover: player value relative to salary and contract year, cap impact, positional balance,
category impact (especially the manager's weak categories), and fit with their competitive window.
Consider whether any player involved could be cut and re-signed cheaper at auction.
Do not summarize both sides neutrally. Make the case.

COUNTER OFFER
If ACCEPT or DECLINE: briefly note whether a modified version of this trade is worth exploring,
or whether it is not worth countering at all.
If COUNTER: propose a specific modification to this trade — swap, add, or remove a player.
The counter must stay within the framework of this trade, not propose an entirely different deal.
When identifying what to ask for, prioritize players on the opponent's roster who address the
manager's identified category weaknesses. The modified deal should be fair to both sides or
tilt slightly in the manager's favor. Explain why the adjustment is justified."""

    return (
        philosophy
        + trade_block
        + cap_impact
        + stats_block
        + my_roster_block
        + opp_roster_block
        + format_instructions
    )


# Category -> (player_type, season_stat key, higher_is_better) for the Trade Finder.
# Cap how many opponent players we fetch live stats for, so the Trade Finder
# returns within the gateway timeout. Ranked by salary (a strong proxy for value
# in a contract league) before fetching, so realistic targets aren't dropped.
CANDIDATE_LIMIT = 30

CATEGORY_STAT = {
    "R": ("hitter", "runs", True),
    "HR": ("hitter", "home_runs", True),
    "RBI": ("hitter", "rbi", True),
    "SB": ("hitter", "stolen_bases", True),
    "OBP": ("hitter", "obp", True),
    "QS": ("pitcher", "quality_starts", True),
    "SV": ("pitcher", "saves", True),
    "K": ("pitcher", "strikeouts", True),
    "ERA": ("pitcher", "era", False),
    "WHIP": ("pitcher", "whip", False),
}


def _stat_to_float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


async def build_finder_context(
    league_id: str,
    my_team_id: str,
    target_category: str | None = None,
) -> dict[str, Any]:
    """
    Category-first Trade Finder. Picks (or accepts) a category the manager needs
    help in, then ranks opponent players across the league by their real
    production in that category. Returns the league profile, the resolved target
    category, and a stats-grounded candidate shortlist.
    """
    sb = get_supabase()

    league_row = sb.table("leagues").select(
        "name, competitive_window, cap_philosophy, team_weaknesses, goals"
    ).eq("id", league_id).single().execute()
    league = league_row.data or {}

    # Resolve the target category — explicit, else the weakest ranked category.
    category_ranks: dict = {}
    try:
        ranks_result = (
            sb.table("dashboard_cache")
            .select("content")
            .eq("league_id", league_id)
            .eq("widget", "category_ranks")
            .limit(1)
            .execute()
        )
        if ranks_result.data:
            import json as _json
            category_ranks = _json.loads(ranks_result.data[0]["content"])
    except Exception:
        pass

    if not target_category:
        ranked = {c: r for c, r in category_ranks.items() if c in CATEGORY_STAT and isinstance(r, int)}
        if ranked:
            target_category = max(ranked, key=ranked.get)  # highest rank number = weakest
    if not target_category or target_category not in CATEGORY_STAT:
        raise ValueError(
            "No target category. Set category ranks on the dashboard, or pass a category."
        )

    player_type, stat_key, higher_is_better = CATEGORY_STAT[target_category]

    # Load every roster except the manager's.
    roster_rows = sb.table("rosters").select(
        "fantrax_team_id, team_name, roster_items"
    ).eq("league_id", league_id).neq("fantrax_team_id", my_team_id).execute()
    opp_rosters = roster_rows.data or []

    # Resolve all opponent players to MLB IDs + player_type. Batch the IN filter —
    # the full opponent pool (~250 IDs) can exceed PostgREST's query-length limit.
    all_ids = [item["id"] for r in opp_rosters for item in r["roster_items"]]
    id_map = {}
    for i in range(0, len(all_ids), 100):
        chunk = all_ids[i:i + 100]
        rows = sb.table("player_id_map").select(
            "fantrax_id, full_name, player_type, mlb_id, mlb_team"
        ).in_("fantrax_id", chunk).execute()
        for row in (rows.data or []):
            id_map[row["fantrax_id"]] = row

    # Candidate pool: opponent players of the relevant type with a resolved MLB ID.
    candidates = []
    for roster in opp_rosters:
        for item in roster["roster_items"]:
            mapped = id_map.get(item["id"])
            if not mapped or mapped.get("player_type") != player_type or not mapped.get("mlb_id"):
                continue
            candidates.append({
                "fantrax_id": item["id"],
                "name": mapped["full_name"],
                "mlb_id": mapped["mlb_id"],
                "mlb_team": mapped.get("mlb_team") or "",
                "position": item.get("position", "?"),
                "salary": item.get("salary", 0),
                "contract": item.get("contract", {}).get("name", "?"),
                "owner_team_id": roster["fantrax_team_id"],
                "owner_team_name": roster["team_name"],
            })

    # Only fetch stats for the most valuable candidates (by salary) to stay fast.
    candidates.sort(key=lambda c: c["salary"], reverse=True)
    candidates = candidates[:CANDIDATE_LIMIT]

    # Fetch season stats (cached) with bounded concurrency, then score the category.
    sem = asyncio.Semaphore(12)

    async def score(cand):
        async with sem:
            stats = await get_player_stats(cand["mlb_id"], player_type)
        season = (stats or {}).get("season_stats", {})
        cand["stat_value"] = _stat_to_float(season.get(stat_key))
        return cand

    scored = await asyncio.gather(*[score(c) for c in candidates])
    ranked_candidates = [c for c in scored if c["stat_value"] is not None]
    ranked_candidates.sort(key=lambda c: c["stat_value"], reverse=higher_is_better)
    top = ranked_candidates[:12]

    return {
        "league": league,
        "target_category": target_category,
        "stat_key": stat_key,
        "candidates": top,
    }


def build_finder_prompt(context: dict[str, Any]) -> str:
    league = context["league"]
    category = context["target_category"]
    stat_key = context["stat_key"]
    candidates = context["candidates"]

    lines = [
        f"The manager needs help in {category}. Below are the best targets across the "
        f"league for that category, ranked by their {stat_key.replace('_', ' ')} this season.",
        "",
        f"Manager's team: {league.get('name', 'Unknown')} | "
        f"Window: {league.get('competitive_window') or 'Not set'} | "
        f"Cap philosophy: {league.get('cap_philosophy') or 'Not set'}",
        "",
        "Candidates (player | owner | pos | $salary | contract yr | category stat):",
    ]
    for c in candidates:
        lines.append(
            f"  {c['name']} | {c['owner_team_name']} | {c['position']} | "
            f"${c['salary']} | {c['contract']} yr | {category}={c['stat_value']}"
        )

    lines += [
        "",
        "Recommend the 2-3 most realistic acquisition targets from this list and why, "
        f"weighing their {category} production against salary and contract year. For each, "
        "suggest the rough shape of a fair offer (what kind of player/contract to send back) "
        "without inventing players or stats not provided. Be direct and specific. "
        "Do not return a table — write 2-4 short paragraphs.",
    ]
    return "\n".join(lines)