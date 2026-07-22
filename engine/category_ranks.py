import asyncio
import re

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

# Which roster-construction role feeds each category. Posture reads the count of
# that role to tell a deliberate punt (weak rank + ~no contributors, e.g. one RP
# and last in SV) from a genuine hole (weak rank but real depth there). Hitting
# and full-staff categories can't be punted by roster shape — you always field a
# lineup and a staff — so only the single-role categories (SV→RP, QS→SP) ever
# read as "punt".
CATEGORY_ROLE = {
    "R": "hitters", "HR": "hitters", "RBI": "hitters", "SB": "hitters", "OBP": "hitters",
    "SV": "RP",
    "QS": "SP",
    "K": "pitchers", "ERA": "pitchers", "WHIP": "pitchers",
}


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _role_counts(items: list[dict], id_map: dict[str, dict]) -> dict[str, int]:
    """Count a team's contributors by role from roster items + resolved types.

    ``player_type`` (hitter/pitcher) comes from player_id_map; SP/RP granularity
    comes from the raw Fantrax position eligibility string on the roster item
    (e.g. "SP", "RP", "SP,RP"), matched by token so multi-eligible arms count for
    both. Pitchers with no SP/RP token still count toward the generic pitcher
    total. Counts every rostered player (majors + minors) — stashing a reliever
    is still an investment in that category.
    """
    counts = {"hitters": 0, "SP": 0, "RP": 0, "pitchers": 0}
    for item in items:
        mapped = id_map.get(item.get("id"))
        if not mapped:
            continue
        ptype = mapped.get("player_type") or "hitter"
        if ptype == "pitcher":
            counts["pitchers"] += 1
            toks = re.split(r"[^A-Z]+", (item.get("position") or "").upper())
            if "SP" in toks:
                counts["SP"] += 1
            if "RP" in toks:
                counts["RP"] += 1
        else:
            counts["hitters"] += 1
    return counts


def posture(cat: str, rank, roles: dict[str, int], num_teams: int) -> str:
    """Classify a team's stance in one category as punt | need | strong | mid.

    Pure and deterministic so the punt heuristic lives in tested code, not model
    guesswork — and so it can be tuned without a cache flush (labels are never
    persisted; only the numeric ranks + role counts are). "punt" = weak rank with
    ~no contributors (a deliberate zero); "need" = weak rank with real depth (a
    genuine hole); "strong" = top-third rank.
    """
    if not isinstance(rank, int) or num_teams <= 1:
        return "mid"
    contrib = roles.get(CATEGORY_ROLE.get(cat, "hitters"), 0)
    weak = rank > num_teams * 2 / 3
    strong = rank <= num_teams / 3
    if weak and contrib <= 1:
        return "punt"
    if weak:
        return "need"
    if strong:
        return "strong"
    return "mid"


def team_posture_summary(entry: dict, num_teams: int) -> dict[str, list[str]]:
    """Digest one team's matrix entry into {needs, punts, strong} category lists —
    the compact, prompt-facing view of its posture."""
    ranks = entry.get("ranks", {})
    roles = entry.get("roles", {})
    out: dict[str, list[str]] = {"needs": [], "punts": [], "strong": []}
    for cat, rank in ranks.items():
        p = posture(cat, rank, roles, num_teams)
        if p == "need":
            out["needs"].append(cat)
        elif p == "punt":
            out["punts"].append(cat)
        elif p == "strong":
            out["strong"].append(cat)
    return out


async def compute_category_matrix(league_id: str, concurrency: int = 12) -> dict:
    """
    Approximate every team's strength in every scoring category by summing their
    rostered players' current-season stats, then rank the teams. Returns the full
    league matrix — ranks + role counts per team — as the reusable primitive that
    powers both the manager's own ranks and the trade tools' posture reads:

        {
          "version": 1,
          "num_teams": 12,
          "teams": {
            "<fantrax_team_id>": {
              "name": "Inglorious Bashers",
              "ranks": {"R": 4, "HR": 2, ...},   # 1 = best
              "roles": {"hitters": 13, "SP": 5, "RP": 1, "pitchers": 6},
            }, ...
          }
        }

    An approximation: it reflects current roster talent, not season-to-date
    accumulated standings. Rate stats are opportunity-weighted.
    """
    sb = get_supabase()

    roster_rows = sb.table("rosters").select(
        "fantrax_team_id, team_name, roster_items"
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

    # Aggregate each team's category values + role counts.
    team_values: dict[str, dict] = {}
    team_meta: dict[str, dict] = {}
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
        tid = t["fantrax_team_id"]
        team_values[tid] = values
        team_meta[tid] = {
            "name": t.get("team_name") or "",
            "roles": _role_counts(t["roster_items"], id_map),
        }

    # Rank teams per category; teams with no data sort to the bottom.
    n = len(teams)
    ranks_by_team: dict[str, dict] = {tid: {} for tid in team_values}
    for cat, (_key, _weight_key, higher) in CATEGORY_DEFS.items():
        scored = [(tid, v[cat]) for tid, v in team_values.items() if v[cat] is not None]
        scored.sort(key=lambda x: x[1], reverse=higher)
        rank_map = {tid: i + 1 for i, (tid, _) in enumerate(scored)}
        for tid in team_values:
            ranks_by_team[tid][cat] = rank_map.get(tid, n)

    return {
        "version": 1,
        "num_teams": n,
        "teams": {
            tid: {
                "name": team_meta[tid]["name"],
                "ranks": ranks_by_team[tid],
                "roles": team_meta[tid]["roles"],
            }
            for tid in team_values
        },
    }


def my_ranks_from_matrix(matrix: dict, my_team_id: str) -> dict:
    """Extract one team's per-category ranks from the full matrix — the backward-
    compatible {cat: rank} shape the widget, history, and existing readers use."""
    n = matrix.get("num_teams") or 1
    team = (matrix.get("teams") or {}).get(my_team_id)
    if not team:
        return {}
    # Fall back to worst rank for any category the team has no data in.
    return {cat: team["ranks"].get(cat, n) for cat in CATEGORY_DEFS}


async def compute_category_ranks(league_id: str, my_team_id: str, concurrency: int = 12) -> dict:
    """
    Backward-compatible wrapper: compute the league matrix and return only the
    manager's own rank per category, e.g. {"R": 4, "HR": 2, ...} (1 = best).
    """
    matrix = await compute_category_matrix(league_id, concurrency)
    if not matrix:
        return {}
    return my_ranks_from_matrix(matrix, my_team_id)
