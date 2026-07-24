"""Football (Sleeper/NFL) trade analysis: dynasty market valuation, draft-pick
pricing, and the context/prompt builders for /trade/analyze and /trade/finder.

Kept separate from the MLB ``trade_analyzer`` so each sport stays clean; the API
dispatches by the league's sport. Player metadata is already embedded in the
shared ``rosters`` table (from the Sleeper sync), season fantasy points come from
Sleeper's in-process-cached season stats, and dynasty values come from the
in-process-cached FantasyCalc client — so this module does no live per-player
fetches.
"""
import asyncio
from datetime import datetime, timezone
from typing import Any

from .supabase_client import get_supabase
from .sleeper_client import get_season_stats
from . import fantasycalc
from .nfl_dynasty import (
    derive_fc_params,
    index_fc,
    league_position_averages,
    league_standing,
    team_posture,
)


def _market_values(rules: dict) -> tuple[dict, dict]:
    """FantasyCalc dynasty values for this league's settings, indexed for joins:
    ({sleeper_id: entry}, {pick_label: entry}). ({}, {}) when the API is
    unavailable — callers degrade to unpriced assets rather than fabricating
    numbers. Blocking; called from inside _load_blocking's worker thread."""
    try:
        params = derive_fc_params(rules or {})
        fc = fantasycalc.get_values(params["num_qbs"], params["ppr"], params["num_teams"])
        return index_fc(fc.get("entries"))
    except Exception:
        return {}, {}


async def _load_blocking(
    sb, league_id: str, team_ids: list | None = None
) -> tuple[dict, dict, list, dict, dict]:
    """League row, season stats, rosters, and dynasty market values — all
    blocking (sync Supabase + Sleeper's season-stats download on a cold cache +
    the FantasyCalc fetch), so off the event loop."""
    def load():
        league = _load_league(sb, league_id)
        stats = get_season_stats(stats_season())
        rosters = _load_rosters(sb, league_id, team_ids)
        fc_players, fc_picks = _market_values(league.get("rules") or {})
        return league, stats, rosters, fc_players, fc_picks
    return await asyncio.to_thread(load)

STARTABLE = ["QB", "RB", "WR", "TE"]


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


def _value_players(players: list, stats: dict, fmt_key: str, fc_players: dict) -> None:
    """Attach season production (`points`, `gp`, `ppg`, `pos_rank` — descriptive)
    and `value`: the player's dynasty market value, one cross-positional scale
    where the best asset in football sits near 10,000. Mutates in place.

    `value` used to be a percentile of points *within the player's own position*,
    which made every position's best player a 100 — so "my WR1 for your RB1"
    read as a perfectly even swap and the tools proposed trades nobody would
    take (Olave-for-Bijan, 100 vs 100, when the market says 3,898 vs 10,191).
    Only an absolute cross-positional scale can balance a deal, and it already
    accounts for age, scarcity, and this league's superflex/PPR/size settings.

    `value` is None when the market doesn't price a player. Never coerce that to
    0 — an unpriced deep-bench player is unknown, not worthless.
    """
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
        entry = fc_players.get(str(p.get("id") or "")) or {}
        p["value"] = entry.get("value")
        p["market_rank"] = entry.get("overallRank")


