import type { RosterRow } from "./types";

export function money(n: number) {
  if (!Number.isFinite(n)) return "—";
  return `$${n.toFixed(0)}`;
}

export function isPitcher(eligible?: string) {
  const e = (eligible ?? "").toUpperCase();
  return e.includes("SP") || e.includes("RP") || e === "P";
}

export function isMinors(status?: string) {
  return (status ?? "").toUpperCase() === "MIN";
}

export function isCapCounting(status?: string) {
  const s = (status ?? "").toUpperCase();
  return s === "ACT" || s === "RES";
}

export function rowKey(p: RosterRow) {
  // Good-enough stable key for selection until we add a Fantrax ID field
  return [
    p.player ?? "",
    p.team ?? "",
    p.eligible ?? "",
    p.status ?? "",
    String(p.salary ?? ""),
    p.contract ?? "",
  ].join("||");
}