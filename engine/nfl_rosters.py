"""The single door every NFL read path goes through to get a league's rosters.

The `rosters` table holds a *sync snapshot*: who owned what, and what each
player's NFL situation was, at the moment the owner last pressed sync. Two
different things go stale in it, on two different clocks:

  * **Who's on the roster** — changes when the *league* transacts (waiver adds,
    drops, trades, taxi moves, pick trades). Fixed here, from Sleeper.
  * **What's true of a player** — team, injury, age. Changes on the *NFL's*
    schedule. Fixed by `refresh_item_meta` from the players dump (#138).

Neither is the owner's sync cadence, so the app used to answer with old facts
under a fresh timestamp: a dropped player still on your roster, a traded pick on
the wrong team, Rachaad White on Tampa Bay weeks after Washington signed him.
The AI surfaces made it worse by reasoning and web-searching from those.

The rule throughout is **stale beats blank**. Every refresh step is independent
and each one falls back to the stored value on its own: Sleeper unreachable ->
stored membership; players dump unreachable -> stored metadata; season
unknowable -> stored picks. A read never returns an empty league because an
upstream was down.

Costs nothing per request: the players dump is cached a day in-process, rosters
and traded picks ~10 minutes, all shared across leagues and call sites.
"""
from .sleeper_client import (
    get_players,
    get_rosters_cached,
    get_traded_picks_cached,
)
from .sleeper_sync import (
    build_roster_items,
    carry_forward_gaps,
    compute_pick_inventory,
    infer_league_season,
    refresh_item_meta,
)

_ROSTER_COLUMNS = "fantrax_team_id, team_name, roster_items, draft_picks"


def _stored(sb, league_id: str) -> list:
    return (
        sb.table("rosters").select(_ROSTER_COLUMNS).eq("league_id", league_id)
        .execute().data or []
    )


def _league(sb, league_id: str) -> dict:
    try:
        return (
            sb.table("leagues")
            .select("sleeper_league_id, rules")
            .eq("id", league_id)
            .single()
            .execute()
        ).data or {}
    except Exception as e:
        print(f"[nfl] league row unavailable for {league_id}: {e}")
        return {}


def _refresh_membership(rows: list, live_rosters: list, players: dict) -> list:
    """Rebuild each row's items from the live Sleeper roster, keyed by
    `fantrax_team_id` (which *is* the Sleeper roster_id, as a string).

    A team Sleeper doesn't return, or one whose live rebuild comes back empty,
    keeps its stored items — an empty roster is never the right answer, and a
    partial Sleeper response shouldn't wipe half a league.
    """
    live_by_id = {str(r.get("roster_id")): r for r in live_rosters or []}
    out = []
    for row in rows:
        live = live_by_id.get(str(row.get("fantrax_team_id")))
        if not live:
            out.append(row)
            continue
        items = build_roster_items(
            live.get("players"), live.get("starters"), players,
            taxi=live.get("taxi"), reserve=live.get("reserve"),
        )
        if not items:
            out.append(row)
            continue
        # A rebuild reads every field from the dump, so a player it has no age
        # for would lose the age we already had. Gaps aren't news.
        out.append({**row, "roster_items": carry_forward_gaps(items, row.get("roster_items"))})
    return out


def _refresh_picks(rows: list, league_id: str, sleeper_lid: str, rules: dict) -> list:
    """Recompute pick inventory from currently-traded picks.

    Ownership is league-wide (defaults plus reassignments), which is why
    `load_rosters` always reads the whole league before narrowing. Keeps the
    stored picks whenever any input is missing: guessing the season would
    silently hand everyone the wrong draft capital.
    """
    traded = get_traded_picks_cached(sleeper_lid)
    if traded is None:
        return rows
    season = infer_league_season(rules, rows)
    if season is None:
        return rows
    total = int(rules.get("league_size") or len(rows) or 0)
    rounds = int(rules.get("draft_rounds") or 0)
    if not total or not rounds:
        return rows
    try:
        inventory = compute_pick_inventory(traded, total, rounds, season)
    except Exception as e:
        print(f"[nfl] pick inventory recompute failed for {league_id}: {e}")
        return rows
    out = []
    for row in rows:
        try:
            rid = int(row.get("fantrax_team_id"))
        except (TypeError, ValueError):
            out.append(row)  # non-numeric team id can't be a Sleeper roster
            continue
        out.append({**row, "draft_picks": inventory.get(rid, [])})
    return out


def _meta_only(rows: list, players: dict) -> list:
    if not players:
        return rows
    return [
        {**r, "roster_items": refresh_item_meta(r.get("roster_items"), players)}
        for r in rows
    ]


def load_rosters(sb, league_id: str, team_ids: list | None = None) -> list:
    """Stored NFL roster rows with membership, metadata and picks refreshed.

    `team_ids` narrows the *returned* rows (the trade surfaces want two teams,
    not twelve); pick ownership is still computed league-wide, because it has to
    be. Shape is identical to a plain `rosters` select, so callers are unchanged.
    """
    wanted = {str(t) for t in team_ids} if team_ids else None

    # Pick ownership needs every team, so read the league once and filter at the
    # end rather than querying twice. A league is a dozen rows.
    all_rows = _stored(sb, league_id)
    if not all_rows:
        return []

    league = _league(sb, league_id)
    rules = league.get("rules") or {}
    sleeper_lid = league.get("sleeper_league_id")

    try:
        players = get_players() or {}
    except Exception as e:
        print(f"[nfl] players dump unavailable: {e}")
        players = {}

    if not sleeper_lid:
        # Not a Sleeper-synced league (or synced before the id was stored) —
        # metadata is still worth refreshing on its own.
        all_rows = _meta_only(all_rows, players)
    else:
        live = get_rosters_cached(sleeper_lid)
        if live and players:
            all_rows = _refresh_membership(all_rows, live, players)
        else:
            all_rows = _meta_only(all_rows, players)
        if live:
            # Only trust Sleeper's pick answer for a league it just confirmed
            # rosters for. A stale or wrong sleeper_league_id returns 200/null
            # for traded picks — an empty list reads as "nobody has traded a
            # pick" and would hand every team back its default inventory.
            all_rows = _refresh_picks(all_rows, league_id, sleeper_lid, rules)

    if wanted is None:
        return all_rows
    return [r for r in all_rows if str(r.get("fantrax_team_id")) in wanted]