def _pick_assets(draft_picks: list, fc_picks: dict) -> list:
    """Tradeable pick assets priced on the same market scale as players — the
    old hand-tuned 0-100 pick curve was a third scale that never reconciled with
    either of the others."""
    assets = []
    for pk in draft_picks or []:
        try:
            season, rnd = int(pk["season"]), int(pk["round"])
        except (KeyError, TypeError, ValueError):
            continue
        label = (pk.get("label") or f"{season} R{rnd}").strip()
        entry = fc_picks.get(label) or {}
        assets.append({
            "id": f"pick:{season}:{rnd}:{pk.get('original_roster_id', '?')}",
            "name": pk.get("label") or f"{season} R{rnd}",
            "position": "PICK",
            "value": entry.get("value"),
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

VOICE: Write straight to the manager in the second person — "you", "your roster", "your WRs".
Never talk about them in the third person ("the manager has…", "this team should…") and never
address a general audience. Below, "the manager" and "your"/"my" all refer to the same person you
are advising — speak to them as "you".

NEVER narrate your process or tools. Do not mention web searches, the data provided, or any tool
limitation — no "based on my research", no "given the persistent tool limitation", no notes about
what you did, could, or could not check. If a fact can't be confirmed, just tell the manager what
to verify before pulling the trigger and move on. Open with the substance, not with meta-commentary.

IMPORTANT: Only reference player facts explicitly provided in this prompt — position, team, age,
injury status, fantasy production, and the value figures given. Do not use training knowledge to
invent injuries, depth-chart roles, or stats not provided; player situations change frequently.

Data grounding: rosters, ages, and injury designations below come from live data and may lag
reality by up to ~24 hours. If a fact you need isn't provided, treat it as unknown — say so and
tell the manager what to verify, rather than guessing. (Don't describe this as a tool or data
limitation; just name what to double-check.)

League format:
- {size}-team dynasty league, {fmt} scoring, {sf}
- No salary cap and no contracts — value is rest-of-career production plus positional scarcity
- Draft picks are tradeable assets; earlier rounds and nearer years are worth more
- Weigh roster construction, age / dynasty window, and bye weeks alongside raw production

Players carry age, injury status when listed, season fantasy points with games played and
points-per-game, and a positional rank (e.g. WR12 = 12th-best WR league-wide that season in this
scoring format).

Each asset also carries `value` — its dynasty trade value on the open market. This is ONE scale
across every position, where the best asset in football sits near 10,000 and rookie picks are
priced on the same scale. It already reflects age, positional scarcity, and this league's
superflex/PPR/size settings. Value is what balances a deal: compare the TOTAL value on each side.
Points explain why an asset is priced as it is; they never balance a trade on their own, because a
top RB and a mid WR can post similar points and be worth wildly different amounts.

An asset marked `unpriced` is outside the market's coverage (deep depth) — treat it as a marginal
throw-in, not as worthless, and say so rather than pretending to price it.

Value measures price, not willingness. A deal that is fair by value can still be one an owner
refuses, and a slight overpay for a genuine roster fit can be correct — judge the fit, but never
call a lopsided package fair."""


def _fmt_val(v) -> str:
    """Market values render as readable integers; missing means the market
    doesn't cover the asset, which must never look like a zero."""
    return f"{round(v):,}" if isinstance(v, (int, float)) else "unpriced"


def _fmt_asset(a: dict) -> str:
    if a.get("is_pick"):
        return f"{a['name']} (pick) | value {_fmt_val(a.get('value'))}"
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
    mkt = f" (#{a['market_rank']} overall)" if a.get("market_rank") else ""
    return (
        f"{a['name']} | {a.get('position', '?')} {a.get('team', '')} | {age}{inj} | "
        f"{pts_str} | value {_fmt_val(a.get('value'))}{mkt}"
    )


# Short window tag for a posture line — the roster-view verdict is a bit long
# for an inline "Team: …, thin at WR" summary.
_WINDOW_TAG = {
    "Ascending": "ascending",
    "Balanced": "balanced",
    "Win-now": "win-now",
    "Aging — sell high": "aging/selling",
}


def _format_nfl_posture(name: str, posture: dict) -> str:
    """One compact line of a team's roster-construction stance, or "" if there's
    nothing notable. The prompt-facing slice — mirrors the baseball
    _format_posture; never dumps the underlying numbers."""
    parts = []
    tag = _WINDOW_TAG.get((posture or {}).get("window"))
    if tag:
        parts.append(tag)
    if posture.get("picks"):
        parts.append(f"{posture['picks']} in picks")
    if posture.get("thin"):
        parts.append(f"thin at {', '.join(posture['thin'])}")
    if posture.get("surplus"):
        parts.append(f"surplus at {', '.join(posture['surplus'])}")
    if not parts:
        return ""
    return f"{name}: " + ", ".join(parts)


def _nfl_posture_map(rosters: list, by_team: dict, fc_players: dict,
                     fc_picks: dict, rules: dict, team_ids) -> dict[str, dict]:
    """{team_id: {team_name, window, thin, surplus, picks}} for the given teams.
    Pure math over already-loaded, already-valued rosters — no query."""
    averages = league_position_averages(by_team)
    roster_by_tid = {str(r.get("fantrax_team_id")): r for r in rosters}
    out = {}
    for tid in team_ids:
        raw = roster_by_tid.get(str(tid)) or {}
        picks = _pick_assets(raw.get("draft_picks"), fc_picks)
        standing = league_standing(rosters, fc_players, fc_picks, tid)
        out[str(tid)] = {
            "team_name": raw.get("team_name") or "",
            **team_posture(by_team.get(str(tid), by_team.get(tid, [])), picks,
                           rules, averages, standing),
        }
    return out


def _nfl_posture_block(context: dict) -> str | None:
    """The analyze prompt's posture section — your stance and theirs, so the
    model can argue fit (who a player helps more) not just raw value. None when
    neither side has anything notable."""
    mine = _format_nfl_posture("Your team", context.get("my_posture") or {})
    theirs = _format_nfl_posture(
        context.get("opp_team_name") or "Their team", context.get("opp_posture") or {}
    )
    lines = [ln for ln in (mine, theirs) if ln]
    if not lines:
        return None
    return "\nRoster posture (thin = a need they'd pay up to fill; surplus = depth to deal from):\n" + \
        "\n".join(f"  {ln}" for ln in lines)


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
    # Load the whole league (not just the two teams) so the counterparty's
    # thin/surplus reads are league-relative — one wider query, same pattern as
    # the roster endpoint.
    league, stats, rosters, fc_players, fc_picks = await _load_blocking(sb, league_id)
    rules = league.get("rules") or {}
    fmt_key = _format_key(rules)
    season = stats_season()
    my = next((r for r in rosters if r["fantrax_team_id"] == my_team_id), None)
    opp = next((r for r in rosters if r["fantrax_team_id"] == opponent_team_id), None)
    if not my or not opp:
        raise ValueError("Could not load both rosters.")

    # Value every team on one scale — needed for the league averages behind
    # posture, and for the two trading rosters' own asset values.
    by_team = {r["fantrax_team_id"]: [dict(it) for it in (r.get("roster_items") or [])]
               for r in rosters}
    for items in by_team.values():
        _value_players(items, stats, fmt_key, fc_players)
    my_players = by_team[my_team_id]
    opp_players = by_team[opponent_team_id]
    my_picks = _pick_assets(my.get("draft_picks"), fc_picks)
    opp_picks = _pick_assets(opp.get("draft_picks"), fc_picks)

    postures = _nfl_posture_map(rosters, by_team, fc_players, fc_picks, rules,
                                [my_team_id, opponent_team_id])

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
        "market_available": bool(fc_players),
        "my_posture": postures.get(str(my_team_id)),
        "opp_posture": postures.get(str(opponent_team_id)),
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

    # Spell the imbalance out rather than leaving two raw totals to be eyeballed
    # — a lopsided deal should be impossible to read as fair.
    hi, lo = max(give_val, get_val), min(give_val, get_val)
    if hi and lo:
        pct = round((hi - lo) / hi * 100)
        heavier = "you give" if give_val > get_val else "you get"
        gap = (
            " — within 5%, an even deal by market value"
            if pct <= 5
            else f" — the '{heavier}' side is {pct}% heavier"
        )
    else:
        gap = ""
    unpriced = [a["name"] for a in giving + getting if a.get("value") is None]
    unpriced_line = (
        f"  Not covered by the market (excluded from the totals): {', '.join(unpriced)}"
        if unpriced else None
    )

    def roster_block(label, players, picks):
        lines = [f"\n{label}:"]
        for p in sorted(players, key=lambda x: (x.get("value") or 0), reverse=True):
            lines.append(f"  {_fmt_asset(p)}")
        if picks:
            lines.append("  Picks: " + ", ".join(
                f"{p['name']} ({_fmt_val(p.get('value'))})" for p in picks
            ))
        return "\n".join(lines)

    stats_year = context.get("stats_season") or stats_season()
    market_line = (
        None if context.get("market_available", True)
        else "MARKET VALUES ARE UNAVAILABLE right now — every asset below is unpriced. Do not "
             "guess at numeric values or claim a package is balanced; judge the deal qualitatively "
             "on production, age, position and roster fit, and say plainly that market values "
             "could not be checked."
    )
    return "\n".join(line for line in [
        _nfl_today_line(),
        "",
        market_line,
        "" if market_line else None,
        f"Your team: {context['my_team_name']} | "
        f"Window: {league.get('competitive_window') or 'Not set'} | "
        f"Goals: {league.get('goals') or 'Not set'}",
        "",
        f"Fantasy points below are {stats_year} regular-season totals in this league's scoring "
        "format (gp = games played, ppg = points per game, and e.g. WR12 = league-wide positional "
        "rank that season). `value` is dynasty market value — one scale across all positions, best "
        "asset in football ≈ 10,000.",
        "",
        "Proposed trade:",
        f"  You GIVE: {', '.join(_fmt_asset(a) for a in giving) or '(nothing)'}",
        f"  You GET:  {', '.join(_fmt_asset(a) for a in getting) or '(nothing)'}",
        f"  Value sent: {round(give_val):,} | value received: {round(get_val):,}{gap}",
        unpriced_line,
        _nfl_posture_block(context),
        roster_block(f"Your roster ({context['my_team_name']})", context["my_players"], context["my_picks"]),
        roster_block(f"Their roster ({context['opp_team_name']})", context["opp_players"], context["opp_picks"]),
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
3-5 paragraphs, written straight to the manager as "you". Name the players and picks, cite the
points/ppg/positional ranks and ages, and argue the call. Cover positional scarcity (QB in
superflex), dynasty age/window (weigh each player's age against your competitive window), injury
flags, per-game production vs raw totals (a high total on 17 games is different from the same total
on 12), depth impact, and pick value. Make the case. Use the roster posture: a player who fills the
other side's thin spot is worth more to them than raw market value, and their surplus is what you can
most easily pry loose — factor that into whether they'd actually say yes.

COUNTER OFFER
If COUNTER, propose a specific tweak (swap/add/remove a player or pick) that stays within this deal
and is fair or tilts slightly to you. Aim the ask at their surplus and lead with a piece that fills
their thin spot, so the counter is one they'd realistically accept. Otherwise note whether a tweak is
worth exploring.""",
    ] if line is not None)


# ---------------------------------------------------------------------------
# Trade finder (position-need first)
# ---------------------------------------------------------------------------
def _detect_weak_position(my_players: list, all_players_by_team: dict) -> str:
    """The startable position where the manager's dynasty value is weakest
    relative to the league average. Was points-based, which asked the wrong
    question for a dynasty league — a position can be flush with last season's
    points and still be the thinnest thing you own going forward."""
    def team_pos_value(players, pos):
        return sum(p.get("value") or 0 for p in players if p.get("position") == pos)

    best_pos, best_deficit = "RB", float("-inf")
    n_teams = max(len(all_players_by_team), 1)
    for pos in STARTABLE:
        league_total = sum(team_pos_value(pl, pos) for pl in all_players_by_team.values())
        avg = league_total / n_teams
        deficit = avg - team_pos_value(my_players, pos)
        if deficit > best_deficit:
            best_deficit, best_pos = deficit, pos
    return best_pos


async def build_nfl_finder_context(
    league_id: str,
    my_team_id: str,
    target_position: str | None = None,
) -> dict[str, Any]:
    sb = get_supabase()
    league, stats, rosters, fc_players, fc_picks = await _load_blocking(sb, league_id)
    rules = league.get("rules") or {}
    fmt_key = _format_key(rules)
    season = stats_season()
    my = next((r for r in rosters if r["fantrax_team_id"] == my_team_id), None)
    if not my:
        raise ValueError("Could not load your roster.")
    opp_rosters = [r for r in rosters if r["fantrax_team_id"] != my_team_id]

    by_team = {r["fantrax_team_id"]: [dict(it) for it in (r.get("roster_items") or [])] for r in rosters}
    my_players = by_team[my_team_id]

    # Value every rostered player up front so the weak-spot read and the
    # candidate pool share one scale (values are absolute, not pool-relative).
    for items in by_team.values():
        _value_players(items, stats, fmt_key, fc_players)

    if not target_position:
        target_position = _detect_weak_position(my_players, by_team)
    target_position = target_position.upper()

    # Candidate pool: opponents' players at the target position, best first.
    candidates = []
    for r in opp_rosters:
        for it in by_team[r["fantrax_team_id"]]:
            if it.get("position") != target_position:
                continue
            candidates.append({**it, "owner_team_id": r["fantrax_team_id"], "owner_team_name": r.get("team_name", "")})

    candidates = [
        c for c in candidates
        if c.get("value") is not None or c.get("points") is not None
    ]
    candidates.sort(key=lambda c: (c.get("value") or 0, c.get("points") or 0), reverse=True)
    candidates = candidates[:12]

    my_picks = _pick_assets(my.get("draft_picks"), fc_picks)
    my_assets = my_players + my_picks

    # Posture for every owner of a shortlisted target, plus your own — pure math
    # over rosters already loaded and valued, so no extra query. Turns the finder
    # from a wishlist into matchmaking: who's thin where, who has picks to spend.
    posture_tids = {my_team_id, *(c["owner_team_id"] for c in candidates)}
    postures = _nfl_posture_map(rosters, by_team, fc_players, fc_picks, rules, posture_tids)

    return {
        "sport": "NFL",
        "league": league,
        "rules": rules,
        "stats_season": season,
        "target_position": target_position,
        "candidates": candidates,
        "my_assets": my_assets,
        "market_available": bool(fc_players),
        "team_postures": postures,
        "my_team_id": my_team_id,
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
        f"You need help at {pos}. Below are the best {pos} targets across the league, "
        "ranked by dynasty market value. Points shown are "
        f"{stats_year} regular-season totals in this league's scoring format (gp = games played, "
        "ppg = points per game, WR12-style = league-wide positional rank). `value` is dynasty "
        "market value on ONE scale across all positions — best asset in football ≈ 10,000 — and "
        "your tradeable assets, players and draft picks alike, are priced on that same scale. "
        "Weigh age and injury flags against your window, and per-game production against "
        "raw totals.",
        "",
        f"Your team: {league.get('name', 'Unknown')} | "
        f"Window: {league.get('competitive_window') or 'Not set'}",
        "",
        f"Acquisition targets at {pos} (id | player | pos team | age | points | value | owner):",
    ]
    for c in candidates:
        lines.append(f"  {c['id']} | {_fmt_asset(c)} | {c['owner_team_name']}")
    lines += ["", "Your tradeable assets (id | asset | value):"]
    for a in sorted(my_assets, key=lambda x: (x.get("value") or 0), reverse=True):
        lines.append(f"  {a['id']} | {_fmt_asset(a)}")

    # Posture block: your stance and each owning team's, so offers target owners
    # who actually need what you're deep in — deduped, in candidate order.
    postures = context.get("team_postures") or {}
    my_line = _format_nfl_posture("Your team", postures.get(str(context.get("my_team_id"))) or {})
    rival_lines, seen = [], set()
    for c in candidates:
        tid = str(c["owner_team_id"])
        if tid in seen:
            continue
        seen.add(tid)
        p = postures.get(tid) or {}
        line = _format_nfl_posture(p.get("team_name") or c["owner_team_name"], p)
        if line:
            rival_lines.append(f"  {line}")
    if my_line or rival_lines:
        lines += ["", "Roster posture (thin = a need they'd pay up to fill; surplus = depth to "
                  "deal from):"]
        if my_line:
            lines.append(f"  {my_line}")
        lines += rival_lines

    if not context.get("market_available", True):
        lines.insert(2, "MARKET VALUES ARE UNAVAILABLE right now — assets show as unpriced. Do not "
                        "claim any package is balanced; reason qualitatively from production, age "
                        "and position, and say values could not be checked.")

    lines += [
        "",
        f"Recommend the 2-3 most realistic {pos} targets and why. For EACH, construct a specific, "
        "fair offer using ONLY ids from 'Your tradeable assets' (players and/or picks) — name them. "
        "Aim for total value sent within ~15% of the target's market value — check the arithmetic, "
        "because a package that falls far short is one the other owner simply declines. Favor "
        "packaging depth + a pick to land a clear upgrade rather than a straight swap; a single "
        "mid-tier player almost never buys an elite one. Prefer targets whose owner is thin where "
        "you're deep, and lead your offer with your surplus and (for a pick-poor owner) a pick — "
        "that's what makes a deal they'd actually take. Never invent players, ids, or stats.",
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
# setup, so expendability is dynasty market value + positional depth relative to
# who's coming in.


async def build_nfl_add_drop_context(
    league_id: str,
    my_team_id: str,
    incoming: list[dict],       # [{"id": <sleeper id> | None, "name": <str>}]
    outgoing_ids: list[str],
) -> dict[str, Any]:
    sb = get_supabase()
    league, stats, rosters, fc_players, _fc_picks = await _load_blocking(sb, league_id)
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
    # Taxi players sit outside the main roster in Sleeper — cutting one doesn't
    # free the spot the manager is trying to clear, so they aren't candidates.
    drop_items = [
        it for it in my_items
        if it.get("id") not in exclude and it.get("status") != "taxi"
    ]

    _value_players(drop_items, stats, fmt_key, fc_players)

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
            f"{p.get('status', '')}{inj} | {p.get('points', '?')} pts | "
            f"value {_fmt_val(p.get('value'))}"
        )
    roster_block = "\n".join(drop_lines) or "  (none)"

    if spots > 0:
        ask = f"Recommend exactly which {spots} player(s) to drop"
        spots_line = f"You need to clear {spots} roster spot(s) to make this work."
    else:
        ask = "Recommend who is most expendable"
        spots_line = (
            "No drop is strictly required (the players already leaving cover the additions), "
            "but identify who is most expendable if you want to open a spot."
        )

    return "\n".join([
        _nfl_today_line(),
        "",
        f"You're making room on your roster ({context['team_name']}).",
        f"Adding:\n{incoming_lines}",
        f"Already dropping/trading away: {', '.join(outgoing) or 'none'}",
        spots_line,
        "",
        "Each drop candidate carries last season's fantasy points and a dynasty market value — "
        "one scale across all positions, where the best asset in football sits near 10,000. Lower "
        "value = more expendable, all else equal. 'unpriced' means the market doesn't cover him at "
        "all, which usually makes him the easiest cut — but check depth first.",
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
