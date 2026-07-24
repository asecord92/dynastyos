"""Deterministic dynasty logic for the NFL roster view: age-curve bands,
FantasyCalc param derivation and joins, positional depth flags, and the
roster-window verdict. Pure functions over already-loaded data — no I/O and no
AI, so the always-on roster page costs nothing per view. Unit-test target
(tests/test_nfl_dynasty.py)."""

from collections import Counter

# Per-position (ascending ≤, prime ≤, aging ≤) age edges; older = cliff.
# K/DEF get no curve — age barely moves their dynasty value.
AGE_BANDS = {
    "RB": (22, 25, 27),
    "WR": (23, 28, 30),
    "TE": (24, 29, 31),
    "QB": (24, 32, 35),
}

_STAGE_SCORE = {"ascending": 0.0, "prime": 1.0, "aging": 2.0, "cliff": 3.0}

# Sleeper roster_positions entries that aren't starting lineup slots.
_NON_STARTING = {"BN", "TAXI", "IR"}

# Statuses that can actually take a lineup slot this week.
_STARTABLE = {"starter", "bench"}

# Posture thresholds: a position's startable market value vs the league average
# for that position. Tunable; kept as constants so tuning never needs a cache
# rebuild — posture is computed on read, never persisted.
_THIN_RATIO = 0.6
_SURPLUS_RATIO = 1.4
_POSTURE_POSITIONS = ("QB", "RB", "WR", "TE")


def age_band(position: str | None, age) -> str | None:
    """ascending | prime | aging | cliff, or None (no curve / unknown age)."""
    edges = AGE_BANDS.get(position or "")
    if not edges or not isinstance(age, (int, float)):
        return None
    ascending, prime, aging = edges
    if age <= ascending:
        return "ascending"
    if age <= prime:
        return "prime"
    if age <= aging:
        return "aging"
    return "cliff"


def derive_fc_params(rules: dict) -> dict:
    """FantasyCalc query params from a synced Sleeper rules blob. `ppr` is the
    raw rec value (leagues run 0.25, 1.5, …) snapped to FantasyCalc's 0/0.5/1;
    numQbs counts QB + SUPER_FLEX slots so true 2-QB leagues also price QBs as
    premium."""
    rules = rules or {}
    positions = rules.get("roster_positions") or []
    qb_slots = sum(1 for p in positions if p in ("QB", "SUPER_FLEX"))
    num_qbs = 2 if (qb_slots >= 2 or rules.get("superflex")) else 1
    raw = rules.get("ppr")
    raw = raw if isinstance(raw, (int, float)) else 0
    ppr = 1 if raw >= 0.75 else (0.5 if raw >= 0.25 else 0)
    size = rules.get("league_size")
    num_teams = int(size) if isinstance(size, (int, float)) and size else 10
    return {"num_qbs": num_qbs, "ppr": ppr, "num_teams": num_teams}


def index_fc(entries: list | None) -> tuple[dict, dict]:
    """Split a FantasyCalc response into lookups: players keyed by sleeperId
    (exact match to our roster item ids) and picks keyed by name — generic
    future-pick names ("2027 1st") exactly match compute_pick_inventory labels.
    Slot-specific current-year picks ("2026 Pick 1.01") simply never match."""
    players: dict[str, dict] = {}
    picks: dict[str, dict] = {}
    for e in entries or []:
        p = e.get("player") or {}
        if p.get("position") == "PICK":
            picks[(p.get("name") or "").strip()] = e
        else:
            sid = str(p.get("sleeperId") or "")
            if sid:
                players[sid] = e
    return players, picks


def starting_slots(roster_positions: list | None) -> list[str]:
    return [p for p in roster_positions or [] if p and p not in _NON_STARTING]


