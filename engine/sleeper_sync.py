"""Turn raw Sleeper API data into the shapes DynastyOS stores: an NFL league
rules blob, each roster's future pick inventory, and self-describing roster items
(player metadata embedded from the players dump, so the frontend needs no NFL map)."""

_ORDINAL = {1: "1st", 2: "2nd", 3: "3rd"}


def _ordinal(n: int) -> str:
    return _ORDINAL.get(n, f"{n}th")


def ppr_format(scoring_settings: dict) -> str:
    """Map a league's reception scoring to ppr | half_ppr | std (which selects the
    matching pts_* field from Sleeper's season stats)."""
    rec = (scoring_settings or {}).get("rec", 0) or 0
    if rec >= 1:
        return "ppr"
    if rec >= 0.5:
        return "half_ppr"
    return "std"


def build_nfl_rules(league_detail: dict) -> dict:
    """A football rules blob for leagues.rules — non-contract, points-based. The
    football trade prompt reads scoring_format / superflex / etc. directly."""
    settings = league_detail.get("settings") or {}
    scoring = league_detail.get("scoring_settings") or {}
    positions = league_detail.get("roster_positions") or []
    return {
        "sport": "NFL",
        "league_size": league_detail.get("total_rosters") or settings.get("num_teams") or 10,
        "contract": None,
        "scoring_format": ppr_format(scoring),  # ppr | half_ppr | std
        "superflex": "SUPER_FLEX" in positions,
        "roster_positions": positions,
        "draft_rounds": settings.get("draft_rounds") or 4,
        "ppr": scoring.get("rec", 0),
        "pass_td": scoring.get("pass_td"),
        "taxi_slots": settings.get("taxi_slots"),
        "taxi_years": settings.get("taxi_years"),
        "playoff_teams": settings.get("playoff_teams"),
    }


def compute_pick_inventory(
    traded_picks: list, total_rosters: int, draft_rounds: int, league_season: int
) -> dict[int, list]:
    """Each roster's future rookie-pick inventory (next three draft classes),
    from default ownership with traded picks applied. Returns
    {roster_id: [{season, round, label, original_roster_id}, ...]}.

    A pick is identified by (season, round, original_roster_id); its default owner
    is the original roster, and a traded_pick reassigns it to that pick's current
    `owner_id` roster.
    """
    seasons = [league_season + 1, league_season + 2, league_season + 3]
    traded: dict = {}
    for tp in traded_picks or []:
        try:
            s = int(tp["season"])
        except (KeyError, TypeError, ValueError):
            continue
        if s in seasons:
            traded[(s, tp["round"], tp["roster_id"])] = tp["owner_id"]

    inventory: dict[int, list] = {rid: [] for rid in range(1, total_rosters + 1)}
    for s in seasons:
        for rnd in range(1, draft_rounds + 1):
            for original in range(1, total_rosters + 1):
                owner = traded.get((s, rnd, original), original)
                inventory.setdefault(owner, []).append({
                    "season": s,
                    "round": rnd,
                    "label": f"{s} {_ordinal(rnd)}",
                    "original_roster_id": original,
                })
    return inventory


def build_roster_items(
    player_ids: list, starters: list, players: dict,
    taxi: list | None = None, reserve: list | None = None,
) -> list:
    """Self-describing roster items for the shared rosters table, with player
    metadata embedded from the players dump. Sleeper's `players` list includes
    taxi and IR players, so status distinguishes all four slots:
    starter | bench | taxi | ir."""
    starter_set = set(starters or [])
    taxi_set = set(taxi or [])
    reserve_set = set(reserve or [])
    items = []
    for pid in player_ids or []:
        meta = players.get(pid) or {}
        name = meta.get("full_name") or (
            f"{meta.get('first_name', '')} {meta.get('last_name', '')}".strip()
        ) or pid
        if pid in starter_set:
            status = "starter"
        elif pid in taxi_set:
            status = "taxi"
        elif pid in reserve_set:
            status = "ir"
        else:
            status = "bench"
        items.append({
            "id": pid,
            "name": name,
            "position": meta.get("position") or "?",
            "team": meta.get("team") or meta.get("team_abbr") or "",
            "status": status,
            "injury_status": meta.get("injury_status"),
            # Dynasty-window grounding for the trade prompts.
            "age": meta.get("age"),
            "years_exp": meta.get("years_exp"),
        })
    return items
