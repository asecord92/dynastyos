"use client";

import { useDashboardWidget } from "../lib/useDashboardWidget";

type MinorPlayer = {
  name: string;
  position: string;
  level: string | null;
  stat_line: string;
  trend: "up" | "down" | "steady";
};

type MinorsData = { players: MinorPlayer[] };
type MinorsResponse = { content: MinorsData; updated_at: string };

function timeAgo(iso: string): string {
  const seconds = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

const trendStyle: Record<string, { glyph: string; className: string }> = {
  up: { glyph: "▲", className: "text-green-600" },
  down: { glyph: "▼", className: "text-red-600" },
  steady: { glyph: "–", className: "text-gray-400" },
};

export function MinorsPanel({
  leagueId,
  myTeamId,
}: {
  leagueId: string;
  myTeamId: string;
}) {
  const { data, loading, error, refresh } = useDashboardWidget<MinorsResponse>(
    "minors",
    leagueId,
    myTeamId
  );

  const players = data?.content?.players ?? [];

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="flex items-center justify-end gap-3">
        {data?.updated_at && (
          <span className="text-xs text-gray-400">Updated {timeAgo(data.updated_at)}</span>
        )}
        <button
          onClick={() => refresh(true)}
          disabled={loading}
          className="px-3 py-1.5 rounded-xl text-xs border border-gray-200 hover:border-gray-300 disabled:opacity-40 transition"
        >
          {loading ? "Loading..." : "Refresh"}
        </button>
      </div>

      {/* Loading skeleton */}
      {loading && !data && (
        <div className="space-y-3 animate-pulse">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="flex items-center gap-3">
              <div className="h-4 bg-gray-100 rounded flex-1" />
              <div className="h-4 w-6 bg-gray-100 rounded" />
            </div>
          ))}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-xl p-3">
          {error}{" "}
          <button onClick={() => refresh()} className="underline">
            Retry
          </button>
        </div>
      )}

      {/* Player rows */}
      {!loading && players.length > 0 && (
        <div className="divide-y divide-gray-50">
          {players.map((p, i) => {
            const t = trendStyle[p.trend] ?? trendStyle.steady;
            return (
              <div key={i} className="py-2.5 flex items-start gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium text-gray-900">{p.name}</span>
                    {p.position && (
                      <span className="text-xs text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">
                        {p.position}
                      </span>
                    )}
                    {p.level && (
                      <span className="text-xs text-indigo-700 bg-indigo-50 px-1.5 py-0.5 rounded">
                        {p.level}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-400 mt-0.5 leading-relaxed">{p.stat_line}</p>
                </div>
                <span
                  className={`shrink-0 text-sm font-semibold ${t.className}`}
                  title={`Trending ${p.trend}`}
                >
                  {t.glyph}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && data && players.length === 0 && (
        <p className="text-sm text-gray-400">No minor leaguers on your roster.</p>
      )}
    </div>
  );
}
