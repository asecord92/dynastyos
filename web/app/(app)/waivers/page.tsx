"use client";

import { useEffect, useState } from "react";
import { supabase } from "../../lib/supabaseClient";
import { useLeague } from "../../lib/useLeague";
import { AddDropPanel } from "../../components/AddDropPanel";

type WaiverData = { content: string; updated_at: string };

function timeAgo(iso: string): string {
  const seconds = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function ContentRenderer({ text }: { text: string }) {
  return (
    <div className="space-y-1">
      {text.split("\n").map((line, i) => {
        const parts = line.split(/\*\*(.*?)\*\*/g);
        const isHeading = line.startsWith("**") && line.endsWith("**");
        return (
          <p
            key={i}
            className={
              isHeading
                ? "font-semibold text-gray-900 mt-4 mb-1"
                : line.trim() === ""
                ? "h-2"
                : "text-sm text-gray-700 leading-relaxed"
            }
          >
            {parts.map((part, j) =>
              j % 2 === 1 ? <strong key={j}>{part}</strong> : part
            )}
          </p>
        );
      })}
    </div>
  );
}

export default function WaiversPage() {
  const { leagueId, sport } = useLeague();
  const [myTeamId, setMyTeamId] = useState("");
  const [data, setData] = useState<WaiverData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!leagueId) { setMyTeamId(""); return; }
    supabase
      .from("leagues")
      .select("fantrax_team_id")
      .eq("id", leagueId)
      .single()
      .then(({ data }) => setMyTeamId(data?.fantrax_team_id ?? ""));
  }, [leagueId]);

  async function fetchData(force = false) {
    if (!leagueId || !myTeamId) return;
    setLoading(true);
    setError(null);
    try {
      const { data: sessionData } = await supabase.auth.getSession();
      const accessToken = sessionData.session?.access_token;
      const res = await fetch("/api/dashboard/waiver", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
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
    if (leagueId && myTeamId) fetchData();
  }, [leagueId, myTeamId]);

  return (
    <main className="space-y-6">
      <h1 className="text-3xl font-semibold">Waiver Wire</h1>

      {!leagueId && (
        <div className="text-sm text-amber-300 bg-amber-50 border border-amber-500/30 rounded-xl p-4">
          Select a league from the nav to load waiver recommendations.
        </div>
      )}

      {leagueId && !myTeamId && (
        <div className="text-sm text-gray-500 bg-gray-50 border rounded-2xl p-6 shadow-sm">
          No team found for this league. Sync your league in Settings first.
        </div>
      )}

      {leagueId && myTeamId && (
        <div className="bg-gray-50 border rounded-2xl p-6 shadow-sm space-y-4">
          {/* Header */}
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">Recommendations</h2>
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
            <div className="space-y-2 animate-pulse">
              {[...Array(8)].map((_, i) => (
                <div
                  key={i}
                  className="h-4 bg-gray-100 rounded"
                  style={{ width: `${65 + (i % 3) * 10}%` }}
                />
              ))}
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="text-sm text-red-300 bg-red-50 border border-red-500/30 rounded-xl p-3">
              {error}{" "}
              <button onClick={() => fetchData()} className="underline">
                Retry
              </button>
            </div>
          )}

          {/* Empty state */}
          {!loading && !error && !data && (
            <p className="text-sm text-gray-400">
              No waiver data yet — click Refresh to generate recommendations.
            </p>
          )}

          {/* Content */}
          {data && !loading && <ContentRenderer text={data.content} />}
        </div>
      )}

      {/* Add/Drop analyzer — MLB only for now (NFL support to follow). */}
      {leagueId && myTeamId && sport !== "NFL" && (
        <AddDropPanel leagueId={leagueId} myTeamId={myTeamId} />
      )}
    </main>
  );
}
