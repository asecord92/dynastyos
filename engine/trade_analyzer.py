import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Any
from .supabase_client import get_supabase
from .mlb_stats_client import get_player_stats
from .rules import LeagueRules, ContractRules, load_rules
from .player_value import production_ratings, assign_values


def _today_line() -> str:
    """Anchor trade prompts to the current date so 'current value'/'this season'
    reasoning isn't interpreted against the model's training cutoff."""
    now = datetime.now(timezone.utc)
    return (
        f"Today's date is {now.strftime('%A, %B %d, %Y')}. All stats and rosters below "
        f"reflect the current {now.year} MLB season — evaluate players on their current "
        f"situation, not prior seasons."
    )


_SPORT_WORD = {"MLB": "baseball", "NFL": "football"}

# Persona + grounding preamble — sport-agnostic, stays static across leagues.
_PERSONA = """You are a sharp, opinionated dynasty {sport_word} trade advisor built into DynastyOS.
You give direct, defensible recommendations — not balanced summaries. You have a point of view and
you back it up with specifics. You never hedge without committing to a final answer. You are not a
journalist presenting both sides — you are a trusted advisor telling the manager what to do and why.

IMPORTANT: Only reference player facts explicitly provided in this prompt — current team, stats,
contract, and salary. Do not use your training knowledge to fill in details about any player.
Player situations change frequently and your training data may be wrong."""


def _money(v: float) -> str:
    """Render a dollar amount without a trailing .0 for whole numbers."""
    return str(int(v)) if float(v).is_integer() else str(v)


def _trajectory_example(draft: int, c: ContractRules) -> str:
    """Compute an extension salary path for a given draft price from the rule
    numbers, so the example stays accurate for any league's contract terms."""
    raise_ = int(c.extend_raise)
    cap = int(c.extend_cap)
    y3 = max(draft + raise_, int(c.extend_floor))
    y4 = min(y3 + raise_, cap)
    y5 = min(y4 + raise_, cap)
    floor_note = " (floor)" if y3 == int(c.extend_floor) else ""
    return (
        f"- Player drafted at ${draft}, extended in year 3 → ${y3}{floor_note}, "
        f"year 4 → ${y4}, year 5 → ${y5}."
    )


def _contract_block(c: ContractRules) -> str:
    raise_, floor, option, cap = (
        _money(c.extend_raise), _money(c.extend_floor),
        _money(c.option_raise), _money(c.extend_cap),
    )
    examples = "\n".join(_trajectory_example(d, c) for d in (5, 12, 20))
    return f"""Dynasty contract rules:
- 1st and 2nd year contracts: salary does not change from draft price
- 3rd year is the decision point:
  - EXTEND: salary increases by ${raise_} (floor of ${floor}). Player stays on your roster long-term.
  - OPTION: salary increases by ${option}. Player is dropped to the auction pool at end of season — you lose them entirely.
  - CUT: available at any time, any contract year. Player goes to free agency immediately.
- 4th year and beyond (extended players only): salary increases by ${raise_} every year, maximum ${cap}.
- No limit on contract years as long as you keep extending.

Extension trajectory examples:
{examples}
Any player drafted under ${floor} follows the same floor trajectory once extended. +${raise_}/year applies from year 4 onward.

Contract valuation framework — this is critical:
- 1st and 2nd year players are at their draft price. Their future cost is unknown until the 3rd year decision.
- A player's salary on a 4th+ year contract reflects cumulative ${raise_} raises since their extension point.
- The core dynasty question on any trade: is this player's current salary above or below what they would
  realistically go for at auction? If you can cut a $35 player and re-sign them for $20, you've gained
  $15 in cap space — but you risk losing them entirely or paying more. Contract assets (cheap, locked-in
  players on long extensions) are extremely valuable. Overpaid aging players on late contracts are liabilities.
- Always consider: would you rather have this player at this salary, or take your chances at auction?"""


