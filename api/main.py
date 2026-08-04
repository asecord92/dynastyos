import asyncio
import html as _html
import threading
import time
import traceback
import os
import re
import json as _json
import tempfile

import httpx
from fastapi import FastAPI, UploadFile, File, Query, HTTPException, BackgroundTasks, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel
import anthropic
from datetime import datetime, timedelta, timezone

from engine.rules import LeagueRules
from engine.roster_analyzer import analyze_roster_from_csv
from engine.fantrax_client import get_leagues, get_team_rosters, get_player_ids, get_league_info, get_standings
from engine.sleeper_client import (
    get_user as sleeper_get_user,
    get_user_leagues as sleeper_get_user_leagues,
    get_league as sleeper_get_league,
    get_rosters as sleeper_get_rosters,
    get_users as sleeper_get_users,
    get_traded_picks as sleeper_get_traded_picks,
    get_players as sleeper_get_players,
)
from engine.sleeper_sync import build_nfl_rules, compute_pick_inventory, build_roster_items
from engine import fantasycalc
from engine.nfl_dynasty import build_payload as build_nfl_dynasty_payload, derive_fc_params
from engine.nfl_trade import (
    build_nfl_trade_context,
    build_nfl_trade_prompt,
    build_nfl_finder_context,
    build_nfl_finder_prompt,
    build_nfl_system_prompt,
    build_nfl_add_drop_context,
    build_nfl_add_drop_prompt,
)
from engine.nfl_dashboard import build_nfl_dashboard
from engine.nfl_widgets import (
    my_roster as nfl_my_roster,
    start_sit_prompt as nfl_start_sit_prompt,
    news_prompt as nfl_news_prompt,
    waiver_pool as nfl_waiver_pool,
    waiver_prompt as nfl_waiver_prompt,
)
from engine.supabase_client import get_supabase
from engine.fantrax_mapper import map_roster_to_analyze_result
from engine.player_resolver import resolve_player, refresh_roster_statuses, get_existing_fantrax_ids
from engine.mlb_stats_client import get_milb_player_summary, get_cached_stats_bulk, get_schedule_context
from engine.category_ranks import compute_category_matrix, my_ranks_from_matrix
from engine.trade_analyzer import (
    build_trade_context,
    build_trade_prompt,
    build_finder_context,
    build_finder_prompt,
    parse_finder_response,
    build_system_prompt,
    build_add_drop_context,
    build_add_drop_prompt,
)
from engine.auth import get_current_user, _get_jwks
from engine import crypto
from jose import jwt

app = FastAPI(title="DynastyOS API")

allow_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

rules = LeagueRules()


# ── App-event logging (powers the admin error/support view) ───────────────────
def _log_event(*, kind, level="error", status=None, message=None,
               user_id=None, league_id=None, meta=None) -> None:
    """Best-effort insert into app_events. Never raises — logging must not break
    the request it's observing."""
    try:
        get_supabase().table("app_events").insert({
            "kind": kind,
            "level": level,
            "status": status,
            "message": (message or "")[:2000] or None,
            "user_id": user_id,
            "league_id": league_id,
            "meta": meta,
        }).execute()
    except Exception:
        traceback.print_exc()


def _user_id_from_request(request: Request) -> str | None:
    """Best-effort user id from the bearer token, for attributing errors to a
    user in the admin view. Never raises."""
    try:
        auth = request.headers.get("authorization") or ""
        if not auth.lower().startswith("bearer "):
            return None
        payload = jwt.decode(
            auth.split(" ", 1)[1],
            _get_jwks(),
            algorithms=["ES256"],
            options={"verify_aud": False},
        )
        return payload.get("sub")
    except Exception:
        return None


@app.exception_handler(StarletteHTTPException)
async def _http_exception_handler(request: Request, exc: StarletteHTTPException):
    # Log genuine failures (5xx); leave expected 4xx (incl. 402 no_api_key) alone.
    if exc.status_code >= 500:
        _log_event(
            kind=request.url.path,
            status=exc.status_code,
            message=str(exc.detail),
            user_id=_user_id_from_request(request),
        )
    return JSONResponse(
        {"detail": exc.detail},
        status_code=exc.status_code,
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    traceback.print_exc()
    _log_event(
        kind=request.url.path,
        status=500,
        message=f"{type(exc).__name__}: {exc}",
        user_id=_user_id_from_request(request),
    )
    return JSONResponse({"detail": "Internal Server Error"}, status_code=500)


DASHBOARD_CACHE_TTL = timedelta(hours=4)

# Standings come from a live Fantrax call; cache them briefly in-process so a
# dashboard load doesn't hit Fantrax every time (records change at most weekly).
STANDINGS_TTL = timedelta(minutes=10)
_standings_cache: dict[str, tuple[datetime, list]] = {}


def _get_standings_cached(fantrax_league_id: str) -> list:
    now = datetime.now(timezone.utc)
    hit = _standings_cache.get(fantrax_league_id)
    if hit and now - hit[0] < STANDINGS_TTL:
        return hit[1]
    teams = get_standings(fantrax_league_id)
    _standings_cache[fantrax_league_id] = (now, teams)
    return teams


# Re-warm AI widgets in the background before their cache goes too stale, so a
# user rarely triggers a slow on-demand Sonnet+web_search generation themselves.
# Raised from 3h → 8h: the old cadence regenerated every widget ~8×/day around
# the clock (the bulk of the AI bill). At 8h an active league warms ~2–3×/day;
# the morning digest covers the overnight gap and an on-demand gen still fills in
# the moment someone opens the app to a widget older than the 4h cache TTL.
REFRESH_AFTER = timedelta(hours=8)

# The standalone widget warmer only keeps a league's AI widgets fresh while its
# owner is actually opening the app — no point paying to re-warm a dormant
# league round the clock. (The opt-in daily digest is exempt: it's meant to
# reach owners who AREN'T currently in the app.) `last_viewed_at` is touched on
# dashboard reads; everything tolerates the column being absent pre-migration.
WARM_VIEW_WINDOW = timedelta(hours=36)
_LAST_VIEWED_COL_MISSING = False
# In-process debounce so a dashboard load (which fires several widget calls)
# writes last_viewed_at at most once per league per window, not once per widget.
_last_viewed_touch: dict[str, float] = {}
_VIEW_TOUCH_DEBOUNCE_S = 600


def _touch_league_viewed(sb, league_id: str) -> None:
    """Record that an owner just opened this league's dashboard, gating the
    warmer to leagues in active use. Best-effort, debounced, and tolerant of the
    column predating its migration (goes quiet instead of erroring per call)."""
    global _LAST_VIEWED_COL_MISSING
    if _LAST_VIEWED_COL_MISSING or not league_id:
        return
    now = time.monotonic()
    if now - _last_viewed_touch.get(league_id, 0.0) < _VIEW_TOUCH_DEBOUNCE_S:
        return
    _last_viewed_touch[league_id] = now
    try:
        sb.table("leagues").update(
            {"last_viewed_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", league_id).execute()
    except Exception as e:
        if "last_viewed_at" in str(e):
            _LAST_VIEWED_COL_MISSING = True  # migration not applied yet — stop trying


def _recently_viewed_league_ids(sb) -> set[str] | None:
    """League ids opened within WARM_VIEW_WINDOW — the standalone warmer's
    activity gate. Returns None ('warm everything', the pre-gate behavior) if the
    column isn't there yet or the query fails, so this is safe before the
    migration and never silently starves the warmer on a transient error."""
    global _LAST_VIEWED_COL_MISSING
    cutoff = (datetime.now(timezone.utc) - WARM_VIEW_WINDOW).isoformat()
    try:
        rows = (
            sb.table("leagues").select("id").gte("last_viewed_at", cutoff).execute()
        ).data or []
        return {r["id"] for r in rows if r.get("id")}
    except Exception as e:
        if "last_viewed_at" in str(e):
            _LAST_VIEWED_COL_MISSING = True
        return None


def _digest_enabled_league_ids(sb) -> set[str] | None:
    """League ids opted into the digest — the digest warmer only pays to warm
    what it will actually email (disabled leagues short-circuit to 'opted_out'
    anyway). None on error so a query blip warms all rather than emptying every
    digest."""
    try:
        rows = (
            sb.table("leagues").select("id").eq("digest_enabled", True).execute()
        ).data or []
        return {r["id"] for r in rows if r.get("id")}
    except Exception:
        return None


def _cache_age(sb, league_id: str, widget: str) -> timedelta | None:
    """Age of a cached widget, or None if it has never been generated."""
    try:
        row = (
            sb.table("dashboard_cache")
            .select("updated_at")
            .eq("league_id", league_id)
            .eq("widget", widget)
            .limit(1)
            .execute()
        )
        if not row.data:
            return None
        updated = datetime.fromisoformat(row.data[0]["updated_at"].replace("Z", "+00:00"))
        return datetime.now(timezone.utc) - updated
    except Exception:
        return None

# Model selection: Opus for deep trade reasoning, Sonnet for the high-frequency
# dashboard widgets (news / start_sit / waiver) — faster and cheaper.
MODEL_TRADE = "claude-opus-5"
MODEL_DASHBOARD = "claude-sonnet-5"

# Sonnet 5 turns adaptive thinking ON by default. These widgets are simple,
# 4h-cached generations and every call bills the league owner's own key (BYOK),
# so we keep them lean by disabling thinking — matches the no-thinking behavior
# these prompts were tuned for on Sonnet 4.6.
_NO_THINKING = {"type": "disabled"}

# Opus 5 thinks by DEFAULT — omitting the param is equivalent to adaptive. (This
# inverted at Opus 5: on Opus 4.8 omitting it meant no thinking, so the explicit
# param used to be the switch that turned thinking on.) Trade analysis is the
# app's deepest reasoning surface and wants adaptive, so we keep passing it to
# state that intent — it's documentation now, not an activation. Don't "simplify"
# it to {"type": "disabled"} to save tokens: that 400s on Opus 5 at effort
# xhigh/max (we set no effort, so the default `high` applies, where it's legal).
# Thinking tokens count against max_tokens, hence the generous caps below.
_ADAPTIVE_THINKING = {"type": "adaptive"}

# Effort for the three MODEL_TRADE surfaces. #119 moved them from Opus 4.8 to
# Opus 5 by swapping the model string alone, so they silently kept running at
# Opus 5's `high` DEFAULT — and Opus 5 at high deliberates, self-verifies, and
# writes materially longer than 4.8 did at the same settings. On /trade/analyze,
# where thinking interleaves with up to four web searches, that compounded into
# minutes of think→search→think→search (the "cycles between Weighing the deal
# and Searching the web" report). Anthropic's Opus 5 migration guidance is to
# re-sweep effort precisely because low/medium punch well above their weight on
# this model; `medium` is that sweep's starting point. Raise it if answers get
# shallow — but never drop the parameter again, since absent means `high`.
_TRADE_EFFORT = {"effort": "medium"}

# web_search_20260209 (dynamic filtering built in) — supported by both Sonnet 5
# (dashboard widgets) and Opus 5 (trade analysis). Dynamic filtering runs code
# execution server-side per search, so each one costs real wall time — the
# budgets below are latency ceilings, not just cost ceilings.
# Dashboard widgets (news/start_sit/waiver/minors) get a bounded search budget —
# results are billed as input tokens, and an unbounded loop was the biggest
# silent cost. 3 is plenty to cover a roster's worth of injury/role news.
_WEB_SEARCH = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}]

# Trade analysis gets a bounded search allowance to verify injuries / roster
# moves newer than the 24h stats cache. Searches bill the owner's BYOK key.
_TRADE_WEB_SEARCH = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 4}]

# Bring-your-own-key (BYOK): every AI call uses the league OWNER's own Anthropic
# key, stored encrypted in `user_secrets`. There is no shared fallback — friends
# sharing the app each bring their own key so they're billed for their own usage.
_ai_client_cache: dict[str, anthropic.Anthropic] = {}


class NoApiKeyError(HTTPException):
    """402 raised when a league owner has no Anthropic key set. The frontend keys
    off the 402 status to show an 'Add your key in Settings' prompt rather than an
    error. Callers must let this propagate — `except HTTPException: raise`."""

    def __init__(self) -> None:
        super().__init__(status_code=402, detail="no_api_key")


def _league_owner(sb, league_id: str) -> str | None:
    try:
        row = sb.table("leagues").select("owner_user_id").eq("id", league_id).single().execute()
    except Exception:
        return None
    return (row.data or {}).get("owner_user_id")


def _get_user_api_key(sb, user_id: str | None) -> str | None:
    """Decrypt and return a user's stored Anthropic key, or None if unset."""
    if not user_id:
        return None
    try:
        row = (
            sb.table("user_secrets")
            .select("anthropic_key_ciphertext")
            .eq("user_id", user_id)
            .single()
            .execute()
        )
    except Exception:
        return None
    ciphertext = (row.data or {}).get("anthropic_key_ciphertext")
    if not ciphertext:
        return None
    try:
        return crypto.decrypt(ciphertext)
    except Exception:
        return None


# The owner's key can *exist* but still fail the call — out of credits, revoked,
# or rate-limited. We translate those Anthropic errors into stable codes the
# frontend keys off (a global banner for the first two, an inline retry for the
# last), the same way `no_api_key` drives the "add your key" prompt. Anything we
# don't recognize stays a 500 so real bugs still surface as errors.
_AI_ERROR_STATUS = {"out_of_credits": 402, "invalid_api_key": 402, "rate_limited": 429}


def _ai_error_code(exc: BaseException) -> str | None:
    """Map an Anthropic SDK error to one of our AI error codes, or None if it
    isn't a recognized key/billing problem."""
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return "invalid_api_key"
    if isinstance(exc, anthropic.RateLimitError):
        return "rate_limited"
    if isinstance(exc, anthropic.APIStatusError):
        msg = str(getattr(exc, "message", "") or exc).lower()
        if "credit balance" in msg or "billing" in msg:
            return "out_of_credits"
    return None


def _ai_http_error(exc: BaseException) -> HTTPException | None:
    """HTTPException for a recognized AI key/billing error, else None (caller 500s)."""
    code = _ai_error_code(exc)
    if not code:
        return None
    return HTTPException(status_code=_AI_ERROR_STATUS[code], detail=code)


# --- AI usage metering --------------------------------------------------------
# Every Anthropic response carries exact token/web-search counts; we persist
# them per call in `ai_usage` (see 20260716_ai_usage.sql — no prompt content,
# just meters). Best-effort: a logging failure must never break a real request.
# The table may predate its migration being applied — remember that and stop
# trying instead of erroring on every call.
_AI_USAGE_TABLE_MISSING = False


def _usage_counts(usage) -> dict:
    """Flatten an Anthropic Usage object (or None) into our counter columns."""
    def num(attr: str, obj=usage) -> int:
        try:
            return int(getattr(obj, attr, 0) or 0)
        except (TypeError, ValueError):
            return 0

    server_tools = getattr(usage, "server_tool_use", None) if usage else None
    return {
        "input_tokens": num("input_tokens"),
        "output_tokens": num("output_tokens"),
        "cache_read_tokens": num("cache_read_input_tokens"),
        "cache_creation_tokens": num("cache_creation_input_tokens"),
        "web_searches": num("web_search_requests", server_tools) if server_tools else 0,
    }


def _log_ai_usage(ctx: dict | None, model, usage, duration_ms: int, ok: bool, error: str | None = None):
    """Insert one ai_usage row. Called from worker threads / threadpool stream
    generators, so the blocking insert is fine."""
    global _AI_USAGE_TABLE_MISSING
    if ctx is None or _AI_USAGE_TABLE_MISSING:
        return
    try:
        get_supabase().table("ai_usage").insert({
            "league_id": ctx.get("league_id"),
            "user_id": ctx.get("user_id"),
            "tool": ctx.get("tool") or "unknown",
            "model": model,
            **_usage_counts(usage),
            "duration_ms": duration_ms,
            "ok": ok,
            "error": str(error)[:300] if error else None,
        }).execute()
    except Exception as e:
        if "ai_usage" in str(e) and ("does not exist" in str(e) or "PGRST205" in str(e)):
            _AI_USAGE_TABLE_MISSING = True  # migration not applied yet — go quiet
        else:
            traceback.print_exc()


class _LoggedStreamManager:
    """Wraps the SDK's MessageStreamManager so usage is logged when the stream
    context exits — from the accumulated message snapshot, which is populated
    even if the client disconnected mid-stream (partial counts beat none)."""

    def __init__(self, manager, ctx: dict | None, model):
        self._manager = manager
        self._ctx = ctx
        self._model = model
        self._t0 = time.monotonic()
        self._stream = None

    def __enter__(self):
        self._stream = self._manager.__enter__()
        return self._stream

    def __exit__(self, exc_type, exc, tb):
        try:
            snapshot = getattr(self._stream, "current_message_snapshot", None)
            _log_ai_usage(
                self._ctx,
                self._model,
                getattr(snapshot, "usage", None),
                duration_ms=int((time.monotonic() - self._t0) * 1000),
                ok=exc is None,
                error=(_ai_error_code(exc) or str(exc)) if exc else None,
            )
            if snapshot is not None:
                _note_web_search_failures(self._ctx, snapshot)
        except Exception:
            traceback.print_exc()
        return self._manager.__exit__(exc_type, exc, tb)


