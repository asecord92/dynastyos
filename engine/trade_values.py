"""Deterministic, AI-free asset pricing for the trade builder.

Pure functions over already-loaded rows (the engine/nfl_dynasty.py pattern) —
no I/O, no Anthropic call, no cost. Given a league's rosters and a market value
feed, produce one flat ``{asset_id: value_info}`` map keyed by exactly the ids
the trade page already uses, so the frontend can price any package instantly
without a round trip per toggle.

Football reads FantasyCalc (engine/fantasycalc.py), baseball reads
HarryKnowsBall (engine/mlb_market_values.py). Both are cardinal market scales,
so the same percentage-delta comparison works for either.

Unpriced assets stay ``None``, never 0 — the same rule the football roster page
follows. A 0 would silently make a real player look worthless and quietly skew
a package total; a ``None`` lets the UI say "we don't know" and flag the
comparison as incomplete.
"""

import unicodedata

from .nfl_dynasty import index_fc

# Years of slack when disambiguating same-name players by age. player_id_map
# stores an integer age, the value feed a decimal one, so an exact match is not
# available; 1.5 comfortably separates two players who share a name without
# accepting a wrong-generation match.
_AGE_TOLERANCE = 1.5


def normalize_name(name) -> str:
    """A join key that survives the cosmetic differences between two name
    sources: accents (``Ronald Acuña Jr.`` vs ``Ronald Acuna Jr.``), punctuation
    in suffixes (``Jr.`` vs ``Jr``), casing, and stray whitespace."""
    decomposed = unicodedata.normalize("NFKD", str(name or ""))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    kept = "".join(c if c.isalnum() or c.isspace() else " " for c in stripped.lower())
    return " ".join(kept.split())


def index_mlb_values(entries: list | None) -> dict[str, list]:
    """Normalized name -> entries. A *list*, not a single entry: roughly three
    names in the ~1,700-player feed are shared by two real players, so the
    lookup has to be able to report ambiguity rather than pick arbitrarily."""
    index: dict[str, list] = {}
    for e in entries or []:
        if e.get("assetType") == "PICK":
            continue  # this league drafts by auction — picks are not assets
        key = normalize_name(e.get("name"))
        if key:
            index.setdefault(key, []).append(e)
    return index


def match_mlb(full_name, age, index: dict[str, list]) -> dict | None:
    """The value entry for a player, or None when we can't be sure.

    Disambiguates duplicates by age rather than team: player_id_map stores the
    full club name ("Los Angeles Dodgers") while the feed stores an abbreviation
    ("LAD"), and maintaining a 30-team crosswalk to settle three players is a
    worse trade than declining to guess.
    """
    candidates = index.get(normalize_name(full_name)) or []
    if len(candidates) == 1:
        return candidates[0]
    if not candidates or not isinstance(age, (int, float)):
        return None
    close = [
        c for c in candidates
        if isinstance(c.get("age"), (int, float)) and abs(c["age"] - age) <= _AGE_TOLERANCE
    ]
    return close[0] if len(close) == 1 else None


def pick_key(pick: dict) -> str:
    """The synthetic id the trade page builds for a draft pick. Must stay in
    lockstep with buildPlayerOptions in web/app/(app)/trade/page.tsx — the whole
    value map is keyed on ids the frontend already holds."""
    return f"pick:{pick.get('season')}:{pick.get('round')}:{pick.get('original_roster_id')}"


def _roster_asset_ids(roster_rows: list | None) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for row in roster_rows or []:
        for item in row.get("roster_items") or []:
            key = str(item.get("id") or "")
            if key and key not in seen:
                seen.add(key)
                ids.append(key)
    return ids


def _mlb_values(roster_rows, id_map_rows, entries) -> dict:
    index = index_mlb_values(entries)
    meta = {
        str(r.get("fantrax_id")): r
        for r in id_map_rows or []
        if r.get("fantrax_id")
    }
    values: dict[str, dict] = {}
    for asset_id in _roster_asset_ids(roster_rows):
        row = meta.get(asset_id) or {}
        entry = match_mlb(row.get("full_name"), row.get("age"), index) if row else None
        if not entry:
            continue
        values[asset_id] = {
            "value": entry.get("value"),
            "rank": entry.get("rank"),
            "age": entry.get("age"),
            "prospect": bool(entry.get("prospect")),
            "trend": entry.get("valueChange30Days"),
        }
    return values


def _nfl_values(roster_rows, entries) -> dict:
    fc_players, fc_picks = index_fc(entries)
    values: dict[str, dict] = {}
    for row in roster_rows or []:
        for item in row.get("roster_items") or []:
            asset_id = str(item.get("id") or "")
            entry = fc_players.get(asset_id)
            if not asset_id or not entry:
                continue
            values[asset_id] = {
                "value": entry.get("value"),
                "rank": entry.get("overallRank"),
                "age": item.get("age") or ((entry.get("player") or {}).get("maybeAge")),
                "prospect": False,
                "trend": entry.get("trend30Day"),
            }
        for pick in row.get("draft_picks") or []:
            entry = fc_picks.get((pick.get("label") or "").strip())
            if not entry:
                continue
            values[pick_key(pick)] = {
                "value": entry.get("value"),
                "rank": entry.get("overallRank"),
                "age": None,
                "prospect": False,
                "trend": entry.get("trend30Day"),
            }
    return values


def _total_assets(roster_rows, sport: str) -> int:
    total = len(_roster_asset_ids(roster_rows))
    if sport == "NFL":
        total += sum(len(r.get("draft_picks") or []) for r in roster_rows or [])
    return total


def build_values_payload(sport: str, roster_rows: list | None,
                         id_map_rows: list | None, entries: list | None,
                         fetched_at: str | None) -> dict:
    """The ready-to-render /dashboard/trade_values body: every asset on every
    roster in the league, priced on one scale. `matched`/`unmatched` let the UI
    say how complete the pricing is instead of implying a total is whole."""
    sport = (sport or "MLB").upper()
    if sport == "NFL":
        values = _nfl_values(roster_rows, entries)
        source = "FantasyCalc"
    else:
        values = _mlb_values(roster_rows, id_map_rows, entries)
        source = "HarryKnowsBall"
    matched = len(values)
    return {
        "sport": sport,
        "source": source,
        "available": bool(entries),
        "updated_at": fetched_at,
        "values": values,
        "matched": matched,
        "unmatched": max(_total_assets(roster_rows, sport) - matched, 0),
    }
