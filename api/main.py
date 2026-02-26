from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
import tempfile

from engine.rules import LeagueRules
from engine.roster_analyzer import analyze_roster_from_csv

app = FastAPI(title="DynastyOS API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

rules = LeagueRules()

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/roster/analyze")
async def roster_analyze(file: UploadFile = File(...)):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    return analyze_roster_from_csv(tmp_path, rules)