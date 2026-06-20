import asyncio
import traceback
import os
import re
import json as _json
import tempfile
from fastapi import FastAPI, UploadFile, File, Query, HTTPException, BackgroundTasks, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
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
from engine.nfl_trade import (
    build_nfl_trade_context,
    build_nfl_trade_prompt,
    build_nfl_finder_context,
    build_nfl_finder_prompt,
    build_nfl_system_prompt,
)
from engine.nfl_dashboard import build_nfl_dashboard
from engine.nfl_widgets import (
    my_roster as nfl_my_roster,
    start_sit_prompt as nfl_start_sit_prompt,
    news_prompt as nfl_news_prompt,
    waiver_pool as nfl_waiver_pool,
    waiver_prompt as nfl_waiver_prompt,
)

_WEB_SEARCH = [{"type": "web_search_20250305", "name": "web_search"}]
from engine.supabase_client import get_supabase
from engine.fantrax_mapper import map_roster_to_analyze_result
from engine.player_resolver import resolve_player, refresh_roster_statuses
from engine.mlb_stats_client import get_milb_player_summary
from engine.category_ranks import compute_category_ranks
from engine.trade_analyzer import (
    build_trade_context,
    build_trade_prompt,
    build_finder_context,
    build_finder_prompt,
    parse_finder_response,
    build_system_prompt,
)
from engine.auth import get_current_user

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


# Re-warm AI widgets in the background before their 4h cache lapses, so a user
# never triggers a slow on-demand Sonnet+web_search generation themselves.
REFRESH_AFTER = timedelta(hours=3)


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
# dashboard widgets (news / start_sit / waiver) — faster and ~40% cheaper.
MODEL_TRADE = "claude-opus-4-8"
MODEL_DASHBOARD = "claude-sonnet-4-6"

_ai_client: anthropic.Anthropic | None = None


def get_ai_client() -> anthropic.Anthropic:
    global _ai_client
    if _ai_client is None:
        _ai_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _ai_client


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


def resolve_all_players(rosters: dict, player_names: dict) -> None:
    """
    Background task: resolve Fantrax IDs to MLB IDs for all players
    across all league rosters. Runs after the sync response is sent.
    """
    print("[bg] Starting full league player resolution...")
    all_items = []
    for tdata in rosters.values():
        all_items.extend(tdata.get("rosterItems", []))

    resolved = 0
    unresolved = []
    processed_ids = []
    for item in all_items:
        fantrax_id = item.get("id", "")
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


def _check_cache(sb, league_id: str, widget: str, force: bool) -> dict | None:
    """Returns cached row {content, updated_at} if fresh, else None."""
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
            if datetime.now(timezone.utc) - updated_at < DASHBOARD_CACHE_TTL:
                return row
    except Exception:
        pass
    return None


def _upsert_cache(sb, league_id: str, widget: str, content: str) -> str:
    """Upserts content to dashboard_cache. Returns updated_at ISO string."""
    now = datetime.now(timezone.utc).isoformat()
    sb.table("dashboard_cache").upsert(
        {"league_id": league_id, "widget": widget, "content": content, "updated_at": now},
        on_conflict="league_id,widget",
    ).execute()
    return now


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


def _extract_text(response: anthropic.types.Message) -> str:
    text = "\n".join(
        block.text
        for block in response.content
        if hasattr(block, "text") and block.type == "text"
    )
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

    sb = get_supabase()
    leagues = (sb.table("leagues").select("id, fantrax_team_id").execute().data) or []

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
        for widget, handler in handlers.items():
            age = _cache_age(sb, league_id, widget)
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
    return {"refreshed": refreshed, "count": len(refreshed)}


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


@app.get("/league/standings")
async def league_standings(
    league_id: str = Query(...),
    my_team_id: str = Query(...),
    user: dict = Depends(get_current_user),
):
    try:
        sb = get_supabase()
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


