import type { RosterRow } from "./types";
import { isMinors } from "./rosterUtils";

/**
 * Pure cap-planner math. Mirrors the league's contract semantics as encoded in
 * engine/rules.py: salary flat years 1-2; option/extend/cut decided in the
 * offseason after year 2 (extend jumps under-floor salaries to exactly the
 * floor); "3rd year" means optioned (expiring, auto-drops); extended players
 * are labeled 4th+ and take +extend_raise/yr up to extend_cap; the contract
 * clock is frozen for players in minors slots and their salaries never count
 * against the cap.
 */

export type ContractRules = {
  option_raise: number;
  extend_raise: number;
  extend_floor: number;
  extend_cap: number;
};

export type RosterSlots = {
  active: number;
  reserve: number;
  ir: number;
  minors: number;
};

export type LeagueRules = {
  sport: string;
  in_season_cap: number;
  offseason_cap: number;
  contract: ContractRules | null;
  slots: RosterSlots | null;
};

export const DEFAULT_RULES: LeagueRules = {
  sport: "MLB",
  in_season_cap: 450,
  offseason_cap: 335,
  contract: { option_raise: 1, extend_raise: 4, extend_floor: 15, extend_cap: 75 },
  slots: { active: 24, reserve: 6, ir: 12, minors: 12 },
};

/** Where a player sits in the contract lifecycle, derived from the Fantrax
 * contract-year label. */
export type Stage = "y1" | "y2" | "optioned" | "extended" | "unknown";

export type Decision = "keep" | "extend" | "option" | "cut";

export function contractStage(contract?: string): Stage {
  const m = /(\d+)/.exec(contract ?? "");
  if (!m) return "unknown";
  const yr = Number(m[1]);
  if (yr === 1) return "y1";
  if (yr === 2) return "y2";
  if (yr === 3) return "optioned";
  if (yr >= 4) return "extended";
  return "unknown";
}

/** The decisions actually available at a given stage. Optioned players are
 * gone after the season either way — "cut" just frees in-season cap early. */
export function decisionOptions(stage: Stage): Decision[] {
  return stage === "y2" ? ["extend", "option", "cut"] : ["keep", "cut"];
}

/** Default lean: keep everyone; for 2nd-years, extend when the floor doesn't
 * bite (extension is the normal +raise), option when extending would jump a
 * cheap player to the floor. */
export function defaultDecision(stage: Stage, salary: number, c: ContractRules): Decision {
  if (stage === "y2") {
    return salary >= c.extend_floor - c.extend_raise ? "extend" : "option";
  }
  return "keep";
}

/** Salary this player carries next season (0 = off the books). */
export function nextSeasonSalary(
  stage: Stage,
  decision: Decision,
  salary: number,
  c: ContractRules
): number {
  if (decision === "cut" || stage === "optioned") return 0;
  switch (stage) {
    case "y1":
      return salary; // year 2, flat
    case "y2":
      if (decision === "option") return salary + c.option_raise;
      return salary < c.extend_floor ? c.extend_floor : salary + c.extend_raise;
    case "extended":
      return Math.min(salary + c.extend_raise, c.extend_cap);
    default:
      return salary;
  }
}

export type PlannedRow = {
  row: RosterRow;
  key: string;
  stage: Stage;
  decision: Decision;
  salary: number;
  nextSalary: number; // 0 for minors rows (clock frozen, never cap-counting)
  minors: boolean;
};

export function planRow(row: RosterRow, key: string, decision: Decision | undefined, c: ContractRules): PlannedRow {
  const stage = contractStage(row.contract);
  const salary = Number(row.salary ?? 0);
  const minors = isMinors(row.status);
  const d = decision ?? defaultDecision(stage, salary, c);
  return {
    row,
    key,
    stage,
    decision: d,
    salary,
    nextSalary: minors ? 0 : nextSeasonSalary(stage, d, salary, c),
    minors,
  };
}

export type PlanTotals = {
  /** Salary committed against next season's offseason cap. */
  committed: number;
  /** offseason_cap - committed (negative = must shed before the draft). */
  room: number;
  /** Salary that comes off the books automatically (optioned expiring). */
  expiringRelief: number;
  /** In-season cap freed if every selected cut is made today (minors cuts free nothing). */
  cutReliefNow: number;
  openMajors: number;
  openMinors: number;
  /** $1-minimum bids reserved for open spots. */
  minBids: number;
  /** Room minus the $1 holds — real bidding power at the auction. */
  spendable: number;
};

export function planTotals(rows: PlannedRow[], rules: LeagueRules): PlanTotals {
  const slots = rules.slots ?? { active: 24, reserve: 6, ir: 12, minors: 12 };
  const majorsSlots = slots.active + slots.reserve;

  let committed = 0;
  let expiringRelief = 0;
  let cutReliefNow = 0;
  let keptMajors = 0;
  let keptMinors = 0;

  for (const p of rows) {
    committed += p.nextSalary;
    if (p.stage === "optioned" && !p.minors) expiringRelief += p.salary;
    if (p.decision === "cut" && !p.minors) cutReliefNow += p.salary;
    const gone = p.decision === "cut" || p.stage === "optioned";
    if (!gone) {
      if (p.minors) keptMinors += 1;
      // Kept IR players sit in IR slots, not the Act/Res spots you fill at
      // the auction (their salary still counts vs the cap via nextSalary).
      else if ((p.row.status ?? "").toUpperCase() !== "IR") keptMajors += 1;
    }
  }

  const openMajors = Math.max(majorsSlots - keptMajors, 0);
  const openMinors = Math.max(slots.minors - keptMinors, 0);
  const minBids = openMajors + openMinors;
  const room = rules.offseason_cap - committed;

  return {
    committed,
    room,
    expiringRelief,
    cutReliefNow,
    openMajors,
    openMinors,
    minBids,
    spendable: room - minBids,
  };
}
