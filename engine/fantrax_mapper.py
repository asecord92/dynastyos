from typing import Any

from .rules import LeagueRules
from .roster_analyzer import recommend_contract_action

# Map Fantrax API status values to the short codes the rest of the app uses
STATUS_MAP = {
    "ACTIVE": "Act",
    "RESERVE": "Res",
    "MINORS": "Min",
    "INJURED_RESERVE": "Res",  # treat IR as reserve for cap purposes
}


def map_roster_to_analyze_result(
    team_roster: dict[str, Any],
    player_names: dict[str, str],
    rules: LeagueRules,
) -> dict[str, Any]:
    """
    Takes a single team's roster from getTeamRosters, the player ID->name map,
    and league rules, and returns an AnalyzeResult-shaped dict.
    """
    roster_items = team_roster.get("rosterItems", [])
    salary_cap = float(team_roster.get("salaryCap", rules.in_season_cap))

    # Build normalized roster rows
    roster = []
    for item in roster_items:
        fantrax_status = item.get("status", "")
        status = STATUS_MAP.get(fantrax_status, "Min")
        salary = float(item.get("salary", 0))
        contract_name = item.get("contract", {}).get("name", "")
        player_id = item.get("id", "")
        player_name = player_names.get(player_id, f"Unknown ({player_id})")

        roster.append({
            "player": player_name,
            "team": "",        # not provided by this endpoint
            "eligible": item.get("position", ""),
            "status": status,
            "salary": salary,
            "contract": contract_name,
        })

    # Cap math — same logic as roster_analyzer.py
    active_cap_used = sum(
        r["salary"] for r in roster if r["status"] in ("Act", "Res")
    )
    cap_remaining = salary_cap - active_cap_used

    # Decision queue — 3rd year contracts
    decision_queue = []
    for r in roster:
        if "3rd" not in r["contract"]:
            continue
        rec, rationale = recommend_contract_action(
            status=r["status"],
            salary=r["salary"],
            cap_remaining=cap_remaining,
        )
        decision_queue.append({
            "player": r["player"],
            "status": r["status"],
            "salary": r["salary"],
            "contract": r["contract"],
            "recommendation": rec,
            "rationale": rationale,
            "cap_relief_if_cut": r["salary"],
            "cap_remaining_if_cut": round(cap_remaining + r["salary"], 2),
        })

    # Sort decision queue by salary desc
    decision_queue.sort(key=lambda x: x["salary"], reverse=True)

    # Sort roster by status then salary desc
    roster.sort(key=lambda x: (x["status"], -x["salary"]))

    return {
        "cap": {
            "used": round(active_cap_used, 2),
            "limit": salary_cap,
            "remaining": round(cap_remaining, 2),
        },
        "decision_queue": decision_queue,
        "roster": roster,
    }