async def _run_category_ranks_compute(league_id: str, my_team_id: str) -> None:
    """Background task: approximate category ranks from rosters + season stats and
    write them to the category_ranks widget. Never raises."""
    try:
        ranks = await compute_category_ranks(league_id, my_team_id)
        if not ranks:
            return
        sb = get_supabase()
        sb.table("dashboard_cache").upsert(
            {
                "league_id": league_id,
                "widget": "category_ranks",
                "content": _json.dumps(ranks),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="league_id,widget",
        ).execute()
        print(f"[category_ranks] Computed ranks for league {league_id}: {ranks}")
    except Exception:
        traceback.print_exc()


@app.post("/league/category-ranks/compute")
async def compute_category_ranks_endpoint(
    body: DashboardRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    """Kick off an approximate category-rank calculation from current rosters + stats.
    Runs in the background (fetching stats for the whole league is slow on a cold
    cache); the client polls GET /league/category-ranks for the updated result."""
    background_tasks.add_task(
        _run_category_ranks_compute, body.league_id, body.my_team_id
    )
    return {"status": "started"}


@app.post("/roster/analyze")
async def roster_analyze(
    file: UploadFile = File(...),
    mode: str = Query(default="in_season"),
):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    return analyze_roster_from_csv(tmp_path, rules, mode=mode)


@app.get("/fantrax/leagues")
async def fantrax_leagues(user_secret_id: str = Query(...)):
    try:
        leagues = get_leagues(user_secret_id)
        return {"leagues": leagues}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sleeper/leagues")
async def sleeper_leagues(username: str = Query(...), season: int = Query(None)):
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
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/sleeper/sync")
async def sleeper_sync(body: SleeperSyncRequest, user: dict = Depends(get_current_user)):
    """Sync a Sleeper NFL league: persist every roster (with player metadata
    embedded from the players dump + computed pick inventory) and the league's
    rules. Requires the leagues row to already carry sleeper_user_id."""
    try:
        sb = get_supabase()
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
            if owner and owner == sleeper_user_id:
                my_roster_id = rid
            roster_upserts.append({
                "league_id": body.league_id,
                "fantrax_team_id": str(rid),
                "team_name": team_names.get(owner, f"Roster {rid}"),
                "roster_items": build_roster_items(r.get("players"), r.get("starters"), players),
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

        # Step 2.5: Fetch league info and persist structural profile fields
        league_info = {}
        try:
            league_info = get_league_info(fantrax_league_id)
            profile = extract_league_profile(league_info, team_id)
            sb = get_supabase()
            sb.table("leagues").update(profile).eq("fantrax_league_id", fantrax_league_id).execute()
        except Exception as e:
            print(f"[sync] League profile update failed (non-fatal): {e}")

        # Step 2.5b: Auto-detect structural league rules (caps, size, budget),
        # preserving any user-set scoring/contract. Isolated update so a missing
        # rules column (migration not yet applied) can't break the profile write.
        try:
            sb = get_supabase()
            existing = (
                sb.table("leagues")
                .select("rules")
                .eq("fantrax_league_id", fantrax_league_id)
                .single()
                .execute()
            )
            merged_rules = detect_rules(
                league_info, team_roster, rosters, (existing.data or {}).get("rules"), sport
            )
            sb.table("leagues").update({"rules": merged_rules}).eq(
                "fantrax_league_id", fantrax_league_id
            ).execute()
        except Exception as e:
            print(f"[sync] Rules auto-detect skipped (non-fatal): {e}")

        # Step 2.6: Persist all team rosters to Supabase
        try:
            sb = get_supabase()
            league_row = sb.table("leagues").select("id").eq("fantrax_league_id", fantrax_league_id).single().execute()
            league_uuid = league_row.data["id"]

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

        # Step 3.6: Resolve all OTHER league players in the background
        background_tasks.add_task(resolve_all_players, rosters, player_names)

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


@app.post("/trade/analyze")
async def trade_analyze(
    body: TradeAnalyzeRequest,
    user: dict = Depends(get_current_user),
):
    try:
        offering = [x.strip() for x in body.offering_ids.split(",") if x.strip()]
        receiving = [x.strip() for x in body.receiving_ids.split(",") if x.strip()]

        if _league_sport(get_supabase(), body.league_id) == "NFL":
            context = await build_nfl_trade_context(
                body.league_id, body.my_team_id, body.opponent_team_id, offering, receiving
            )
            prompt = build_nfl_trade_prompt(context)
            system_prompt = build_nfl_system_prompt(context["rules"])
        else:
            context = await build_trade_context(
                league_id=body.league_id,
                my_team_id=body.my_team_id,
                opponent_team_id=body.opponent_team_id,
                offering_ids=offering,
                receiving_ids=receiving,
            )
            prompt = build_trade_prompt(context)
            system_prompt = build_system_prompt(context["rules"], context["sport"])

        ai = get_ai_client()

        def stream():
            with ai.messages.stream(
                model=MODEL_TRADE,
                max_tokens=2000,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
            ) as s:
                for text in s.text_stream:
                    yield text

        return StreamingResponse(stream(), media_type="text/plain")

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/trade/finder")
async def trade_finder(
    body: TradeFinderRequest,
    user: dict = Depends(get_current_user),
):
    """Category-first Trade Finder. Streams newline-delimited JSON: a `meta` event
    with the ranked targets first (so the UI shows them immediately, before the
    slow Opus call), then `text` events as the recommendation streams, then a
    final `packages` event with the parsed, validated offers."""
    # Build context up front so input errors surface as a normal HTTP status
    # (not mid-stream). This is also where the candidate ranking is computed.
    # The finder's `target_category` field carries an NFL position for football.
    sport = _league_sport(get_supabase(), body.league_id)
    try:
        if sport == "NFL":
            context = await build_nfl_finder_context(
                body.league_id, body.my_team_id, target_position=body.target_category
            )
        else:
            context = await build_finder_context(
                league_id=body.league_id,
                my_team_id=body.my_team_id,
                target_category=body.target_category,
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

    if sport == "NFL":
        target_label = context["target_position"]
        candidates = [
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
        ]
        # parse_finder_response keys on `fantrax_id`; football assets/candidates use `id`.
        parse_candidates = [{**c, "fantrax_id": c["id"]} for c in context["candidates"]]
        parse_assets = [{**a, "fantrax_id": a["id"]} for a in context["my_assets"]]
        prompt = build_nfl_finder_prompt(context)
        system_prompt = build_nfl_system_prompt(context["rules"])
    else:
        target_label = context["target_category"]
        candidates = [
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
        ]
        parse_candidates = context["candidates"]
        parse_assets = context.get("my_assets", [])
        prompt = build_finder_prompt(context)
        system_prompt = build_system_prompt(context["rules"], context["sport"])
    ai = get_ai_client()

    def event(obj: dict) -> str:
        return _json.dumps(obj) + "\n"

    def stream():
        # Targets are ready before the AI call — send them first.
        yield event({
            "type": "meta",
            "target_category": target_label,
            "candidates": candidates,
        })
        full: list[str] = []
        emitted = 0  # chars of the prose already streamed
        stopped = False  # once the ```json fence starts, hold back the rest
        try:
            with ai.messages.stream(
                model=MODEL_TRADE,
                max_tokens=2000,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
            ) as s:
                for text in s.text_stream:
                    full.append(text)
                    if stopped:
                        continue
                    joined = "".join(full)
                    fence = joined.find("```")
                    if fence != -1:
                        if fence > emitted:
                            yield event({"type": "text", "delta": joined[emitted:fence]})
                        emitted = fence
                        stopped = True  # the rest is the JSON package block
                    else:
                        # Hold back a 2-char lookbehind so a fence split across
                        # deltas is never shown to the user.
                        safe = len(joined) - 2
                        if safe > emitted:
                            yield event({"type": "text", "delta": joined[emitted:safe]})
                            emitted = safe
            raw = "".join(full)
            analysis, packages = parse_finder_response(raw, parse_candidates, parse_assets)
            yield event({"type": "packages", "packages": packages, "analysis": analysis})
        except Exception as e:
            traceback.print_exc()
            yield event({"type": "error", "detail": str(e)})

    return StreamingResponse(stream(), media_type="application/x-ndjson")


# --- Football dashboard widgets (start_sit / news / waiver) -------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _nfl_start_sit(sb, body) -> dict:
    team_name, items = nfl_my_roster(sb, body.league_id, body.my_team_id)
    if not items:
        raise HTTPException(status_code=404, detail="No roster found. Sync your league first.")
    out_alerts = [
        {"name": it.get("name"), "status": it.get("injury_status"), "detail": f"Listed {it.get('injury_status')}"}
        for it in items if it.get("injury_status")
    ]
    ai = get_ai_client()
    response = ai.messages.create(
        model=MODEL_DASHBOARD, max_tokens=4000, tools=_WEB_SEARCH,
        messages=[{"role": "user", "content": nfl_start_sit_prompt(team_name, items)}],
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
    seen = {a["name"]: a for a in structured["alerts"] if a.get("name")}
    structured["alerts"] = list(seen.values())
    if not structured.get("players"):  # don't cache an empty generation
        return {"content": structured, "updated_at": _now_iso()}
    return {"content": structured, "updated_at": _upsert_cache(sb, body.league_id, "start_sit", _json.dumps(structured))}


async def _nfl_news(sb, body) -> dict:
    team_name, items = nfl_my_roster(sb, body.league_id, body.my_team_id)
    if not items:
        return {"content": "Sync your league to see news.", "updated_at": _now_iso()}
    ai = get_ai_client()
    response = ai.messages.create(
        model=MODEL_DASHBOARD, max_tokens=2000, tools=_WEB_SEARCH,
        messages=[{"role": "user", "content": nfl_news_prompt(team_name, items)}],
    )
    content = _extract_text(response)
    if not content.strip():
        return {"content": content, "updated_at": _now_iso()}
    return {"content": content, "updated_at": _upsert_cache(sb, body.league_id, "news", content)}


async def _nfl_waiver(sb, body) -> dict:
    league = sb.table("leagues").select("rules").eq("id", body.league_id).single().execute().data or {}
    fmt_key = f"pts_{((league.get('rules') or {}).get('scoring_format') or 'half_ppr')}"
    team_name, _items = nfl_my_roster(sb, body.league_id, body.my_team_id)
    fas = nfl_waiver_pool(sb, body.league_id, fmt_key)
    ai = get_ai_client()
    response = ai.messages.create(
        model=MODEL_DASHBOARD, max_tokens=2000, tools=_WEB_SEARCH,
        messages=[{"role": "user", "content": nfl_waiver_prompt(team_name or "Your Team", fas)}],
    )
    content = _extract_text(response)
    if not content.strip():
        return {"content": content, "updated_at": _now_iso()}
    return {"content": content, "updated_at": _upsert_cache(sb, body.league_id, "waiver", content)}


@app.post("/dashboard/news")
async def dashboard_news(
    body: DashboardRequest,
    user: dict = Depends(get_current_user),
):
    try:
        sb = get_supabase()

        cached = _check_cache(sb, body.league_id, "news", body.force)
        if cached:
            return {"content": cached["content"], "updated_at": cached["updated_at"]}

        if _league_sport(sb, body.league_id) == "NFL":
            return await _nfl_news(sb, body)

        roster_result = (
            sb.table("rosters")
            .select("roster_items,team_name")
            .eq("league_id", body.league_id)
            .eq("fantrax_team_id", body.my_team_id)
            .limit(1)
            .execute()
        )
        if not roster_result.data:
            raise HTTPException(status_code=404, detail="No roster found. Sync your league first.")

        roster_row = roster_result.data[0]
        roster_items = roster_row.get("roster_items", [])
        team_name = roster_row.get("team_name", "Your Team")

        fantrax_ids = [item.get("id") for item in roster_items if item.get("id")]
        name_result = (
            sb.table("player_id_map")
            .select("fantrax_id,full_name")
            .in_("fantrax_id", fantrax_ids)
            .execute()
        )
        name_map = {r["fantrax_id"]: r["full_name"] for r in (name_result.data or [])}

        player_lines = []
        for item in roster_items:
            fid = item.get("id", "")
            name = name_map.get(fid) or item.get("name", fid)
            pos = item.get("position", "")
            status = item.get("status", "")
            player_lines.append(f"- {name} ({pos}, {status})")

        prompt = f"""You are a fantasy baseball analyst. Use web search to find the latest injury and performance news for the following players.
{_today_line()}

Team: {team_name}
Roster:
{chr(10).join(player_lines)}

Search for and summarize recent news (last 2 weeks) for each player. Focus on: IL placements, returns from IL, lineup changes, role changes, injury updates, and anything else affecting fantasy value. Skip players with nothing to report. Format as a bulleted list with the player name in bold at the start of each item.

Do not include any preamble, introduction, or horizontal rules (---). Do not say "Based on my research" or similar. Start directly with the first player bullet point."""

        ai = get_ai_client()
        response = ai.messages.create(
            model=MODEL_DASHBOARD,
            max_tokens=2000,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}],
        )
        content = _extract_text(response)

        updated_at = _upsert_cache(sb, body.league_id, "news", content)
        return {"content": content, "updated_at": updated_at}

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

        cached = _check_cache(sb, body.league_id, "start_sit", body.force)
        if cached:
            try:
                content = _json.loads(cached["content"])
                # Ignore an empty cached result (a prior failed generation) so it
                # doesn't stick for the full TTL — fall through and regenerate.
                if content.get("players"):
                    return {"content": content, "updated_at": cached["updated_at"]}
            except Exception:
                pass  # Old prose cache — fall through to regenerate

        if _league_sport(sb, body.league_id) == "NFL":
            return await _nfl_start_sit(sb, body)

        roster_result = (
            sb.table("rosters")
            .select("roster_items,team_name")
            .eq("league_id", body.league_id)
            .eq("fantrax_team_id", body.my_team_id)
            .limit(1)
            .execute()
        )
        if not roster_result.data:
            raise HTTPException(status_code=404, detail="No roster found. Sync your league first.")

        roster_row = roster_result.data[0]
        roster_items = roster_row.get("roster_items", [])
        team_name = roster_row.get("team_name", "Your Team")

        fantrax_ids = [item.get("id") for item in roster_items if item.get("id")]
        name_result = (
            sb.table("player_id_map")
            .select("fantrax_id,full_name,mlb_team,roster_status,il_type")
            .in_("fantrax_id", fantrax_ids)
            .execute()
        )
        name_map = {r["fantrax_id"]: r["full_name"] for r in (name_result.data or [])}
        team_map = {r["fantrax_id"]: r.get("mlb_team", "") for r in (name_result.data or [])}
        status_map = {r["fantrax_id"]: r.get("roster_status") for r in (name_result.data or [])}
        il_type_map = {r["fantrax_id"]: r.get("il_type") for r in (name_result.data or [])}

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
                il_alerts.append({
                    "name": name,
                    "status": il_type,
                    "detail": f"On {il_type} — check return timeline",
                })
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

        # Short-term IL players to include in AI research (return timelines)
        short_term_il_names = [
            name_map.get(item.get("id", "")) or item.get("name", "")
            for item in roster_items
            if item.get("status", "").upper() == "INJURED_RESERVE"
            and il_type_map.get(item.get("id", "")) in ("10-Day IL", "15-Day IL")
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

        short_term_il_section = ""
        if short_term_il_names:
            short_term_il_section = f"""
Short-term IL players (10-Day or 15-Day) — search for return timeline for each:
{chr(10).join(f"- {n}" for n in short_term_il_names)}
If a return timeline is found, include each in the alerts array with status "DTD" or the IL type and the expected return detail.
"""

        prompt = f"""You are a fantasy baseball analyst for a dynasty contract league.
{_today_line()}

Team: {team_name}
Active/Reserve Roster (name | position | MLB team | salary):
{chr(10).join(player_lines) if player_lines else "No active players."}
{ranks_line}
{short_term_il_section}
The team and status shown for each player above are current as of today. Every player listed is on an active MLB roster — do NOT describe any of them as a minor leaguer, prospect, or "stash"; base your analysis only on the data above and current web-search results, not on prior-season assumptions.

Use web search to check current status for this roster. Limit yourself to 2-3 searches total — search for a general injury report and maybe one targeted search for a specific player concern. Do not search every player individually.

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
- alerts: include DTD players and any short-term IL return timelines found — do not re-list confirmed IL/MiLB players
- Include every player from the Active/Reserve roster above in the players array"""

        ai = get_ai_client()
        response = ai.messages.create(
            model=MODEL_DASHBOARD,
            max_tokens=4000,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}],
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

        # Deduplicate by name — last occurrence wins (AI detail is richer than fallback)
        seen = {}
        for alert in structured["alerts"]:
            seen[alert["name"]] = alert
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

        cached = _check_cache(sb, body.league_id, "waiver", body.force)
        if cached:
            return {"content": cached["content"], "updated_at": cached["updated_at"]}

        if _league_sport(sb, body.league_id) == "NFL":
            return await _nfl_waiver(sb, body)

        # Collect all claimed fantrax IDs across every team's roster
        all_rosters_result = (
            sb.table("rosters")
            .select("fantrax_team_id,roster_items")
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

        # Query unclaimed hitters from player_id_map
        unclaimed_hitters_result = (
            sb.table("player_id_map")
            .select("fantrax_id,full_name,mlb_team,player_type")
            .eq("player_type", "hitter")
            .not_.in_("fantrax_id", claimed_list)
            .order("full_name")
            .limit(150)
            .execute()
        )

        # Query unclaimed pitchers from player_id_map
        unclaimed_pitchers_result = (
            sb.table("player_id_map")
            .select("fantrax_id,full_name,mlb_team,player_type")
            .eq("player_type", "pitcher")
            .not_.in_("fantrax_id", claimed_list)
            .order("full_name")
            .limit(100)
            .execute()
        )

        unclaimed_lines = [
            f"- {r['full_name']} ({r.get('mlb_team', '?')}, {r['player_type']})"
            for r in (unclaimed_hitters_result.data or []) + (unclaimed_pitchers_result.data or [])
        ]

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
        category_ranks = _load_category_ranks(sb, body.league_id)
        if category_ranks:
            ranks_str = ", ".join(f"{cat}:{rank}" for cat, rank in category_ranks.items())
            context_lines.append(f"Category ranks (1=best, {num_teams}=worst): {ranks_str}")
            weak_cats = [cat for cat, rank in category_ranks.items() if isinstance(rank, int) and rank >= 7]
            if weak_cats:
                context_lines.append(f"Weakest categories (priority targets): {', '.join(weak_cats)}")

        unclaimed_section = "\n".join(unclaimed_lines) if unclaimed_lines else "No unclaimed player data available."

        prompt = f"""You are a fantasy baseball analyst for a dynasty contract league. Use web search to evaluate and recommend waiver wire pickups.
{_today_line()}

League: {league_name} ({num_teams} teams)
{chr(10).join(context_lines) if context_lines else ""}

My current roster:
{chr(10).join(my_roster_lines) if my_roster_lines else "No roster data."}

Available waiver pool (unclaimed in this league):
{unclaimed_section}

From the unclaimed pool above, identify the best 4-5 players to target right now. Use web search to check their current performance, role, and injury status. For each recommendation include:
- Player name, team, position
- Why they're a good pickup right now
- Short-term and dynasty value assessment

Prioritize players who address the team's weakest categories (high rank numbers) if possible.

Do not include any preamble or introduction. Start directly with the first player recommendation."""

        ai = get_ai_client()
        response = ai.messages.create(
            model=MODEL_DASHBOARD,
            max_tokens=4000,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}],
        )
        content = _extract_text(response)

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

        cached = _check_cache(sb, body.league_id, "minors", body.force)
        if cached:
            try:
                return {"content": _json.loads(cached["content"]), "updated_at": cached["updated_at"]}
            except Exception:
                pass  # malformed cache — regenerate

        roster_result = (
            sb.table("rosters")
            .select("roster_items")
            .eq("league_id", body.league_id)
            .eq("fantrax_team_id", body.my_team_id)
            .limit(1)
            .execute()
        )
        if not roster_result.data:
            raise HTTPException(status_code=404, detail="No roster found. Sync your league first.")

        roster_items = roster_result.data[0].get("roster_items", [])
        fantrax_ids = [item.get("id") for item in roster_items if item.get("id")]

        map_result = (
            sb.table("player_id_map")
            .select("fantrax_id,full_name,mlb_id,player_type,roster_status")
            .in_("fantrax_id", fantrax_ids)
            .execute()
        )
        id_map = {r["fantrax_id"]: r for r in (map_result.data or [])}

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
        updated_at = _upsert_cache(sb, body.league_id, "minors", _json.dumps(structured))
        return {"content": structured, "updated_at": updated_at}

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
