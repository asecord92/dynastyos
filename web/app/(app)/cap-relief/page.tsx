"use client";

import { useSnapshot } from "../../lib/useSnapshot";
import { CapReliefTool } from "../../components/CapReliefTool";

export default function CapReliefPage() {
  const { data, loading, leagueId } = useSnapshot();

  return (
    <main className="space-y-8">
      <header className="space-y-1">
        <h1 className="text-3xl font-semibold">Cap Relief</h1>
        <p className="text-gray-700">
          Focused cap tool: pick cuts and see the live cap result.
        </p>
      </header>

      {!leagueId && (
        <div className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-xl p-4">
          Select a league from the nav to load your roster.
        </div>
      )}

      {loading && (
        <div className="text-sm text-gray-500">Loading latest snapshot...</div>
      )}

      {!loading && leagueId && !data && (
        <div className="text-sm text-gray-500 bg-white border rounded-2xl p-6 shadow-sm">
          No snapshot found for this league yet. Go to Settings to upload a CSV.
        </div>
      )}

      {data && <CapReliefTool data={data} />}
    </main>
  );
}