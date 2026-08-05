"""Dynasty baseball market values from HarryKnowsBall (free, no key).

The baseball counterpart to engine/fantasycalc.py, and deliberately the same
shape: one universal value scale, cached in-process with a ~12h TTL and
stale-if-error, because there is no AI cost to protect and the values are
identical for every league. Blocking (httpx) — call via asyncio.to_thread.

There is no documented API. The values come from the public /rankings page,
which is a Next.js Pages Router page: the entire ranking ships as JSON inside a
single `<script id="__NEXT_DATA__">` tag, so parsing is one json.loads rather
than scraping markup. robots.txt explicitly allows /rankings (it disallows
/calculator?*, which we never touch) and we identify ourselves in the UA.

Fragility is contained rather than avoided: any parse or transport failure
raises into the stale-if-error path, so a page-shape change degrades the
feature to yesterday's values instead of taking it down. The caller reports
`fetched_at` to the user so stale data is visible, not silent.

Known limitation: one scale for all leagues. These values are not roto/points
or league-size aware, which is exactly why they answer "is this close?" and not
"does this fit my roster" — the latter is what the paid AI analysis is for.
"""

import json
import threading
import time
from datetime import datetime, timezone

import httpx

_URL = "https://harryknowsball.com/rankings"
_TTL_S = 12 * 3600
_TAG = '<script id="__NEXT_DATA__" type="application/json">'
_UA = "DynastyOS/1.0 (+https://dynastyos.app)"

# (monotonic fetch time, source-reported ISO timestamp, entries)
_cache: tuple[float, str, list] | None = None
# Single-flight: concurrent misses share one fetch instead of stampeding a free
# hobby site. Same coarse lock as fantasycalc — the fetch is ~1s on a worker
# thread, so contention is negligible at this app's scale.
_lock = threading.Lock()


def parse_rankings(html: str) -> tuple[list, str | None]:
    """``(entries, last_updated)`` out of a /rankings page.

    Raises on anything unexpected — a missing tag, an empty roster of players,
    or the site's own ``playersError`` flag — so callers fall through to the
    stale cache rather than serving an empty value map, which would silently
    read as "every player is unpriced".
    """
    start = html.index(_TAG) + len(_TAG)  # ValueError when the tag is gone
    end = html.index("</script>", start)
    props = ((json.loads(html[start:end]) or {}).get("props") or {}).get("pageProps") or {}
    if props.get("playersError"):
        raise ValueError(f"source reported an error: {props['playersError']}")
    entries = props.get("players")
    if not isinstance(entries, list) or not entries:
        raise ValueError("no players in payload")
    last_updated = props.get("lastUpdated")
    return entries, last_updated if isinstance(last_updated, str) else None


def get_values(force: bool = False) -> dict:
    """Current dynasty baseball values. Returns ``{"entries": [...],
    "fetched_at": iso}`` — stale entries when a refetch fails, and
    ``{"entries": None, "fetched_at": None}`` only when nothing was ever
    fetched."""
    with _lock:
        return _get_values_locked(force)


def _get_values_locked(force: bool) -> dict:
    global _cache
    hit = _cache
    if hit and not force and time.monotonic() - hit[0] < _TTL_S:
        return {"entries": hit[2], "fetched_at": hit[1]}
    try:
        resp = httpx.get(
            _URL,
            headers={"User-Agent": _UA, "Accept": "text/html"},
            timeout=30,
            follow_redirects=True,
        )
        resp.raise_for_status()
        entries, last_updated = parse_rankings(resp.text)
        # The source's own timestamp beats our fetch time — it says when the
        # values changed, not when we happened to ask.
        fetched_at = last_updated or datetime.now(timezone.utc).isoformat()
        _cache = (time.monotonic(), fetched_at, entries)
        return {"entries": entries, "fetched_at": fetched_at}
    except Exception as e:
        print(f"[mlb_market_values] fetch failed: {e}")
    if hit:  # stale-if-error: old market values beat no values
        return {"entries": hit[2], "fetched_at": hit[1]}
    return {"entries": None, "fetched_at": None}
