"""Lightweight, transparent dynasty player valuation for the Trade Finder and
add/drop analyzer.

This is a heuristic meant to *ground* the AI's reasoning, not a precise
projection engine. Each player gets two orthogonal signals so downstream tools
can weigh talent and cost separately:

  * talent = mean per-category production percentile (0-100) within the type
             pool — "how good, ignoring cost."
  * value  = talent adjusted for contract efficiency — "what it's worth as an
             asset":

        value = talent * (1 + efficiency_bonus + control_bonus)

    where
      * efficiency_bonus = ±20% for salary cheaper / pricier than the pool median
                           (the "would you re-sign them at this salary" surplus),
      * control_bonus    = +10% for cost-controlled 1st/2nd-year contracts.

Both are comparable across positions because talent is a within-type percentile
(a 90th-percentile hitter and 90th-percentile pitcher both score ~90), so summing
values to compare trade packages is reasonable. The prompts also carry raw salary
and contract year, so the model can do finer weighing than this aggregate.
"""
import re
from statistics import median

# Opportunity floor for rate stats: below this, the rate is too small-sample to
# trust, so it's excluded from the talent percentile (mirrors the opportunity
# weighting in category_ranks.py). Keyed by the stat's denominator. Conservative
# — meant to kill obvious flukes (a .600 OBP on 8 PA), not bench real part-timers.
_MIN_OPPORTUNITY = {"plate_appearances": 30.0, "innings_pitched": 10.0}


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _contract_year(contract) -> int | None:
    """Leading contract-year number from Fantrax's contract label ('1', '1st',
    'Year 2', ...). Format-tolerant so the young-player premium isn't silently
    dead if the label isn't a bare digit. None when there's no number."""
    m = re.search(r"\d+", str(contract or ""))
    return int(m.group()) if m else None


def _percentile_ranks(values: list, higher_is_better: bool) -> list:
    """Map values to 0-100 percentile ranks (100 = best in the pool). ``None``
    values stay ``None``. Lower-is-better stats (ERA, WHIP) are inverted so the
    smallest value scores highest. Tied values share the mean position of their
    tie block, so equal production scores equally instead of by arbitrary sort
    order (important: counting stats are full of zeros)."""
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
    i = 0
    while i < n:
        j = i
        while j < n and ordered[j][1] == ordered[i][1]:
            j += 1
        avg_pos = (i + j - 1) / 2.0  # shared position for the whole tie block
        pct = round(100.0 * avg_pos / (n - 1), 1)
        for k in range(i, j):
            out[ordered[k][0]] = pct
        i = j
    return out


def production_ratings(players: list, stat_specs: list) -> list:
    """Add a ``production`` score (0-100) to each player: the mean of its
    per-category percentiles within ``players``.

    ``players``: dicts each carrying a ``season`` stats dict.
    ``stat_specs``: list of ``(season_stat_key, higher_is_better, weight_key)``
    for the type. ``weight_key`` is the opportunity denominator for a rate stat
    (e.g. ``plate_appearances`` for OBP) or ``None`` for a counting stat; a
    player below the opportunity floor is dropped from that category.
    """
    if not players or not stat_specs:
        for p in players:
            p["production"] = None
        return players

    per_cat = []
    for spec in stat_specs:
        stat_key, higher_is_better = spec[0], spec[1]
        weight_key = spec[2] if len(spec) > 2 else None
        min_opp = _MIN_OPPORTUNITY.get(weight_key) if weight_key else None
        vals = []
        for p in players:
            season = p.get("season") or {}
            v = _to_float(season.get(stat_key))
            if v is not None and min_opp is not None:
                opp = _to_float(season.get(weight_key))
                if opp is None or opp < min_opp:
                    v = None  # too small a sample to trust this rate stat
            vals.append(v)
        per_cat.append(_percentile_ranks(vals, higher_is_better))

    for i, p in enumerate(players):
        ranks = [col[i] for col in per_cat if col[i] is not None]
        p["production"] = round(sum(ranks) / len(ranks), 1) if ranks else None
    return players


def assign_values(players: list) -> list:
    """Add ``talent`` (pure production) and ``value`` (production + contract
    efficiency) scores to each player, using the median salary of the rated
    players as the reference. Players with no production (no stats) get ``None``
    for both."""
    rated = [p for p in players if p.get("production") is not None]
    if not rated:
        for p in players:
            p["talent"] = p.get("production")
            p["value"] = None
        return players

    med_sal = median(max(_to_float(p.get("salary")) or 0.0, 0.0) for p in rated) or 1.0

    for p in players:
        prod = p.get("production")
        p["talent"] = prod  # pure production, exposed as its own signal
        if prod is None:
            p["value"] = None
            continue
        sal = max(_to_float(p.get("salary")) or 0.0, 0.0)
        # Cheaper than the pool median -> up to +20%; pricier -> down to -20%.
        eff = (med_sal - sal) / med_sal if med_sal else 0.0
        eff_bonus = max(-0.20, min(0.20, eff * 0.20))
        # Young, cost-controlled contracts carry a small premium.
        control_bonus = 0.10 if _contract_year(p.get("contract")) in (1, 2) else 0.0
        p["value"] = round(prod * (1 + eff_bonus + control_bonus), 1)
    return players