def build_system_prompt(rules: LeagueRules | None = None, sport: str = "MLB") -> str:
    """Generate the trade advisor system prompt from a league's rules so each
    league produces an accurate prompt instead of the old hardcoded constants.
    The contract section is omitted entirely for non-contract leagues."""
    rules = rules or LeagueRules()
    sport_word = _SPORT_WORD.get(sport, "fantasy")

    parts = [_PERSONA.format(sport_word=sport_word)]

    fmt = [
        "League format:",
        f"- {rules.league_size}-team head-to-head category scoring (weekly matchups)",
        f"- Hitting categories: {', '.join(rules.scoring.hitting)}",
        f"- Pitching categories: {', '.join(rules.scoring.pitching)}",
        f"- In-season salary cap: ${_money(rules.in_season_cap)}",
        f"- Offseason auction budget: ${_money(rules.offseason_cap)}",
    ]
    parts.append("\n".join(fmt))

    if rules.contract is not None:
        parts.append(_contract_block(rules.contract))

    return "\n\n".join(parts)


# Backwards-compatible default (Inglorious Bashers / MLB) for any import site
# that hasn't been threaded through per-league rules yet.
SYSTEM_PROMPT = build_system_prompt()


# Caches whether the leagues.rules column exists yet (the migration is applied
# manually in Supabase). Avoids hammering a missing column with failed selects.
_rules_column_available: bool | None = None


def _load_league_rules(sb, league_id: str, league: dict) -> LeagueRules:
    """Best-effort per-league rules load. The ``rules`` column may not exist yet
    (manual migration), so a failed select falls back to defaults — keeping this
    deploy-order-independent. Once the column exists it is used on every call."""
    global _rules_column_available
    raw = None
    if _rules_column_available is not False:
        try:
            rr = sb.table("leagues").select("rules").eq("id", league_id).single().execute()
            raw = (rr.data or {}).get("rules")
            _rules_column_available = True
        except Exception:
            _rules_column_available = False
            raw = None
    return load_rules({"sport": league.get("sport"), "rules": raw})


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


