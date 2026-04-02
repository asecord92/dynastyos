import traceback
import os
import tempfile
from fastapi import FastAPI, UploadFile, File, Query, HTTPException, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import anthropic
from datetime import datetime, timedelta, timezone

from engine.rules import LeagueRules
from engine.roster_analyzer import analyze_roster_from_csv
from engine.fantrax_client import get_leagues, get_team_rosters, get_player_ids, get_league_info
from engine.supabase_client import get_supabase
from engine.fantrax_mapper import map_roster_to_analyze_result
from engine.player_resolver import resolve_player
from engine.trade_analyzer import build_trade_context, build_trade_prompt, SYSTEM_PROMPT
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

_ai_client: anthropic.Anthropic | None = None


def get_ai_client() -> anthropic.Anthropic:
    global _ai_client
    if _ai_client is None:
        _ai_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _ai_client


class RosterSyncRequest(BaseModel):
    user_secret_id: str
    fantrax_league_id: str


class TradeAnalyzeRequest(BaseModel):
    league_id: str
    my_team_id: str
    opponent_team_id: str
    offering_ids: str  # comma-separated fantrax player IDs
    receiving_ids: str  # comma-separated fantrax player IDs


class DashboardRequest(BaseModel):
    league_id: str
    my_team_id: str
    force: bool = False


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
        else:
            unresolved.append(name)

    print(f"[bg] Resolution complete: {resolved} resolved, {len(unresolved)} unresolved")
    if unresolved:
        print(f"[bg] Unresolved: {unresolved}")


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


def _extract_text(response: anthropic.types.Message) -> str:
    """Extract text blocks from an Anthropic response."""
    return "\n".join(
        block.text
        for block in response.content
        if hasattr(block, "text") and block.type == "text"
    )


@app.get("/health")
def health():
    return {"ok": True}


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
            (l for l in leagues if l.get("leagueId") == fantrax_league_id),
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
        try:
            league_info = get_league_info(fantrax_league_id)
            profile = extract_league_profile(league_info, team_id)
            sb = get_supabase()
            sb.table("leagues").update(profile).eq("fantrax_league_id", fantrax_league_id).execute()
        except Exception as e:
            print(f"[sync] League profile update failed (non-fatal): {e}")

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


@app.post("/trade/analyze")
async def trade_analyze(
    body: TradeAnalyzeRequest,
    user: dict = Depends(get_current_user),
):
    try:
        offering = [x.strip() for x in body.offering_ids.split(",") if x.strip()]
        receiving = [x.strip() for x in body.receiving_ids.split(",") if x.strip()]

        context = await build_trade_context(
            league_id=body.league_id,
            my_team_id=body.my_team_id,
            opponent_team_id=body.opponent_team_id,
            offering_ids=offering,
            receiving_ids=receiving,
        )
        prompt = build_trade_prompt(context)

        ai = get_ai_client()

        def stream():
            with ai.messages.stream(
                model="claude-opus-4-5",
                max_tokens=2000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            ) as s:
                for text in s.text_stream:
                    yield text

        return StreamingResponse(stream(), media_type="text/plain")

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


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

Team: {team_name}
Roster:
{chr(10).join(player_lines)}

Search for and summarize recent news (last 2 weeks) for each player. Focus on: IL placements, returns from IL, lineup changes, role changes, injury updates, and anything else affecting fantasy value. Skip players with nothing to report. Format as a bulleted list with the player name in bold at the start of each item."""

        ai = get_ai_client()
        response = ai.messages.create(
            model="claude-opus-4-5",
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
            return {"content": cached["content"], "updated_at": cached["updated_at"]}

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

        active_items = [
            item for item in roster_items
            if item.get("status", "").upper() in ("ACT", "RES")
        ]

        player_lines = []
        for item in active_items:
            fid = item.get("id", "")
            name = name_map.get(fid) or item.get("name", fid)
            pos = item.get("position", "")
            sal = item.get("salary", 0)
            status = item.get("status", "")
            player_lines.append(f"- {name} ({pos}, ${sal}, {status})")

        prompt = f"""You are a fantasy baseball analyst for a dynasty contract league. Use web search to get current player news, injury status, and recent performance data.

Team: {team_name}
Active/Reserve Roster:
{chr(10).join(player_lines) if player_lines else "No active players."}

For the current week, provide start/sit recommendations. Focus on non-obvious decisions. Consider: injuries, recent form, upcoming matchups, platoon situations, and role changes.

Format your response as:

**MUST START** — Players who should definitely be in the lineup
**CONSIDER SITTING** — Players to consider benching this week
**CLOSE CALLS** — Borderline decisions with your recommendation

Keep it concise and actionable."""

        ai = get_ai_client()
        response = ai.messages.create(
            model="claude-opus-4-5",
            max_tokens=2000,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}],
        )
        content = _extract_text(response)

        updated_at = _upsert_cache(sb, body.league_id, "start_sit", content)
        return {"content": content, "updated_at": updated_at}

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
        if league_data.get("team_weaknesses"):
            context_lines.append(f"Category weaknesses: {', '.join(league_data['team_weaknesses'])}")
        if league_data.get("cap_philosophy"):
            context_lines.append(f"Cap philosophy: {league_data['cap_philosophy']}")
        if league_data.get("goals"):
            context_lines.append(f"Season goals: {league_data['goals']}")

        unclaimed_section = "\n".join(unclaimed_lines) if unclaimed_lines else "No unclaimed player data available."

        prompt = f"""You are a fantasy baseball analyst for a dynasty contract league. Use web search to evaluate and recommend waiver wire pickups.

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

Prioritize players who address my category weaknesses if possible."""

        ai = get_ai_client()
        response = ai.messages.create(
            model="claude-opus-4-5",
            max_tokens=2000,
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
