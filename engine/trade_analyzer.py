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


def format_stats_for_prompt(player_stats: dict, name: str, player_type: str) -> str:
    if not player_stats:
        return f"  {name}: No stats available (prospect or no MLB appearances yet)"

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
        "fantrax_id, full_name, player_type, mlb_id"
    ).in_("fantrax_id", all_fantrax_ids).execute()

    # Build resolved lookup
    player_id_map = {
        row["fantrax_id"]: {"name": row["full_name"], "player_type": row["player_type"]}
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

    return {
        "league": league,
        "my_roster": my_roster_row,
        "opp_roster": opp_roster_row,
        "player_id_map": player_id_map,
        "fantrax_to_mlb": fantrax_to_mlb,
        "trade_stats": trade_stats,
        "offering_ids": offering_ids,
        "receiving_ids": receiving_ids,
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
    philosophy = f"""
Manager's team philosophy:
  League: {league.get('name', 'Unknown')}
  Competitive window: {league.get('competitive_window') or 'Not set'}
  Category weaknesses: {', '.join(league.get('team_weaknesses') or []) or 'Not set'}
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
        stats_lines.append(format_stats_for_prompt(stats, name, player_type))

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
If ACCEPT or DECLINE: one sentence on whether a counter was worth exploring.
If COUNTER: name the exact players to swap and explain why it's fair but better for the manager."""

    return (
        philosophy
        + trade_block
        + cap_impact
        + stats_block
        + my_roster_block
        + opp_roster_block
        + format_instructions
    )