def _pick_assets(draft_picks: list | None) -> list[dict]:
    """Turn stored draft picks into tradeable assets whose id matches what the
    trade builder sends (`pick:<season>:<round>:<original_owner>`)."""
    assets = []
    for pk in draft_picks or []:
        try:
            season, rnd = int(pk["season"]), int(pk["round"])
        except (KeyError, TypeError, ValueError):
            continue
        orig = pk.get("original_roster_id", "?")
        assets.append({
            "id": f"pick:{season}:{rnd}:{orig}",
            "name": pk.get("label") or f"{season} Round {rnd}",
            "is_pick": True,
        })
    return assets


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
    rules = _load_league_rules(sb, league_id, league)

    # Load both rosters
    roster_rows = sb.table("rosters").select(
        "fantrax_team_id, team_name, roster_items, draft_picks, salary_cap"
    ).eq("league_id", league_id).in_(
        "fantrax_team_id", [my_team_id, opponent_team_id]
    ).execute()

    my_roster_row = next((r for r in roster_rows.data if r["fantrax_team_id"] == my_team_id), None)
    opp_roster_row = next((r for r in roster_rows.data if r["fantrax_team_id"] == opponent_team_id), None)

    if not my_roster_row or not opp_roster_row:
        raise ValueError("Could not load one or both rosters from Supabase.")

    # Draft picks are tradeable assets; the builder sends them with `pick:` ids.
    my_picks = _pick_assets(my_roster_row.get("draft_picks"))
    opp_picks = _pick_assets(opp_roster_row.get("draft_picks"))
    pick_by_id = {a["id"]: a for a in my_picks + opp_picks}

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

    # Fetch stats for all trade participants concurrently (skip draft picks).
    trade_ids = [fid for fid in offering_ids + receiving_ids if not fid.startswith("pick:")]

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
        "rules": rules,
        "sport": league.get("sport") or "MLB",
        "my_roster": my_roster_row,
        "opp_roster": opp_roster_row,
        "player_id_map": player_id_map,
        "fantrax_to_mlb": fantrax_to_mlb,
        "trade_stats": trade_stats,
        "offering_ids": offering_ids,
        "receiving_ids": receiving_ids,
        "category_ranks": category_ranks,
        "my_picks": my_picks,
        "opp_picks": opp_picks,
        "pick_by_id": pick_by_id,
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

    # Draft picks are assets too; resolve a traded id to a player OR pick name.
    pick_by_id = context.get("pick_by_id", {})
    my_picks = context.get("my_picks", [])
    opp_picks = context.get("opp_picks", [])

    def name_of(fid: str) -> str:
        if fid in pick_by_id:
            return pick_by_id[fid]["name"]
        return get_player_name(fid, player_id_map)

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
    offering_names = [name_of(fid) for fid in offering_ids]
    receiving_names = [name_of(fid) for fid in receiving_ids]

    trade_block = f"""
Proposed trade:
  Manager gives up: {', '.join(offering_names)}
  Manager receives: {', '.join(receiving_names)}"""

    # Stats block for trade participants (players only — picks have no stats).
    stats_lines = ["\nStats for players in this trade:"]
    for fid in offering_ids + receiving_ids:
        if fid in pick_by_id:
            continue
        name = get_player_name(fid, player_id_map)
        player_type = player_id_map.get(fid, {}).get("player_type", "hitter")
        stats = trade_stats.get(fid)
        mlb_team = player_id_map.get(fid, {}).get("mlb_team", "")
        stats_lines.append(format_stats_for_prompt(stats, name, player_type, mlb_team))

    stats_block = "\n".join(stats_lines)

    # Full rosters, each followed by that team's tradeable draft picks.
    def picks_line(picks: list) -> str:
        return "\n  Draft picks: " + ", ".join(p["name"] for p in picks) if picks else ""

    my_roster_block = format_roster_for_prompt(
        my_items, player_id_map,
        f"Manager's roster ({my_roster['team_name']})",
        highlight_ids=offering_ids,
    ) + picks_line(my_picks)
    opp_roster_block = format_roster_for_prompt(
        opp_items, player_id_map,
        f"Opponent's roster ({opp_roster['team_name']})",
        highlight_ids=receiving_ids,
    ) + picks_line(opp_picks)

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
If draft picks are involved, weigh them as dynasty prospect capital — earlier rounds and nearer
years are worth more, and a rebuilder should value picks higher than a win-now contender.
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
        _today_line()
        + "\n"
        + philosophy
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


# Opportunity denominator for rate stats — a player below the floor (see
# player_value._MIN_OPPORTUNITY) is dropped from that category's percentile, so a
# tiny-sample fluke (a .600 OBP on 8 PA) can't inflate their talent score.
RATE_STAT_WEIGHT = {
    "obp": "plate_appearances",
    "era": "innings_pitched",
    "whip": "innings_pitched",
}


