"use client";

import { useEffect, useState } from "react";
import { supabase } from "../lib/supabaseClient";

type WidgetData = { content: string; updated_at: string };

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
                ? "font-semibold text-gray-900 mt-3 mb-1"
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

export function WaiverWidget({
  leagueId,
  myTeamId,
}: {
  leagueId: string;
  myTeamId: string;
}) {
  const [data, setData] = useState<WidgetData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

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
      setExpanded(false);
    } catch (e: any) {
      setError(e?.message ?? "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchData();
  }, [leagueId, myTeamId]);

  return (
    <div className="bg-white border rounded-2xl p-6 shadow-sm space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Waiver Spotlight</h2>
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

      {loading && !data && (
        <div className="space-y-2 animate-pulse">
          {[...Array(8)].map((_, i) => (
            <div key={i} className="h-4 bg-gray-100 rounded" style={{ width: `${65 + (i % 3) * 10}%` }} />
          ))}
        </div>
      )}

      {error && (
        <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-xl p-3">
          {error}{" "}
          <button onClick={() => fetchData()} className="underline">
            Retry
          </button>
        </div>
      )}

      {data && !loading && (
        <>
          <div className={`relative ${expanded ? "" : "max-h-48 overflow-hidden"}`}>
            <ContentRenderer text={data.content} />
            {!expanded && (
              <div className="absolute bottom-0 left-0 right-0 h-12 bg-gradient-to-t from-white to-transparent" />
            )}
          </div>
          <button
            onClick={() => setExpanded((e) => !e)}
            className="px-3 py-1.5 rounded-xl text-xs border border-gray-200 hover:border-gray-300 transition"
          >
            {expanded ? "Show less" : "Show more"}
          </button>
        </>
      )}
    </div>
  );
}
