"use client";

import { useMemo, useState } from "react";
import type { AnalyzeResult, RosterRow } from "../lib/types";
import { money, rowKey } from "../lib/rosterUtils";
import {
  type Decision,
  type LeagueRules,
  type PlannedRow,
  decisionOptions,
  planRow,
  planTotals,
} from "../lib/capPlanner";

const DECISION_LABEL: Record<Decision, string> = {
  keep: "Keep",
  extend: "Extend",
  option: "Option",
  cut: "Cut",
};

function DecisionPicker({
  value,
  options,
  onChange,
}: {
  value: Decision;
  options: Decision[];
  onChange: (d: Decision) => void;
}) {
  return (
    <div className="inline-flex rounded-lg border border-gray-200 overflow-hidden">
      {options.map((d) => {
        const selected = d === value;
        const cls = selected
          ? d === "cut"
            ? "bg-red-100 text-red-800"
            : d === "option"
            ? "bg-amber-100 text-amber-800"
            : "bg-violet-600 text-white"
          : "bg-gray-50 text-gray-600 hover:text-gray-800";
        return (
          <button
            key={d}
            type="button"
            onClick={() => onChange(d)}
            className={`px-2.5 py-1.5 text-xs font-medium transition ${cls}`}
          >
            {DECISION_LABEL[d]}
          </button>
        );
      })}
    </div>
  );
}

function NextSalaryCell({ p }: { p: PlannedRow }) {
  if (p.minors) {
    return <span className="text-xs text-gray-500">no cap hit</span>;
  }
  if (p.nextSalary === 0) {
    return <span className="text-xs text-gray-500">off the books</span>;
  }
  const delta = p.nextSalary - p.salary;
  return (
    <span className="whitespace-nowrap">
      {money(p.nextSalary)}
      {delta !== 0 && (
        <span className={`ml-1.5 text-xs ${delta > 0 ? "text-amber-400" : "text-green-400"}`}>
          {delta > 0 ? `+$${delta}` : `-$${-delta}`}
        </span>
      )}
    </span>
  );
}

type Section = {
  title: string;
  note: string;
  rows: PlannedRow[];
  /** Sum shown in the section header: next-season salary for cap-counting sections. */
  showSubtotal: boolean;
};