def _ordinal(n: int) -> str:
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def league_standing(rosters: list | None, fc_players: dict, fc_picks: dict,
                    my_team_id: str) -> dict | None:
    """Rank every synced team by total roster value and by pick capital, and
    return where the owner lands. A bare percentage ("picks are 29% of what you
    own") means nothing without a reference point; "2nd-most in the league"
    does — and every rival's roster is already in the rosters table, so this
    costs one wider query and pure math. None when values are unavailable."""
    if not fc_players and not fc_picks:
        return None
    rows = []
    for r in rosters or []:
        team_id = str(r.get("fantrax_team_id") or "")
        roster_value = sum(
            (fc_players.get(str(it.get("id") or "")) or {}).get("value") or 0
            for it in (r.get("roster_items") or [])
        )
        pick_value = sum(
            (fc_picks.get((pk.get("label") or "").strip()) or {}).get("value") or 0
            for pk in (r.get("draft_picks") or [])
        )
        rows.append({"team_id": team_id, "roster_value": roster_value,
                     "pick_value": pick_value})
    mine = next((r for r in rows if r["team_id"] == str(my_team_id)), None)
    if not mine or len(rows) < 2:
        return None

    def rank_of(key: str) -> int:
        ordered = sorted(rows, key=lambda r: r[key], reverse=True)
        return next(i for i, r in enumerate(ordered, 1) if r["team_id"] == mine["team_id"])

    return {
        "size": len(rows),
        "value_rank": rank_of("roster_value"),
        "pick_rank": rank_of("pick_value"),
        "roster_value": mine["roster_value"],
        "pick_value": mine["pick_value"],
    }


def depth_flags(players: list[dict], rules: dict) -> list[dict]:
    """At most 3 deterministic lineup-construction warnings, worst first, from
    startable bodies (taxi/IR excluded) vs dedicated slots. FLEX-type slots are
    ignored on purpose: a dedicated slot can only be filled by its position, so
    `have < need` is a real hole regardless of flex math."""
    rules = rules or {}
    slots = starting_slots(rules.get("roster_positions"))
    dedicated = Counter(s for s in slots if s in ("QB", "RB", "WR", "TE", "K", "DEF"))
    available = Counter(
        p.get("position") for p in players if p.get("status") in _STARTABLE
    )
    superflex = bool(rules.get("superflex")) or "SUPER_FLEX" in slots

    flags: list[dict] = []
    qb_critical = False
    for pos in ("QB", "RB", "WR", "TE", "K", "DEF"):
        need, have = dedicated.get(pos, 0), available.get(pos, 0)
        if need and have < need:
            qb_critical = qb_critical or pos == "QB"
            flags.append({
                "level": "critical",
                "text": f"Only {have} startable {pos} for {need} {pos} "
                        f"slot{'s' if need != 1 else ''} — you can't field a legal lineup.",
            })
    if superflex and not qb_critical and available.get("QB", 0) < 2:
        flags.append({
            "level": "critical",
            "text": f"Superflex league with only {available.get('QB', 0)} startable QB — "
                    "a second QB is the top roster priority.",
        })
    for pos in ("QB", "RB", "WR", "TE"):
        need, have = dedicated.get(pos, 0), available.get(pos, 0)
        if pos == "QB" and superflex:
            continue  # QB thinness in superflex is already the flag above
        if need and have == need:
            flags.append({
                "level": "warn",
                "text": f"No depth behind your {pos} starter{'s' if need != 1 else ''} "
                        f"({have} rostered for {need} slot{'s' if need != 1 else ''}).",
            })
    flags.sort(key=lambda f: 0 if f["level"] == "critical" else 1)
    return flags[:3]


