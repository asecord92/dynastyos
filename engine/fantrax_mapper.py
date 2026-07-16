from typing import Any

from .rules import LeagueRules
from .roster_analyzer import recommend_contract_action

# Map Fantrax API status values to the short codes the rest of the app uses
STATUS_MAP = {
    "ACTIVE": "Act",
    "RESERVE": "Res",
    "MINORS": "Min",
    "INJURED_RESERVE": "IR",
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
        player_data = player_names.get(player_id, {})
        player_name = player_data.get("name", f"Unknown ({player_id})")
        player_team = player_data.get("team", "")

        roster.append({
            "player": player_name,
            "team": player_team,
            "eligible": item.get("position", ""),
            "status": status,
            "salary": salary,
            "contract": contract_name,
            })

    # Cap math — same logic as roster_analyzer.py: Act + Res + IR all count
    # against the in-season cap; only Minors doesn't.
    active_cap_used = sum(
        r["salary"] for r in roster if r["status"] != "Min"
    )
    cap_remaining = salary_cap - active_cap_used

    # Decision queue — 2nd-year contracts face the option/extend/cut decision
    # in the offseason after this season. A player still labeled "3rd year" was
    # OPTIONED (the commish relabels extended players to 4th year), so he's an
    # expiring rental that auto-drops after the season — surfaced as such.
    decision_queue = []
    expiring = []
    for r in roster:
        base = {
            "player": r["player"],
            "status": r["status"],
            "salary": r["salary"],
            "contract": r["contract"],
            "cap_relief_if_cut": r["salary"],
            "cap_remaining_if_cut": round(cap_remaining + r["salary"], 2),
        }
        if "2nd" in r["contract"]:
            rec, rationale = recommend_contract_action(
                status=r["status"],
                salary=r["salary"],
                cap_remaining=cap_remaining,
                contract=rules.contract,
            )
            decision_queue.append({**base, "recommendation": rec, "rationale": rationale})
        elif "3rd" in r["contract"]:
            expiring.append({
                **base,
                "recommendation": "expiring",
                "rationale": [
                    "Optioned — final year; auto-drops to the auction pool after the season",
                ],
            })

    # Sort each group by salary desc; pending decisions first, expiring after.
    decision_queue.sort(key=lambda x: x["salary"], reverse=True)
    expiring.sort(key=lambda x: x["salary"], reverse=True)
    decision_queue.extend(expiring)

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