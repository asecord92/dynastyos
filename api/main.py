from fastapi import FastAPI, UploadFile, File, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import tempfile

from engine.rules import LeagueRules
from engine.roster_analyzer import analyze_roster_from_csv
from engine.fantrax_client import get_leagues, get_team_rosters, get_player_ids
from engine.fantrax_mapper import map_roster_to_analyze_result

app = FastAPI(title="DynastyOS API")

import os

allow_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

rules = LeagueRules()


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
    user_secret_id: str = Query(...),
    fantrax_league_id: str = Query(...),
):
    try:
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

        # Step 3: Get player ID -> name map (cached 24hr)
        player_names = get_player_ids(sport)

        # Step 4: Map to AnalyzeResult shape
        result = map_roster_to_analyze_result(team_roster, player_names, rules)

        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))