def _picks_phrase(pick_share: float, standing: dict | None) -> tuple[str, bool]:
    """How to describe the pick stash, plus whether it counts as 'real' capital.
    League-relative when we can see rivals (a rank is a reference point a bare
    percentage never gives you); falls back to share-of-assets otherwise."""
    if standing:
        rank, size = standing["pick_rank"], standing["size"]
        strong = rank <= max(1, size // 3)
        if rank == 1:
            return "you hold the most draft capital in the league", True
        if strong:
            return f"you hold the {_ordinal(rank)}-most draft capital of {size} teams", True
        if rank > (size * 2) // 3:
            # Parenthesised, not em-dashed: these phrases land inside sentences
            # that already carry an em-dash.
            return f"your draft capital is thin ({_ordinal(rank)} of {size})", False
        return f"your draft capital is middle of the pack ({_ordinal(rank)} of {size})", False
    pct = round(pick_share * 100)
    if pick_share >= 0.15:
        return f"picks make up a real slice of your assets ({pct}%)", True
    return f"you're light on picks ({pct}% of your assets)", False


def roster_window(players: list[dict], picks: list[dict], rules: dict,
                  standing: dict | None = None) -> dict:
    """One-line dynasty window verdict: value-weighted life-stage of the core
    (top-N by market value, N = starting slots so chaff doesn't skew) plus pick
    capital, described relative to the rest of the league when `standing` is
    available. Taxi/IR players count — a stashed rookie is part of the young
    core."""
    n = max(1, len(starting_slots((rules or {}).get("roster_positions"))))
    valued = [p for p in players if p.get("value") and p.get("band")]
    core = sorted(valued, key=lambda p: p["value"], reverse=True)[:n]
    if not core:
        return {"verdict": None, "detail": "No market values available to read the window.",
                "core_age": None}

    core_value = sum(p["value"] for p in core)
    pick_value = sum(pk.get("value") or 0 for pk in picks)
    stage = sum(_STAGE_SCORE[p["band"]] * p["value"] for p in core) / core_value
    pick_share = pick_value / (core_value + pick_value) if core_value + pick_value else 0.0
    ages = [p["age"] for p in core if isinstance(p.get("age"), (int, float))]
    core_age = round(sum(ages) / len(ages), 1) if ages else None

    # Plain English only: the 0-3 stage score is internal, and a bare percentage
    # is meaningless without something to compare it against.
    phrase, strong_picks = _picks_phrase(pick_share, standing)
    if stage < 0.9:
        verdict = "Ascending"
        detail = f"Your best players are young and still gaining value, and {phrase}."
    elif stage <= 1.5:
        if strong_picks:
            verdict = "Balanced"
            detail = f"Your best players are in their prime and {phrase}."
        else:
            verdict = "Win-now"
            detail = (
                f"Your best players are in their prime but {phrase} — "
                "this is the year to push."
            )
    else:
        verdict = "Aging — sell high"
        detail = (
            f"Your best players are past their prime and {phrase} — "
            "move the vets while they still hold value."
        )
    return {
        "verdict": verdict,
        "detail": detail,
        "core_age": core_age,
        "stage": round(stage, 2),
        "pick_share": round(pick_share, 3),
    }


def _startable_value_by_pos(players: list[dict]) -> dict[str, float]:
    """Sum of dynasty market value at each position among players who can take a
    lineup slot (starters + bench; taxi/IR excluded)."""
    out: dict[str, float] = {}
    for p in players:
        if p.get("status") in _STARTABLE and p.get("value"):
            pos = p.get("position")
            if pos in _POSTURE_POSITIONS:
                out[pos] = out.get(pos, 0) + p["value"]
    return out


def league_position_averages(players_by_team: dict[str, list]) -> dict[str, float]:
    """Average startable market value per position across all teams — the
    reference line thin/surplus are measured against. Empty when no team has
    valued players."""
    n = max(len(players_by_team), 1)
    totals: dict[str, float] = {}
    for players in players_by_team.values():
        for pos, val in _startable_value_by_pos(players).items():
            totals[pos] = totals.get(pos, 0) + val
    return {pos: total / n for pos, total in totals.items()}


def team_posture(players: list[dict], picks: list[dict], rules: dict,
                 averages: dict[str, float], standing: dict | None = None) -> dict:
    """A team's roster-construction stance, composed from the roster-view
    primitives: dynasty window, positions it's thin at (a real need you can sell
    into — football has no punting, every slot must be filled each week),
    positions it's deep at (its surplus, what it would pay you with), and whether
    it's rich or poor in draft capital. Pure; thresholds are tunable constants,
    never persisted. Returns {window, thin[], surplus[], picks}."""
    # roster_window needs an age band per player; the trade valuation path
    # doesn't set one, so attach it here (cheap, pure) without mutating callers'
    # dicts.
    banded = [dict(p, band=age_band(p.get("position"), p.get("age"))) for p in players]
    verdict = roster_window(banded, picks, rules, standing).get("verdict")

    mine = _startable_value_by_pos(players)
    thin, surplus = [], []
    for pos in _POSTURE_POSITIONS:
        avg = averages.get(pos, 0)
        if avg <= 0:
            continue
        have = mine.get(pos, 0)
        if have < _THIN_RATIO * avg:
            thin.append(pos)
        elif have > _SURPLUS_RATIO * avg:
            surplus.append(pos)

    picks_stance = None
    if standing:
        rank, size = standing["pick_rank"], standing["size"]
        if rank <= max(1, size // 3):
            picks_stance = "rich"
        elif rank > (size * 2) // 3:
            picks_stance = "poor"

    return {"window": verdict, "thin": thin, "surplus": surplus, "picks": picks_stance}


def build_payload(roster_items: list | None, draft_picks: list | None,
                  rules: dict, fc_entries: list | None,
                  all_rosters: list | None = None, my_team_id: str = "") -> dict:
    """The ready-to-render /dashboard/nfl_roster body (minus team_name /
    values_updated_at, which the endpoint adds). Joins are best-effort: players
    or picks FantasyCalc doesn't know keep value None and still render. Pass
    `all_rosters` (every synced team) to ground the window read in league ranks
    rather than a free-floating percentage."""
    fc_players, fc_picks = index_fc(fc_entries)
    standing = league_standing(all_rosters, fc_players, fc_picks, my_team_id)

    players = []
    for it in roster_items or []:
        e = fc_players.get(str(it.get("id") or ""))
        meta = (e or {}).get("player") or {}
        age = it.get("age")
        if not isinstance(age, (int, float)):
            age = meta.get("maybeAge")  # backfill: Sleeper dump ages go missing
        yexp = it.get("years_exp")
        players.append({
            "id": it.get("id"),
            "name": it.get("name"),
            "position": it.get("position"),
            "team": it.get("team"),
            "status": it.get("status") or "bench",
            "injury_status": it.get("injury_status"),
            "age": age,
            "band": age_band(it.get("position"), age),
            "rookie_tag": "Rookie" if yexp == 0 else ("2nd yr" if yexp == 1 else None),
            "value": (e or {}).get("value"),
            "overall_rank": (e or {}).get("overallRank"),
            "pos_rank": (e or {}).get("positionRank"),
            "tier": (e or {}).get("maybeTier"),
            "trend": (e or {}).get("trend30Day"),
        })

    picks = []
    for pk in sorted(
        draft_picks or [], key=lambda p: (p.get("season") or 0, p.get("round") or 0)
    ):
        e = fc_picks.get((pk.get("label") or "").strip())
        picks.append({
            "label": pk.get("label"),
            "season": pk.get("season"),
            "round": pk.get("round"),
            "value": (e or {}).get("value"),
            "trend": (e or {}).get("trend30Day"),
        })

    groups: dict[str, list] = {"starter": [], "bench": [], "taxi": [], "ir": []}
    for p in players:
        groups.get(p["status"], groups["bench"]).append(p)
    for group in groups.values():
        group.sort(key=lambda p: (-(p.get("value") or 0), p.get("name") or ""))

    valued_picks = [p for p in picks if p["value"]]
    return {
        "fc_available": bool(fc_entries),
        "players": groups,
        "picks": picks,
        "pick_capital": {
            "total": sum(p["value"] for p in valued_picks),
            "valued": len(valued_picks),
            "unvalued": len(picks) - len(valued_picks),
        },
        "window": roster_window(players, picks, rules, standing),
        "depth_flags": depth_flags(players, rules),
        "standing": standing,
    }
