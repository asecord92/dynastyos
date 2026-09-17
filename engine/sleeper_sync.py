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


# --- Keeping embedded metadata honest -----------------------------------------
# `build_roster_items` freezes NFL-world facts (team, injury, age) into the
# roster row at sync time, because the frontend has no NFL map of its own. But
# those facts describe the real NFL, not the fantasy league: a player gets
# traded, signed or hurt on the NFL's schedule, while the row they're embedded
# in only changes when the *owner* runs a sync. Between the two, the app states
# a stale fact with a fresh timestamp on it — Rachaad White was still being
# shown on Tampa Bay weeks after Washington signed him, and the AI widgets were
# reasoning (and web-searching) from that wrong team.
#
# So the snapshot is the fallback, not the source: every read overlays the live
# players dump, which `get_players()` already keeps cached in-process for a day
# and most of these paths already load anyway. The join is exact (item["id"] IS
# the Sleeper player_id), so this costs a dict lookup per player.

# Fields where the dump's *absence* of a value is itself the news — a player who
# healed has no injury_status, a player who was cut has no team. Always taken
# live, None included.
_AUTHORITATIVE_FIELDS = ("team", "injury_status")

# Fields where a missing value means the dump has a hole, not that the player
# lost the attribute (Sleeper ages/experience go missing routinely — see the
# maybeAge backfill in nfl_dynasty). Taken live only when actually present.
_BEST_EFFORT_FIELDS = ("name", "position", "age", "years_exp")


def refresh_item_meta(items: list | None, players: dict | None = None) -> list:
    """Return `items` with their NFL metadata re-read from the players dump.

    Never raises and never empties a roster: an unavailable or empty dump, or a
    player the dump doesn't know (retired, or an id that predates a Sleeper
    change), leaves the synced values exactly as they were. Fantasy-league facts
    — `id` and `status` (starter/bench/taxi/ir) — are never touched here; they
    come from the league, and only a sync can tell us they changed.
    """
    items = items or []
    if players is None:
        try:
            from .sleeper_client import get_players
            players = get_players()
        except Exception as e:  # dump unreachable — stale beats empty
            print(f"[nfl] players dump unavailable, serving synced metadata: {e}")
            return items
    if not players:
        return items

    out = []
    for it in items:
        meta = players.get(str(it.get("id") or ""))
        if not meta:
            out.append(it)
            continue
        fresh = dict(it)
        for field in _AUTHORITATIVE_FIELDS:
            fresh[field] = meta.get(field) or meta.get(f"{field}_abbr") or (
                "" if field == "team" else None
            )
        for field in _BEST_EFFORT_FIELDS:
            live = meta.get("full_name") if field == "name" else meta.get(field)
            if live is not None and live != "":
                fresh[field] = live
        out.append(fresh)
    return out


def refresh_roster_rows(rows: list | None, players: dict | None = None) -> list:
    """`refresh_item_meta` over a list of `rosters` rows, loading the dump once
    for the whole league. Rows are copied, never mutated in place."""
    rows = rows or []
    if players is None:
        try:
            from .sleeper_client import get_players
            players = get_players()
        except Exception as e:
            print(f"[nfl] players dump unavailable, serving synced metadata: {e}")
            return rows
    if not players:
        return rows
    return [
        {**r, "roster_items": refresh_item_meta(r.get("roster_items"), players)}
        for r in rows
    ]
