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


def roster_window(players: list[dict], picks: list[dict], rules: dict) -> dict:
    """One-line dynasty window verdict: value-weighted life-stage of the core
    (top-N by market value, N = starting slots so chaff doesn't skew) plus pick
    capital's share of total asset value. Taxi/IR players count — a stashed
    rookie is part of the young core."""
    n = max(1, len(starting_slots((rules or {}).get("roster_positions"))))
    valued = [p for p in players if p.get("value") and p.get("band")]
    core = sorted(valued, key=lambda p: p["value"], reverse=True)[:n]
    if not core:
        return {"verdict": None, "detail": "No market values available to read the window."}

    core_value = sum(p["value"] for p in core)
    pick_value = sum(pk.get("value") or 0 for pk in picks)
    stage = sum(_STAGE_SCORE[p["band"]] * p["value"] for p in core) / core_value
    pick_share = pick_value / (core_value + pick_value) if core_value + pick_value else 0.0

    # Plain-English detail: the underlying stage score (0-3) is jargon nobody
    # asked for, so it stays in the payload as data and out of the sentence.
    pct = round(pick_share * 100)
    if stage < 0.9:
        verdict = "Ascending"
        detail = "Your best players are young and still gaining value."
    elif stage <= 1.5:
        if pick_share >= 0.15:
            verdict = "Balanced"
            detail = (
                "Your best players are in their prime and you hold real draft capital "
                f"({pct}% of everything you own)."
            )
        else:
            verdict = "Win-now"
            detail = (
                "Your best players are in their prime but you're light on picks "
                f"({pct}% of everything you own) — this is the year to push."
            )
    else:
        verdict = "Aging — sell high"
        detail = "Your best players are past their prime — move them while they still hold value."
    return {
        "verdict": verdict,
        "detail": detail,
        "stage": round(stage, 2),
        "pick_share": round(pick_share, 3),
    }


def build_payload(roster_items: list | None, draft_picks: list | None,
                  rules: dict, fc_entries: list | None) -> dict:
    """The ready-to-render /dashboard/nfl_roster body (minus team_name /
    values_updated_at, which the endpoint adds). Joins are best-effort: players
    or picks FantasyCalc doesn't know keep value None and still render."""
    fc_players, fc_picks = index_fc(fc_entries)

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
        "window": roster_window(players, picks, rules),
        "depth_flags": depth_flags(players, rules),
    }
