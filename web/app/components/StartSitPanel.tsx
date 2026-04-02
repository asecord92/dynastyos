"use client";

import { useEffect, useState } from "react";
import { supabase } from "../lib/supabaseClient";

type PlayerRec = {
  name: string;
  position: string;
  team: string;
  salary: number;
  recommendation: "start" | "monitor" | "sit";
  reason: string;
};

type Alert = {
  name: string;
  status: string;
  detail: string;
};

type StartSitData = {
  players: PlayerRec[];
  alerts: Alert[];
};

type WidgetResponse = { content: StartSitData; updated_at: string };

function timeAgo(iso: string): string {
  const seconds = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

const recPill: Record<string, string> = {
  start: "bg-green-100 text-green-700",
  monitor: "bg-amber-100 text-amber-700",
  sit: "bg-red-100 text-red-600",
};

export function StartSitPanel({
  leagueId,
  myTeamId,
}: {
  leagueId: string;
  myTeamId: string;
}) {
  const [data, setData] = useState<WidgetResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function fetchData(force = false) {
    if (!leagueId || !myTeamId) return;
    setLoading(true);
    setError(null);
    try {
      const { data: sessionData } = await supabase.auth.getSession();
      const token = sessionData.session?.access_token;
      const res = await fetch("/api/dashboard/start_sit", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ league_id: leagueId, my_team_id: myTeamId, force }),
      });
      if (!res.ok) throw new Error(await res.text());
      setData(await res.json());
    } catch (e: any) {
      setError(e?.message ?? "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchData();
  }, [leagueId, myTeamId]);

  const [showAll, setShowAll] = useState(false);

  const recOrder: Record<string, number> = { sit: 0, monitor: 1, start: 2 };
  const allPlayers = [...(data?.content?.players ?? [])].sort(
    (a, b) => (recOrder[a.recommendation] ?? 3) - (recOrder[b.recommendation] ?? 3)
  );
  const players = showAll ? allPlayers : allPlayers.slice(0, 6);
  const alerts = data?.content?.alerts ?? [];

  return (
    <div className="bg-white border rounded-2xl p-6 shadow-sm space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Start / Sit</h2>
        <div className="flex items-center gap-3">
          {data?.updated_at && (
            <span className="text-xs text-gray-400">
              Updated {timeAgo(data.updated_at)}
            </span>
          )}
          <button
            onClick={() => fetchData(true)}
            disabled={loading}
            className="px-3 py-1.5 rounded-xl text-xs border border-gray-200 hover:border-gray-300 disabled:opacity-40 transition"
          >
            {loading ? "Loading..." : "Refresh"}
          </button>
        </div>
      </div>

      {/* Loading skeleton */}
      {loading && !data && (
        <div className="space-y-3 animate-pulse">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="flex items-center gap-3">
              <div className="h-4 bg-gray-100 rounded flex-1" />
              <div className="h-6 w-16 bg-gray-100 rounded-full" />
            </div>
          ))}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-xl p-3">
          {error}{" "}
          <button onClick={() => fetchData()} className="underline">
            Retry
          </button>
        </div>
      )}

      {/* Player rows */}
      {!loading && players.length > 0 && (
        <div className="divide-y divide-gray-50">
          {players.map((p, i) => (
            <div key={i} className="py-2.5 flex items-start gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-medium text-gray-900">{p.name}</span>
                  {p.position && (
                    <span className="text-xs text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">
                      {p.position}
                    </span>
                  )}
                  {p.team && (
                    <span className="text-xs text-gray-400">{p.team}</span>
                  )}
                  {p.salary != null && (
                    <span className="text-xs text-gray-400">${p.salary}</span>
                  )}
                </div>
                {p.reason && (
                  <p className="text-xs text-gray-400 mt-0.5 leading-relaxed">{p.reason}</p>
                )}
              </div>
              <span
                className={`shrink-0 text-xs font-medium px-2.5 py-1 rounded-full capitalize ${
                  recPill[p.recommendation] ?? "bg-gray-100 text-gray-600"
                }`}
              >
                {p.recommendation}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Show all toggle */}
      {!loading && allPlayers.length > 6 && (
        <button
          onClick={() => setShowAll((s) => !s)}
          className="px-3 py-1.5 rounded-xl text-xs border border-gray-200 hover:border-gray-300 transition"
        >
          {showAll ? "Show less" : `Show all ${allPlayers.length} players`}
        </button>
      )}

      {/* Injury alert banner */}
      {!loading && alerts.length > 0 && (
        <div className="border-l-4 border-orange-400 bg-amber-50 rounded-r-xl p-4 space-y-2">
          <div className="text-xs font-semibold text-amber-700 uppercase tracking-wide">
            Injury / Status Alerts
          </div>
          {alerts.map((a, i) => (
            <div key={i} className="text-xs text-gray-600">
              <span className="font-medium text-gray-800">{a.name}</span>
              {a.status && (
                <span className="ml-1.5 text-orange-600 font-medium">{a.status}</span>
              )}
              {a.detail && <span className="ml-1.5">{a.detail}</span>}
            </div>
          ))}
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && data && players.length === 0 && (
        <p className="text-sm text-gray-400">No recommendations yet. Try refreshing.</p>
      )}
    </div>
  );
}