class _MessagesProxy:
    """Wraps `client.messages` so non-streaming `.create()` calls translate
    Anthropic key/billing errors into our HTTPExceptions (caught by each
    endpoint's `except HTTPException: raise`), and so every call — streaming or
    not — meters its token/web-search usage into `ai_usage`. Stream errors still
    surface to the endpoints' own handlers, since a mid-stream failure can't
    change an already-committed HTTP status."""

    def __init__(self, inner, ctx: dict | None = None):
        self._inner = inner
        self._ctx = ctx

    def create(self, *args, **kwargs):
        t0 = time.monotonic()
        try:
            resp = self._inner.create(*args, **kwargs)
        except anthropic.APIStatusError as e:
            _log_ai_usage(
                self._ctx, kwargs.get("model"), None,
                duration_ms=int((time.monotonic() - t0) * 1000),
                ok=False, error=_ai_error_code(e) or str(e),
            )
            raise (_ai_http_error(e) or e)
        _log_ai_usage(
            self._ctx, kwargs.get("model"), getattr(resp, "usage", None),
            duration_ms=int((time.monotonic() - t0) * 1000), ok=True,
        )
        _note_web_search_failures(self._ctx, resp)
        return resp

    def stream(self, *args, **kwargs):
        return _LoggedStreamManager(
            self._inner.stream(*args, **kwargs), self._ctx, kwargs.get("model")
        )

    def __getattr__(self, name):
        return getattr(self._inner, name)


class _AIClientProxy:
    def __init__(self, inner, ctx: dict | None = None):
        self._inner = inner
        self._ctx = ctx

    @property
    def messages(self):
        return _MessagesProxy(self._inner.messages, self._ctx)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def get_ai_client_for_league(sb, league_id: str, tool: str | None = None) -> anthropic.Anthropic:
    """Anthropic client keyed to the league owner's stored key. Raises 402
    (NoApiKeyError) when the owner hasn't set one — AI features stay off until
    they bring their own key. Works on the background cron path too: it resolves
    the owner from the league row, not from a logged-in user. The returned client
    translates key/billing errors and meters usage under `tool` (see
    `_MessagesProxy`)."""
    owner = _league_owner(sb, league_id)
    key = _get_user_api_key(sb, owner)
    if not key:
        raise NoApiKeyError()
    client = _ai_client_cache.get(key)
    if client is None:
        client = anthropic.Anthropic(api_key=key)
        _ai_client_cache[key] = client
    return _AIClientProxy(client, {"league_id": league_id, "user_id": owner, "tool": tool})


class ApiKeyRequest(BaseModel):
    key: str


@app.get("/settings/api-key")
async def get_api_key_status(user: dict = Depends(get_current_user)):
    """Whether the caller has an Anthropic key on file, plus its last 4 chars.
    Never returns the key itself."""
    sb = get_supabase()
    last4 = None
    try:
        row = (
            sb.table("user_secrets")
            .select("anthropic_key_last4")
            .eq("user_id", user.get("sub"))
            .single()
            .execute()
        )
        last4 = (row.data or {}).get("anthropic_key_last4")
    except Exception:
        last4 = None
    return {"set": bool(last4), "last4": last4}


