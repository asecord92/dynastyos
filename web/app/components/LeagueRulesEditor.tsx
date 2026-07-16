"use client";

import { useEffect, useState } from "react";
import { supabase } from "../lib/supabaseClient";

type Contract = {
  option_raise?: number;
  extend_raise?: number;
  extend_floor?: number;
  extend_cap?: number;
};

type Slots = {
  active?: number;
  reserve?: number;
  ir?: number;
  minors?: number;
};

type Rules = {
  sport?: string;
  league_size?: number;
  in_season_cap?: number;
  offseason_cap?: number;
  scoring?: { hitting?: string[]; pitching?: string[] };
  contract?: Contract | null;
  slots?: Slots | null;
  // Football (Sleeper) — auto-detected, read-only
  scoring_format?: string;
  superflex?: boolean;
  roster_positions?: string[];
  draft_rounds?: number;
  taxi_slots?: number;
  taxi_years?: number;
};

const PPR_LABEL: Record<string, string> = {
  ppr: "Full PPR",
  half_ppr: "0.5 PPR (half)",
  std: "Standard (non-PPR)",
};

function lineupSummary(positions: string[]): string {
  const slots = positions.filter((p) => !["BN", "IR", "TAXI"].includes(p));
  const counts: Record<string, number> = {};
  for (const p of slots) counts[p] = (counts[p] ?? 0) + 1;
  const label = (p: string) =>
    p === "SUPER_FLEX" ? "SuperFlex" : p === "FLEX" ? "Flex" : p === "DEF" ? "DEF" : p;
  return Object.entries(counts).map(([p, c]) => `${c} ${label(p)}`).join(" · ");
}

const DEFAULT_HITTING = ["R", "HR", "RBI", "SB", "OBP"];
const DEFAULT_PITCHING = ["QS", "SV", "K", "ERA", "WHIP"];
const DEFAULT_CONTRACT: Required<Contract> = {
  option_raise: 1,
  extend_raise: 4,
  extend_floor: 15,
  extend_cap: 75,
};
const DEFAULT_SLOTS: Required<Slots> = {
  active: 24,
  reserve: 6,
  ir: 12,
  minors: 12,
};

function numStr(v: number | undefined, fallback: number): string {
  return (v ?? fallback).toString();
}
function toNum(s: string): number {
  const n = Number(s.trim());
  return Number.isFinite(n) ? n : 0;
}
function toList(s: string): string[] {
  return s.split(",").map((t) => t.trim()).filter(Boolean);
}

const inputCls =
  "w-full px-3 py-2 rounded-xl border border-gray-200 bg-gray-50 text-sm outline-none focus:border-gray-400";
const labelCls = "text-xs font-medium text-gray-500 uppercase tracking-wide";

