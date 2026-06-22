"use client";

import { useEffect, useMemo, useState } from "react";
import type { AnalyzeResult, RosterRow } from "../lib/types";
import { isCapCounting, isMinors, isPitcher, money, rowKey } from "../lib/rosterUtils";
import { useRosterFilterSort } from "../useRosterFilterSort";

export function CapReliefTool({ data }: { data: AnalyzeResult }) {
  const roster = data.roster ?? [];

  const [tab, setTab] = useState<"hitting" | "pitching" | "all">("all");
  const [selectedCuts, setSelectedCuts] = useState<Record<string, boolean>>({});

  useEffect(() => {
    setSelectedCuts({});
    setTab("all");
  }, [data]);

  const capRemaining = Number(data.cap?.remaining ?? 0);

  const capRoster = useMemo(
    () => roster.filter((r) => isCapCounting(r.status)),
    [roster]
  );

  const majors = useMemo(
    () => roster.filter((r) => !isMinors(r.status)),
    [roster]
  );

  const majorsHitting = useMemo(
    () => majors.filter((r) => !isPitcher(r.eligible)),
    [majors]
  );

  const majorsPitching = useMemo(
    () => majors.filter((r) => isPitcher(r.eligible)),
    [majors]
  );

  const allFS = useRosterFilterSort(capRoster);
  const hitFS = useRosterFilterSort(majorsHitting.filter((r) => isCapCounting(r.status)));
  const pitFS = useRosterFilterSort(majorsPitching.filter((r) => isCapCounting(r.status)));

  const activeFS = tab === "all" ? allFS : tab === "hitting" ? hitFS : pitFS;

  const selectedSavings = useMemo(() => {
    const lookup = new Map<string, number>();
    for (const r of roster) lookup.set(rowKey(r), Number(r.salary ?? 0));

    return Object.entries(selectedCuts).reduce((sum, [k, v]) => {
      if (!v) return sum;
      return sum + (lookup.get(k) ?? 0);
    }, 0);
  }, [selectedCuts, roster]);

  const capRemainingIfCut = capRemaining + selectedSavings;

  function toggleSelected(row: RosterRow) {
    if (!isCapCounting(row.status)) return;
    const k = rowKey(row);
    setSelectedCuts((prev) => ({ ...prev, [k]: !prev[k] }));
  }

  function selectVisible(rows: RosterRow[]) {
    setSelectedCuts((prev) => {
      const next = { ...prev };
      for (const r of rows) {
        if (!isCapCounting(r.status)) continue;
        next[rowKey(r)] = true;
      }
      return next;
    });
  }

  function clearVisible(rows: RosterRow[]) {
    setSelectedCuts((prev) => {
      const next = { ...prev };
      for (const r of rows) delete next[rowKey(r)];
      return next;
    });
  }

  function clearAll() {
    setSelectedCuts({});
  }

  return (
    <div className="space-y-6">
      {/* Summary */}
      <div className="bg-white border rounded-2xl p-6 shadow-sm">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold">Cap Relief</h1>
            <p className="text-sm text-gray-700">
              Select Act/Res players as cuts and see live cap impact.
            </p>
          </div>

          <button
            type="button"
            onClick={clearAll}
            className="px-3 py-2 rounded-xl text-sm border border-gray-200 bg-white hover:border-gray-300"
          >
            Clear all
          </button>
        </div>

        <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="border rounded-2xl p-4">
            <div className="text-sm text-gray-600">Selected Salary</div>
            <div className="text-2xl font-semibold">{money(selectedSavings)}</div>
          </div>

          <div className="border rounded-2xl p-4">
            <div className="text-sm text-gray-600">Cap Remaining Now</div>
            <div className={`text-2xl font-semibold ${capRemaining < 0 ? "text-red-600" : "text-green-600"}`}>
              {money(capRemaining)}
            </div>
          </div>

          <div className="border rounded-2xl p-4">
            <div className="text-sm text-gray-600">Cap Remaining If Cut</div>
            <div className={`text-2xl font-semibold ${capRemainingIfCut < 0 ? "text-red-600" : "text-green-600"}`}>
              {money(capRemainingIfCut)}
            </div>
          </div>
        </div>
      </div>

      {/* Controls */}
      <div className="bg-white border rounded-2xl p-6 shadow-sm space-y-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex gap-2">
            {(["all", "hitting", "pitching"] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-3 py-1.5 rounded-xl text-sm border transition ${
                  tab === t
                    ? "bg-indigo-600 text-white border-indigo-600"
                    : "bg-white text-gray-700 border-gray-200 hover:border-gray-300"
                }`}
              >
                {t}
              </button>
            ))}
          </div>

          <div className="flex flex-col gap-2 md:flex-row md:items-center">
            <input
              value={activeFS.query}
              onChange={(e) => activeFS.setQuery(e.target.value)}
              placeholder="Search player..."
              className="w-full md:w-64 px-3 py-2 rounded-xl border border-gray-200 bg-white text-sm outline-none focus:border-gray-400"
            />

            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => selectVisible(activeFS.rows)}
                className="px-3 py-2 rounded-xl text-sm border border-gray-200 bg-white hover:border-gray-300"
              >
                Select visible
              </button>
              <button
                type="button"
                onClick={() => clearVisible(activeFS.rows)}
                className="px-3 py-2 rounded-xl text-sm border border-gray-200 bg-white hover:border-gray-300"
              >
                Clear visible
              </button>
            </div>
          </div>
        </div>

        {/* Table */}
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="border-b text-left text-gray-600">
              <tr>
                <th className="py-2 pr-4 w-10">Cut</th>
                <th className="py-2 pr-6">Player</th>
                <th className="py-2 pr-6">Team</th>
                <th className="py-2 pr-6">Eligible</th>
                <th className="py-2 pr-6">Status</th>
                <th className="py-2 pr-6">Contract</th>
                <th className="py-2 pr-6">Salary</th>
              </tr>
            </thead>

            <tbody>
              {activeFS.rows.map((p, i) => {
                const k = rowKey(p);
                const checked = !!selectedCuts[k];
                return (
                  <tr key={`${k}__${i}`} className={`border-b last:border-0 ${checked ? "bg-yellow-50" : ""}`}>
                    <td className="py-2 pr-4">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleSelected(p)}
                        className="h-4 w-4"
                      />
                    </td>
                    <td className="py-2 pr-6 font-medium">{p.player ?? "—"}</td>
                    <td className="py-2 pr-6">{p.team ?? "—"}</td>
                    <td className="py-2 pr-6 whitespace-nowrap">{p.eligible ?? "—"}</td>
                    <td className="py-2 pr-6">{p.status ?? "—"}</td>
                    <td className="py-2 pr-6">{p.contract ?? "—"}</td>
                    <td className="py-2 pr-6">{money(Number(p.salary))}</td>
                  </tr>
                );
              })}

              {activeFS.rows.length === 0 && (
                <tr>
                  <td colSpan={7} className="py-4 text-gray-600">
                    No players found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="text-xs text-gray-600">
          Only <span className="font-medium">Act</span> /{" "}
          <span className="font-medium">Res</span> are included here.
        </div>
      </div>
    </div>
  );
}