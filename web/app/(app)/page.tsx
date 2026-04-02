"use client";

import { useEffect, useState } from "react";
import { supabase } from "../lib/supabaseClient";
import { useLeague } from "../lib/useLeague";
import { NewsWidget } from "../components/NewsWidget";
import { StartSitWidget } from "../components/StartSitWidget";
import { WaiverWidget } from "../components/WaiverWidget";

export default function DashboardPage() {
  const { leagueId } = useLeague();
  const [myTeamId, setMyTeamId] = useState("");

  useEffect(() => {
    if (!leagueId) { setMyTeamId(""); return; }
    supabase
      .from("leagues")
      .select("fantrax_team_id")
      .eq("id", leagueId)
      .single()
      .then(({ data }) => {
        setMyTeamId(data?.fantrax_team_id ?? "");
      });
  }, [leagueId]);

  return (
    <main className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-3xl font-semibold">Dashboard</h1>
        <p className="text-gray-700">
          AI-powered insights for your dynasty team, updated every 4 hours.
        </p>
      </header>

      {!leagueId && (
        <div className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-xl p-4">
          Select a league from the nav to load your dashboard.
        </div>
      )}

      {leagueId && !myTeamId && (
        <div className="text-sm text-gray-500 bg-white border rounded-2xl p-6 shadow-sm">
          No team found for this league. Sync your league in Settings first.
        </div>
      )}

      {leagueId && myTeamId && (
        <>
          <NewsWidget leagueId={leagueId} myTeamId={myTeamId} />

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <StartSitWidget leagueId={leagueId} myTeamId={myTeamId} />
            <WaiverWidget leagueId={leagueId} myTeamId={myTeamId} />
          </div>
        </>
      )}
    </main>
  );
}
