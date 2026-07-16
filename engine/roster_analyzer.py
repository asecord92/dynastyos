import csv
import io
from typing import Dict, Any, List

import pandas as pd

from .rules import ContractRules, LeagueRules

def recommend_contract_action(
    status: str,
    salary: float,
    cap_remaining: float,
    contract: ContractRules | None = None,
):
    """Salary-only lean for a 2nd-year player's upcoming option/extend/cut
    decision. This can't see production (the AI tools do real valuation), so it
    frames the economics of each path and leans on cap pressure + the extension
    floor: extending under-floor players jumps them to exactly the floor, which
    makes 'cheap keeps' expensive."""
    c = contract or ContractRules()
    sal = float(salary or 0)

    extend_cost = int(c.extend_floor if sal < c.extend_floor else sal + c.extend_raise)
    option_cost = int(sal + c.option_raise)
    pressure = "high" if cap_remaining < 0 else "medium" if cap_remaining < 20 else "low"

    rationale = [
        f"Extend → ${extend_cost}/yr (then +${int(c.extend_raise)}/yr); "
        f"option → ${option_cost} for one final year, then he's auctioned"
    ]

    if sal < c.extend_floor - c.extend_raise:
        # Extension jumps him to the floor — only worth it for a core piece.
        rationale.append(
            f"Under ${int(c.extend_floor)}: extending jumps him to the floor — "
            "only extend if he's a core piece; otherwise the cheap option year wins"
        )
        return "option", rationale

    if pressure == "high":
        rationale.append("Over the cap; cutting or optioning frees meaningful space")
        return ("cut" if sal >= 10 else "option"), rationale

    rationale.append(
        f"At ${int(sal)} the floor doesn't bite — extending costs the normal "
        f"+${int(c.extend_raise)} raise, so keep him if he's producing"
    )
    return "extend", rationale

def _detect_header_rows(lines: List[str]) -> List[int]:
    """
    Return 0-based line indexes that look like a real table header.
    Fantrax tables typically have headers containing Player + Salary + Contract.
    """
    header_rows: List[int] = []
    reader = csv.reader(lines)
    for i, row in enumerate(reader):
        cells = [c.strip() for c in row if c is not None]
        joined = " | ".join(cells).lower()
        if "player" in joined and "salary" in joined and "contract" in joined:
            header_rows.append(i)
    return header_rows


def _read_section_df(lines: List[str], header_row: int, next_header_row: int | None) -> pd.DataFrame:
    """
    Read exactly one section (Hitting or Pitching) into a DataFrame:
    from header_row up to (but not including) next_header_row.
    """
    section_lines = lines[header_row : (next_header_row if next_header_row is not None else len(lines))]
    section_text = "".join(section_lines)
    return pd.read_csv(io.StringIO(section_text))


def analyze_roster_from_csv(
    csv_path: str,
    rules: LeagueRules,
    cap_override: float | None = None,
    mode: str = "in_season",
) -> Dict[str, Any]:
    # Read raw file lines (keeps us in control of where each table starts/ends)
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        lines = f.readlines()

    header_rows = _detect_header_rows(lines)

    # If we can't find headers, fall back to a naive read (so we fail gracefully)
    if not header_rows:
        df = pd.read_csv(csv_path)
    else:
        frames: List[pd.DataFrame] = []
        for idx, hr in enumerate(header_rows):
            next_hr = header_rows[idx + 1] if idx + 1 < len(header_rows) else None
            frames.append(_read_section_df(lines, hr, next_hr))
        df = pd.concat(frames, ignore_index=True)

    df = df.copy()

    # Normalize required columns if missing
    for col in ["Player", "Team", "Eligible", "Status", "Contract", "Salary", "ID"]:
        if col not in df.columns:
            df[col] = ""

    # Clean salary and drop non-player rows (headers/labels/etc.)
    df["Salary"] = pd.to_numeric(df["Salary"], errors="coerce")
    df = df[df["Salary"].notna()]

    # Normalize types for string ops
    for col in ["Player", "Team", "Eligible", "Status", "Contract", "ID"]:
        df[col] = df[col].astype(str)

    # Optional: dedupe by ID if present (Fantrax usually has this)
    if "ID" in df.columns:
        df = df.drop_duplicates(subset=["ID"], keep="first")

    # Determine cap limit
    if cap_override is not None:
        cap_limit = cap_override
    elif mode == "offseason":
        cap_limit = rules.offseason_cap
    else:
        cap_limit = rules.in_season_cap

    # Cap math: everything except Minors counts (Act + Res + IL all hit the
    # in-season cap in this league; minors salaries don't).
    cap_mask = ~df["Status"].str.startswith("Min")
    active_cap_used = float(df.loc[cap_mask, "Salary"].sum())
    cap_remaining = float(cap_limit - active_cap_used)

    # Decision queue: 2nd-year contracts face the option/extend/cut decision in
    # the offseason after this season. (A player still labeled "3rd year" was
    # OPTIONED — the commish relabels extended players to 4th year — so he's an
    # expiring rental with no decision left; auto-drops after the season.)
    decision_df = df[df["Contract"].str.contains("2nd", case=False, na=False)][
        ["Player", "Status", "Salary", "Contract"]
    ].sort_values(by="Salary", ascending=False)

    decision_records = []
    for _, row in decision_df.iterrows():
        rec, rationale = recommend_contract_action(
            status=row.get("Status", ""),
            salary=row.get("Salary", 0),
            cap_remaining=cap_remaining,
            contract=rules.contract,
        )
        sal = float(row.get("Salary", 0) or 0)

        decision_records.append(
            {
                "player": row.get("Player", ""),
                "status": row.get("Status", ""),
                "salary": sal,
                "contract": row.get("Contract", ""),
                "recommendation": rec,
                "rationale": rationale,
                "cap_relief_if_cut": sal,
                "cap_remaining_if_cut": round(cap_remaining + sal, 2),
            }
        )

    # Optioned players (labeled 3rd year) leave at season's end — surface them
    # in the queue as expiring so the roster page tells the whole story.
    expiring_df = df[df["Contract"].str.contains("3rd", case=False, na=False)][
        ["Player", "Status", "Salary", "Contract"]
    ].sort_values(by="Salary", ascending=False)
    for _, row in expiring_df.iterrows():
        sal = float(row.get("Salary", 0) or 0)
        decision_records.append(
            {
                "player": row.get("Player", ""),
                "status": row.get("Status", ""),
                "salary": sal,
                "contract": row.get("Contract", ""),
                "recommendation": "expiring",
                "rationale": [
                    "Optioned — final year; auto-drops to the auction pool after the season",
                ],
                "cap_relief_if_cut": sal,
                "cap_remaining_if_cut": round(cap_remaining + sal, 2),
            }
        )

    # Normalize decision queue columns to snake_case
    decision_df = decision_df.rename(
        columns={
            "Player": "player",
            "Status": "status",
            "Salary": "salary",
            "Contract": "contract"
        }
    )

    roster_df = (
        df[["Player", "Team", "Eligible", "Status", "Salary", "Contract"]]
        .sort_values(by=["Status", "Salary"], ascending=[True, False])
        .rename(
            columns={
                "Player": "player",
                "Team": "team",
                "Eligible": "eligible",
                "Status": "status",
                "Salary": "salary",
                "Contract": "contract",
            }
        )
    )

    return {
        "cap": {
            "used": round(active_cap_used, 2),
            "limit": cap_limit,
            "remaining": round(cap_remaining, 2),
        },
        "decision_queue": decision_records,
        "roster": roster_df.to_dict(orient="records"),
    }