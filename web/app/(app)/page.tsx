"use client";

import { useEffect, useState } from "react";
import { supabase } from "../lib/supabaseClient";
import { useLeague } from "../lib/useLeague";
import { readCache, writeCache } from "../lib/clientCache";
import { StatCard } from "../components/StatCard";
import { StartSitPanel } from "../components/StartSitPanel";
import { CategoryRanksWidget } from "../components/CategoryRanksWidget";
import { InjuryTicker } from "../components/InjuryTicker";
import { FootballDashboard } from "../components/FootballDashboard";
import type { Alert } from "../components/StartSitPanel";

type Record = { wins: number | null; losses: number | null; ties: number };
type RosterSummary = { capUsed: number; capLimit: number; ilPlayers: string[] };
type Standings = { wins: number | null; losses: number | null; ties: number | null };
type CachedRanks = { content: { [k: string]: number }; updated_at: string } | null;
type Summary = { standings: Standings | null; category_ranks: CachedRanks; start_sit: unknown };

export default function DashboardPage() {
  const { leagueId, sport } = useLeague();
  const isNFL = sport === "NFL";
  const [myTeamId, setMyTeamId] = useState("");
  const [summary, setSummary] = useState<Summary | null>(null);
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
    const cacheKey = `dynastyos:roster-summary:${leagueId}:${myTeamId}`;
    setRosterSummary(readCache<RosterSummary>(cacheKey)); // instant paint, then revalidate
    supabase
      .from("rosters")
      .select("roster_items,salary_cap")
      .eq("league_id", leagueId)
      .eq("fantrax_team_id", myTeamId)
      .single()
      .then(async ({ data }) => {
        if (!data) return;
        const items: any[] = data.roster_items ?? [];
        const capItems = items.filter((i) =>
          ["ACTIVE", "RESERVE", "INJURED_RESERVE"].includes(i.status?.toUpperCase() ?? "")
        );
        const capUsed = capItems.reduce((sum: number, i: any) => sum + (i.salary ?? 0), 0);

        const ilItems = items.filter((i) => i.status?.toUpperCase() === "INJURED_RESERVE");
        const ilIds = ilItems.map((i) => i.id).filter(Boolean);

        // Resolve names from player_id_map; fall back to roster item's own name field
        const nameMap: { [key: string]: string } = {};
        if (ilIds.length > 0) {
          const { data: mapped } = await supabase
            .from("player_id_map")
            .select("fantrax_id,full_name")
            .in("fantrax_id", ilIds);
          for (const row of mapped ?? []) {
            if (row.full_name) nameMap[row.fantrax_id] = row.full_name;
          }
        }

        const ilPlayers = ilItems
          .map((i) => nameMap[i.id] || i.name || "")
          .filter(Boolean);

        const summary = { capUsed, capLimit: data.salary_cap ?? 450, ilPlayers };
        setRosterSummary(summary);
        writeCache(cacheKey, summary);
      });
  }, [leagueId, myTeamId]);

  // One call for standings + cached widget contents (instant paint, then revalidate)
  useEffect(() => {
    if (!leagueId || !myTeamId) { setSummary(null); return; }
    const cacheKey = `dynastyos:summary:${leagueId}:${myTeamId}`;
    setSummary(readCache<Summary>(cacheKey));
    setRecordLoading(true);
    supabase.auth.getSession().then(async ({ data: sessionData }) => {
      const token = sessionData.session?.access_token;
      try {
        const res = await fetch(
          `/api/dashboard/summary?league_id=${leagueId}&my_team_id=${myTeamId}`,
          { headers: token ? { Authorization: `Bearer ${token}` } : {} }
        );
        if (res.ok) {
          const json = (await res.json()) as Summary;
          setSummary(json);
          writeCache(cacheKey, json);
        }
      } catch {}
      finally { setRecordLoading(false); }
    });
  }, [leagueId, myTeamId]);

  const record: Record | null = summary?.standings
    ? {
        wins: summary.standings.wins,
        losses: summary.standings.losses,
        ties: summary.standings.ties ?? 0,
      }
    : null;
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

      {leagueId && myTeamId && isNFL && (
        <FootballDashboard leagueId={leagueId} myTeamId={myTeamId} />
      )}

      {leagueId && myTeamId && !isNFL && (
        <>
          {/* Stat cards */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard
              label="Record"
              value={recordStr}
              loading={recordLoading && !record}
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
            <div className="flex flex-col gap-4">
              <StartSitPanel
                leagueId={leagueId}
                myTeamId={myTeamId}
                onAlertsChange={setAlerts}
              />
              <InjuryTicker alerts={alerts} />
            </div>
            <CategoryRanksWidget
              leagueId={leagueId}
              myTeamId={myTeamId}
              initialRanks={summary?.category_ranks?.content}
              initialUpdatedAt={summary?.category_ranks?.updated_at}
            />
          </div>
        </>
      )}
    </main>
  );
}