function PlannerSection({
  section,
  onDecide,
}: {
  section: Section;
  onDecide: (key: string, d: Decision) => void;
}) {
  if (section.rows.length === 0) return null;
  const subtotal = section.rows.reduce((s, p) => s + p.nextSalary, 0);
  return (
    <div className="bg-gray-50 border rounded-2xl p-4 md:p-6 shadow-sm space-y-3">
      <div className="flex items-baseline justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{section.title}</h2>
          <p className="text-xs text-gray-500">{section.note}</p>
        </div>
        {section.showSubtotal && (
          <div className="text-right shrink-0">
            <div className="text-xs text-gray-500">next season</div>
            <div className="text-lg font-semibold">{money(subtotal)}</div>
          </div>
        )}
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="border-b text-left text-gray-600">
            <tr>
              <th className="py-2 pr-4">Player</th>
              <th className="py-2 pr-4">Pos</th>
              <th className="py-2 pr-4">Status</th>
              <th className="py-2 pr-4">Contract</th>
              <th className="py-2 pr-4">Salary</th>
              <th className="py-2 pr-4">Decision</th>
              <th className="py-2">Next Season</th>
            </tr>
          </thead>
          <tbody>
            {section.rows.map((p) => (
              <tr key={p.key} className={`border-b last:border-0 align-middle ${p.decision === "cut" ? "opacity-60" : ""}`}>
                <td className="py-2 pr-4">
                  <div className="font-medium">{p.row.player ?? "—"}</div>
                  <div className="text-xs text-gray-500">{p.row.team ?? ""}</div>
                </td>
                <td className="py-2 pr-4 whitespace-nowrap">{p.row.eligible ?? "—"}</td>
                <td className="py-2 pr-4">{p.row.status ?? "—"}</td>
                <td className="py-2 pr-4 whitespace-nowrap">{p.row.contract ?? "—"}</td>
                <td className="py-2 pr-4">{money(p.salary)}</td>
                <td className="py-2 pr-4">
                  <DecisionPicker
                    value={p.decision}
                    options={decisionOptions(p.stage)}
                    onChange={(d) => onDecide(p.key, d)}
                  />
                </td>
                <td className="py-2">
                  <NextSalaryCell p={p} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function CapPlanner({ data, rules }: { data: AnalyzeResult; rules: LeagueRules }) {
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [query, setQuery] = useState("");

  const contract = rules.contract;

  const planned = useMemo(() => {
    if (!contract) return [];
    return (data.roster ?? []).map((r: RosterRow) =>
      planRow(r, rowKey(r), decisions[rowKey(r)], contract)
    );
  }, [data, decisions, contract]);

  const totals = useMemo(() => planTotals(planned, rules), [planned, rules]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return planned;
    return planned.filter((p) => (p.row.player ?? "").toLowerCase().includes(q));
  }, [planned, query]);

  const bySalary = (a: PlannedRow, b: PlannedRow) => b.salary - a.salary;
  const sections: Section[] = [
    {
      title: "Offseason Decisions — 2nd year",
      note: "Extend, option, or cut this offseason. Extending under-$15 salaries jumps them to exactly $15.",
      rows: visible.filter((p) => p.stage === "y2" && !p.minors).sort(bySalary),
      showSubtotal: true,
    },
    {
      title: "Expiring — optioned (3rd year)",
      note: "Auto-drop to the auction pool after the season. Cut now only to free in-season cap early.",
      rows: visible.filter((p) => p.stage === "optioned" && !p.minors).sort(bySalary),
      showSubtotal: false,
    },
    {
      title: "Extended — 4th year and beyond",
      note: `+$${contract?.extend_raise ?? 4} per year, capped at $${contract?.extend_cap ?? 75}. Keep paying or cut — salary never goes down.`,
      rows: visible.filter((p) => p.stage === "extended" && !p.minors).sort(bySalary),
      showSubtotal: true,
    },
    {
      title: "First year",
      note: "Flat salary through year 2 — no decision until next offseason.",
      rows: visible.filter((p) => (p.stage === "y1" || p.stage === "unknown") && !p.minors).sort(bySalary),
      showSubtotal: true,
    },
    {
      title: "Minors — clock frozen",
      note: "No cap hit and contract years don't tick until they join the active roster.",
      rows: visible.filter((p) => p.minors).sort(bySalary),
      showSubtotal: false,
    },
  ];

  const cap = data.cap;
  const remainingNow = Number(cap?.remaining ?? 0);
  const anyCuts = totals.cutReliefNow > 0;
  const anyDecisions = Object.keys(decisions).length > 0;

  return (
    <div className="space-y-6">
      {/* Summary cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-gray-50 border rounded-2xl p-6 shadow-sm">
          <div className="text-sm text-gray-700">This Season</div>
          <div className="text-2xl font-semibold">
            {money(Number(cap?.used ?? 0))}
            <span className="text-base font-normal text-gray-500"> / {money(Number(cap?.limit ?? rules.in_season_cap))}</span>
          </div>
          <div className={`text-sm mt-1 ${remainingNow < 0 ? "text-red-400" : "text-green-400"}`}>
            {money(remainingNow)} remaining
          </div>
          {anyCuts && (
            <div className="text-xs text-gray-500 mt-1">
              {money(remainingNow + totals.cutReliefNow)} if selected cuts are made now
            </div>
          )}
        </div>

        <div className="bg-gray-50 border rounded-2xl p-6 shadow-sm">
          <div className="text-sm text-gray-700">Next Season · offseason cap {money(rules.offseason_cap)}</div>
          <div className="text-2xl font-semibold">{money(totals.committed)} committed</div>
          <div className={`text-sm mt-1 ${totals.room < 0 ? "text-red-400" : "text-green-400"}`}>
            {totals.room < 0
              ? `${money(-totals.room)} over — must shed before the draft`
              : `${money(totals.room)} under the cap`}
          </div>
          {totals.expiringRelief > 0 && (
            <div className="text-xs text-gray-500 mt-1">
              {money(totals.expiringRelief)} in optioned contracts comes off automatically
            </div>
          )}
        </div>

        <div className="bg-gray-50 border rounded-2xl p-6 shadow-sm">
          <div className="text-sm text-gray-700">Auction Day</div>
          <div className={`text-2xl font-semibold ${totals.spendable < 0 ? "text-red-400" : ""}`}>
            {money(totals.spendable)} to spend
          </div>
          <div className="text-sm text-gray-500 mt-1">
            {money(Math.max(totals.room, 0))} budget − {money(totals.minBids)} in $1 holds
          </div>
          <div className="text-xs text-gray-500 mt-1">
            {totals.openMajors} open majors + {totals.openMinors} open minors spots to fill
          </div>
        </div>
      </div>

      {/* Controls */}
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search player..."
          className="w-full md:w-64 px-3 py-2 rounded-xl border border-gray-200 bg-gray-50 text-sm outline-none focus:border-gray-400"
        />
        {anyDecisions && (
          <button
            type="button"
            onClick={() => setDecisions({})}
            className="px-3 py-2 rounded-xl text-sm border border-gray-200 bg-gray-50 hover:border-gray-300 self-start md:self-auto"
          >
            Reset decisions
          </button>
        )}
      </div>

      {sections.map((s) => (
        <PlannerSection
          key={s.title}
          section={s}
          onDecide={(key, d) => setDecisions((prev) => ({ ...prev, [key]: d }))}
        />
      ))}
    </div>
  );
}
