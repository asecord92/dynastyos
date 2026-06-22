"use client";

import { useEffect, useState } from "react";
import { supabase } from "../lib/supabaseClient";
import { readCache, writeCache } from "../lib/clientCache";
import { StatCard } from "./StatCard";
import { StartSitPanel } from "./StartSitPanel";
import { InjuryTicker } from "./InjuryTicker";
import type { Alert } from "./StartSitPanel";

type Standing = {
  team_id: string;
  team: string;
  wins: number;
  losses: number;
  ties: number;
  points_for: number;
  rank: number;
  is_me: boolean;
};
type Positional = { position: string; my_points: number; league_avg: number; rank: number };
type NFLDash = {
  record: { wins: number; losses: number; ties: number; points_for: number; rank: number; total: number } | null;
  players_out: string[];
  standings: Standing[];
  positional_strength: Positional[];
};

function posColor(rank: number, total: number): string {
  if (rank <= Math.ceil(total / 3)) return "bg-emerald-400/80";
  if (rank <= Math.ceil((2 * total) / 3)) return "bg-amber-400/70";
  return "bg-rose-400/70";
}

export function FootballDashboard({ leagueId, myTeamId }: { leagueId: string; myTeamId: string }) {
  const cacheKey = `dynastyos:nfldash:${leagueId}:${myTeamId}`;
  const [data, setData] = useState<NFLDash | null>(() => readCache<NFLDash>(cacheKey));
  const [alerts, setAlerts] = useState<Alert[]>([]);

  useEffect(() => {
    if (!leagueId || !myTeamId) return;
    // Ignore a superseded fetch: when myTeamId settles (e.g. switching leagues),
    // a stale in-flight request must not land last and overwrite good data.
    let active = true;
    setData(readCache<NFLDash>(cacheKey));
    supabase.auth.getSession().then(async ({ data: sess }) => {
      const token = sess.session?.access_token;
      try {
        const res = await fetch(
          `/api/nfl/dashboard?league_id=${leagueId}&my_team_id=${myTeamId}`,
          { headers: token ? { Authorization: `Bearer ${token}` } : {} }
        );
        if (res.ok && active) {
          const j = (await res.json()) as NFLDash;
          setData(j);
          writeCache(cacheKey, j);
        }
      } catch {}
    });
    return () => {
      active = false;
    };
  }, [leagueId, myTeamId]);

  const rec = data?.record;
  const recordStr = rec ? `${rec.wins}-${rec.losses}${rec.ties ? `-${rec.ties}` : ""}` : null;
  const total = data?.standings.length ?? 10;
  const outCount = data?.players_out.length ?? null;
  const maxPosPoints = Math.max(
    1,
    ...(data?.positional_strength.flatMap((p) => [p.my_points, p.league_avg]) ?? [1])
  );

  return (
    <>
      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Record" value={recordStr} loading={!data} />
        <StatCard
          label="Points For"
          value={rec ? `${rec.points_for}` : null}
          loading={!data}
        />
        <StatCard
          label="League Rank"
          value={rec ? `${rec.rank} / ${rec.total}` : null}
          loading={!data}
        />
        <StatCard
          label="Players Out"
          value={outCount}
          subtext={data && data.players_out.length > 0 ? data.players_out.slice(0, 3).join(", ") : undefined}
          subtextColor={data && data.players_out.length > 0 ? "red" : "muted"}
          loading={!data}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-6 items-start">
        {/* Left — Start/Sit + injury ticker */}
        <div className="flex flex-col gap-4">
          <StartSitPanel leagueId={leagueId} myTeamId={myTeamId} isNFL onAlertsChange={setAlerts} />
          <InjuryTicker alerts={alerts} />
        </div>

        {/* Right rail — positional strength + standings */}
        <div className="space-y-4">
          <div className="bg-gray-50 border rounded-2xl p-5 shadow-sm space-y-3">
            <div className="text-xs font-semibold uppercase tracking-widest text-gray-400">
              Positional Strength
            </div>
            <p className="text-[11px] text-gray-400 -mt-1">Your points by position vs league (last season)</p>
            <div className="space-y-2.5">
              {(data?.positional_strength ?? []).map((p) => (
                <div key={p.position} className="space-y-1">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-medium text-gray-600">{p.position}</span>
                    <span className="text-gray-400">
                      {p.my_points} <span className="text-gray-300">/ avg {p.league_avg}</span> · #{p.rank}
                    </span>
                  </div>
                  <div className="relative bg-gray-100 rounded-full h-3 overflow-hidden">
                    <div
                      className={`h-full rounded-full ${posColor(p.rank, total)}`}
                      style={{ width: `${Math.max((p.my_points / maxPosPoints) * 100, 4)}%` }}
                    />
                    {/* league-average tick */}
                    <div
                      className="absolute top-0 h-full w-px bg-gray-500/50"
                      style={{ left: `${(p.league_avg / maxPosPoints) * 100}%` }}
                    />
                  </div>
                </div>
              ))}
              {!data && <div className="h-24 bg-gray-50 rounded animate-pulse" />}
            </div>
          </div>

          <div className="bg-gray-50 border rounded-2xl p-5 shadow-sm space-y-3">
            <div className="text-xs font-semibold uppercase tracking-widest text-gray-400">
              Standings
            </div>
            <div className="divide-y divide-gray-50">
              {(data?.standings ?? []).map((s) => (
                <div
                  key={s.team_id}
                  className={`flex items-center justify-between py-1.5 text-sm ${
                    s.is_me ? "font-semibold text-gray-900" : "text-gray-600"
                  }`}
                >
                  <span className="truncate">
                    <span className="text-gray-400 mr-2">{s.rank}</span>
                    {s.team}
                  </span>
                  <span className="shrink-0 text-xs text-gray-400">
                    {s.wins}-{s.losses}
                    {s.ties ? `-${s.ties}` : ""} · {s.points_for} PF
                  </span>
                </div>
              ))}
              {!data && <div className="h-32 bg-gray-50 rounded animate-pulse" />}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
