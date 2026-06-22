import type { DecisionItem } from "../lib/types";
import { money } from "../lib/rosterUtils";

export function DecisionQueueTable({ items }: { items: DecisionItem[] }) {
  return (
    <div className="bg-gray-50 border rounded-2xl p-6 shadow-sm">
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-xl font-semibold">Decision Queue (3rd Year)</h2>
        <span className="text-sm text-gray-700">{items.length} players</span>
      </div>

      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="border-b text-left text-gray-600">
            <tr>
              <th className="py-2 pr-6">Player</th>
              <th className="py-2 pr-6">Status</th>
              <th className="py-2 pr-6">Contract</th>
              <th className="py-2 pr-6">Salary</th>
              <th className="py-2 pr-6">Recommendation</th>
              <th className="py-2 pr-6">Why</th>
            </tr>
          </thead>

          <tbody>
            {items.map((p, i) => {
              const rec = String(p.recommendation ?? "option").toLowerCase();
              const pill =
                rec === "extend"
                  ? "bg-green-100 text-green-800 border-green-500/30"
                  : rec === "cut"
                  ? "bg-red-100 text-red-800 border-red-500/30"
                  : "bg-gray-100 text-gray-800 border-gray-200";

              return (
                <tr key={i} className="border-b last:border-0 align-top">
                  <td className="py-2 pr-6 font-medium">{p.player}</td>
                  <td className="py-2 pr-6">{p.status}</td>
                  <td className="py-2 pr-6">{p.contract}</td>
                  <td className="py-2 pr-6">{money(Number(p.salary))}</td>

                  <td className="py-2 pr-6">
                    <span
                      className={`inline-flex items-center px-2 py-1 rounded-lg border text-xs font-medium ${pill}`}
                    >
                      {rec}
                    </span>

                    {typeof p.cap_remaining_if_cut === "number" && (
                      <div className="text-xs text-gray-600 mt-1">
                        If cut → cap: {money(Number(p.cap_remaining_if_cut))}
                      </div>
                    )}
                  </td>

                  <td className="py-2 pr-6">
                    {Array.isArray(p.rationale) && p.rationale.length > 0 ? (
                      <details className="cursor-pointer">
                        <summary className="text-xs text-gray-700 hover:underline">
                          View
                        </summary>
                        <ul className="mt-2 list-disc pl-5 text-xs text-gray-700 space-y-1">
                          {p.rationale.map((r, idx) => (
                            <li key={idx}>{r}</li>
                          ))}
                        </ul>
                      </details>
                    ) : (
                      <span className="text-xs text-gray-500">—</span>
                    )}
                  </td>
                </tr>
              );
            })}

            {items.length === 0 && (
              <tr>
                <td colSpan={6} className="py-4 text-gray-700">
                  No 3rd-year contracts found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}