import csv
import io
from typing import Dict, Any, List

import pandas as pd

from .rules import LeagueRules


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


def analyze_roster_from_csv(csv_path: str, rules: LeagueRules) -> Dict[str, Any]:
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

    # Cap math: Act + Res count; Min does not
    active_mask = df["Status"].isin(["Act", "Res"])
    active_cap_used = float(df.loc[active_mask, "Salary"].sum())
    cap_remaining = float(rules.in_season_cap - active_cap_used)

    # Decision queue: 3rd-year contracts
    decision_df = df[df["Contract"].str.contains("3rd", case=False, na=False)][
        ["Player", "Status", "Salary", "Contract"]
    ].sort_values(by="Salary", ascending=False)

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
            "limit": rules.in_season_cap,
            "remaining": round(cap_remaining, 2),
        },
        "decision_queue": decision_df.to_dict(orient="records"),
        "roster": roster_df.to_dict(orient="records"),
}