def _type_specs(categories: list[str]) -> list[tuple[str, bool, str | None]]:
    """Translate a league's category codes into
    (season_stat_key, higher_is_better, weight_key) specs for valuation, skipping
    any code without a known stat mapping. ``weight_key`` is the opportunity
    denominator for a rate stat, else ``None``."""
    specs = []
    for cat in categories:
        mapping = CATEGORY_STAT.get(cat)
        if mapping:
            _, stat_key, higher_is_better = mapping
            specs.append((stat_key, higher_is_better, RATE_STAT_WEIGHT.get(stat_key)))
    return specs


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
        "name, competitive_window, cap_philosophy, team_weaknesses, goals, sport"
    ).eq("id", league_id).single().execute()
    league = league_row.data or {}
    rules = _load_league_rules(sb, league_id, league)

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
        cand["season"] = season
        cand["player_type"] = player_type
        cand["stat_value"] = _stat_to_float(season.get(stat_key))
        return cand

    scored = await asyncio.gather(*[score(c) for c in candidates])
    ranked_candidates = [c for c in scored if c["stat_value"] is not None]
    ranked_candidates.sort(key=lambda c: c["stat_value"], reverse=higher_is_better)
    top = ranked_candidates[:12]

    # Load the manager's own roster so we can suggest concrete, value-balanced
    # packages to send back — not just the abstract "shape" of an offer.
    my_row = sb.table("rosters").select(
        "roster_items, salary_cap"
    ).eq("league_id", league_id).eq("fantrax_team_id", my_team_id).limit(1).execute()
    my_data = (my_row.data or [{}])[0]
    my_items = my_data.get("roster_items") or []
    salary_cap = my_data.get("salary_cap")

    my_ids = [item["id"] for item in my_items]
    my_id_map = {}
    for i in range(0, len(my_ids), 100):
        chunk = my_ids[i:i + 100]
        rows = sb.table("player_id_map").select(
            "fantrax_id, full_name, player_type, mlb_id"
        ).in_("fantrax_id", chunk).execute()
        for row in (rows.data or []):
            my_id_map[row["fantrax_id"]] = row

    my_assets = []
    for item in my_items:
        mapped = my_id_map.get(item["id"])
        if not mapped or not mapped.get("mlb_id"):
            continue
        my_assets.append({
            "fantrax_id": item["id"],
            "name": mapped["full_name"],
            "mlb_id": mapped["mlb_id"],
            "player_type": mapped.get("player_type") or "hitter",
            "position": item.get("position", "?"),
            "salary": item.get("salary", 0),
            "contract": item.get("contract", {}).get("name", "?"),
        })

    async def fetch_season(p):
        async with sem:
            stats = await get_player_stats(p["mlb_id"], p["player_type"])
        p["season"] = (stats or {}).get("season_stats", {})
        return p

    await asyncio.gather(*[fetch_season(p) for p in my_assets])

    # Value both sides on a shared within-type percentile scale so package totals
    # are comparable. Pool each type from the candidate shortlist + my roster.
    type_specs = {
        "hitter": _type_specs(rules.scoring.hitting),
        "pitcher": _type_specs(rules.scoring.pitching),
    }
    pool = top + my_assets
    for ptype, specs in type_specs.items():
        group = [p for p in pool if p.get("player_type") == ptype]
        production_ratings(group, specs)
        assign_values(group)

    return {
        "league": league,
        "rules": rules,
        "sport": league.get("sport") or "MLB",
        "target_category": target_category,
        "stat_key": stat_key,
        "candidates": top,
        "my_assets": my_assets,
        "salary_cap": salary_cap,
    }


def _fmt_num(v) -> str:
    return str(v) if v is not None else "?"


def build_finder_prompt(context: dict[str, Any]) -> str:
    league = context["league"]
    category = context["target_category"]
    stat_key = context["stat_key"]
    candidates = context["candidates"]
    my_assets = context.get("my_assets", [])
    salary_cap = context.get("salary_cap")

    cap_line = f" | Salary cap: ${salary_cap}" if salary_cap else ""
    lines = [
        _today_line(),
        "",
        f"The manager needs help in {category}. Below are the best targets across the "
        f"league for that category, ranked by their {stat_key.replace('_', ' ')} this season. "
        "Each player carries two scores: talent (0-100 production percentile, cost-blind) and "
        "value (talent adjusted up/down for salary and contract year — i.e. asset worth). Use "
        "value to balance packages; use talent when you want to compare pure production apart "
        "from cost.",
        "",
        f"Manager's team: {league.get('name', 'Unknown')} | "
        f"Window: {league.get('competitive_window') or 'Not set'} | "
        f"Cap philosophy: {league.get('cap_philosophy') or 'Not set'}{cap_line}",
        "",
        "Acquisition targets (id | player | owner | pos | $salary | contract yr | "
        f"{category} | talent | value):",
    ]
    for c in candidates:
        lines.append(
            f"  {c['fantrax_id']} | {c['name']} | {c['owner_team_name']} | {c['position']} | "
            f"${c['salary']} | {c['contract']} yr | {category}={c['stat_value']} | "
            f"talent={_fmt_num(c.get('talent'))} | value={_fmt_num(c.get('value'))}"
        )

    lines += [
        "",
        "Your tradeable assets (id | player | pos | $salary | contract yr | talent | value):",
    ]
    if my_assets:
        for p in sorted(my_assets, key=lambda x: (x.get("value") or 0), reverse=True):
            lines.append(
                f"  {p['fantrax_id']} | {p['name']} | {p['position']} | "
                f"${p['salary']} | {p['contract']} yr | "
                f"talent={_fmt_num(p.get('talent'))} | value={_fmt_num(p.get('value'))}"
            )
    else:
        lines.append("  (none resolved)")

    lines += [
        "",
        "Recommend the 2-3 most realistic acquisition targets and why, weighing their "
        f"{category} production against salary and contract year. For EACH recommended target, "
        "construct a specific, fair offer using ONLY players from 'Your tradeable assets' above "
        "— name them explicitly. Aim for the total value sent to land within ~15% of the "
        "target's value (a contender may pay slightly over; a rebuilder should aim slightly "
        "under), and respect the salary cap. Never invent players, ids, or stats not provided.",
        "",
        "Favor CONSOLIDATION over one-for-one swaps: to pry loose a high-value target, package "
        "two or three complementary lower-value players (depth, a redundant position, a useful "
        "but non-core piece) whose combined value reaches the target — managers rarely trade a "
        "star straight up for a single comparable star. Only offer a single player when one of "
        "your assets genuinely matches the target's value on its own. At least one of your "
        "suggested packages should be a multi-player offer.",
        "",
        "Write 2-4 short paragraphs, then end your response with a fenced ```json block (and "
        "nothing after it) listing the offers you described, using the numeric ids from the "
        "lists above, in exactly this schema:",
        "```json",
        '[{"target_ids": ["<target id>"], "offer_ids": ["<your asset id>", "..."], '
        '"rationale": "<one sentence>"}]',
        "```",
        "Only include offers you actually recommend.",
    ]
    return "\n".join(lines)


