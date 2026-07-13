import asyncio

from .supabase_client import get_supabase
from .mlb_stats_client import get_player_stats, get_cached_stats_bulk

# category -> (season_stat key, weight key for rate stats or None, higher_is_better)
# Counting stats sum across the roster; rate stats (OBP/ERA/WHIP) are weighted by
# opportunity (PA / IP) so a 2-PA cameo doesn't swing a team's OBP.
CATEGORY_DEFS = {
    "R":    ("runs",           None,                True),
    "HR":   ("home_runs",      None,                True),
    "RBI":  ("rbi",            None,                True),
    "SB":   ("stolen_bases",   None,                True),
    "OBP":  ("obp",            "plate_appearances", True),
    "QS":   ("quality_starts", None,                True),
    "SV":   ("saves",          None,                True),
    "K":    ("strikeouts",     None,                True),
    "ERA":  ("era",            "innings_pitched",   False),
    "WHIP": ("whip",           "innings_pitched",   False),
}


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


async def compute_category_ranks(league_id: str, my_team_id: str, concurrency: int = 12) -> dict:
    """
    Approximate each team's strength in every scoring category by summing their
    rostered players' current-season stats, then rank the teams. Returns the
    manager's own rank per category, e.g. {"R": 4, "HR": 2, ...} (1 = best).

    An approximation: it reflects current roster talent, not season-to-date
    accumulated standings. Rate stats are opportunity-weighted.
    """
    sb = get_supabase()

    roster_rows = sb.table("rosters").select(
        "fantrax_team_id, roster_items"
    ).eq("league_id", league_id).execute()
    teams = roster_rows.data or []
    if not teams:
        return {}

    # Resolve every rostered player to an MLB id + type (batch the IN filter).
    all_ids = [item["id"] for t in teams for item in t["roster_items"]]
    id_map: dict[str, dict] = {}
    for i in range(0, len(all_ids), 100):
        rows = sb.table("player_id_map").select(
            "fantrax_id, mlb_id, player_type"
        ).in_("fantrax_id", all_ids[i:i + 100]).execute()
        for r in (rows.data or []):
            id_map[r["fantrax_id"]] = r

    # Fetch season stats once per unique MLB id (cached in player_stats). Read the
    # whole warm cache in one batched query first, then fan out only for the ids
    # that are missing or stale — on a warm cache this collapses ~one SELECT per
    # player into a couple of queries.
    unique: dict[int, str] = {
        m["mlb_id"]: (m.get("player_type") or "hitter")
        for m in id_map.values()
        if m.get("mlb_id")
    }
    # Offload the blocking bulk read to a thread. The Supabase client is
    # synchronous, and running it inline froze the whole event loop while it
    # pulled the league's cached stats — stalling every other request (499s).
    cached = await asyncio.to_thread(get_cached_stats_bulk, list(unique.keys()))
    season_by_mlb = {
        mid: (row or {}).get("season_stats", {}) for mid, row in cached.items()
    }

    misses = {mid: pt for mid, pt in unique.items() if mid not in cached}
    sem = asyncio.Semaphore(concurrency)

    async def fetch(mlb_id, ptype):
        async with sem:
            return mlb_id, await get_player_stats(mlb_id, ptype)

    results = await asyncio.gather(*[fetch(mid, pt) for mid, pt in misses.items()])
    for mid, s in results:
        season_by_mlb[mid] = (s or {}).get("season_stats", {})

    # Aggregate each team's category values.
    team_values: dict[str, dict] = {}
    for t in teams:
        counting = {c: 0.0 for c in CATEGORY_DEFS}
        seen = {c: False for c in CATEGORY_DEFS}
        rate_num = {c: 0.0 for c in CATEGORY_DEFS}
        rate_den = {c: 0.0 for c in CATEGORY_DEFS}

        for item in t["roster_items"]:
            mapped = id_map.get(item["id"])
            if not mapped or not mapped.get("mlb_id"):
                continue
            season = season_by_mlb.get(mapped["mlb_id"], {})
            if not season:
                continue
            for cat, (key, weight_key, _higher) in CATEGORY_DEFS.items():
                val = _f(season.get(key))
                if val is None:
                    continue
                if weight_key is None:
                    counting[cat] += val
                    seen[cat] = True
                else:
                    w = _f(season.get(weight_key))
                    if w and w > 0:
                        rate_num[cat] += val * w
                        rate_den[cat] += w

        values = {}
        for cat, (key, weight_key, _higher) in CATEGORY_DEFS.items():
            if weight_key is None:
                values[cat] = counting[cat] if seen[cat] else None
            else:
                values[cat] = (rate_num[cat] / rate_den[cat]) if rate_den[cat] > 0 else None
        team_values[t["fantrax_team_id"]] = values

    # Rank teams per category; teams with no data sort to the bottom.
    n = len(teams)
    ranks = {}
    for cat, (_key, _weight_key, higher) in CATEGORY_DEFS.items():
        scored = [(tid, v[cat]) for tid, v in team_values.items() if v[cat] is not None]
        scored.sort(key=lambda x: x[1], reverse=higher)
        rank_map = {tid: i + 1 for i, (tid, _) in enumerate(scored)}
        ranks[cat] = rank_map.get(my_team_id, n)

    return ranks