@app.get("/me/ai-status")
async def get_ai_status(user: dict = Depends(get_current_user)):
    """The caller's current AI key health, derived from their most recent
    `ai_usage` row. Every AI call — including the background daily digest —
    meters here, so if the digest hits an out-of-credits wall at 8:43am this
    flips to `out_of_credits` and the frontend shows the banner on the next app
    load, without the user having to trigger a fresh failing call. `null` when
    the last call succeeded (or there's no history / the table predates its
    migration). Mirrors `aiIssueFromDetail`, just sourced from the DB instead of
    a live response."""
    sb = get_supabase()

    def _load() -> str | None:
        try:
            row = (
                sb.table("ai_usage")
                .select("ok, error")
                .eq("user_id", user.get("sub"))
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            data = row.data or []
            if data and not data[0].get("ok"):
                err = data[0].get("error")
                if err in ("out_of_credits", "invalid_api_key"):
                    return err
        except Exception:
            pass
        return None

    return {"issue": await asyncio.to_thread(_load)}


@app.put("/settings/api-key")
async def set_api_key(body: ApiKeyRequest, user: dict = Depends(get_current_user)):
    """Validate an Anthropic key against the API, then store it encrypted."""
    uid = user.get("sub")
    if not uid:
        raise HTTPException(status_code=401, detail="No user identity in token")
    key = (body.key or "").strip()
    if not key.startswith("sk-ant-"):
        raise HTTPException(
            status_code=400,
            detail="That doesn't look like an Anthropic API key (it should start with 'sk-ant-').",
        )
    # Cheap, no-token call that confirms the key authenticates before we store it.
    try:
        anthropic.Anthropic(api_key=key).models.list(limit=1)
    except anthropic.AuthenticationError:
        raise HTTPException(status_code=400, detail="Anthropic rejected that key. Double-check it and try again.")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Couldn't verify the key with Anthropic: {e}")
    sb = get_supabase()
    try:
        sb.table("user_secrets").upsert(
            {
                "user_id": uid,
                "anthropic_key_ciphertext": crypto.encrypt(key),
                "anthropic_key_last4": key[-4:],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="user_id",
        ).execute()
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    _ai_client_cache.clear()  # drop any client built from a previous key
    return {"set": True, "last4": key[-4:]}


@app.delete("/settings/api-key")
async def delete_api_key(user: dict = Depends(get_current_user)):
    sb = get_supabase()
    try:
        sb.table("user_secrets").delete().eq("user_id", user.get("sub")).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    _ai_client_cache.clear()
    return {"set": False, "last4": None}


# ── Admin dashboard (usage + troubleshooting) ─────────────────────────────────
# Gated to an allowlist of admin emails (env ADMIN_EMAILS, comma-separated;
# defaults to the app owner). Read-only snapshot derived from existing tables —
# no usage-event logging table yet — so it doubles as a health/troubleshooting
# view: spot users with no key or no sync at a glance.
ADMIN_EMAILS = {
    e.strip().lower()
    for e in os.getenv("ADMIN_EMAILS", "asecord92@gmail.com").split(",")
    if e.strip()
}


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if (user.get("email") or "").lower() not in ADMIN_EMAILS:
        raise HTTPException(status_code=403, detail="Admins only.")
    return user


@app.get("/admin/overview")
async def admin_overview(_user: dict = Depends(require_admin)):
    """Per-user usage + health snapshot for the app owner."""
    sb = get_supabase()
    now = datetime.now(timezone.utc)

    def _iso(ts) -> str | None:
        if ts is None:
            return None
        return ts if isinstance(ts, str) else ts.isoformat()

    def _age_days(ts: str | None) -> float:
        if not ts:
            return 1e9
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return (now - dt).total_seconds() / 86400
        except Exception:
            return 1e9

    try:
        raw_users = sb.auth.admin.list_users()
        users = getattr(raw_users, "users", raw_users) or []
    except Exception:
        traceback.print_exc()
        users = []

    leagues = sb.table("leagues").select(
        "id,owner_user_id,name,sport,platform,created_at"
    ).execute().data or []
    secrets = sb.table("user_secrets").select(
        "user_id,anthropic_key_last4"
    ).execute().data or []
    snaps = sb.table("snapshots").select(
        "league_id,created_at"
    ).order("created_at", desc=True).execute().data or []
    cache = sb.table("dashboard_cache").select(
        "league_id,widget,updated_at"
    ).execute().data or []
    try:  # tolerate the app_events migration not being applied yet
        events = sb.table("app_events").select(
            "created_at,user_id,league_id,kind,level,status,message"
        ).order("created_at", desc=True).limit(200).execute().data or []
    except Exception:
        events = []

    keys_by_user = {s["user_id"]: s for s in secrets}
    leagues_by_user: dict[str, list] = {}
    for lg in leagues:
        leagues_by_user.setdefault(lg["owner_user_id"], []).append(lg)

    last_sync_by_league: dict[str, str] = {}  # snaps already newest-first
    for s in snaps:
        last_sync_by_league.setdefault(s["league_id"], s["created_at"])

    widgets_by_league: dict[str, list] = {}
    for c in cache:
        widgets_by_league.setdefault(c["league_id"], []).append(c)

    errors_by_user: dict[str, int] = {}  # error count in the last 7 days
    for e in events:
        if e.get("level") == "error" and e.get("user_id") and _age_days(e.get("created_at")) <= 7:
            errors_by_user[e["user_id"]] = errors_by_user.get(e["user_id"], 0) + 1

    rows = []
    for u in users:
        uid = getattr(u, "id", None)
        u_leagues = leagues_by_user.get(uid, [])
        syncs = [last_sync_by_league.get(lg["id"]) for lg in u_leagues]
        syncs = [s for s in syncs if s]
        widget_times = [
            c["updated_at"]
            for lg in u_leagues
            for c in widgets_by_league.get(lg["id"], [])
        ]
        key = keys_by_user.get(uid)
        rows.append({
            "user_id": uid,
            "email": getattr(u, "email", None),
            "created_at": _iso(getattr(u, "created_at", None)),
            "last_sign_in_at": _iso(getattr(u, "last_sign_in_at", None)),
            "league_count": len(u_leagues),
            "leagues": [
                {"name": lg.get("name"), "sport": lg.get("sport")}
                for lg in u_leagues
            ],
            "has_key": bool(key),
            "key_last4": (key or {}).get("anthropic_key_last4"),
            "last_sync_at": max(syncs) if syncs else None,
            "last_widget_at": max(widget_times) if widget_times else None,
            "errors_7d": errors_by_user.get(uid, 0),
        })

    rows.sort(key=lambda r: r.get("last_sign_in_at") or "", reverse=True)

    # Recent error feed (most recent first), with the user's email attached.
    email_by_id = {r["user_id"]: r["email"] for r in rows}
    recent_errors = [
        {
            "created_at": e.get("created_at"),
            "email": email_by_id.get(e.get("user_id")),
            "kind": e.get("kind"),
            "status": e.get("status"),
            "message": e.get("message"),
        }
        for e in events
        if e.get("level") == "error"
    ][:40]

    return {
        "generated_at": now.isoformat(),
        "totals": {
            "users": len(rows),
            "leagues": len(leagues),
            "keys_set": sum(1 for r in rows if r["has_key"]),
            "active_7d": sum(1 for r in rows if _age_days(r["last_sign_in_at"]) <= 7),
            "synced_7d": sum(1 for r in rows if _age_days(r["last_sync_at"]) <= 7),
            "widgets_refreshed_7d": sum(1 for c in cache if _age_days(c["updated_at"]) <= 7),
            "errors_7d": sum(errors_by_user.values()),
        },
        "users": rows,
        "recent_errors": recent_errors,
    }


# --- AI usage / cost rollups ----------------------------------------------------
# Dollar costs are computed at DISPLAY time from this pricing map, so ai_usage
# history stays truthful when prices change. Rates are USD per MTok, from the
# platform pricing docs (fetched 2026-07-16). Sonnet 5 runs introductory
# pricing through 2026-08-31, so its rate is chosen per row by created_at.
# Web search bills $10 per 1,000 searches on top of tokens.
_WEB_SEARCH_COST = 0.01
_SONNET5_INTRO_UNTIL = "2026-09-01"


def _model_rates(model: str, created_at: str) -> dict:
    m = model or ""
    if m.startswith("claude-sonnet-5"):
        if (created_at or "") < _SONNET5_INTRO_UNTIL:
            return {"input": 2.0, "output": 10.0, "cache_read": 0.20, "cache_write": 2.50}
        return {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write": 3.75}
    if m.startswith("claude-haiku"):
        return {"input": 1.0, "output": 5.0, "cache_read": 0.10, "cache_write": 1.25}
    if m.startswith("claude-sonnet"):
        return {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write": 3.75}
    # Opus-tier, and anything unknown — don't understate a mystery model.
    return {"input": 5.0, "output": 25.0, "cache_read": 0.50, "cache_write": 6.25}


def _row_cost(row: dict) -> float:
    r = _model_rates(row.get("model") or "", row.get("created_at") or "")
    per_tok = 1 / 1_000_000
    return (
        (row.get("input_tokens") or 0) * r["input"] * per_tok
        + (row.get("output_tokens") or 0) * r["output"] * per_tok
        + (row.get("cache_read_tokens") or 0) * r["cache_read"] * per_tok
        + (row.get("cache_creation_tokens") or 0) * r["cache_write"] * per_tok
        + (row.get("web_searches") or 0) * _WEB_SEARCH_COST
    )


@app.get("/admin/usage")
async def admin_usage(_user: dict = Depends(require_admin)):
    """AI usage + estimated-cost rollups over the last 30 days, per tool and
    per user. Dollars are computed here (see _row_cost), never stored. Returns
    {available: false} until the ai_usage migration is applied."""
    sb = get_supabase()
    now = datetime.now(timezone.utc)
    since_30d = (now - timedelta(days=30)).isoformat()

    def _load():
        rows = (
            sb.table("ai_usage").select("*")
            .gte("created_at", since_30d)
            .order("created_at", desc=True)
            .limit(5000)
            .execute()
            .data
            or []
        )
        try:
            raw_users = sb.auth.admin.list_users()
            users = getattr(raw_users, "users", raw_users) or []
        except Exception:
            users = []
        return rows, users

    try:
        rows, users = await asyncio.to_thread(_load)
    except Exception:
        return {"available": False}

    email_by_id = {getattr(u, "id", None): getattr(u, "email", None) for u in users}
    cutoff_7d = (now - timedelta(days=7)).isoformat()

    _SUMMED = ("input_tokens", "output_tokens", "cache_read_tokens",
               "cache_creation_tokens", "web_searches")

    def bucket() -> dict:
        b = dict.fromkeys(_SUMMED, 0)
        b.update({"calls": 0, "errors": 0, "duration_ms": 0, "cost": 0.0,
                  "calls_7d": 0, "cost_7d": 0.0})
        return b

    by_tool: dict[str, dict] = {}
    by_user: dict[str, dict] = {}
    totals = bucket()
    for row in rows:
        cost = _row_cost(row)
        recent = (row.get("created_at") or "") >= cutoff_7d
        for b in (
            by_tool.setdefault(row.get("tool") or "unknown", bucket()),
            by_user.setdefault(row.get("user_id") or "unknown", bucket()),
            totals,
        ):
            b["calls"] += 1
            if row.get("ok") is False:
                b["errors"] += 1
            for k in _SUMMED:
                b[k] += row.get(k) or 0
            b["duration_ms"] += row.get("duration_ms") or 0
            b["cost"] += cost
            if recent:
                b["calls_7d"] += 1
                b["cost_7d"] += cost

    def finish(groups: dict[str, dict], label_key: str, label) -> list[dict]:
        out = []
        for key, b in groups.items():
            b[label_key] = label(key)
            b["avg_duration_ms"] = int(b["duration_ms"] / b["calls"]) if b["calls"] else 0
            out.append(b)
        out.sort(key=lambda x: x["cost"], reverse=True)
        return out

    return {
        "available": True,
        "generated_at": now.isoformat(),
        "window_days": 30,
        "totals": totals,
        "tools": finish(by_tool, "tool", lambda k: k),
        "users": finish(by_user, "email", lambda k: email_by_id.get(k) or k),
    }


class RosterSyncRequest(BaseModel):
    user_secret_id: str
    fantrax_league_id: str


class SleeperSyncRequest(BaseModel):
    league_id: str          # our leagues.id (UUID)
    sleeper_league_id: str


class TradeAnalyzeRequest(BaseModel):
    league_id: str
    my_team_id: str
    opponent_team_id: str
    offering_ids: str  # comma-separated fantrax player IDs
    receiving_ids: str  # comma-separated fantrax player IDs


class TradeFinderRequest(BaseModel):
    league_id: str
    my_team_id: str
    target_category: str | None = None  # omit to auto-pick the weakest category


class TradeHistoryItem(BaseModel):
    league_id: str
    offering: list[dict] = []   # players given up: [{id, name}]
    receiving: list[dict] = []  # players received:  [{id, name}]
    verdict: str = ""           # short parsed verdict line
    analysis: str = ""          # full streamed recommendation


# The lifecycle states a user can tag a recorded trade with. None = untracked.
_TRADE_OUTCOME_STATES = {"proposed", "accepted", "rejected", "completed"}


class TradeOutcomeUpdate(BaseModel):
    id: str                       # trade_history row id
    league_id: str                # for ownership check
    status: str | None = None     # one of _TRADE_OUTCOME_STATES, or None to clear
    note: str = ""                # optional retrospective note


class AddDropPlayer(BaseModel):
    id: str | None = None  # fantrax id when the player is rostered; None for free text
    name: str = ""


class AddDropRequest(BaseModel):
    league_id: str
    my_team_id: str
    incoming: list[AddDropPlayer] = []   # who you're adding (IL activation / trade / waiver)
    outgoing_ids: list[str] = []         # players already being dropped / traded away


class DashboardRequest(BaseModel):
    league_id: str
    my_team_id: str
    force: bool = False


class CategoryRanksRequest(BaseModel):
    league_id: str
    ranks: dict  # e.g. {"R": 4, "HR": 11, "RBI": 6, ...}


def extract_league_profile(league_info: dict, team_id: str) -> dict:
    draft = league_info.get("draftSettings", {})
    roster = league_info.get("rosterInfo", {})

    def to_int(val):
        return int(val) if val is not None else None

    return {
        "fantrax_team_id": team_id,
        "draft_budget": to_int(draft.get("budget")),
        "season_year": to_int(league_info.get("seasonYear")),
        "season_start": league_info.get("startDate"),
        "season_end": league_info.get("endDate"),
        "roster_max": to_int(roster.get("maxTotalPlayers")),
        "roster_active": to_int(roster.get("maxTotalActivePlayers")),
        "roster_reserve": to_int(roster.get("maxTotalReservePlayers")),
    }


def detect_rules(
    league_info: dict,
    team_roster: dict,
    rosters: dict,
    existing_rules: dict | None,
    sport: str,
) -> dict:
    """Refresh the auto-detectable structural rule fields (league size, in-season
    cap, offseason/auction budget) from Fantrax, while preserving user-owned
    fields (scoring categories, contract trajectory). Never invents contract
    rules — they stay as-is, or null until set in the Settings editor, so one
    league never silently inherits another's house rules."""
    rules = dict(existing_rules or {})
    rules["sport"] = sport

    if rosters:
        rules["league_size"] = len(rosters)

    cap = team_roster.get("salaryCap")
    if cap:
        try:
            rules["in_season_cap"] = int(cap)
        except (TypeError, ValueError):
            pass

    budget = (league_info.get("draftSettings") or {}).get("budget")
    if budget is not None:
        try:
            rules["offseason_cap"] = int(budget)
        except (TypeError, ValueError):
            pass

    # Scoring + contract are user-owned; only seed on first creation, and never
    # assume contract terms for a league we haven't been told the rules for.
    if "scoring" not in rules:
        rules["scoring"] = (
            {"hitting": ["R", "HR", "RBI", "SB", "OBP"], "pitching": ["QS", "SV", "K", "ERA", "WHIP"]}
            if sport == "MLB"
            else {"hitting": [], "pitching": []}
        )
    if "contract" not in rules:
        rules["contract"] = None

    return rules


# Single-flight guard for background resolution: rapid re-syncs of the same
# league would otherwise each spawn a full resolve pass, re-attempting the same
# unresolvable prospects concurrently (each a slow MLB API call). If a pass is
# already running for a league, later ones are skipped — the in-flight run
# already covers essentially the same rosters. Thread-safe because Starlette runs
# these sync background tasks in a worker-thread pool.
_resolve_in_progress: set[str] = set()
_resolve_guard = threading.Lock()


def resolve_all_players(rosters: dict, player_names: dict, league_id: str | None = None) -> None:
    """
    Background task: resolve Fantrax IDs to MLB IDs for all players
    across all league rosters. Runs after the sync response is sent.
    Deduplicated per league so overlapping syncs don't run it concurrently.
    """
    if league_id:
        with _resolve_guard:
            if league_id in _resolve_in_progress:
                print(f"[bg] Resolution already running for league {league_id}; skipping duplicate")
                return
            _resolve_in_progress.add(league_id)
    try:
        _resolve_all_players_inner(rosters, player_names)
    finally:
        if league_id:
            with _resolve_guard:
                _resolve_in_progress.discard(league_id)


def _resolve_all_players_inner(rosters: dict, player_names: dict) -> None:
    print("[bg] Starting full league player resolution...")
    all_items = []
    for tdata in rosters.values():
        all_items.extend(tdata.get("rosterItems", []))

    # Most of the league is already mapped after the first sync — find those in a
    # few batched queries instead of one Supabase round-trip per player.
    all_ids = [item.get("id", "") for item in all_items if item.get("id")]
    already_mapped = get_existing_fantrax_ids(all_ids)

    resolved = 0
    unresolved = []
    processed_ids = list(already_mapped)
    for item in all_items:
        fantrax_id = item.get("id", "")
        if fantrax_id in already_mapped:
            resolved += 1
            continue
        player_data = player_names.get(fantrax_id, {})
        name = player_data.get("name", "")
        team = player_data.get("team", "")
        if not name:
            continue
        mapping = resolve_player(fantrax_id, name, team)
        if mapping:
            resolved += 1
            processed_ids.append(fantrax_id)
        else:
            unresolved.append(name)

    print(f"[bg] Resolution complete: {resolved} resolved, {len(unresolved)} unresolved")
    if unresolved:
        print(f"[bg] Unresolved: {unresolved}")

    # Refresh roster statuses for all processed players — status changes frequently
    if processed_ids:
        refresh_roster_statuses(processed_ids)


def _check_cache(sb, league_id: str, widget: str, force: bool,
                 max_age: timedelta | None = None) -> dict | None:
    """Returns cached row {content, updated_at} if fresh, else None. `max_age`
    tightens the freshness window below the normal TTL (used after waiting on a
    concurrent generation, where only a just-written row should count)."""
    if force:
        return None
    try:
        result = (
            sb.table("dashboard_cache")
            .select("content,updated_at")
            .eq("league_id", league_id)
            .eq("widget", widget)
            .limit(1)
            .execute()
        )
        if result.data:
            row = result.data[0]
            updated_at = datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - updated_at < (max_age or DASHBOARD_CACHE_TTL):
                return row
    except Exception:
        pass
    return None


# One lock per (league, widget): a widget generation is an expensive AI call
# billed to the owner's key, so two concurrent requests (double-tap refresh,
# user + cron overlapping) must not both pay for it. The map only ever holds a
# few dozen entries (leagues × widgets), so it's never evicted.
_widget_locks: dict[tuple[str, str], asyncio.Lock] = {}

# After waiting on a concurrent generation, only a row written by that
# generation should count as a cache hit — not an older row within normal TTL.
_RECHECK_WINDOW = timedelta(minutes=5)


async def _single_flight(league_id: str, widget: str, recheck, generate):
    """Deduplicate concurrent generations of the same widget. If another request
    holds the lock, wait for it and serve its freshly cached result via
    `recheck()` (a callable returning the endpoint's cache-hit response or
    None); only generate if the cache is still missing. `generate()` must
    return an awaitable producing the endpoint response."""
    lock = _widget_locks.setdefault((league_id, widget), asyncio.Lock())
    waited = lock.locked()
    async with lock:
        if waited:
            cached = await asyncio.to_thread(recheck)
            if cached is not None:
                return cached
        return await generate()


def _upsert_cache(sb, league_id: str, widget: str, content: str) -> str:
    """Upserts content to dashboard_cache. Returns updated_at ISO string."""
    now = datetime.now(timezone.utc).isoformat()
    sb.table("dashboard_cache").upsert(
        {"league_id": league_id, "widget": widget, "content": content, "updated_at": now},
        on_conflict="league_id,widget",
    ).execute()
    return now


def _load_my_roster(sb, league_id: str, my_team_id: str,
                    map_columns: str = "fantrax_id,full_name") -> tuple[str, list, dict]:
    """The shared first step of every dashboard widget: the user's roster row
    plus their players' id-map rows. Returns (team_name, roster_items, id_map)
    where id_map is {fantrax_id: row with `map_columns`}. Raises 404 when the
    league has no synced roster. Blocking — call from a worker thread."""
    roster_result = (
        sb.table("rosters")
        .select("roster_items,team_name")
        .eq("league_id", league_id)
        .eq("fantrax_team_id", my_team_id)
        .limit(1)
        .execute()
    )
    if not roster_result.data:
        raise HTTPException(status_code=404, detail="No roster found. Sync your league first.")
    roster_row = roster_result.data[0]
    roster_items = roster_row.get("roster_items", [])
    team_name = roster_row.get("team_name", "Your Team")

    fantrax_ids = [item.get("id") for item in roster_items if item.get("id")]
    id_map: dict[str, dict] = {}
    if fantrax_ids:
        map_result = (
            sb.table("player_id_map")
            .select(map_columns)
            .in_("fantrax_id", fantrax_ids)
            .execute()
        )
        id_map = {r["fantrax_id"]: r for r in (map_result.data or [])}
    return team_name, roster_items, id_map


def _weak_categories_context(sb, league_id: str) -> tuple[dict, list[str]]:
    """Category ranks plus the categories ranked 7th or worse — the strategic
    context that keeps widget prompts prioritizing what actually helps."""
    category_ranks = _load_category_ranks(sb, league_id)
    weak_cats = [
        cat for cat, rank in category_ranks.items()
        if isinstance(rank, int) and rank >= 7
    ]
    return category_ranks, weak_cats


def _today_line() -> str:
    """Anchor AI prompts to the current date so 'current'/'recent' framing isn't
    interpreted against the model's training cutoff (which produced season-start
    feeling recommendations)."""
    now = datetime.now(timezone.utc)
    return (
        f"Today's date is {now.strftime('%A, %B %d, %Y')}. Base your analysis on the "
        f"current {now.year} MLB season and the last few weeks of games — do not rely "
        f"on storylines or stats from earlier seasons."
    )


# Delimiter the free-text widget prompts (news, waiver) are instructed to emit
# before their final answer. Needed because the model bridges its last search
# into the answer within a single text block ("This confirms Yates is the
# closer. I have enough to finalize…"), so block-level cuts alone can't
# separate narration from answer.
_ANSWER_MARKER = "===ANSWER==="

_ANSWER_MARKER_INSTRUCTION = (
    f"When your research is complete, output the line {_ANSWER_MARKER} on its own, "
    "then your final answer. Everything before that line is discarded — keep all "
    "research commentary before it and never reference your research process after it."
)


# Sonnet 5 reaches for tools LESS when thinking is disabled — which is exactly
# how the widgets run (`_NO_THINKING`, a deliberate BYOK cost choice). Their
# prompts also hard-forbid asserting a team/role/health status that wasn't
# confirmed by search, so a run where the model declines to search can't produce
# recommendations at all — only the "I was unable to verify…" disclaimer.
#
# That failure mode is INVISIBLE to `_web_search_failed`: zero attempts is
# deliberately not an outage (see its docstring), so the disclaimer caches for
# the full 8h window and ships in the digest looking identical to a real
# upstream outage. The two need opposite fixes, so make the trigger explicit
# rather than implied. Diagnostic: `ai_usage.web_searches == 0` on a news /
# start_sit / waiver row means the model skipped searching, not that search
# broke — check that before touching this.
_SEARCH_FIRST_INSTRUCTION = (
    "Use web search before you answer — do not skip this step. The roster and "
    "stat data above is current, but it says nothing about health, role, or "
    "playing time, and your answer is wrong if any of those changed recently. "
    "Search first, then write the answer."
)


def _with_search_first(prompt: str) -> str:
    """Append the search-first trigger to a web-search widget prompt. Applied at
    the call sites rather than inside each prompt builder so all six (MLB + NFL
    × news / start_sit / waiver) stay provably in sync, and so the whole nudge
    can be lifted in one edit if a future model stops needing it."""
    return f"{prompt}\n\n{_SEARCH_FIRST_INSTRUCTION}"


def _extract_text(response: anthropic.types.Message) -> str:
    # With web search enabled the model narrates BETWEEN tool calls ("Let me
    # dig deeper…", "Good data. Kim has been placed on IL…"). Those interleaved
    # text blocks are research process, not answer — the real response is the
    # text after the LAST tool block. The phrase filter below only catches
    # known preamble openers, so it can't be the primary defense.
    blocks = response.content
    last_tool = -1
    for i, block in enumerate(blocks):
        if getattr(block, "type", "") != "text":
            last_tool = i

    def joined(from_index: int) -> str:
        return "\n".join(
            block.text
            for block in blocks[from_index:]
            if hasattr(block, "text") and block.type == "text"
        )

    text = joined(last_tool + 1)
    if not text.strip():
        # Truncated response with nothing after the final search — better to
        # show the narration than nothing at all.
        text = joined(0)

    # Strongest cut: prompts that use _ANSWER_MARKER_INSTRUCTION delimit the
    # answer explicitly; drop everything up to and including the marker.
    marker_at = text.find(_ANSWER_MARKER)
    if marker_at != -1:
        text = text[marker_at + len(_ANSWER_MARKER):]
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if any(stripped.lower().startswith(p) for p in [
            "let me search",
            "i'll search",
            "i will search",
            "let me check",
            "let me look",
            "based on my research",
            "based on current",
            "i appreciate",
            "now i have",
            "here is a summary",
        ]):
            continue
        cleaned.append(line)
    result = "\n".join(cleaned)
    result = re.sub(r"^(\s*---\s*\n)+", "", result)
    result = re.sub(r"^(\s*\n)+", "", result)
    return result


def _web_search_failed(response: anthropic.types.Message) -> bool:
    """True when the model attempted web searches and every one errored — an
    upstream search outage. The widget prompts hard-forbid asserting player
    status without verification, so an all-errored run is a compliance
    disclaimer ("I was unable to complete the required web verification…"), not
    an answer — never cache it (mirrors mlb_stats_client's outage rule; a cached
    one shipped in the digest email). Zero attempts is NOT an outage: the model
    may legitimately answer from the provided data alone, and treating that as
    failure would loop the warmer on re-billing regenerations."""
    attempted = errored = 0
    for block in response.content:
        if getattr(block, "type", "") != "web_search_tool_result":
            continue
        attempted += 1
        # On success .content is a list of results; on failure it's an error
        # object typed web_search_tool_result_error.
        if getattr(getattr(block, "content", None), "type", "") == "web_search_tool_result_error":
            errored += 1
    return attempted > 0 and errored == attempted


def _web_search_error_codes(message) -> list[str]:
    """Anthropic's error codes from a response's failed web searches, in order.

    Server-tool failures arrive *inside* a 200 response (the result block's
    content is an error object), so they never reach an exception handler and
    `_web_search_failed` only answers yes/no. The codes are the missing `why`,
    and they point at different fixes: `unavailable` is an upstream outage to
    wait out, `too_many_requests` is the owner's key being throttled (the daily
    digest warms every opted-in league's widgets in a burst, which is exactly
    how you'd earn that), and `max_uses_exceeded` is our own `max_uses` budget.
    """
    codes: list[str] = []
    for block in getattr(message, "content", None) or []:
        if getattr(block, "type", "") != "web_search_tool_result":
            continue
        content = getattr(block, "content", None)
        if getattr(content, "type", "") == "web_search_tool_result_error":
            codes.append(str(getattr(content, "error_code", "") or "unknown"))
    return codes


def _note_web_search_failures(ctx: dict | None, message) -> None:
    """Record failed web searches to app_events so an outage is diagnosable
    instead of merely visible. Hooked into the AI metering wrappers rather than
    the six widget call sites, so it covers *every* call — including
    /trade/analyze, which searches but has no `_web_search_failed` check of its
    own (it isn't cached, so it never needed the caching decision). Best-effort:
    this observes requests, it must never break one."""
    try:
        codes = _web_search_error_codes(message)
        if not codes:
            return
        total = _web_search_failed(message)
        _log_event(
            kind="web_search",
            # Only a total outage is actionable enough for the admin error feed
            # (which filters level == "error"); a partial still had real data.
            level="error" if total else "warning",
            message=(
                f"{len(codes)} web search(es) failed"
                f"{' — ALL of them' if total else ''}: "
                f"{', '.join(sorted(set(codes)))}"
            ),
            user_id=(ctx or {}).get("user_id"),
            league_id=(ctx or {}).get("league_id"),
            meta={"tool": (ctx or {}).get("tool"), "codes": codes, "all_failed": total},
        )
    except Exception:
        traceback.print_exc()


def _load_category_ranks(sb, league_id: str) -> dict:
    """Load category ranks from dashboard_cache. Returns {} if not set."""
    try:
        result = (
            sb.table("dashboard_cache")
            .select("content")
            .eq("league_id", league_id)
            .eq("widget", "category_ranks")
            .limit(1)
            .execute()
        )
        if result.data:
            return _json.loads(result.data[0]["content"])
    except Exception:
        pass
    return {}


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/cron/refresh-widgets")
async def cron_refresh_widgets(x_cron_secret: str = Header(default="")):
    """Machine-triggered re-warm of the AI dashboard widgets so users never wait
    on an on-demand generation. Guarded by the CRON_SECRET shared secret (not a
    user JWT). Only refreshes widgets that already have a cache entry near expiry,
    so dormant leagues incur no AI cost."""
    secret = os.getenv("CRON_SECRET")
    if not secret or x_cron_secret != secret:
        raise HTTPException(status_code=401, detail="Unauthorized")
    # Only keep actively-used leagues warm — dormant ones cost nothing until the
    # owner opens the app again (or their opt-in digest warms them each morning).
    active = await asyncio.to_thread(_recently_viewed_league_ids, get_supabase())
    refreshed = await _warm_stale_widgets(get_supabase(), only_league_ids=active)
    return {"refreshed": refreshed, "count": len(refreshed)}


async def _warm_stale_widgets(sb, only_league_ids: set[str] | None = None) -> list[str]:
    """Regenerate every near-expiry cached widget (the warmer's core). Can run
    for many minutes across leagues — callers over HTTP must background it or
    Railway's edge cuts the request around the 5-minute mark (which is exactly
    how the first digest run died). `only_league_ids` restricts the sweep — the
    standalone cron passes recently-viewed leagues, the digest passes opted-in
    ones; None warms every league (the pre-gate behavior)."""
    leagues = (await asyncio.to_thread(
        lambda: sb.table("leagues").select("id, fantrax_team_id").execute()
    )).data or []

    handlers = {
        "news": dashboard_news,
        "start_sit": dashboard_start_sit,
        "waiver": dashboard_waiver,
    }
    refreshed: list[str] = []
    for lg in leagues:
        league_id = lg.get("id")
        team_id = lg.get("fantrax_team_id")
        if not league_id or not team_id:
            continue
        if only_league_ids is not None and league_id not in only_league_ids:
            continue  # not in active use (cron) / not opted in (digest) — skip
        for widget, handler in handlers.items():
            age = await asyncio.to_thread(_cache_age, sb, league_id, widget)
            if age is None or age < REFRESH_AFTER:
                continue  # never generated (dormant league) or still fresh
            try:
                await handler(
                    DashboardRequest(league_id=league_id, my_team_id=team_id, force=True),
                    user={},
                )
                refreshed.append(f"{league_id}:{widget}")
            except Exception as e:
                print(f"[cron] refresh failed {league_id}:{widget}: {e}")
    return refreshed


# --- Daily digest email ---------------------------------------------------------
# Assembled from the already-cached widgets plus one small no-search AI call for
# "The Lead" — a punchy morning brief in the trade advisor's voice. Sent via the
# Brevo HTTPS API (BREVO_API_KEY + DIGEST_FROM_EMAIL env). Opt-IN per league via
# leagues.digest_enabled; recipients are each league owner's auth email.

# Reading the cache for the digest: anything generated this morning (or still
# within the widget TTL) qualifies — we never trigger a generation from here.
_DIGEST_CACHE_WINDOW = timedelta(hours=6)


def _truncate_readable(text: str, limit: int) -> str:
    """Truncate to ~limit chars on a boundary — never mid-sentence or mid-word —
    and append a marker so a trimmed section reads as intentional, not cut off.
    Prefers a line break, then a sentence end, then a word boundary; falls back
    to a hard cut only if no boundary sits in the back half. Returns the text
    unchanged when it already fits."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    window = text[:limit]
    for sep in ("\n", ". ", "! ", "? ", " "):
        idx = window.rfind(sep)
        if idx >= limit // 2:  # only snap back to a boundary that isn't too greedy
            window = window[: idx + (0 if sep == "\n" else 1)]
            break
    return window.rstrip(" ,;:—-\n") + "\n\n… more in the app"


def _md_lite_html(text: str) -> str:
    """Tiny markdown-to-HTML for email bodies: **bold**, bullet lines, paragraphs.
    Everything is HTML-escaped first — widget content is model output."""
    out: list[str] = []
    in_list = False
    for raw_line in (text or "").splitlines():
        line = _html.escape(raw_line.strip())
        line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
        is_bullet = line.startswith(("- ", "* ", "• "))
        if is_bullet:
            if not in_list:
                out.append('<ul style="margin:6px 0 12px;padding-left:20px;">')
                in_list = True
            out.append(f'<li style="margin:4px 0;">{line[2:].strip()}</li>')
        else:
            if in_list:
                out.append("</ul>")
                in_list = False
            if line:
                out.append(f'<p style="margin:6px 0;">{line}</p>')
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def _digest_start_sit_text(raw: str) -> str:
    """Condense the cached start_sit JSON into a few readable lines."""
    try:
        content = _json.loads(raw)
    except Exception:
        return ""
    by_rec: dict[str, list[str]] = {}
    for p in content.get("players") or []:
        rec = (p.get("recommendation") or "").lower()
        if p.get("name"):
            by_rec.setdefault(rec, []).append(p["name"])
    lines = [
        f"**{label}:** {', '.join(names)}"
        for label, key in (("Start", "start"), ("Monitor", "monitor"), ("Sit", "sit"))
        if (names := by_rec.get(key))
    ]
    for a in (content.get("alerts") or [])[:6]:
        if a.get("name"):
            status = f" ({a['status']})" if a.get("status") else ""
            detail = f" — {a['detail']}" if a.get("detail") else ""
            lines.append(f"- {a['name']}{status}{detail}")
    return "\n".join(lines)


def _digest_waiver_text(raw: str) -> str:
    """Prefer the scannable Priority order section; fall back to a trimmed body."""
    m = re.search(r"\*\*Priority order\*\*[:\s]*", raw or "", re.IGNORECASE)
    if m:
        return _truncate_readable(raw[m.start():], 2200)
    return _truncate_readable(raw or "", 2200)


def _digest_lead(sb, league_id: str, sport: str, sections: dict[str, str], standings_line: str,
                 prev_lead: str | None = None) -> str | None:
    """One small no-web-search AI call that turns the cached intel into 'The
    Lead'. Returns None (digest still sends, stitched-only) if the owner has no
    key or the call fails — the lead is garnish, not load-bearing."""
    intel = "\n\n".join(f"## {title}\n{body[:2500]}" for title, body in sections.items() if body)
    if standings_line:
        intel = f"## Standings\n{standings_line}\n\n{intel}"
    if not intel:
        return None
    sport_word = "football" if sport == "NFL" else "baseball"
    # Give the model yesterday's lead so it stops re-sending the same brief on a
    # quiet news day (the main "it's all the same thing daily" complaint).
    novelty = ""
    if prev_lead and prev_lead.strip():
        novelty = f"""

Yesterday you sent this brief — do NOT repeat these points unless there's a genuinely new development:
{prev_lead.strip()[:1200]}

If nothing meaningful has changed since yesterday, reply with exactly this one line and nothing else: "{_DIGEST_QUIET_SENTINEL.capitalize()} — nothing new since yesterday."."""
    prompt = f"""You write "The Lead" of a dynasty {sport_word} team's morning email digest. You are sharp,
opinionated, and direct — a trusted advisor, not a newsletter bot. {_today_line()}

Below is this morning's intel for the team (already generated — do not invent anything beyond it).

{intel}{novelty}

Write The Lead: 3-5 punchy markdown bullets, about 100 words TOTAL. Pick only what actually matters
today — the one news item that changes something, a borderline lineup call with your verdict, the #1
waiver move and why, the standings picture only if it's notable. No preamble, no headers, no
sign-off — start directly with the first bullet."""
    try:
        ai = get_ai_client_for_league(sb, league_id, tool="digest")
        response = ai.messages.create(
            model=MODEL_DASHBOARD,
            max_tokens=800,
            thinking=_NO_THINKING,
            messages=[{"role": "user", "content": prompt}],
        )
        lead = _extract_text(response).strip()
        return lead or None
    except Exception as e:
        print(f"[digest] lead generation failed for {league_id}: {e}")
        return None


# When several leagues share one email, each section gets trimmed harder — the
# combined email should read like a newspaper (leads up top, compact sections
# below), with the app holding the full content.
_MULTI_SECTION_CAP = 1400

_LEAD_BOX = (
    '<div style="background:#f4f1fb;border-left:4px solid #7c3aed;border-radius:8px;'
    'padding:10px 14px;margin-bottom:16px;">'
)


def _sport_emoji(sport: str) -> str:
    return "🏈" if sport == "NFL" else "⚾"


def _digest_email_bodies(parts: list[dict]) -> tuple[str, str, str]:
    """(subject, html, plain-text) for one recipient's digest. Each part is one
    league's content ({league_name, sport, sections, standings_line, lead}).
    A single league renders as before; multiple leagues share one email in
    newspaper form — every league's Lead up top, capped sections below."""
    try:
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("America/Los_Angeles"))
    except Exception:
        today = datetime.now(timezone.utc)
    multi = len(parts) > 1

    if multi:
        subject = f"🗞️ Your DynastyOS Daily — {today.strftime('%A, %B %d')}"
        header = "🗞️ DynastyOS Daily"
        header_sub = today.strftime("%A, %B %d, %Y")
    else:
        p = parts[0]
        emoji = _sport_emoji(p["sport"])
        subject = f"{emoji} {p['league_name']} Daily — {today.strftime('%A, %B %d')}"
        header = f"{emoji} {_html.escape(p['league_name'])} Daily"
        header_sub = today.strftime("%A, %B %d, %Y") + (
            f" · {_html.escape(p['standings_line'])}" if p["standings_line"] else ""
        )

    html_parts = [
        '<div style="max-width:600px;margin:0 auto;font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#1a1a1a;font-size:15px;line-height:1.5;padding:16px;">',
        f'<h2 style="margin:0 0 2px;">{header}</h2>',
        f'<div style="color:#777;font-size:13px;margin-bottom:14px;">{header_sub}</div>',
    ]
    text_parts = [f"{subject.split(' — ')[0]} — {today.strftime('%A, %B %d, %Y')}"]

    def league_label(p: dict) -> str:
        label = f"{_sport_emoji(p['sport'])} {p['league_name']}"
        if p["standings_line"]:
            label += f" · {p['standings_line']}"
        return label

    # The Lead — for a combined email, every league's bullets sit up top so the
    # whole morning read is the first screen.
    for p in parts:
        if not p["lead"]:
            continue
        if multi:
            html_parts.append(
                f'<div style="font-weight:600;margin:12px 0 4px;">{_html.escape(league_label(p))}</div>'
            )
            text_parts += ["", league_label(p).upper()]
        else:
            text_parts += ["", "THE LEAD"]
        html_parts.append(_LEAD_BOX + _md_lite_html(p["lead"]) + "</div>")
        text_parts.append(p["lead"])

    # Below the fold — each league's sections, trimmed harder when sharing.
    for p in parts:
        if multi:
            html_parts.append(
                f'<h2 style="margin:24px 0 2px;border-bottom:2px solid #e5e5e5;padding-bottom:4px;">'
                f'{_sport_emoji(p["sport"])} {_html.escape(p["league_name"])}</h2>'
            )
            text_parts += ["", "=" * 8, league_label(p).upper()]
        for title, body in p["sections"].items():
            if not body:
                continue
            if multi:
                body = _truncate_readable(body, _MULTI_SECTION_CAP)
            html_parts.append(
                f'<h3 style="margin:18px 0 4px;border-bottom:1px solid #e5e5e5;padding-bottom:4px;">{_html.escape(title)}</h3>'
            )
            html_parts.append(_md_lite_html(body))
            text_parts += ["", title.upper(), body]

    html_parts.append(
        '<div style="color:#999;font-size:12px;margin-top:22px;border-top:1px solid #e5e5e5;padding-top:10px;">'
        "Sent by DynastyOS. Turn the daily digest off in Settings.</div></div>"
    )
    text_parts += ["", "Sent by DynastyOS. Turn the daily digest off in Settings."]
    return subject, "\n".join(html_parts), "\n".join(text_parts)


def _send_digest_email(to_addr: str, subject: str, html: str, text: str) -> None:
    """Deliver via Brevo's HTTPS API. Railway blocks ALL outbound SMTP ports
    (25/465/587) on Hobby plans — a classic SMTP send dies with '[Errno 101]
    Network is unreachable' — so email must go over HTTPS from here.
    DIGEST_FROM_EMAIL must be a Brevo-verified sender address."""
    api_key = os.getenv("BREVO_API_KEY")
    sender = os.getenv("DIGEST_FROM_EMAIL")
    if not api_key or not sender:
        raise RuntimeError("BREVO_API_KEY / DIGEST_FROM_EMAIL not configured")
    payload = {
        "sender": {"name": "DynastyOS", "email": sender},
        "to": [{"email": to_addr}],
        "subject": subject,
        "htmlContent": html,
        "textContent": text,
    }
    # The sender address is send-only; route replies to a real inbox when
    # configured so "hey, this digest is wrong" reaches the app owner.
    reply_to = os.getenv("DIGEST_REPLY_TO")
    if reply_to:
        payload["replyTo"] = {"email": reply_to}
    resp = httpx.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={"api-key": api_key, "content-type": "application/json"},
        json=payload,
        timeout=30,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"Brevo send failed ({resp.status_code}): {resp.text[:300]}")


def _owner_email(sb, user_id: str | None) -> str | None:
    if not user_id:
        return None
    try:
        res = sb.auth.admin.get_user_by_id(user_id)
        return getattr(getattr(res, "user", res), "email", None)
    except Exception:
        return None


def _nfl_digest_offseason(today: datetime | None = None) -> bool:
    """True during the NFL dead period (roughly mid-Feb → late Aug), when there's
    no real weekly news and the widgets recycle the same evergreen roster takes
    daily. Football is dropped from the digest in this window and auto-resumes for
    training camp/preseason. Uses Pacific date to match the send time."""
    if today is None:
        try:
            from zoneinfo import ZoneInfo
            today = datetime.now(ZoneInfo("America/Los_Angeles"))
        except Exception:
            today = datetime.now(timezone.utc)
    md = (today.month, today.day)
    return (2, 16) <= md <= (8, 24)


# Dedupe: the digest remembers what it sent each league yesterday (stored as a
# `digest_prev` cache row) and drops sections that haven't meaningfully changed,
# so a quiet news day doesn't re-send the same brief. A league with nothing new
# is skipped entirely; a recipient with no fresh league drops out of the send.
_DIGEST_STALE_SIMILARITY = 0.85
_DIGEST_QUIET_SENTINEL = "quiet day"


def _text_similarity(a: str, b: str) -> float:
    """Jaccard overlap of lowercased word tokens — a cheap 'is this basically the
    same text as yesterday' signal that tolerates minor model-prose drift."""
    ta = set(re.findall(r"\w+", (a or "").lower()))
    tb = set(re.findall(r"\w+", (b or "").lower()))
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _read_prev_digest(sb, league_id: str) -> dict:
    """Yesterday's stitched digest for this league ({sections, lead}), or {}."""
    try:
        result = (
            sb.table("dashboard_cache")
            .select("content")
            .eq("league_id", league_id)
            .eq("widget", "digest_prev")
            .limit(1)
            .execute()
        )
        if result.data:
            return _json.loads(result.data[0]["content"]) or {}
    except Exception:
        pass
    return {}


def _league_digest_part(sb, league: dict) -> tuple[str, dict | None]:
    """Assemble one league's digest content (including its AI lead). Returns
    (status, part) — part is None unless status is "ready". Blocking — run in
    a worker thread."""
    league_id = league.get("id")
    if league.get("digest_enabled") is not True:  # opt-in: only explicit True sends
        return "opted_out", None

    sport = league.get("sport") or "MLB"
    if sport == "NFL" and _nfl_digest_offseason():
        return "offseason_skip", None

    sections: dict[str, str] = {}
    row = _check_cache(sb, league_id, "start_sit", force=False, max_age=_DIGEST_CACHE_WINDOW)
    if row:
        sections["Today's Calls"] = _digest_start_sit_text(row["content"])
    row = _check_cache(sb, league_id, "news", force=False, max_age=_DIGEST_CACHE_WINDOW)
    if row:
        sections["News"] = _truncate_readable(row["content"], 3000)
    row = _check_cache(sb, league_id, "waiver", force=False, max_age=_DIGEST_CACHE_WINDOW)
    if row:
        sections["Waiver Watch"] = _digest_waiver_text(row["content"])
    if not any(sections.values()):
        return "no_content", None  # dormant/off-season league — nothing to say

    standings_line = ""
    if league.get("fantrax_league_id") and league.get("fantrax_team_id"):
        try:
            s = _build_standings(league["fantrax_league_id"], league["fantrax_team_id"])
            if s.get("rank"):
                standings_line = f"{s['record']}, #{s['rank']} of {s['total_teams']}"
        except Exception:
            pass

    # Dedupe against yesterday: the lead is generated from the full sections (with
    # yesterday's lead for context), but only sections that actually changed are
    # shown below the fold. Persist today's full content for tomorrow either way.
    prev = _read_prev_digest(sb, league_id)
    prev_sections = prev.get("sections") or {}
    fresh_sections = {
        title: body for title, body in sections.items()
        if body and _text_similarity(body, prev_sections.get(title, "")) < _DIGEST_STALE_SIMILARITY
    }

    lead = _digest_lead(sb, league_id, sport, sections, standings_line, prev_lead=prev.get("lead"))
    try:
        _upsert_cache(sb, league_id, "digest_prev", _json.dumps({"sections": sections, "lead": lead or ""}))
    except Exception:
        pass  # best-effort memory — a failed write just means no dedupe next run

    lead_is_quiet = (lead or "").strip().lower().startswith(_DIGEST_QUIET_SENTINEL)
    if not fresh_sections and (lead_is_quiet or not lead):
        return "quiet", None  # nothing new since yesterday — drop from the email

    return "ready", {
        "league_name": league.get("name") or "Your League",
        "sport": sport,
        "sections": fresh_sections,
        "standings_line": standings_line,
        "lead": None if lead_is_quiet else lead,
    }


async def _daily_digest_job():
    """Warm the widget caches, then assemble + email each opted-in league's
    digest. Runs as a background task — the whole pipeline takes minutes, far
    past Railway's ~5-minute edge timeout for a live HTTP request. The outcome
    is summarized to app_events so the admin page shows how each run went."""
    sb = get_supabase()

    # Bail before any AI spend if the sender isn't configured — each league's
    # digest generates a billed lead call before it would hit the email API, so
    # a missing env var must not cost a lead generation per league per attempt.
    if not (os.getenv("BREVO_API_KEY") and os.getenv("DIGEST_FROM_EMAIL")):
        print("[digest] aborted: BREVO_API_KEY / DIGEST_FROM_EMAIL not configured")
        await asyncio.to_thread(
            _log_event, kind="digest", level="warning", status=500,
            message="digest aborted: BREVO_API_KEY / DIGEST_FROM_EMAIL not configured",
        )
        return

    try:
        # Warm only opted-in leagues — disabled ones short-circuit to
        # "opted_out" below, so warming them would be pure waste.
        enabled = await asyncio.to_thread(_digest_enabled_league_ids, sb)
        refreshed = await _warm_stale_widgets(sb, only_league_ids=enabled)
        print(f"[digest] warmed {len(refreshed)} widgets")
    except Exception:
        traceback.print_exc()  # digest still sends from whatever cache exists

    leagues = (await asyncio.to_thread(
        lambda: sb.table("leagues").select("*").execute()
    )).data or []

    # One email per person: group leagues by owner, assemble every opted-in
    # league's content, and send a single combined digest per recipient.
    by_owner: dict[str, list[dict]] = {}
    for lg in leagues:
        if lg.get("id"):
            by_owner.setdefault(lg.get("owner_user_id") or "", []).append(lg)

    results: dict[str, str] = {}
    emails_sent = 0
    for owner_id, owner_leagues in by_owner.items():
        email = await asyncio.to_thread(_owner_email, sb, owner_id)
        if not email:
            # Resolve the address before assembling anything — each ready
            # league costs a billed AI lead, pointless with nowhere to send.
            for lg in owner_leagues:
                results[lg["id"]] = "no_email"
            continue

        parts: list[dict] = []
        ready_ids: list[str] = []
        for lg in owner_leagues:
            try:
                status, part = await asyncio.to_thread(_league_digest_part, sb, lg)
            except Exception as e:
                print(f"[digest] failed for {lg['id']}: {e}")
                results[lg["id"]] = f"error: {e}"
                continue
            results[lg["id"]] = status
            if part is not None:
                parts.append(part)
                ready_ids.append(lg["id"])
        if not parts:
            continue

        try:
            subject, html_body, text_body = _digest_email_bodies(parts)
            await asyncio.to_thread(_send_digest_email, email, subject, html_body, text_body)
            emails_sent += 1
            for lid in ready_ids:
                results[lid] = "sent"
        except Exception as e:
            print(f"[digest] send failed for {email}: {e}")
            for lid in ready_ids:
                results[lid] = f"error: {e}"

    sent = sum(1 for v in results.values() if v == "sent")
    print(f"[digest] done: emails={emails_sent} leagues_sent={sent} results={results}")
    await asyncio.to_thread(
        _log_event,
        kind="digest",
        level="info" if sent or not results else "warning",
        status=200,
        message=_json.dumps({"emails": emails_sent, "sent": sent, "results": results}),
    )


@app.post("/cron/daily-digest")
async def cron_daily_digest(background_tasks: BackgroundTasks, x_cron_secret: str = Header(default="")):
    """Machine-triggered morning digest: warms the widgets, then emails each
    opted-in league owner. Responds immediately and runs the pipeline as a
    background task; the run's outcome lands in app_events (admin page)."""
    secret = os.getenv("CRON_SECRET")
    if not secret or x_cron_secret != secret:
        raise HTTPException(status_code=401, detail="Unauthorized")
    background_tasks.add_task(_daily_digest_job)
    return {"started": True}


def _build_standings(fantrax_league_id: str, my_team_id: str) -> dict:
    """Resolve a team's record from the (10-min cached) Fantrax standings list."""
    teams = _get_standings_cached(fantrax_league_id)
    total_teams = len(teams)
    team = next((t for t in teams if t.get("teamId") == my_team_id), None)
    if not team:
        return {"wins": None, "losses": None, "ties": None, "record": "—",
                "rank": None, "team_name": "", "total_teams": total_teams}
    parts = (team.get("points") or "0-0-0").split("-")

    def _p(i: int) -> int:
        try:
            return int(parts[i])
        except (IndexError, ValueError):
            return 0

    return {
        "wins": _p(0), "losses": _p(1), "ties": _p(2),
        "record": team.get("points", "—"), "rank": team.get("rank"),
        "team_name": team.get("teamName", ""), "total_teams": total_teams,
    }


def require_league_owner(sb, user: dict, league_id: str) -> None:
    """Ensure the authenticated user owns this league. The backend uses the
    service key (bypassing RLS), so league ownership must be checked explicitly,
    or any logged-in user could read/modify any league by id. Rows with no owner
    set (legacy) are allowed; a row owned by someone else is blocked (403)."""
    sub = (user or {}).get("sub")
    try:
        row = sb.table("leagues").select("owner_user_id").eq("id", league_id).single().execute()
    except Exception:
        return  # lookup failed (e.g. not found) — let the endpoint's logic handle it
    owner = (row.data or {}).get("owner_user_id")
    # Block only when we have both a known owner and a known requester that differ —
    # never lock out on a missing owner (legacy rows) or indeterminate identity.
    if owner and sub and owner != sub:
        raise HTTPException(status_code=403, detail="You don't have access to this league.")


@app.get("/league/standings")
async def league_standings(
    league_id: str = Query(...),
    my_team_id: str = Query(...),
    user: dict = Depends(get_current_user),
):
    try:
        sb = get_supabase()
        require_league_owner(sb, user, league_id)
        league_row = (
            sb.table("leagues")
            .select("fantrax_league_id")
            .eq("id", league_id)
            .single()
            .execute()
        )
        fantrax_league_id = league_row.data.get("fantrax_league_id") if league_row.data else None
        if not fantrax_league_id:
            raise HTTPException(status_code=404, detail="No Fantrax league connected.")
        return _build_standings(fantrax_league_id, my_team_id)
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/nfl/dashboard")
async def nfl_dashboard(
    league_id: str = Query(...),
    my_team_id: str = Query(...),
    user: dict = Depends(get_current_user),
):
    """Football dashboard data: record, standings + points-for, positional
    strength, and players currently out."""
    try:
        require_league_owner(get_supabase(), user, league_id)
        return await build_nfl_dashboard(league_id, my_team_id)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/league/category-ranks")
async def get_category_ranks(
    league_id: str = Query(...),
    user: dict = Depends(get_current_user),
):
    try:
        sb = get_supabase()
        require_league_owner(sb, user, league_id)
        result = (
            sb.table("dashboard_cache")
            .select("content,updated_at")
            .eq("league_id", league_id)
            .eq("widget", "category_ranks")
            .limit(1)
            .execute()
        )
        if result.data:
            try:
                ranks = _json.loads(result.data[0]["content"])
            except Exception:
                ranks = {}
            return {"ranks": ranks, "updated_at": result.data[0]["updated_at"]}
        return {"ranks": {}, "updated_at": None}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/league/category-ranks/history")
async def get_category_rank_history(
    league_id: str = Query(...),
    limit: int = Query(12, ge=2, le=60),
    user: dict = Depends(get_current_user),
):
    """Recent daily category-rank snapshots for this league, oldest→newest, for
    the dashboard sparklines. Returns [] when history hasn't accrued yet (or the
    table isn't migrated) so the widget just renders without trend lines."""
    try:
        sb = get_supabase()
        require_league_owner(sb, user, league_id)
        rows = (
            sb.table("category_rank_history")
            .select("snapshot_date,ranks,num_teams")
            .eq("league_id", league_id)
            .order("snapshot_date", desc=True)
            .limit(limit)
            .execute()
        ).data or []
        rows.reverse()  # chronological for plotting
        points = [
            {
                "date": r["snapshot_date"],
                "ranks": r["ranks"] if isinstance(r.get("ranks"), dict) else {},
                "num_teams": r.get("num_teams"),
            }
            for r in rows
        ]
        return {"history": points}
    except HTTPException:
        raise
    except Exception:
        traceback.print_exc()
        return {"history": []}  # trends are optional garnish — never 500 the dashboard


@app.get("/dashboard/summary")
async def dashboard_summary(
    league_id: str = Query(...),
    my_team_id: str = Query(...),
    user: dict = Depends(get_current_user),
):
    """One call for the dashboard: standings + the cached start_sit and
    category_ranks contents. No AI generation here — pure cache reads (kept warm
    by /cron/refresh-widgets), so the page fetches once instead of three times."""
    try:
        sb = get_supabase()
        require_league_owner(sb, user, league_id)
        league_row = (
            sb.table("leagues").select("fantrax_league_id").eq("id", league_id).single().execute()
        )
        flid = league_row.data.get("fantrax_league_id") if league_row.data else None
        standings = _build_standings(flid, my_team_id) if flid else None

        def _cached(widget: str):
            row = (
                sb.table("dashboard_cache")
                .select("content,updated_at")
                .eq("league_id", league_id)
                .eq("widget", widget)
                .limit(1)
                .execute()
            )
            if not row.data:
                return None
            try:
                return {
                    "content": _json.loads(row.data[0]["content"]),
                    "updated_at": row.data[0]["updated_at"],
                }
            except Exception:
                return None

        return {
            "standings": standings,
            "start_sit": _cached("start_sit"),
            "category_ranks": _cached("category_ranks"),
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/league/category-ranks")
async def upsert_category_ranks(
    body: CategoryRanksRequest,
    user: dict = Depends(get_current_user),
):
    try:
        sb = get_supabase()
        require_league_owner(sb, user, body.league_id)
        content = _json.dumps(body.ranks)
        now = datetime.now(timezone.utc).isoformat()
        sb.table("dashboard_cache").upsert(
            {
                "league_id": body.league_id,
                "widget": "category_ranks",
                "content": content,
                "updated_at": now,
            },
            on_conflict="league_id,widget",
        ).execute()
        return {"ok": True, "updated_at": now}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


def _snapshot_rank_history(sb, league_id: str, ranks: dict) -> None:
    """Record today's computed ranks as one daily point in category_rank_history,
    powering the dashboard sparklines. Upserted by (league_id, snapshot_date) so
    several syncs a day update the day's point instead of spamming it. Best-effort
    and tolerant of the table being absent (pre-migration)."""
    if not ranks:
        return
    num_teams = None
    try:
        cnt = (
            sb.table("rosters")
            .select("fantrax_team_id", count="exact")
            .eq("league_id", league_id)
            .execute()
        )
        num_teams = cnt.count
    except Exception:
        pass
    try:
        today = datetime.now(timezone.utc).date().isoformat()
        sb.table("category_rank_history").upsert(
            {
                "league_id": league_id,
                "snapshot_date": today,
                "ranks": ranks,  # jsonb column — pass the dict, not a JSON string
                "num_teams": num_teams,
            },
            on_conflict="league_id,snapshot_date",
        ).execute()
    except Exception:
        traceback.print_exc()  # missing table / older schema — history just won't grow


# Leagues with a full-league rank compute currently running. Each compute fans
# out season-stat fetches/writes for the whole league, so a roster sync and a
# manual "Auto" firing within seconds of each other would double the concurrent
# Supabase/MLB load — which is what triggered the HTTP/2 connection terminations
# and the ~90s cold-cache runs. A compute already in flight makes the second a
# no-op: the in-flight run produces fresh ranks either way. Safe without a lock
# because the check-and-add below is synchronous (no await between them) on the
# single-threaded event loop.
_rank_compute_inflight: set[str] = set()


async def _run_category_ranks_compute(league_id: str, my_team_id: str) -> None:
    """Background task: approximate category ranks from rosters + season stats,
    write them to the category_ranks widget, and append a daily history point.
    Single-flighted per league. Never raises."""
    if league_id in _rank_compute_inflight:
        print(f"[category_ranks] Compute already in flight for {league_id}; skipping duplicate")
        return
    _rank_compute_inflight.add(league_id)
    try:
        matrix = await compute_category_matrix(league_id)
        if not matrix:
            return
        ranks = my_ranks_from_matrix(matrix, my_team_id)
        if not ranks:
            return
        sb = get_supabase()
        now = datetime.now(timezone.utc).isoformat()
        # The essential write: the legacy per-manager ranks blob that the widget,
        # history, and existing readers consume. Must land on its own.
        sb.table("dashboard_cache").upsert(
            {
                "league_id": league_id,
                "widget": "category_ranks",
                "content": _json.dumps(ranks),
                "updated_at": now,
            },
            on_conflict="league_id,widget",
        ).execute()
        _snapshot_rank_history(sb, league_id, ranks)
        # The enhancement: the full league matrix (ranks + role counts per team)
        # that the trade tools read for rival posture. Written separately and
        # best-effort so a matrix failure (e.g. the widget-constraint migration
        # not yet applied) never blocks the ranks/history above.
        try:
            sb.table("dashboard_cache").upsert(
                {
                    "league_id": league_id,
                    "widget": "category_matrix",
                    "content": _json.dumps(matrix),
                    "updated_at": now,
                },
                on_conflict="league_id,widget",
            ).execute()
        except Exception:
            traceback.print_exc()  # missing constraint value / older schema
        print(f"[category_ranks] Computed ranks for league {league_id}: {ranks}")
    except Exception:
        traceback.print_exc()
    finally:
        _rank_compute_inflight.discard(league_id)


@app.post("/league/category-ranks/compute")
async def compute_category_ranks_endpoint(
    body: DashboardRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    """Kick off an approximate category-rank calculation from current rosters + stats.
    Runs in the background (fetching stats for the whole league is slow on a cold
    cache); the client polls GET /league/category-ranks for the updated result."""
    require_league_owner(get_supabase(), user, body.league_id)
    background_tasks.add_task(
        _run_category_ranks_compute, body.league_id, body.my_team_id
    )
    return {"status": "started"}


# Roster CSVs are a few hundred rows; anything near this is abuse, not a roster.
_MAX_CSV_UPLOAD_BYTES = 2 * 1024 * 1024


@app.post("/roster/analyze")
async def roster_analyze(
    file: UploadFile = File(...),
    mode: str = Query(default="in_season"),
    _user: dict = Depends(get_current_user),
):
    # Read in chunks and bail past the cap, so an oversized upload can't be
    # buffered whole before we reject it. The temp file is removed in `finally`
    # — it used to be written with delete=False and never cleaned up, which on
    # an unauthenticated endpoint meant anyone could fill the disk.
    content = b""
    while chunk := await file.read(64 * 1024):
        content += chunk
        if len(content) > _MAX_CSV_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="CSV is too large (2 MB max).")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        return analyze_roster_from_csv(tmp_path, rules, mode=mode)
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


@app.get("/fantrax/leagues")
async def fantrax_leagues(
    user_secret_id: str = Query(...),
    _user: dict = Depends(get_current_user),
):
    try:
        leagues = get_leagues(user_secret_id)
        return {"leagues": leagues}
    except Exception:
        # Don't echo the upstream error back — it's a Fantrax-side message about
        # someone's Secret ID, and the client only needs to know it failed.
        traceback.print_exc()
        raise HTTPException(status_code=502, detail="Couldn't reach Fantrax. Check your Secret ID.")


@app.get("/sleeper/leagues")
async def sleeper_leagues(
    username: str = Query(...),
    season: int = Query(None),
    _user: dict = Depends(get_current_user),
):
    """Resolve a Sleeper username and list their NFL leagues for a season
    (falling back to the prior season in the offseason)."""
    try:
        season = season or datetime.now(timezone.utc).year
        user = sleeper_get_user(username)
        if not user or not user.get("user_id"):
            raise HTTPException(status_code=404, detail="Sleeper user not found.")
        user_id = user["user_id"]
        leagues = sleeper_get_user_leagues(user_id, season)
        if not leagues:
            leagues = sleeper_get_user_leagues(user_id, season - 1)
        return {
            "user_id": user_id,
            "leagues": [
                {
                    "leagueId": lg["league_id"],
                    "leagueName": lg.get("name"),
                    "season": lg.get("season"),
                    "status": lg.get("status"),
                    "sport": "NFL",
                }
                for lg in leagues
            ],
        }
    except HTTPException:
        raise
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=502, detail="Couldn't reach Sleeper. Try again.")


@app.post("/sleeper/sync")
async def sleeper_sync(body: SleeperSyncRequest, user: dict = Depends(get_current_user)):
    """Sync a Sleeper NFL league: persist every roster (with player metadata
    embedded from the players dump + computed pick inventory) and the league's
    rules. Requires the leagues row to already carry sleeper_user_id."""
    try:
        sb = get_supabase()
        require_league_owner(sb, user, body.league_id)
        league_row = (
            sb.table("leagues").select("id, sleeper_user_id").eq("id", body.league_id).single().execute()
        )
        if not league_row.data:
            raise HTTPException(status_code=404, detail="League not found.")
        sleeper_user_id = league_row.data.get("sleeper_user_id")

        detail = sleeper_get_league(body.sleeper_league_id)
        rosters = sleeper_get_rosters(body.sleeper_league_id)
        users = sleeper_get_users(body.sleeper_league_id)
        traded = sleeper_get_traded_picks(body.sleeper_league_id)
        players = sleeper_get_players()

        settings = detail.get("settings") or {}
        total = detail.get("total_rosters") or len(rosters) or 10
        draft_rounds = settings.get("draft_rounds") or 4
        league_season = int(detail.get("season") or datetime.now(timezone.utc).year)

        rules = build_nfl_rules(detail)
        picks = compute_pick_inventory(traded, total, draft_rounds, league_season)

        team_names = {}
        for u in users:
            meta = u.get("metadata") or {}
            team_names[u["user_id"]] = meta.get("team_name") or u.get("display_name") or "Team"

        my_roster_id = None
        roster_upserts = []
        for r in rosters:
            rid = r["roster_id"]
            owner = r.get("owner_id")
            co_owners = r.get("co_owners") or []
            if sleeper_user_id and (owner == sleeper_user_id or sleeper_user_id in co_owners):
                my_roster_id = rid
            roster_upserts.append({
                "league_id": body.league_id,
                "fantrax_team_id": str(rid),
                "team_name": team_names.get(owner, f"Roster {rid}"),
                "roster_items": build_roster_items(
                    r.get("players"), r.get("starters"), players,
                    taxi=r.get("taxi"), reserve=r.get("reserve"),
                ),
                "salary_cap": None,
                "draft_picks": picks.get(rid, []),
                "synced_at": datetime.now(timezone.utc).isoformat(),
            })

        sb.table("rosters").upsert(
            roster_upserts, on_conflict="league_id,fantrax_team_id"
        ).execute()

        league_update = {"name": detail.get("name"), "sport": "NFL", "rules": rules}
        if my_roster_id is not None:
            league_update["fantrax_team_id"] = str(my_roster_id)
        sb.table("leagues").update(league_update).eq("id", body.league_id).execute()

        return {
            "ok": True,
            "teams": len(roster_upserts),
            "my_team_id": str(my_roster_id) if my_roster_id is not None else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/dashboard/nfl_roster")
async def dashboard_nfl_roster(body: DashboardRequest, user: dict = Depends(get_current_user)):
    """Dynasty roster view payload for Sleeper NFL leagues: FantasyCalc market
    values joined onto the synced roster + picks, plus deterministic age-curve,
    depth, and roster-window reads (engine/nfl_dynasty.py). No AI call and no
    dashboard_cache row — the only cached piece is the FantasyCalc response
    (in-process per settings combo, engine/fantasycalc.py), so the page is
    always fresh after a sync. `force` refetches FantasyCalc. Named under
    /dashboard/ so the frontend's useDashboardWidget hook works unchanged."""
    try:
        sb = get_supabase()
        require_league_owner(sb, user, body.league_id)

        def _load():
            league = (
                sb.table("leagues").select("rules").eq("id", body.league_id)
                .single().execute()
            ).data or {}
            # Every team, not just the owner's: rival rosters + picks are what
            # turn the window read into league ranks instead of a bare percentage.
            rows = (
                sb.table("rosters")
                .select("fantrax_team_id, team_name, roster_items, draft_picks")
                .eq("league_id", body.league_id)
                .execute()
            ).data or []
            mine = next(
                (r for r in rows if str(r.get("fantrax_team_id")) == str(body.my_team_id)),
                None,
            )
            return league, mine, rows

        league, roster_row, all_rosters = await asyncio.to_thread(_load)
        rules = league.get("rules") or {}
        if (rules.get("sport") or "").upper() != "NFL":
            raise HTTPException(status_code=400, detail="Not an NFL league.")
        if not roster_row:
            raise HTTPException(
                status_code=404, detail="No synced roster yet — sync your league first."
            )

        params = derive_fc_params(rules)
        fc = await asyncio.to_thread(
            fantasycalc.get_values,
            params["num_qbs"], params["ppr"], params["num_teams"], body.force,
        )
        payload = build_nfl_dynasty_payload(
            roster_row.get("roster_items"), roster_row.get("draft_picks"),
            rules, fc["entries"], all_rosters, body.my_team_id,
        )
        payload["team_name"] = roster_row.get("team_name") or "Your Team"
        payload["values_updated_at"] = fc["fetched_at"]
        return payload
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/roster/sync")
async def roster_sync(
    background_tasks: BackgroundTasks,
    body: RosterSyncRequest,
    user: dict = Depends(get_current_user),
):
    try:
        user_secret_id = body.user_secret_id
        fantrax_league_id = body.fantrax_league_id

        # Step 1: Get the user's leagues to find their teamId and sport
        leagues = get_leagues(user_secret_id)
        league_entry = next(
            (entry for entry in leagues if entry.get("leagueId") == fantrax_league_id),
            None,
        )
        if not league_entry:
            raise HTTPException(
                status_code=404,
                detail="League not found for this user. Check your Secret ID and League ID.",
            )

        team_id = league_entry["teamId"]
        sport = league_entry.get("sport", "MLB")

        # Step 2: Get all rosters and filter to the user's team
        rosters = get_team_rosters(fantrax_league_id)
        team_roster = rosters.get(team_id)
        if not team_roster:
            raise HTTPException(
                status_code=404,
                detail="Could not find your team in the league roster data.",
            )

        # Step 2.4: Resolve THIS owner's league row. Two people can connect the
        # SAME Fantrax league — each gets their own row — so we must never key
        # writes on the shared fantrax_league_id (that cross-writes both rows and
        # makes .single() throw). Everything below is scoped to league_uuid.
        # Set which team is theirs up front so the dashboard works even if the
        # enrichment steps hiccup.
        sb = get_supabase()
        owner_id = user.get("sub")
        league_row = (
            sb.table("leagues")
            .select("id")
            .eq("owner_user_id", owner_id)
            .eq("fantrax_league_id", fantrax_league_id)
            .limit(1)
            .execute()
        )
        league_uuid = league_row.data[0]["id"] if league_row.data else None
        if not league_uuid:
            raise HTTPException(
                status_code=404,
                detail="This league isn't connected to your account. Reconnect it in Settings.",
            )
        sb.table("leagues").update({"fantrax_team_id": team_id}).eq("id", league_uuid).execute()

        # Step 2.5: Fetch league info and persist structural profile fields
        league_info = {}
        try:
            league_info = get_league_info(fantrax_league_id)
            profile = extract_league_profile(league_info, team_id)
            sb.table("leagues").update(profile).eq("id", league_uuid).execute()
        except Exception as e:
            print(f"[sync] League profile update failed (non-fatal): {e}")

        # Step 2.5b: Auto-detect structural league rules (caps, size, budget),
        # preserving any user-set scoring/contract. Isolated update so a missing
        # rules column (migration not yet applied) can't break the profile write.
        try:
            existing = (
                sb.table("leagues")
                .select("rules")
                .eq("id", league_uuid)
                .single()
                .execute()
            )
            merged_rules = detect_rules(
                league_info, team_roster, rosters, (existing.data or {}).get("rules"), sport
            )
            sb.table("leagues").update({"rules": merged_rules}).eq(
                "id", league_uuid
            ).execute()
        except Exception as e:
            print(f"[sync] Rules auto-detect skipped (non-fatal): {e}")

        # Step 2.6: Persist all team rosters to Supabase (under THIS owner's row)
        try:
            roster_upserts = [
                {
                    "league_id": league_uuid,
                    "fantrax_team_id": tid,
                    "team_name": tdata.get("teamName", ""),
                    "roster_items": tdata.get("rosterItems", []),
                    "salary_cap": int(tdata.get("salaryCap", 0)) if tdata.get("salaryCap") else None,
                    "synced_at": datetime.now(timezone.utc).isoformat(),
                }
                for tid, tdata in rosters.items()
            ]

            sb.table("rosters").upsert(
                roster_upserts,
                on_conflict="league_id,fantrax_team_id"
            ).execute()
            print(f"[sync] Persisted {len(roster_upserts)} team rosters")
        except Exception as e:
            print(f"[sync] Roster persistence failed (non-fatal): {e}")

        # Step 3: Get player ID -> {name, team} map (cached 24hr)
        player_names = get_player_ids(sport)

        # Step 3.5: Resolve your team's players synchronously (needed for step 4)
        unresolved = []
        for item in team_roster.get("rosterItems", []):
            fantrax_id = item.get("id", "")
            player_data = player_names.get(fantrax_id, {})
            name = player_data.get("name", "")
            team = player_data.get("team", "")
            if not name:
                continue
            mapping = resolve_player(fantrax_id, name, team)
            if mapping:
                print(f"[sync] Resolved {name} → MLB ID {mapping['mlb_id']} ({mapping['confidence']})")
            else:
                unresolved.append({"fantrax_id": fantrax_id, "name": name})

        if unresolved:
            print(f"[sync] Could not resolve {len(unresolved)} players: {unresolved}")

        # Step 3.6: Resolve all OTHER league players in the background, then
        # auto-compute category ranks (MLB only) so the trend history gains a
        # point every sync with no manual "Auto" click. BackgroundTasks run in
        # order, so the compute sees a fully-resolved id map + fresh stats.
        background_tasks.add_task(resolve_all_players, rosters, player_names, league_uuid)
        if sport != "NFL":
            background_tasks.add_task(_run_category_ranks_compute, league_uuid, team_id)

        # Step 4: Map to AnalyzeResult shape
        result = map_roster_to_analyze_result(team_roster, player_names, rules)

        return result

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


def _league_sport(sb, league_id: str) -> str:
    """The selected league's sport ('MLB' | 'NFL'), defaulting to MLB."""
    try:
        row = sb.table("leagues").select("sport").eq("id", league_id).single().execute()
        return (row.data or {}).get("sport") or "MLB"
    except Exception:
        return "MLB"


# --- AI stream keepalive protocol ---------------------------------------------
# The three AI streams (/trade/analyze, /trade/finder, /waivers/add-drop) die
# whenever the connection sits silent too long: the Vercel proxy kills a
# response with no first byte after ~30s, and mobile browsers / cell networks
# kill idle mid-stream connections (worst with the screen locked). So the
# ndjson protocol guarantees a byte at least every _STATUS_INTERVAL_S seconds:
# `meta` commits the stream instantly, context building pings while it runs on
# the event loop, and thinking/web-search phases emit throttled `status` events
# that double as progress UX. Frontends render `status.label`; unknown event
# types are ignored, so older clients degrade gracefully.
_STATUS_INTERVAL_S = 8.0


def _ndjson(obj: dict) -> str:
    return _json.dumps(obj) + "\n"


def _prep_lines(fut, label: str):
    """Wait on a run_coroutine_threadsafe future from inside a (threadpooled)
    sync stream generator, yielding a keepalive `status` line every interval.
    The caller takes fut.result() afterwards; call sites run in Starlette's
    threadpool so blocking here never touches the event loop."""
    while True:
        try:
            fut.exception(timeout=_STATUS_INTERVAL_S)  # waits; doesn't raise the result
            return
        except TimeoutError:
            yield _ndjson({"type": "status", "label": label})


class _FenceHoldback:
    """Stateful text filter for the finder stream: pass prose through, but hold
    back everything from the ```json fence on (the machine-readable packages),
    with a 2-char lookbehind so a fence split across deltas never leaks."""

    def __init__(self):
        self.joined = ""
        self.emitted = 0
        self.stopped = False

    def __call__(self, delta: str) -> str:
        self.joined += delta
        if self.stopped:
            return ""
        fence = self.joined.find("```")
        if fence != -1:
            out = self.joined[self.emitted:fence] if fence > self.emitted else ""
            self.emitted = fence
            self.stopped = True
            return out
        safe = len(self.joined) - 2  # lookbehind: never emit a partial fence
        if safe > self.emitted:
            out = self.joined[self.emitted:safe]
            self.emitted = safe
            return out
        return ""


class TruncatedResponseError(Exception):
    """The model hit `max_tokens` mid-answer, so the text is incomplete. Not an
    SDK error — the stream ends cleanly — which is exactly why we raise our own:
    without it a half-written response looks like a successful one."""


class PausedTurnError(Exception):
    """The server-side tool loop hit its iteration cap and returned
    `stop_reason: "pause_turn"`, so the answer stops wherever the last search
    left it. Like a max_tokens stop this ends the stream *cleanly* — no SDK
    exception — so without this the user gets a `done` on a half-finished
    analysis. Only /trade/analyze can hit it today (it's the one trade surface
    with web search), and erroring searches make it far likelier: a failed
    search burns a loop iteration without making progress."""


def _ai_ndjson_lines(ai, *, status_label: str, text_mapper=None, collect=None,
                     failed=None, done_event=True, **stream_kwargs):
    """Iterate one Anthropic stream as ndjson lines. Answer text becomes `text`
    deltas (through text_mapper when given); everything else — thinking deltas,
    web-search activity — becomes throttled `status` keepalives, since those
    phases produce no answer text for minutes at a time. Sync generator: it runs
    in Starlette's threadpool, keeping the sync SDK off the event loop, and the
    metering wrapper (_LoggedStreamManager) logs usage on context exit exactly
    as before. `collect` accumulates the full raw text for post-processing;
    `failed` (a list) is appended to on error so callers can skip finalization —
    including a `max_tokens` truncation, which is a clean stream end, not a
    raised error."""
    last = time.monotonic()

    def line(obj: dict) -> str:
        nonlocal last
        last = time.monotonic()
        return _ndjson(obj)

    stop_reason = None
    try:
        # Mark the phase transition immediately — otherwise the last prep status
        # ("Pulling live stats…") lingers on screen into the thinking phase.
        yield line({"type": "status", "label": status_label})
        with ai.messages.stream(**stream_kwargs) as s:
            for ev in s:
                etype = getattr(ev, "type", "")
                if etype == "text":
                    delta = getattr(ev, "text", "") or ""
                    if collect is not None:
                        collect.append(delta)
                    out = text_mapper(delta) if text_mapper else delta
                    if out:
                        yield line({"type": "text", "delta": out})
                elif etype == "content_block_start" and getattr(
                    getattr(ev, "content_block", None), "type", ""
                ) == "server_tool_use":
                    yield line({"type": "status", "label": "Searching the web…"})
                elif time.monotonic() - last >= _STATUS_INTERVAL_S:
                    yield line({"type": "status", "label": status_label})
            # Two stop reasons end the stream normally — no exception — so
            # nothing downstream would notice on its own. `max_tokens`: thinking
            # tokens share the budget with the answer, so an unlucky long think
            # truncates a request that usually fits (left undetected, the finder
            # parses a half-written ```json block and blames the parser).
            # `pause_turn`: the server-side web-search loop hit its iteration
            # cap. Both leave a partial answer that must not be sold as `done`.
            snapshot = getattr(s, "current_message_snapshot", None)
            stop_reason = getattr(snapshot, "stop_reason", None)
        if stop_reason in ("max_tokens", "pause_turn"):
            paused = stop_reason == "pause_turn"
            if failed is not None:
                failed.append(PausedTurnError() if paused else TruncatedResponseError())
            yield _ndjson({
                "type": "error",
                "detail": "paused" if paused else "truncated",
            })
        elif done_event:
            yield _ndjson({"type": "done"})
    except anthropic.APIStatusError as e:
        traceback.print_exc()
        if failed is not None:
            failed.append(e)
        yield _ndjson({"type": "error", "detail": _ai_error_code(e) or str(e)})
    except Exception as e:
        traceback.print_exc()
        if failed is not None:
            failed.append(e)
        yield _ndjson({"type": "error", "detail": str(e)})


@app.post("/trade/analyze")
async def trade_analyze(
    body: TradeAnalyzeRequest,
    user: dict = Depends(get_current_user),
):
    try:
        require_league_owner(get_supabase(), user, body.league_id)
        offering = [x.strip() for x in body.offering_ids.split(",") if x.strip()]
        receiving = [x.strip() for x in body.receiving_ids.split(",") if x.strip()]
        sport = _league_sport(get_supabase(), body.league_id)
        # The key lookup stays before the stream so a missing key is still a
        # clean 402 the frontend routes to the "add your key" card.
        ai = get_ai_client_for_league(get_supabase(), body.league_id, tool="trade_analyze")

        async def _prep() -> tuple[str, str]:
            """The slow part — live stat fetches for every player in the trade.
            Runs on the event loop while the stream generator pings keepalives,
            so a slow MLB Stats night can no longer starve the first byte."""
            if sport == "NFL":
                context = await build_nfl_trade_context(
                    body.league_id, body.my_team_id, body.opponent_team_id, offering, receiving
                )
                return build_nfl_trade_prompt(context), build_nfl_system_prompt(context["rules"])
            context = await build_trade_context(
                league_id=body.league_id,
                my_team_id=body.my_team_id,
                opponent_team_id=body.opponent_team_id,
                offering_ids=offering,
                receiving_ids=receiving,
            )
            return build_trade_prompt(context), build_system_prompt(context["rules"], context["sport"])

        loop = asyncio.get_running_loop()

        def stream():
            yield _ndjson({"type": "meta"})  # first byte in milliseconds
            fut = asyncio.run_coroutine_threadsafe(_prep(), loop)
            try:
                yield from _prep_lines(fut, "Pulling live stats and contracts…")
                prompt, system_prompt = fut.result()
            except GeneratorExit:
                fut.cancel()  # client disconnected — stop the stat fetches
                raise
            except Exception as e:
                traceback.print_exc()
                yield _ndjson({"type": "error", "detail": str(e)})
                return
            yield from _ai_ndjson_lines(
                ai,
                status_label="Weighing the deal…",
                model=MODEL_TRADE,
                max_tokens=8000,
                thinking=_ADAPTIVE_THINKING,
                output_config=_TRADE_EFFORT,
                tools=_TRADE_WEB_SEARCH,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/trade/history")
async def save_trade_history(
    body: TradeHistoryItem,
    user: dict = Depends(get_current_user),
):
    """Record one analyzed trade for the user's private history (best-effort — a
    failure here must never disrupt the analysis the user already saw)."""
    sb = get_supabase()
    require_league_owner(sb, user, body.league_id)
    uid = user.get("sub")
    if not uid or not body.analysis.strip():
        return {"ok": False}
    try:
        sb.table("trade_history").insert({
            "user_id": uid,
            "league_id": body.league_id,
            "offering": body.offering,
            "receiving": body.receiving,
            "verdict": ((body.verdict or "").strip()[:500]) or None,
            "analysis": body.analysis,
        }).execute()
    except Exception:
        traceback.print_exc()
        return {"ok": False}
    return {"ok": True}


@app.get("/trade/history")
async def list_trade_history(
    league_id: str = Query(...),
    user: dict = Depends(get_current_user),
):
    """The user's last 20 analyzed trades for this league, newest first."""
    sb = get_supabase()
    require_league_owner(sb, user, league_id)
    uid = user.get("sub")
    if not uid:
        return {"items": []}
    # `status`/`outcome_*` may not exist yet (pre-migration) — fall back to the
    # base columns so history keeps loading either way.
    full_cols = ("id, created_at, offering, receiving, verdict, analysis, "
                 "status, outcome_note, outcome_updated_at")
    for cols in (full_cols, "id, created_at, offering, receiving, verdict, analysis"):
        try:
            rows = (
                sb.table("trade_history")
                .select(cols)
                .eq("league_id", league_id)
                .eq("user_id", uid)
                .order("created_at", desc=True)
                .limit(20)
                .execute()
            )
            return {"items": rows.data or []}
        except Exception:
            continue
    traceback.print_exc()
    return {"items": []}


@app.post("/trade/history/outcome")
async def update_trade_outcome(
    body: TradeOutcomeUpdate,
    user: dict = Depends(get_current_user),
):
    """Tag a recorded trade with what actually happened (proposed / accepted /
    rejected / completed) plus an optional retrospective note. Scoped to the
    caller's own row."""
    sb = get_supabase()
    require_league_owner(sb, user, body.league_id)
    uid = user.get("sub")
    if not uid:
        raise HTTPException(status_code=401, detail="Not signed in")
    status = (body.status or "").strip().lower() or None
    if status is not None and status not in _TRADE_OUTCOME_STATES:
        raise HTTPException(status_code=400, detail="Invalid status")
    try:
        sb.table("trade_history").update({
            "status": status,
            "outcome_note": (body.note or "").strip()[:2000] or None,
            "outcome_updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", body.id).eq("user_id", uid).execute()
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True}


@app.post("/waivers/add-drop")
async def waivers_add_drop(
    body: AddDropRequest,
    user: dict = Depends(get_current_user),
):
    """Given who the manager is adding (and anyone already leaving), rank the most
    droppable players on their roster. Streams the recommendation as plain text,
    same as /trade/analyze."""
    try:
        sb = get_supabase()
        require_league_owner(sb, user, body.league_id)
        if not body.incoming and not body.outgoing_ids:
            raise HTTPException(status_code=400, detail="Add at least one incoming player.")

        incoming = [inc.model_dump() for inc in body.incoming]
        sport = _league_sport(sb, body.league_id)
        ai = get_ai_client_for_league(sb, body.league_id, tool="add_drop")

        async def _prep() -> tuple[str, str]:
            if sport == "NFL":
                context = await build_nfl_add_drop_context(
                    league_id=body.league_id,
                    my_team_id=body.my_team_id,
                    incoming=incoming,
                    outgoing_ids=body.outgoing_ids,
                )
                return build_nfl_add_drop_prompt(context), build_nfl_system_prompt(context["rules"])
            context = await build_add_drop_context(
                league_id=body.league_id,
                my_team_id=body.my_team_id,
                incoming=incoming,
                outgoing_ids=body.outgoing_ids,
            )
            return build_add_drop_prompt(context), build_system_prompt(context["rules"], context["sport"])

        loop = asyncio.get_running_loop()

        # ndjson protocol — same as /trade/analyze: immediate `meta`, keepalive
        # `status` events through context build and thinking, errors as events.
        def stream():
            yield _ndjson({"type": "meta"})
            fut = asyncio.run_coroutine_threadsafe(_prep(), loop)
            try:
                yield from _prep_lines(fut, "Sizing up your roster…")
                prompt, system_prompt = fut.result()
            except GeneratorExit:
                fut.cancel()
                raise
            except Exception as e:
                traceback.print_exc()
                yield _ndjson({"type": "error", "detail": str(e)})
                return
            yield from _ai_ndjson_lines(
                ai,
                status_label="Ranking the drop candidates…",
                model=MODEL_TRADE,
                max_tokens=6000,
                thinking=_ADAPTIVE_THINKING,
                output_config=_TRADE_EFFORT,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/trade/finder")
async def trade_finder(
    body: TradeFinderRequest,
    user: dict = Depends(get_current_user),
):
    """Category-first Trade Finder. Streams newline-delimited JSON: a bare `meta`
    handshake first (commits the response instantly), keepalive `status` events
    while the league scan runs, a `candidates` event with the ranked targets,
    then `text` events as the recommendation streams, then a final `packages`
    event with the parsed, validated offers. Input errors surface as `error`
    events since the scan now runs after the stream has committed.
    The finder's `target_category` field carries an NFL position for football."""
    require_league_owner(get_supabase(), user, body.league_id)
    sport = _league_sport(get_supabase(), body.league_id)
    ai = get_ai_client_for_league(get_supabase(), body.league_id, tool="trade_finder")

    async def _prep() -> dict:
        """The league-wide roster + stats scan — the heaviest context build of
        the three AI streams — plus all the sport-specific derivation."""
        if sport == "NFL":
            context = await build_nfl_finder_context(
                body.league_id, body.my_team_id, target_position=body.target_category
            )
            return {
                "target_label": context["target_position"],
                "candidates": [
                    {
                        "fantrax_id": c["id"],
                        "name": c["name"],
                        "position": c.get("position"),
                        "team": c.get("team"),
                        "owner_team_id": c["owner_team_id"],
                        "owner_team_name": c["owner_team_name"],
                        "stat_value": c.get("points"),
                        "value": c.get("value"),
                    }
                    for c in context["candidates"]
                ],
                # parse_finder_response keys on `fantrax_id`; football assets/candidates use `id`.
                "parse_candidates": [{**c, "fantrax_id": c["id"]} for c in context["candidates"]],
                "parse_assets": [{**a, "fantrax_id": a["id"]} for a in context["my_assets"]],
                "prompt": build_nfl_finder_prompt(context),
                "system_prompt": build_nfl_system_prompt(context["rules"]),
            }
        context = await build_finder_context(
            league_id=body.league_id,
            my_team_id=body.my_team_id,
            target_category=body.target_category,
        )
        return {
            "target_label": context["target_category"],
            "candidates": [
                {
                    "fantrax_id": c["fantrax_id"],
                    "name": c["name"],
                    "position": c["position"],
                    "salary": c["salary"],
                    "contract": c["contract"],
                    "owner_team_id": c["owner_team_id"],
                    "owner_team_name": c["owner_team_name"],
                    "stat_value": c["stat_value"],
                    "value": c.get("value"),
                }
                for c in context["candidates"]
            ],
            "parse_candidates": context["candidates"],
            "parse_assets": context.get("my_assets", []),
            "prompt": build_finder_prompt(context),
            "system_prompt": build_system_prompt(context["rules"], context["sport"]),
        }

    loop = asyncio.get_running_loop()

    def stream():
        yield _ndjson({"type": "meta"})  # bare handshake — first byte instantly
        fut = asyncio.run_coroutine_threadsafe(_prep(), loop)
        try:
            yield from _prep_lines(fut, "Scanning rosters and season stats…")
            prep = fut.result()
        except GeneratorExit:
            fut.cancel()
            raise
        except Exception as e:
            traceback.print_exc()
            yield _ndjson({"type": "error", "detail": str(e)})
            return
        # Targets are ready before the AI call — send them first.
        yield _ndjson({
            "type": "candidates",
            "target_category": prep["target_label"],
            "candidates": prep["candidates"],
        })
        full: list[str] = []
        failed: list = []
        yield from _ai_ndjson_lines(
            ai,
            status_label="Building trade packages…",
            text_mapper=_FenceHoldback(),  # hold back the ```json package block
            collect=full,
            failed=failed,
            done_event=False,
            model=MODEL_TRADE,
            # Roomier than the other two trade calls: the finder writes prose
            # AND a ```json package block that gets parsed, so a truncation here
            # loses the packages entirely rather than just clipping a sentence.
            # Opus 5 also writes longer than 4.8 at the same settings.
            max_tokens=16000,
            thinking=_ADAPTIVE_THINKING,
            output_config=_TRADE_EFFORT,
            system=prep["system_prompt"],
            messages=[{"role": "user", "content": prep["prompt"]}],
        )
        if not failed:
            try:
                analysis, packages = parse_finder_response(
                    "".join(full), prep["parse_candidates"], prep["parse_assets"]
                )
                yield _ndjson({"type": "packages", "packages": packages, "analysis": analysis})
            except Exception as e:
                traceback.print_exc()
                yield _ndjson({"type": "error", "detail": str(e)})

    return StreamingResponse(stream(), media_type="application/x-ndjson")


# --- Football dashboard widgets (start_sit / news / waiver) -------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _nfl_start_sit(sb, body) -> dict:
    team_name, items = nfl_my_roster(sb, body.league_id, body.my_team_id)
    if not items:
        raise HTTPException(status_code=404, detail="No roster found. Sync your league first.")
    out_alerts = [
        {"name": it.get("name"), "status": it.get("injury_status"), "detail": f"Listed {it.get('injury_status')}"}
        for it in items if it.get("injury_status")
    ]
    ai = get_ai_client_for_league(sb, body.league_id, tool="start_sit")
    response = ai.messages.create(
        model=MODEL_DASHBOARD, max_tokens=5000, thinking=_NO_THINKING, tools=_WEB_SEARCH,
        messages=[{"role": "user", "content": _with_search_first(nfl_start_sit_prompt(team_name, items))}],
    )
    raw = _extract_text(response)
    structured = {"players": [], "alerts": []}
    m = re.search(r"```json\s*([\s\S]*?)\s*```", raw)
    if m:
        try:
            structured = _json.loads(m.group(1))
        except Exception:
            pass
    structured["alerts"] = out_alerts + structured.get("alerts", [])
    seen = {(a["name"], a.get("status")): a for a in structured["alerts"] if a.get("name")}
    structured["alerts"] = list(seen.values())
    # Don't cache an empty generation, or one where every web search errored
    # (unverified statuses — serve once, let the next load retry).
    if not structured.get("players") or _web_search_failed(response):
        return {"content": structured, "updated_at": _now_iso()}
    return {"content": structured, "updated_at": _upsert_cache(sb, body.league_id, "start_sit", _json.dumps(structured))}


def _nfl_news(sb, body) -> dict:
    team_name, items = nfl_my_roster(sb, body.league_id, body.my_team_id)
    if not items:
        return {"content": "Sync your league to see news.", "updated_at": _now_iso()}
    ai = get_ai_client_for_league(sb, body.league_id, tool="news")
    response = ai.messages.create(
        model=MODEL_DASHBOARD, max_tokens=3000, thinking=_NO_THINKING, tools=_WEB_SEARCH,
        messages=[{"role": "user", "content": _with_search_first(nfl_news_prompt(team_name, items))}],
    )
    content = _extract_text(response)
    if not content.strip() or _web_search_failed(response):
        return {"content": content, "updated_at": _now_iso()}
    return {"content": content, "updated_at": _upsert_cache(sb, body.league_id, "news", content)}


def _nfl_waiver(sb, body) -> dict:
    league = sb.table("leagues").select("rules").eq("id", body.league_id).single().execute().data or {}
    fmt_key = f"pts_{((league.get('rules') or {}).get('scoring_format') or 'half_ppr')}"
    team_name, _items = nfl_my_roster(sb, body.league_id, body.my_team_id)
    fas = nfl_waiver_pool(sb, body.league_id, fmt_key)
    ai = get_ai_client_for_league(sb, body.league_id, tool="waiver")
    response = ai.messages.create(
        model=MODEL_DASHBOARD, max_tokens=3000, thinking=_NO_THINKING, tools=_WEB_SEARCH,
        messages=[{"role": "user", "content": _with_search_first(nfl_waiver_prompt(team_name or "Your Team", fas))}],
    )
    content = _extract_text(response)
    if not content.strip() or _web_search_failed(response):
        return {"content": content, "updated_at": _now_iso()}
    return {"content": content, "updated_at": _upsert_cache(sb, body.league_id, "waiver", content)}


@app.post("/dashboard/news")
async def dashboard_news(
    body: DashboardRequest,
    user: dict = Depends(get_current_user),
):
    try:
        sb = get_supabase()
        require_league_owner(sb, user, body.league_id)
        if (user or {}).get("sub"):  # a real owner view (not the warmer) keeps it warm
            await asyncio.to_thread(_touch_league_viewed, sb, body.league_id)

        def cached_response(force: bool, max_age: timedelta | None = None) -> dict | None:
            row = _check_cache(sb, body.league_id, "news", force, max_age)
            if row:
                return {"content": row["content"], "updated_at": row["updated_at"]}
            return None

        cached = cached_response(body.force)
        if cached:
            return cached

        # Generation is all blocking I/O (Supabase + a web-search AI call that can
        # run tens of seconds) — run it in a worker thread so the event loop stays
        # free, deduplicated so concurrent requests don't bill two generations.
        def build() -> dict:
            if _league_sport(sb, body.league_id) == "NFL":
                return _nfl_news(sb, body)

            team_name, roster_items, id_map = _load_my_roster(
                sb, body.league_id, body.my_team_id
            )

            player_lines = []
            for item in roster_items:
                fid = item.get("id", "")
                name = (id_map.get(fid) or {}).get("full_name") or item.get("name", fid)
                pos = item.get("position", "")
                status = item.get("status", "")
                sal = item.get("salary", 0)
                contract = (item.get("contract") or {}).get("name", "?")
                player_lines.append(f"- {name} ({pos}, {status}, ${sal}, contract {contract})")

            # Strategic context: which categories this team is weak in, so the
            # model prioritizes news that actually moves this team's needle.
            _, weak_cats = _weak_categories_context(sb, body.league_id)
            weak_line = (
                f"\nThis team's weakest categories: {', '.join(weak_cats)}. "
                "Prioritize news about players who affect those categories, and IL returns."
                if weak_cats else ""
            )

            prompt = f"""You are a fantasy baseball analyst for a dynasty contract league. Use web search to find the latest injury and performance news for the following players.
{_today_line()}

Team: {team_name}
Roster (name (position, roster status, salary, contract year)):
{chr(10).join(player_lines)}
{weak_line}
Search for and summarize recent news (last 2 weeks) for each player. Focus on: IL placements, returns from IL, lineup changes, role changes, injury updates, and anything else affecting fantasy value. Skip players with nothing to report. Format as a bulleted list with the player name in bold at the start of each item.

{_ANSWER_MARKER_INSTRUCTION} After the marker: no preamble, no horizontal rules (---) — start directly with the first player bullet point."""

            ai = get_ai_client_for_league(sb, body.league_id, tool="news")
            response = ai.messages.create(
                model=MODEL_DASHBOARD,
                max_tokens=3000,
                thinking=_NO_THINKING,
                tools=_WEB_SEARCH,
                messages=[{"role": "user", "content": _with_search_first(prompt)}],
            )
            content = _extract_text(response)

            if _web_search_failed(response):
                return {"content": content, "updated_at": _now_iso()}
            updated_at = _upsert_cache(sb, body.league_id, "news", content)
            return {"content": content, "updated_at": updated_at}

        return await _single_flight(
            body.league_id, "news",
            recheck=lambda: cached_response(False, max_age=_RECHECK_WINDOW),
            generate=lambda: asyncio.to_thread(build),
        )

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/dashboard/start_sit")
async def dashboard_start_sit(
    body: DashboardRequest,
    user: dict = Depends(get_current_user),
):
    try:
        sb = get_supabase()
        require_league_owner(sb, user, body.league_id)
        if (user or {}).get("sub"):  # a real owner view (not the warmer) keeps it warm
            await asyncio.to_thread(_touch_league_viewed, sb, body.league_id)

        def cached_response(force: bool, max_age: timedelta | None = None) -> dict | None:
            row = _check_cache(sb, body.league_id, "start_sit", force, max_age)
            if row:
                try:
                    content = _json.loads(row["content"])
                    # Ignore an empty cached result (a prior failed generation) so it
                    # doesn't stick for the full TTL — fall through and regenerate.
                    if content.get("players"):
                        return {"content": content, "updated_at": row["updated_at"]}
                except Exception:
                    pass  # Old prose cache — fall through to regenerate
            return None

        cached = cached_response(body.force)
        if cached:
            return cached

        # Blocking Supabase + web-search AI call — worker thread + single-flight
        # (see /dashboard/news).
        def build() -> dict:
            if _league_sport(sb, body.league_id) == "NFL":
                return _nfl_start_sit(sb, body)

            return _build_start_sit_mlb(sb, body)

        return await _single_flight(
            body.league_id, "start_sit",
            recheck=lambda: cached_response(False, max_age=_RECHECK_WINDOW),
            generate=lambda: asyncio.to_thread(build),
        )

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


def _build_start_sit_mlb(sb, body) -> dict:
    """Generate the MLB start/sit widget (blocking — runs in a worker thread)."""
    try:
        team_name, roster_items, id_map = _load_my_roster(
            sb, body.league_id, body.my_team_id,
            map_columns="fantrax_id,full_name,mlb_team,roster_status,il_type",
        )
        name_map = {fid: r["full_name"] for fid, r in id_map.items()}
        team_map = {fid: r.get("mlb_team", "") for fid, r in id_map.items()}
        status_map = {fid: r.get("roster_status") for fid, r in id_map.items()}
        il_type_map = {fid: r.get("il_type") for fid, r in id_map.items()}

        # Build data-grounded alerts — no AI needed for these
        il_alerts = []
        milb_alerts = []
        edge_il_alerts = []

        for item in roster_items:
            fid = item.get("id", "")
            name = name_map.get(fid) or item.get("name", fid)
            fantrax_status = item.get("status", "").upper()

            if fantrax_status == "INJURED_RESERVE":
                il_type = il_type_map.get(fid) or "IL"
                # Honest fallback (the AI enriches with the real injury/return below
                # when it can find it). Long-term IL isn't an actionable timeline.
                if "60" in il_type:
                    detail = "Long-term injury — on the 60-day IL"
                else:
                    detail = f"On the {il_type}"
                il_alerts.append({"name": name, "status": il_type, "detail": detail})
            elif fantrax_status == "MINORS":
                milb_alerts.append({
                    "name": name,
                    "status": "MiLB",
                    "detail": "Currently in minors — not eligible to start",
                })

        # Edge case: Fantrax shows ACTIVE/RESERVE but MLB roster says IL
        for item in roster_items:
            fid = item.get("id", "")
            if item.get("status", "").upper() in ("ACTIVE", "RESERVE") and status_map.get(fid) == "IL":
                name = name_map.get(fid) or item.get("name", fid)
                il_type = il_type_map.get(fid) or "IL"
                edge_il_alerts.append({
                    "name": name,
                    "status": il_type,
                    "detail": f"On {il_type} per MLB roster — verify in Fantrax",
                })

        # Only pass truly startable players to AI
        startable_items = [
            item for item in roster_items
            if item.get("status", "").upper() in ("ACTIVE", "RESERVE")
            and status_map.get(item.get("id", "")) not in ("IL", "Minors")
        ]

        # IL players to research — all of them, so 60-day stashes get a real
        # injury + return note instead of a generic flag.
        il_research = [
            (name_map.get(item.get("id", "")) or item.get("name", ""),
             il_type_map.get(item.get("id", "")) or "IL")
            for item in roster_items
            if item.get("status", "").upper() == "INJURED_RESERVE"
        ]

        player_lines = []
        for item in startable_items:
            fid = item.get("id", "")
            name = name_map.get(fid) or item.get("name", fid)
            pos = item.get("position", "")
            sal = item.get("salary", 0)
            mlb_team = team_map.get(fid, "")
            player_lines.append(f"- {name} | {pos} | {mlb_team} | ${sal}")

        # Load category ranks for context
        category_ranks = _load_category_ranks(sb, body.league_id)
        ranks_line = ""
        if category_ranks:
            ranks_line = "\nCategory ranks (1=best, higher = needs improvement): " + ", ".join(
                f"{cat}:{rank}" for cat, rank in category_ranks.items()
            )

        il_section = ""
        if il_research:
            il_section = f"""
Injured (IL) players — for each, search for the injury and the expected return:
{chr(10).join(f"- {n} ({il})" for n, il in il_research)}
For each you can confirm, add an alert: status = the IL type, detail = one concrete sentence with the injury and expected return (e.g. "Hamstring strain, targeting a late-June return" or "Torn ACL, out for the season"). Do not invent a timeline you can't find — skip those and the roster's listed status will be shown instead.
"""

        # Real schedule + announced probables, so the model never infers starts
        # from days of rest (the All-Star-break "Skenes starts today" bug).
        schedule_context = get_schedule_context()
        schedule_section = f"\n{schedule_context}\n" if schedule_context else ""
        schedule_rule = (
            "- Scheduling claims must come ONLY from the schedule above: say a pitcher starts today/tomorrow ONLY if he is listed there as a probable starter. NEVER infer a start from days of rest or rotation order."
            if schedule_context else
            "- The schedule feed is unavailable — make NO claims about who is pitching today or tomorrow."
        )

        prompt = f"""You are a fantasy baseball analyst for a dynasty contract league.
{_today_line()}

Team: {team_name}
Active/Reserve Roster (name | position | MLB team | salary):
{chr(10).join(player_lines) if player_lines else "No active players."}
{ranks_line}
{il_section}{schedule_section}
The team and status shown for each player above are current as of today. Every player listed is on an active MLB roster — do NOT describe any of them as a minor leaguer, prospect, or "stash"; base your analysis only on the data above and current web-search results, not on prior-season assumptions.

Use web search to check current status for this roster. Limit yourself to 3-5 searches total — a general injury report plus targeted searches for the injured (IL) players listed above. Prioritize getting a real injury + return note for the IL players over searching healthy starters individually.

Based on what you find, assign each player a start/sit recommendation for the current week. Consider: injuries, recent form, upcoming matchups, platoon situations.

Return ONLY a ```json code block — no other text before or after it:
{{
  "players": [
    {{"name": "Player Name", "position": "1B", "team": "NYY", "salary": 22, "recommendation": "start", "reason": "one sentence"}}
  ],
  "alerts": [
    {{"name": "Player Name", "status": "DTD", "detail": "one sentence"}}
  ]
}}

Rules:
- recommendation must be exactly: start, monitor, or sit
- alerts: include DTD players and the IL players you researched above (status = IL type, detail = injury + expected return you found). Do not re-list MiLB players.
- Include every player from the Active/Reserve roster above in the players array
{schedule_rule}"""

        ai = get_ai_client_for_league(sb, body.league_id, tool="start_sit")
        response = ai.messages.create(
            model=MODEL_DASHBOARD,
            max_tokens=5000,
            thinking=_NO_THINKING,
            tools=_WEB_SEARCH,
            messages=[{"role": "user", "content": _with_search_first(prompt)}],
        )
        raw_text = _extract_text(response)

        # Extract JSON block from response
        structured: dict = {"players": [], "alerts": []}
        match = re.search(r"```json\s*([\s\S]*?)\s*```", raw_text)
        if match:
            try:
                structured = _json.loads(match.group(1))
            except Exception:
                pass
        else:
            match2 = re.search(r'\{[\s\S]*"players"[\s\S]*\}', raw_text)
            if match2:
                try:
                    structured = _json.loads(match2.group(0))
                except Exception:
                    pass

        # Final alerts order: IL → MiLB → edge-case IL → DTD/return-timeline from AI
        structured["alerts"] = il_alerts + milb_alerts + edge_il_alerts + structured.get("alerts", [])

        # Deduplicate by (name, status) — last occurrence wins (AI detail is
        # richer than fallback). Keying on name alone dropped a second, genuinely
        # different alert for the same player (e.g. Fantrax IL + an AI DTD note).
        seen = {}
        for alert in structured["alerts"]:
            seen[(alert.get("name"), alert.get("status"))] = alert
        structured["alerts"] = list(seen.values())

        # A generation with no start/sit recs means the model returned no parseable
        # JSON (truncation / transient web_search miss), not that there's nothing to
        # say. Don't poison the cache with it: reuse the last good players (with this
        # run's fresh alerts) if we have them, else return uncached so the next load
        # retries instead of showing a sticky "no recommendations".
        if not structured.get("players"):
            prev = (
                sb.table("dashboard_cache")
                .select("content,updated_at")
                .eq("league_id", body.league_id)
                .eq("widget", "start_sit")
                .limit(1)
                .execute()
            )
            if prev.data:
                try:
                    prev_content = _json.loads(prev.data[0]["content"])
                except Exception:
                    prev_content = None
                if prev_content and prev_content.get("players"):
                    prev_content["alerts"] = structured["alerts"]
                    return {"content": prev_content, "updated_at": prev.data[0]["updated_at"]}
            return {"content": structured, "updated_at": datetime.now(timezone.utc).isoformat()}

        if _web_search_failed(response):
            return {"content": structured, "updated_at": _now_iso()}
        updated_at = _upsert_cache(sb, body.league_id, "start_sit", _json.dumps(structured))
        return {"content": structured, "updated_at": updated_at}

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/dashboard/waiver")
async def dashboard_waiver(
    body: DashboardRequest,
    user: dict = Depends(get_current_user),
):
    try:
        sb = get_supabase()
        require_league_owner(sb, user, body.league_id)
        if (user or {}).get("sub"):  # a real owner view (not the warmer) keeps it warm
            await asyncio.to_thread(_touch_league_viewed, sb, body.league_id)

        def cached_response(force: bool, max_age: timedelta | None = None) -> dict | None:
            row = _check_cache(sb, body.league_id, "waiver", force, max_age)
            if row:
                return {"content": row["content"], "updated_at": row["updated_at"]}
            return None

        cached = cached_response(body.force)
        if cached:
            return cached

        # Blocking Supabase + web-search AI call — worker thread + single-flight
        # (see /dashboard/news).
        def build() -> dict:
            if _league_sport(sb, body.league_id) == "NFL":
                return _nfl_waiver(sb, body)
            return _build_waiver_mlb(sb, body)

        return await _single_flight(
            body.league_id, "waiver",
            recheck=lambda: cached_response(False, max_age=_RECHECK_WINDOW),
            generate=lambda: asyncio.to_thread(build),
        )

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


def _season_stat_line(season: dict, player_type: str) -> str:
    """Compact current-season line for a waiver-pool player, from cached stats."""
    if not season:
        return "no current-season MLB stats"
    if player_type == "hitter":
        return (
            f"{season.get('avg', '?')} AVG, {season.get('home_runs', '?')} HR, "
            f"{season.get('rbi', '?')} RBI, {season.get('runs', '?')} R, "
            f"{season.get('stolen_bases', '?')} SB, {season.get('ops', '?')} OPS"
        )
    return (
        f"{season.get('era', '?')} ERA, {season.get('whip', '?')} WHIP, "
        f"{season.get('strikeouts', '?')} K, {season.get('saves', '?')} SV, "
        f"{season.get('quality_starts', '?')} QS"
    )


def _build_waiver_mlb(sb, body) -> dict:
    """Generate the MLB waiver widget (blocking — runs in a worker thread)."""
    try:
        # Collect all claimed fantrax IDs across every team's roster
        all_rosters_result = (
            sb.table("rosters")
            .select("fantrax_team_id,roster_items,salary_cap")
            .eq("league_id", body.league_id)
            .execute()
        )
        all_rosters = all_rosters_result.data or []

        claimed_ids: set[str] = set()
        for roster in all_rosters:
            for item in roster.get("roster_items", []):
                if item.get("id"):
                    claimed_ids.add(item["id"])

        claimed_list = list(claimed_ids)

        # Query unclaimed hitters from player_id_map. roster_status/il_type carry
        # the injury signal — without them the model recommended IL players as
        # clean adds (e.g. an injured closer offered for saves).
        unclaimed_hitters_result = (
            sb.table("player_id_map")
            .select("fantrax_id,full_name,mlb_team,player_type,mlb_id,roster_status,il_type")
            .eq("player_type", "hitter")
            .not_.in_("fantrax_id", claimed_list)
            .order("full_name")
            .limit(150)
            .execute()
        )

        # Query unclaimed pitchers from player_id_map
        unclaimed_pitchers_result = (
            sb.table("player_id_map")
            .select("fantrax_id,full_name,mlb_team,player_type,mlb_id,roster_status,il_type")
            .eq("player_type", "pitcher")
            .not_.in_("fantrax_id", claimed_list)
            .order("full_name")
            .limit(100)
            .execute()
        )
        pool_hitters = unclaimed_hitters_result.data or []
        pool_pitchers = unclaimed_pitchers_result.data or []

        # Ground the pool in real season stats (cache-only read — no API
        # fan-out). Without numbers the model had to web-search every name it
        # considered, which was slow and hallucination-prone.
        pool_mlb_ids = [r["mlb_id"] for r in pool_hitters + pool_pitchers if r.get("mlb_id")]
        pool_stats = get_cached_stats_bulk(pool_mlb_ids)

        def pool_line(r: dict) -> str:
            season = (pool_stats.get(r.get("mlb_id")) or {}).get("season_stats") or {}
            # Flag injured players inline so the model never offers them as a
            # ready-now add (roster_status is refreshed each sync).
            flag = ""
            if (r.get("roster_status") or "") == "IL":
                flag = f" | ⚠ ON IL ({r.get('il_type') or 'IL'})"
            return (
                f"- {r['full_name']} ({r.get('mlb_team', '?')}, {r['player_type']}) | "
                f"{_season_stat_line(season, r['player_type'])}{flag}"
            )

        def stat_sort(rows: list[dict], key: str, reverse: bool) -> list[dict]:
            """Players with stats first (best first), no-stat players after."""
            def sort_key(r):
                season = (pool_stats.get(r.get("mlb_id")) or {}).get("season_stats") or {}
                try:
                    return (0, (-1 if reverse else 1) * float(season.get(key)))
                except (TypeError, ValueError):
                    return (1, 0.0)
            return sorted(rows, key=sort_key)

        unclaimed_lines = (
            [pool_line(r) for r in stat_sort(pool_hitters, "ops", reverse=True)]
            + [pool_line(r) for r in stat_sort(pool_pitchers, "era", reverse=False)]
        )

        # Get my roster for context
        my_roster = next(
            (r for r in all_rosters if r.get("fantrax_team_id") == body.my_team_id),
            {},
        )
        my_items = my_roster.get("roster_items", [])
        my_ids = [item.get("id") for item in my_items if item.get("id")]

        name_result = (
            sb.table("player_id_map")
            .select("fantrax_id,full_name")
            .in_("fantrax_id", my_ids)
            .execute()
        )
        name_map = {r["fantrax_id"]: r["full_name"] for r in (name_result.data or [])}

        my_roster_lines = []
        for item in my_items:
            fid = item.get("id", "")
            name = name_map.get(fid, fid)
            pos = item.get("position", "")
            my_roster_lines.append(f"- {name} ({pos})")

        # Cap space: recommendations must be affordable.
        cap_used = sum(
            (item.get("salary") or 0)
            for item in my_items
            if (item.get("status") or "").upper() in ("ACTIVE", "RESERVE", "INJURED_RESERVE")
        )
        cap_limit = my_roster.get("salary_cap")
        if isinstance(cap_limit, (int, float)):
            def _dollars(v: float) -> str:
                return str(int(v)) if float(v).is_integer() else str(v)
            cap_line = (
                f"My salary cap: ${_dollars(cap_limit)} total, "
                f"${_dollars(max(cap_limit - cap_used, 0))} remaining."
            )
        else:
            cap_line = ""

        # Get league context for weaknesses
        league_result = (
            sb.table("leagues")
            .select("name,cap_philosophy,team_weaknesses,competitive_window,goals")
            .eq("id", body.league_id)
            .limit(1)
            .execute()
        )
        league_data = league_result.data[0] if league_result.data else {}
        league_name = league_data.get("name", "League")
        num_teams = len(all_rosters)

        context_lines = []
        if league_data.get("competitive_window"):
            context_lines.append(f"Competitive window: {league_data['competitive_window']}")
        if league_data.get("cap_philosophy"):
            context_lines.append(f"Cap philosophy: {league_data['cap_philosophy']}")
        if league_data.get("goals"):
            context_lines.append(f"Season goals: {league_data['goals']}")

        # Load category ranks — primary source for identifying weaknesses
        category_ranks, weak_cats = _weak_categories_context(sb, body.league_id)
        if category_ranks:
            ranks_str = ", ".join(f"{cat}:{rank}" for cat, rank in category_ranks.items())
            context_lines.append(f"Category ranks (1=best, {num_teams}=worst): {ranks_str}")
            if weak_cats:
                context_lines.append(f"Weakest categories (priority targets): {', '.join(weak_cats)}")

        unclaimed_section = "\n".join(unclaimed_lines) if unclaimed_lines else "No unclaimed player data available."

        prompt = f"""You are a fantasy baseball analyst for a dynasty contract league. Recommend waiver wire pickups from the pool below.
{_today_line()}

League: {league_name} ({num_teams} teams)
{chr(10).join(context_lines) if context_lines else ""}
{cap_line}

My current roster:
{chr(10).join(my_roster_lines) if my_roster_lines else "No roster data."}

Available waiver pool (unclaimed in this league, with current-season stats where available; hitters sorted by OPS, pitchers by ERA). Lines marked "⚠ ON IL" are currently on the injured list:
{unclaimed_section}

From the unclaimed pool above, identify the best 4-5 players to target right now. The stat lines are real current-season numbers — use them to shortlist, then web search each of your top candidates to confirm role, health, and playing time before recommending them (not the whole pool). For each recommendation include:
- Player name, team, position
- Why they're a good pickup right now (cite their stat line)
- Short-term and dynasty value assessment

Hard rules:
- Use each player's team and position exactly as given in the pool line above. Do NOT state a team, role, or health status from memory — if you can't confirm it via web search, don't assert it.
- Never put a player who is on the IL (marked ⚠, or confirmed injured via search) in the add list — they can't help right now. You may mention a truly elite injured player separately, clearly labeled "IL stash — not active", but never as a priority add.

Prioritize players who address the team's weakest categories (high rank numbers), and keep recommendations affordable within the remaining cap space.

Finish with a **Priority order** section: one short line per player, in the order to add them, each naming the category it fixes — a scannable list, not a paragraph.

{_ANSWER_MARKER_INSTRUCTION} After the marker: no preamble — start directly with the first player recommendation."""

        ai = get_ai_client_for_league(sb, body.league_id, tool="waiver")
        response = ai.messages.create(
            model=MODEL_DASHBOARD,
            max_tokens=5000,
            thinking=_NO_THINKING,
            tools=_WEB_SEARCH,
            messages=[{"role": "user", "content": _with_search_first(prompt)}],
        )
        content = _extract_text(response)

        if _web_search_failed(response):
            return {"content": content, "updated_at": _now_iso()}
        updated_at = _upsert_cache(sb, body.league_id, "waiver", content)
        return {"content": content, "updated_at": updated_at}

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/dashboard/minors")
async def dashboard_minors(
    body: DashboardRequest,
    user: dict = Depends(get_current_user),
):
    """Minor League Tracker — current-season MiLB stats + a stats-grounded trend
    for each rostered prospect. Data-only (no AI). Cached under the 'minors' widget."""
    try:
        sb = get_supabase()
        require_league_owner(sb, user, body.league_id)

        def cached_response(force: bool, max_age: timedelta | None = None) -> dict | None:
            row = _check_cache(sb, body.league_id, "minors", force, max_age)
            if row:
                try:
                    return {"content": _json.loads(row["content"]), "updated_at": row["updated_at"]}
                except Exception:
                    pass  # malformed cache — regenerate
            return None

        cached = cached_response(body.force)
        if cached:
            return cached

        # No AI call here, but the MiLB stat fan-out is still slow enough to
        # dedupe, and the Supabase reads go through threads to keep the loop free.
        return await _single_flight(
            body.league_id, "minors",
            recheck=lambda: cached_response(False, max_age=_RECHECK_WINDOW),
            generate=lambda: _build_minors_mlb(sb, body),
        )

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


async def _build_minors_mlb(sb, body) -> dict:
    """Generate the minors widget — async because the per-prospect MiLB stat
    fetches fan out concurrently."""
    try:
        _, roster_items, id_map = await asyncio.to_thread(
            _load_my_roster, sb, body.league_id, body.my_team_id,
            "fantrax_id,full_name,mlb_id,player_type,roster_status",
        )

        # MiLB players: player_id_map.roster_status == "Minors" is canonical;
        # fall back to the Fantrax roster status for not-yet-enriched prospects.
        milb_items = [
            (item, id_map.get(item.get("id", ""), {}))
            for item in roster_items
            if id_map.get(item.get("id", ""), {}).get("roster_status") == "Minors"
            or item.get("status", "").upper() == "MINORS"
        ]

        async def build(item, mapped):
            fid = item.get("id", "")
            name = mapped.get("full_name") or item.get("name", fid)
            position = item.get("position", "")
            mlb_id = mapped.get("mlb_id")
            player_type = mapped.get("player_type") or (
                "pitcher" if position.upper() in ("SP", "RP", "P") else "hitter"
            )
            summary = await get_milb_player_summary(mlb_id, player_type) if mlb_id else None
            return {
                "name": name,
                "position": position,
                "level": summary["level"] if summary else None,
                "stat_line": summary["stat_line"] if summary else "No MiLB stats yet",
                "trend": summary["trend"] if summary else "steady",
            }

        players = await asyncio.gather(*[build(item, mapped) for item, mapped in milb_items])

        # Surface prospects trending up first, then steady, then down; name as tiebreak.
        trend_order = {"up": 0, "steady": 1, "down": 2}
        players = sorted(players, key=lambda p: (trend_order.get(p["trend"], 1), p["name"]))

        structured = {"players": players}
        updated_at = await asyncio.to_thread(
            _upsert_cache, sb, body.league_id, "minors", _json.dumps(structured)
        )
        return {"content": structured, "updated_at": updated_at}

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