def _extract_json_block(text: str) -> str | None:
    """Pull the JSON array out of the model's fenced block (preferring an explicit
    ```json fence, falling back to any fenced array)."""
    m = re.search(r"```json\s*(.+?)\s*```", text, re.DOTALL)
    if m:
        return m.group(1)
    m = re.search(r"```\s*(\[.+?\])\s*```", text, re.DOTALL)
    if m:
        return m.group(1)
    return None


def parse_finder_response(
    text: str, candidates: list[dict], my_assets: list[dict]
) -> tuple[str, list[dict]]:
    """Split the finder model output into (display prose, validated packages).

    Packages come from the fenced JSON block the prompt requests and are checked
    against the offered players, so the UI only ever shows real, loadable trades
    (ids that exist, targets from a single opponent). The JSON block is stripped
    from the returned prose.
    """
    cand_by_id = {c["fantrax_id"]: c for c in candidates}
    asset_by_id = {p["fantrax_id"]: p for p in my_assets}

    packages: list[dict] = []
    raw = _extract_json_block(text)
    if raw:
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            data = None
        if isinstance(data, list):
            for entry in data:
                if not isinstance(entry, dict):
                    continue
                targets = [cand_by_id[t] for t in (entry.get("target_ids") or []) if t in cand_by_id]
                offers = [asset_by_id[o] for o in (entry.get("offer_ids") or []) if o in asset_by_id]
                if not targets or not offers:
                    continue
                owner_id = targets[0]["owner_team_id"]
                targets = [t for t in targets if t["owner_team_id"] == owner_id]
                packages.append({
                    "owner_team_id": owner_id,
                    "owner_team_name": targets[0]["owner_team_name"],
                    "target_ids": [t["fantrax_id"] for t in targets],
                    "offer_ids": [o["fantrax_id"] for o in offers],
                    "targets": [{"fantrax_id": t["fantrax_id"], "name": t["name"]} for t in targets],
                    "offer": [{"fantrax_id": o["fantrax_id"], "name": o["name"]} for o in offers],
                    "rationale": str(entry.get("rationale") or "").strip(),
                })

    clean = re.sub(r"```json\s*.+?\s*```", "", text, flags=re.DOTALL)
    clean = re.sub(r"```\s*\[.+?\]\s*```", "", clean, flags=re.DOTALL).strip()
    return clean, packages


