"""Lightweight, transparent dynasty player valuation for the Trade Finder.

This is a heuristic meant to *ground* the AI's package-building, not a precise
projection engine. A player's value is their production percentile within the
pool of comparable players (same type) we already have stats for, nudged by
contract efficiency:

    value = production * (1 + efficiency_bonus + control_bonus)

where
  * production       = mean per-category percentile (0-100) within the type pool,
  * efficiency_bonus = ±20% for salary cheaper / pricier than the pool median
                       (the "would you re-sign them at this salary" surplus idea),
  * control_bonus    = +10% for cost-controlled 1st/2nd-year contracts.

Values are comparable across positions because production is a within-type
percentile (a 90th-percentile hitter and 90th-percentile pitcher both score ~90),
so summing them to compare trade packages is reasonable.
"""
from statistics import median


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _percentile_ranks(values: list, higher_is_better: bool) -> list:
    """Map values to 0-100 percentile ranks (100 = best in the pool). ``None``
    values stay ``None``. Lower-is-better stats (ERA, WHIP) are inverted so the
    smallest value scores highest."""
    present = [(i, v) for i, v in enumerate(values) if v is not None]
    out: list = [None] * len(values)
    n = len(present)
    if n == 0:
        return out
    if n == 1:
        out[present[0][0]] = 50.0
        return out
    # Order worst -> best, then percentile by position so best gets 100.
    ordered = sorted(present, key=lambda iv: iv[1], reverse=not higher_is_better)
    for rank, (idx, _) in enumerate(ordered):
        out[idx] = round(100.0 * rank / (n - 1), 1)
    return out


def production_ratings(players: list, stat_specs: list) -> list:
    """Add a ``production`` score (0-100) to each player: the mean of its
    per-category percentiles within ``players``.

    ``players``: dicts each carrying a ``season`` stats dict.
    ``stat_specs``: list of ``(season_stat_key, higher_is_better)`` for the type.
    """
    if not players or not stat_specs:
        for p in players:
            p["production"] = None
        return players

    per_cat = []
    for stat_key, higher_is_better in stat_specs:
        vals = [_to_float((p.get("season") or {}).get(stat_key)) for p in players]
        per_cat.append(_percentile_ranks(vals, higher_is_better))

    for i, p in enumerate(players):
        ranks = [col[i] for col in per_cat if col[i] is not None]
        p["production"] = round(sum(ranks) / len(ranks), 1) if ranks else None
    return players


def assign_values(players: list) -> list:
    """Add a ``value`` score to each player from production + contract
    efficiency, using the median salary of the rated players as the reference.
    Players with no production (no stats) get ``value = None``."""
    rated = [p for p in players if p.get("production") is not None]
    if not rated:
        for p in players:
            p["value"] = None
        return players

    med_sal = median(max(_to_float(p.get("salary")) or 0.0, 0.0) for p in rated) or 1.0

    for p in players:
        prod = p.get("production")
        if prod is None:
            p["value"] = None
            continue
        sal = max(_to_float(p.get("salary")) or 0.0, 0.0)
        # Cheaper than the pool median -> up to +20%; pricier -> down to -20%.
        eff = (med_sal - sal) / med_sal if med_sal else 0.0
        eff_bonus = max(-0.20, min(0.20, eff * 0.20))
        # Young, cost-controlled contracts carry a small premium.
        control_bonus = 0.10 if str(p.get("contract") or "") in ("1", "2") else 0.0
        p["value"] = round(prod * (1 + eff_bonus + control_bonus), 1)
    return players
