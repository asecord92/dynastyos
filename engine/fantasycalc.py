"""FantasyCalc dynasty market values (free API, no key). Values are identical
for every league sharing a settings combo (numQbs, ppr, numTeams), so the
response is cached in-process per combo — ~12h TTL, stale-if-error — instead of
per-league in dashboard_cache: there is no AI cost to protect here, and a
per-league payload cache would go stale the moment a sync changes the roster."""

import threading
import time
from datetime import datetime, timezone

import httpx

_URL = "https://api.fantasycalc.com/values/current"
_TTL_S = 12 * 3600

# combo key -> (monotonic fetch time, wall-clock ISO, entries)
_cache: dict[tuple, tuple[float, str, list]] = {}
# Single-flight: concurrent cache misses share one fetch instead of stampeding
# the free API. Coarse (all combos serialize) but the fetch takes ~a second and
# runs on worker threads, so contention is negligible at this app's scale.
_lock = threading.Lock()


def get_values(num_qbs: int, ppr: float, num_teams: int, force: bool = False) -> dict:
    """Current dynasty values for a settings combo. Returns
    {"entries": [...], "fetched_at": iso} — stale entries when a refetch fails,
    and {"entries": None, "fetched_at": None} only when nothing was ever
    fetched. Blocking (httpx) — call via asyncio.to_thread."""
    key = (num_qbs, ppr, num_teams)
    with _lock:
        return _get_values_locked(key, num_qbs, ppr, num_teams, force)


def _get_values_locked(key: tuple, num_qbs: int, ppr: float, num_teams: int,
                       force: bool) -> dict:
    hit = _cache.get(key)
    if hit and not force and time.monotonic() - hit[0] < _TTL_S:
        return {"entries": hit[2], "fetched_at": hit[1]}
    try:
        resp = httpx.get(
            _URL,
            params={
                "isDynasty": "true",
                "numQbs": num_qbs,
                "ppr": ppr,
                "numTeams": num_teams,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and data:
            fetched_at = datetime.now(timezone.utc).isoformat()
            _cache[key] = (time.monotonic(), fetched_at, data)
            return {"entries": data, "fetched_at": fetched_at}
    except Exception as e:
        print(f"[fantasycalc] fetch failed for {key}: {e}")
    if hit:  # stale-if-error: old market values beat no values
        return {"entries": hit[2], "fetched_at": hit[1]}
    return {"entries": None, "fetched_at": None}