# --- Add/Drop analyzer --------------------------------------------------------
# "I'm adding these players (IL activation / trade arrival / waiver pickup) and
# already dropping these — who else do I cut to make room?" Reuses the finder's
# roster-resolve + valuation, then asks the model to rank the manager's most
# expendable players, weighing talent, positional redundancy relative to who's
# coming in, category impact, and contract cost.


async def build_add_drop_context(
    league_id: str,
    my_team_id: str,
    incoming: list[dict],       # [{"id": <fantrax_id> | None, "name": <str>}]
    outgoing_ids: list[str],    # fantrax ids already being dropped / traded away
) -> dict[str, Any]:
    sb = get_supabase()

    league_row = sb.table("leagues").select(
        "name, competitive_window, cap_philosophy, team_weaknesses, goals, sport"
    ).eq("id", league_id).single().execute()
    league = league_row.data or {}
    rules = _load_league_rules(sb, league_id, league)

    # Load every roster: mine is the drop pool; the full set lets us resolve an
    # incoming player who is already rostered (IL activation or trade arrival).
    roster_rows = sb.table("rosters").select(
        "fantrax_team_id, team_name, roster_items, salary_cap"
    ).eq("league_id", league_id).execute()
    rosters = roster_rows.data or []
    my_row = next((r for r in rosters if r["fantrax_team_id"] == my_team_id), None)
    if not my_row:
        raise ValueError("Could not load your roster. Sync your league first.")
    my_items = my_row.get("roster_items") or []

    item_by_id = {
        item["id"]: item
        for r in rosters for item in r.get("roster_items", [])
        if item.get("id")
    }

    incoming_ids = [inc["id"] for inc in incoming if inc.get("id")]

    # Drop candidates: my roster minus what's already leaving, minus any incoming
    # player already on my roster (activating them is the whole point).
    exclude = set(outgoing_ids) | set(incoming_ids)
    drop_items = [item for item in my_items if item.get("id") not in exclude]

    # Resolve my roster + incoming rostered players in one batched pass.
    resolve_ids = [item["id"] for item in my_items] + incoming_ids
    id_map: dict[str, dict] = {}
    for i in range(0, len(resolve_ids), 100):
        chunk = resolve_ids[i:i + 100]
        rows = sb.table("player_id_map").select(
            "fantrax_id, full_name, player_type, mlb_id, mlb_team, roster_status, il_type"
        ).in_("fantrax_id", chunk).execute()
        for row in (rows.data or []):
            id_map[row["fantrax_id"]] = row

    sem = asyncio.Semaphore(12)

    async def build_asset(item):
        mapped = id_map.get(item["id"], {})
        mlb_id = mapped.get("mlb_id")
        ptype = mapped.get("player_type") or "hitter"
        season = {}
        if mlb_id:
            async with sem:
                stats = await get_player_stats(mlb_id, ptype)
            season = (stats or {}).get("season_stats", {})
        return {
            "fantrax_id": item["id"],
            "name": mapped.get("full_name") or item.get("name") or f"Unknown ({item['id']})",
            "player_type": ptype,
            "position": item.get("position", "?"),
            "salary": item.get("salary", 0),
            "contract": (item.get("contract") or {}).get("name", "?"),
            "status": item.get("status", ""),
            "roster_status": mapped.get("roster_status") or "",
            "il_type": mapped.get("il_type") or "",
            "season": season,
        }

    drop_assets = list(await asyncio.gather(*[build_asset(it) for it in drop_items]))

    # Value candidates on the shared talent/value scale (per type).
    type_specs = {
        "hitter": _type_specs(rules.scoring.hitting),
        "pitcher": _type_specs(rules.scoring.pitching),
    }
    for ptype, specs in type_specs.items():
        group = [p for p in drop_assets if p.get("player_type") == ptype]
        production_ratings(group, specs)
        assign_values(group)

    # Resolve incoming (position/type from rosters+id_map; name-only for free text).
    incoming_resolved = []
    for inc in incoming:
        fid = inc.get("id")
        if fid:
            mapped = id_map.get(fid, {})
            item = item_by_id.get(fid, {})
            incoming_resolved.append({
                "name": mapped.get("full_name") or inc.get("name") or f"Unknown ({fid})",
                "position": item.get("position", "?"),
                "player_type": mapped.get("player_type") or "?",
            })
        else:
            incoming_resolved.append({
                "name": (inc.get("name") or "Unknown").strip(),
                "position": "?",
                "player_type": "?",
            })

    outgoing_named = [
        (id_map.get(oid, {}).get("full_name")
         or item_by_id.get(oid, {}).get("name")
         or f"Unknown ({oid})")
        for oid in outgoing_ids
    ]

    category_ranks: dict = {}
    try:
        ranks_result = sb.table("dashboard_cache").select("content").eq(
            "league_id", league_id).eq("widget", "category_ranks").limit(1).execute()
        if ranks_result.data:
            category_ranks = json.loads(ranks_result.data[0]["content"])
    except Exception:
        pass

    return {
        "league": league,
        "rules": rules,
        "sport": league.get("sport") or "MLB",
        "team_name": my_row.get("team_name") or "Your Team",
        "salary_cap": my_row.get("salary_cap"),
        "drop_assets": drop_assets,
        "incoming": incoming_resolved,
        "outgoing": outgoing_named,
        "spots_needed": max(0, len(incoming) - len(outgoing_ids)),
        "category_ranks": category_ranks,
    }