export function LeagueRulesEditor({ leagueId }: { leagueId: string }) {
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [sport, setSport] = useState("MLB");
  const [rawRules, setRawRules] = useState<Rules>({});

  const [leagueSize, setLeagueSize] = useState("");
  const [inSeasonCap, setInSeasonCap] = useState("");
  const [offseasonCap, setOffseasonCap] = useState("");
  const [hitting, setHitting] = useState("");
  const [pitching, setPitching] = useState("");
  const [isContract, setIsContract] = useState(true);
  const [option, setOption] = useState("");
  const [extend, setExtend] = useState("");
  const [floor, setFloor] = useState("");
  const [capMax, setCapMax] = useState("");
  const [slotsActive, setSlotsActive] = useState("");
  const [slotsReserve, setSlotsReserve] = useState("");
  const [slotsIr, setSlotsIr] = useState("");
  const [slotsMinors, setSlotsMinors] = useState("");

  useEffect(() => {
    if (!leagueId) return;
    let active = true;
    (async () => {
      const { data } = await supabase
        .from("leagues")
        .select("rules, sport")
        .eq("id", leagueId)
        .single();
      if (!active) return;
      const r: Rules = (data?.rules as Rules) ?? {};
      const sp = (data?.sport as string) ?? r.sport ?? "MLB";
      setSport(sp);
      setRawRules(r);
      setLeagueSize(numStr(r.league_size, 10));
      setInSeasonCap(numStr(r.in_season_cap, 450));
      setOffseasonCap(numStr(r.offseason_cap, 335));
      const defH = sp === "MLB" ? DEFAULT_HITTING : [];
      const defP = sp === "MLB" ? DEFAULT_PITCHING : [];
      setHitting((r.scoring?.hitting ?? defH).join(", "));
      setPitching((r.scoring?.pitching ?? defP).join(", "));
      // Contract object present -> on; explicitly null -> off; missing -> default by sport.
      const c = r.contract;
      const on = c ? true : c === null ? false : sp === "MLB";
      setIsContract(on);
      const cc = c ?? DEFAULT_CONTRACT;
      setOption(numStr(cc.option_raise, DEFAULT_CONTRACT.option_raise));
      setExtend(numStr(cc.extend_raise, DEFAULT_CONTRACT.extend_raise));
      setFloor(numStr(cc.extend_floor, DEFAULT_CONTRACT.extend_floor));
      setCapMax(numStr(cc.extend_cap, DEFAULT_CONTRACT.extend_cap));
      const sl = r.slots ?? DEFAULT_SLOTS;
      setSlotsActive(numStr(sl.active, DEFAULT_SLOTS.active));
      setSlotsReserve(numStr(sl.reserve, DEFAULT_SLOTS.reserve));
      setSlotsIr(numStr(sl.ir, DEFAULT_SLOTS.ir));
      setSlotsMinors(numStr(sl.minors, DEFAULT_SLOTS.minors));
      setLoaded(true);
    })();
    return () => {
      active = false;
    };
  }, [leagueId]);

  async function save() {
    setSaving(true);
    setErr(null);
    setSaved(false);
    const rules: Rules = {
      sport,
      league_size: toNum(leagueSize),
      in_season_cap: toNum(inSeasonCap),
      offseason_cap: toNum(offseasonCap),
      scoring: { hitting: toList(hitting), pitching: toList(pitching) },
      contract: isContract
        ? {
            option_raise: toNum(option),
            extend_raise: toNum(extend),
            extend_floor: toNum(floor),
            extend_cap: toNum(capMax),
          }
        : null,
      slots: {
        active: toNum(slotsActive),
        reserve: toNum(slotsReserve),
        ir: toNum(slotsIr),
        minors: toNum(slotsMinors),
      },
    };
    const { error } = await supabase
      .from("leagues")
      .update({ rules })
      .eq("id", leagueId);
    setSaving(false);
    if (error) {
      setErr(error.message);
    } else {
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    }
  }

  if (!loaded) {
    return (
      <div className="bg-gray-50 border rounded-2xl p-6 shadow-sm text-sm text-gray-400 animate-pulse">
        Loading league rules...
      </div>
    );
  }

  // Football: a read-only summary of what Sleeper gives us (points-based — no
  // categories, caps, or contracts to hand-edit).
  if (sport === "NFL") {
    const fmt = PPR_LABEL[rawRules.scoring_format ?? "half_ppr"] ?? "0.5 PPR";
    const sf = rawRules.superflex ? "Superflex" : "Single-QB";
    const positions = rawRules.roster_positions ?? [];
    const bench = positions.filter((p) => p === "BN").length;

    const rows: [string, string][] = [
      ["Scoring", `${fmt} · ${sf}`],
      ["League size", `${rawRules.league_size ?? "?"} teams`],
    ];
    if (positions.length) rows.push(["Starting lineup", lineupSummary(positions)]);
    if (bench) rows.push(["Bench", `${bench} spots`]);
    if (rawRules.taxi_slots) {
      rows.push([
        "Taxi squad",
        `${rawRules.taxi_slots} slots${rawRules.taxi_years ? ` · up to ${rawRules.taxi_years} yrs` : ""}`,
      ]);
    }
    rows.push(["Rookie draft", `${rawRules.draft_rounds ?? 4} rounds`]);

    return (
      <div className="bg-gray-50 border rounded-2xl p-6 shadow-sm space-y-4">
        <p className="text-sm text-gray-400 leading-relaxed">
          Auto-detected from Sleeper on each sync. Football is points-based — there are no scoring
          categories, salary cap, or contracts to set.
        </p>
        <div>
          {rows.map(([label, value]) => (
            <div
              key={label}
              className="flex items-baseline justify-between gap-3 py-1.5 border-b border-gray-50 last:border-0"
            >
              <span className="text-xs font-medium uppercase tracking-wide text-gray-400">{label}</span>
              <span className="text-sm text-gray-800 text-right">{value}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="bg-gray-50 border rounded-2xl p-6 shadow-sm space-y-6">
      <p className="text-sm text-gray-400 leading-relaxed">
        These drive the AI trade advisor&apos;s understanding of your league. Caps and size
        are auto-filled from Fantrax on each sync; categories and contract rules are yours to
        set.
      </p>

      <div className="grid grid-cols-3 gap-3">
        <div className="space-y-2">
          <label className={labelCls}>League size</label>
          <input className={inputCls} value={leagueSize} onChange={(e) => setLeagueSize(e.target.value)} inputMode="numeric" />
        </div>
        <div className="space-y-2">
          <label className={labelCls}>In-season cap</label>
          <input className={inputCls} value={inSeasonCap} onChange={(e) => setInSeasonCap(e.target.value)} inputMode="numeric" />
        </div>
        <div className="space-y-2">
          <label className={labelCls}>Offseason cap</label>
          <input className={inputCls} value={offseasonCap} onChange={(e) => setOffseasonCap(e.target.value)} inputMode="numeric" />
        </div>
      </div>

      <div className="space-y-2">
        <label className={labelCls}>Hitting categories</label>
        <input className={inputCls} value={hitting} onChange={(e) => setHitting(e.target.value)} placeholder="R, HR, RBI, SB, OBP" />
      </div>
      <div className="space-y-2">
        <label className={labelCls}>Pitching categories</label>
        <input className={inputCls} value={pitching} onChange={(e) => setPitching(e.target.value)} placeholder="QS, SV, K, ERA, WHIP" />
      </div>

      <div className="space-y-3 border-t border-gray-100 pt-4">
        <span className={labelCls}>Roster slots</span>
        <div className="grid grid-cols-4 gap-3">
          <div className="space-y-2">
            <label className={labelCls}>Active</label>
            <input className={inputCls} value={slotsActive} onChange={(e) => setSlotsActive(e.target.value)} inputMode="numeric" />
          </div>
          <div className="space-y-2">
            <label className={labelCls}>Reserve</label>
            <input className={inputCls} value={slotsReserve} onChange={(e) => setSlotsReserve(e.target.value)} inputMode="numeric" />
          </div>
          <div className="space-y-2">
            <label className={labelCls}>IR</label>
            <input className={inputCls} value={slotsIr} onChange={(e) => setSlotsIr(e.target.value)} inputMode="numeric" />
          </div>
          <div className="space-y-2">
            <label className={labelCls}>Minors</label>
            <input className={inputCls} value={slotsMinors} onChange={(e) => setSlotsMinors(e.target.value)} inputMode="numeric" />
          </div>
        </div>
        <p className="text-xs text-gray-400">
          Active, reserve, and IL salaries count against the in-season cap; minors don&apos;t.
        </p>
      </div>

      <div className="space-y-3 border-t border-gray-100 pt-4">
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input type="checkbox" checked={isContract} onChange={(e) => setIsContract(e.target.checked)} />
          Contract league (dynasty salary trajectory)
        </label>
        {isContract && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div className="space-y-2">
                <label className={labelCls}>Option raise</label>
                <input className={inputCls} value={option} onChange={(e) => setOption(e.target.value)} inputMode="numeric" />
              </div>
              <div className="space-y-2">
                <label className={labelCls}>Extend raise</label>
                <input className={inputCls} value={extend} onChange={(e) => setExtend(e.target.value)} inputMode="numeric" />
              </div>
              <div className="space-y-2">
                <label className={labelCls}>Extend floor</label>
                <input className={inputCls} value={floor} onChange={(e) => setFloor(e.target.value)} inputMode="numeric" />
              </div>
              <div className="space-y-2">
                <label className={labelCls}>Max salary</label>
                <input className={inputCls} value={capMax} onChange={(e) => setCapMax(e.target.value)} inputMode="numeric" />
              </div>
            </div>
            <p className="text-xs text-gray-400">
              Salary is flat for years 1&ndash;2; the option/extend decision comes after year 2.
              Extending an under-floor salary sets it to exactly the floor.
            </p>
          </>
        )}
      </div>

      <div className="flex items-center justify-end gap-3 pt-2">
        {err && <span className="text-xs text-red-500">{err}</span>}
        {saved && <span className="text-xs text-green-400">Saved</span>}
        <button
          onClick={save}
          disabled={saving}
          className="px-5 py-2 rounded-xl bg-violet-600 text-white text-sm font-medium disabled:opacity-30 disabled:cursor-not-allowed transition"
        >
          {saving ? "Saving..." : "Save"}
        </button>
      </div>
    </div>
  );
}
