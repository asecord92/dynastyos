"use client";

import type { RosterRow } from "../lib/types";
import { money } from "../lib/rosterUtils";
import type { SortKey } from "../useRosterFilterSort";

export function RosterTable({
  rows,
  sortKey,
  sortDir,
  onToggleSort,
}: {
  rows: RosterRow[];
  sortKey: SortKey;
  sortDir: "asc" | "desc";
  onToggleSort: (key: SortKey) => void;
}) {
  const SortLabel = ({ label, k }: { label: string; k: SortKey }) => {
    const active = sortKey === k;
    const arrow = active ? (sortDir === "asc" ? "▲" : "▼") : "";

    return (
      <button
        type="button"
        onClick={() => onToggleSort(k)}
        className={`inline-flex items-center gap-2 hover:underline ${
          active ? "text-gray-900" : "text-gray-600"
        }`}
      >
        {label} <span className="text-xs">{arrow}</span>
      </button>
    );
  };

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead className="border-b text-left">
          <tr>
            <th className="py-2 pr-6">
              <SortLabel label="Player" k="player" />
            </th>
            <th className="py-2 pr-6 text-gray-600">Team</th>
            <th className="py-2 pr-6 text-gray-600">Eligible</th>
            <th className="py-2 pr-6 text-gray-600">Status</th>
            <th className="py-2 pr-6">
              <SortLabel label="Contract" k="contract" />
            </th>
            <th className="py-2 pr-6">
              <SortLabel label="Salary" k="salary" />
            </th>
          </tr>
        </thead>

        <tbody>
          {rows.map((p, i) => (
            <tr key={i} className="border-b last:border-0">
              <td className="py-2 pr-6 font-medium">{p.player ?? "—"}</td>
              <td className="py-2 pr-6">{p.team ?? "—"}</td>
              <td className="py-2 pr-6 whitespace-nowrap">{p.eligible ?? "—"}</td>
              <td className="py-2 pr-6">{p.status ?? "—"}</td>
              <td className="py-2 pr-6">{p.contract ?? "—"}</td>
              <td className="py-2 pr-6">{money(Number(p.salary))}</td>
            </tr>
          ))}

          {rows.length === 0 && (
            <tr>
              <td colSpan={6} className="py-4 text-gray-600">
                No players found.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}