def build_add_drop_prompt(context: dict[str, Any]) -> str:
    drops = context["drop_assets"]
    incoming = context["incoming"]
    outgoing = context["outgoing"]
    spots = context["spots_needed"]
    cat_ranks = context.get("category_ranks", {})
    cap = context.get("salary_cap")

    weak = [c for c, r in cat_ranks.items() if isinstance(r, int) and r >= 7]
    ranks_str = ", ".join(f"{c}:{r}" for c, r in cat_ranks.items()) if cat_ranks else "not set"

    incoming_lines = "\n".join(f"  {p['name']} | {p['position']}" for p in incoming) or "  (none)"

    drop_lines = []
    for p in drops:
        status = p["status"] or p["roster_status"] or "active"
        il = f" ({p['il_type']})" if p["il_type"] else ""
        drop_lines.append(
            f"  {p['fantrax_id']} | {p['name']} | {p['position']} | ${p['salary']} | "
            f"{p['contract']} yr | {status}{il} | "
            f"talent={_fmt_num(p.get('talent'))} | value={_fmt_num(p.get('value'))}"
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

    parts = [
        _today_line(),
        "",
        f"The manager is making room on their roster ({context['team_name']}).",
        f"Adding:\n{incoming_lines}",
        f"Already dropping/trading away: {', '.join(outgoing) or 'none'}",
        spots_line,
        "",
        f"Category ranks (1=best, 10=worst): {ranks_str}"
        + (f"\nWeakest categories: {', '.join(weak)}" if weak else ""),
    ]
    if cap:
        parts.append(f"Salary cap: ${cap}")
    parts += [
        "",
        "Each drop candidate carries talent (0-100 production percentile, cost-blind) and value "
        "(talent adjusted for salary/contract). Lower = more expendable, all else equal.",
        "",
        "Drop candidates (id | player | pos | $salary | contract yr | status | talent | value):",
        roster_block,
        "",
        f"{ask} to make this work. Rank them from most to least droppable. For EACH, give a "
        "one-line rationale weighing: talent/production, positional redundancy RELATIVE TO who's "
        "coming in (never drop the manager's only player at a position the incoming players don't "
        "cover), impact on weak categories (don't gut a category they're already thin in), and "
        "salary/contract (prefer shedding overpriced or expiring players; protect cheap, "
        "cost-controlled young talent). Prefer dropping IL/bench stashes and redundant depth first.",
        "",
        "Format: one short summary sentence, then a numbered list — "
        "'1. **Player Name** (pos, $salary, contract yr) — rationale'. Recommend ONLY players "
        "from the drop candidates list above; never invent players or stats.",
    ]
    return "\n".join(parts)