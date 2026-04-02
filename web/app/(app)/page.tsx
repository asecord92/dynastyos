"use client";

import { useEffect, useState } from "react";
import { supabase } from "../lib/supabaseClient";
import { useLeague } from "../lib/useLeague";
import { StatCard } from "../components/StatCard";
import { StartSitPanel } from "../components/StartSitPanel";
import { CategoryRanksWidget } from "../components/CategoryRanksWidget";
import { InjuryTicker } from "../components/InjuryTicker";
import type { Alert } from "../components/StartSitPanel";

type Record = { wins: number | null; losses: number | null; ties: number };
type RosterSummary = { capUsed: number; capLimit: number; ilPlayers: string[] };

export default function DashboardPage() {
  const { leagueId } = useLeague();
  const [myTeamId, setMyTeamId] = useState("");
  const [record, setRecord] = useState<Record | null>(null);
  const [recordLoading, setRecordLoading] = useState(false);
  const [rosterSummary, setRosterSummary] = useState<RosterSummary | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);

  // Load team ID
  useEffect(() => {
    if (!leagueId) { setMyTeamId(""); return; }
    supabase
      .from("leagues")
      .select("fantrax_team_id")
      .eq("id", leagueId)
      .single()
      .then(({ data }) => setMyTeamId(data?.fantrax_team_id ?? ""));
  }, [leagueId]);

  // Load roster summary (cap + IL) directly from Supabase
  useEffect(() => {
    if (!leagueId || !myTeamId) { setRosterSummary(null); return; }
    supabase
      .from("rosters")
      .select("roster_items,salary_cap")
      .eq("league_id", leagueId)
      .eq("fantrax_team_id", myTeamId)
      .single()
      .then(({ data }) => {
        if (!data) return;
        const items: any[] = data.roster_items ?? [];
        const capItems = items.filter((i) =>
          ["ACTIVE", "RESERVE", "INJURED_RESERVE"].includes(i.status?.toUpperCase() ?? "")
        );
        const capUsed = capItems.reduce((sum: number, i: any) => sum + (i.salary ?? 0), 0);
        const ilPlayers = items
          .filter((i) => i.status?.toUpperCase() === "INJURED_RESERVE")
          .map((i) => i.name ?? "");
        setRosterSummary({ capUsed, capLimit: data.salary_cap ?? 450, ilPlayers });
      });
  }, [leagueId, myTeamId]);

  // Load standings from API
  useEffect(() => {
    if (!leagueId || !myTeamId) { setRecord(null); return; }
    setRecordLoading(true);
    supabase.auth.getSession().then(async ({ data: sessionData }) => {
      const token = sessionData.session?.access_token;
      try {
        const res = await fetch(
          `/api/league/standings?league_id=${leagueId}&my_team_id=${myTeamId}`,
          { headers: token ? { Authorization: `Bearer ${token}` } : {} }
        );
        if (res.ok) {
          const json = await res.json();
          setRecord({ wins: json.wins, losses: json.losses, ties: json.ties ?? 0 });
        }
      } catch {}
      finally { setRecordLoading(false); }
    });
  }, [leagueId, myTeamId]);

  const recordStr = record
    ? `${record.wins ?? "?"}–${record.losses ?? "?"}${record.ties ? `–${record.ties}` : ""}`
    : null;

  const capRemaining = rosterSummary ? rosterSummary.capLimit - rosterSummary.capUsed : null;

  return (
    <main className="space-y-6">
      <h1 className="text-3xl font-semibold">Dashboard</h1>

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
          {/* Stat cards */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard
              label="Record"
              value={recordStr}
              loading={recordLoading}
            />
            <StatCard
              label="Cap Used"
              value={rosterSummary ? `$${rosterSummary.capUsed}` : null}
              subtext={capRemaining != null ? `$${capRemaining} remaining` : undefined}
              subtextColor={capRemaining != null && capRemaining < 30 ? "amber" : "muted"}
              loading={!rosterSummary}
            />
            <StatCard
              label="Players on IL"
              value={rosterSummary ? rosterSummary.ilPlayers.length : null}
              subtext={
                rosterSummary && rosterSummary.ilPlayers.length > 0
                  ? rosterSummary.ilPlayers.slice(0, 3).join(", ")
                  : undefined
              }
              subtextColor={rosterSummary && rosterSummary.ilPlayers.length > 0 ? "red" : "muted"}
              loading={!rosterSummary}
            />
            {/* 4th card — reserved for matchup data */}
            <div className="bg-white border border-dashed border-gray-200 rounded-2xl p-5" />
          </div>

          {/* Main content: start/sit + category ranks */}
          <div className="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-6 items-start">
            <div className="flex flex-col gap-6">
              <StartSitPanel
                leagueId={leagueId}
                myTeamId={myTeamId}
                onAlertsChange={setAlerts}
              />
              <InjuryTicker alerts={alerts} />
            </div>
            <CategoryRanksWidget leagueId={leagueId} />
          </div>
        </>
      )}
    </main>
  );
}
