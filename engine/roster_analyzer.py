import pandas as pd
from typing import Dict, Any
from .rules import LeagueRules
def analyze_roster_from_csv(csv_path: str, rules: LeagueRules) -> Dict[str, Any]:
    df = pd.read_csv(csv_path)
    print("COLUMNS:", df.columns.tolist())
    df = df.copy()
    df["Salary"] = pd.to_numeric(df.get("Salary"), errors="coerce")
    df = df[df["Salary"].notna()]

    for col in ["Player", "Team", "Eligible", "Status", "Contract"]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].astype(str)

    active_mask = df["Status"].isin(["Act", "Res"])
    active_cap_used = float(df.loc[active_mask, "Salary"].sum())
    cap_remaining = float(rules.in_season_cap - active_cap_used)

    decision_df = df[df["Contract"].str.contains("3rd", case=False, na=False)][
        ["Player", "Status", "Salary", "Contract"]
    ].sort_values(by="Salary", ascending=False)

    return {
        "cap": {
            "used": round(active_cap_used, 2),
            "limit": rules.in_season_cap,
            "remaining": round(cap_remaining, 2),
        },
        "decision_queue": decision_df.to_dict(orient="records"),
        "players": df[["Player", "Team", "Eligible", "Status", "Salary", "Contract"]]
            .sort_values(by=["Status", "Salary"], ascending=[True, False])
            .to_dict(orient="records"),
    }