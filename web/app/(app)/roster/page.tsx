"use client";

import { CapPlanner } from "../../components/CapPlanner";
import { useSnapshot } from "../../lib/useSnapshot";
import { useLeagueRules } from "../../lib/useLeagueRules";
import { money } from "../../lib/rosterUtils";

export default function CapPlannerPage() {
  const { data, loading, leagueId } = useSnapshot();
  const rules = useLeagueRules(leagueId);

  return (
    <main className="space-y-8">
      <header className="space-y-1">
        <h1 className="text-3xl font-semibold">Cap Planner</h1>
        <p className="text-gray-700">
          Your roster through the contract rules — this season&apos;s cap, next
          season&apos;s commitments, and your auction budget.
        </p>
      </header>

      {!leagueId && (
        <div className="text-sm text-amber-300 bg-amber-50 border border-amber-500/30 rounded-xl p-4">
          Select a league from the nav to load your roster.
        </div>
      )}

      {loading && <div className="text-sm text-gray-500">Loading latest snapshot...</div>}

      {!loading && leagueId && !data && (
        <div className="text-sm text-gray-500 bg-gray-50 border rounded-2xl p-6 shadow-sm">
          No snapshot found for this league yet. Go to Settings to connect Fantrax or upload a CSV.
        </div>
      )}

      {data && rules && rules.contract && <CapPlanner data={data} rules={rules} />}

      {data && rules && !rules.contract && (
        <div className="bg-gray-50 border rounded-2xl p-6 shadow-sm space-y-4">
          <p className="text-sm text-gray-500">
            This league has no contract rules, so there&apos;s nothing to plan — here&apos;s the roster.
          </p>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="border-b text-left text-gray-600">
                <tr>
                  <th className="py-2 pr-6">Player</th>
                  <th className="py-2 pr-6">Team</th>
                  <th className="py-2 pr-6">Eligible</th>
                  <th className="py-2 pr-6">Status</th>
                  <th className="py-2 pr-6">Salary</th>
                </tr>
              </thead>
              <tbody>
                {(data.roster ?? []).map((p, i) => (
                  <tr key={i} className="border-b last:border-0">
                    <td className="py-2 pr-6 font-medium">{p.player ?? "—"}</td>
                    <td className="py-2 pr-6">{p.team ?? "—"}</td>
                    <td className="py-2 pr-6 whitespace-nowrap">{p.eligible ?? "—"}</td>
                    <td className="py-2 pr-6">{p.status ?? "—"}</td>
                    <td className="py-2 pr-6">{money(Number(p.salary ?? 0))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </main>
  );
}
