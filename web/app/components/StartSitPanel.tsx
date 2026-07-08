"use client";

import { useState } from "react";
import { useDashboardWidget } from "../lib/useDashboardWidget";
import { MinorsPanel } from "./MinorsPanel";
import { Spinner } from "./ui/Spinner";
import { NeedsApiKey } from "./ui/NeedsApiKey";

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
  start: "bg-green-500/15 text-green-300",
  monitor: "bg-amber-500/15 text-amber-300",
  sit: "bg-red-500/15 text-red-300",
};

export type { Alert };

export function StartSitPanel({
  leagueId,
  myTeamId,
  onAlertsChange,
  isNFL = false,
}: {
  leagueId: string;
  myTeamId: string;
  onAlertsChange?: (alerts: Alert[]) => void;
  isNFL?: boolean;
}) {
  const [showAll, setShowAll] = useState(false);
  const [tab, setTab] = useState<"startsit" | "minors">("startsit");
  const { data, loading, validating, error, needsApiKey, refresh } = useDashboardWidget<WidgetResponse>(
    "start_sit",
    leagueId,
    myTeamId,
    { onSuccess: (json) => onAlertsChange?.(json.content?.alerts ?? []) }
  );

  const tabClass = (active: boolean) =>
    `px-3 py-1.5 rounded-xl text-sm border transition ${
      active
        ? "bg-violet-600 text-white border-violet-600"
        : "bg-gray-50 text-gray-700 border-gray-200 hover:border-gray-300"
    }`;

  const recOrder: Record<string, number> = { sit: 0, monitor: 1, start: 2 };
  const allPlayers = [...(data?.content?.players ?? [])].sort(
    (a, b) => (recOrder[a.recommendation] ?? 3) - (recOrder[b.recommendation] ?? 3)
  );
  const players = showAll ? allPlayers : allPlayers.slice(0, 6);

  return (
    <div className="bg-gray-50 border rounded-2xl p-6 shadow-sm space-y-4">
      {/* Tabs */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex gap-2">
          <button onClick={() => setTab("startsit")} className={tabClass(tab === "startsit")}>
            Start / Sit
          </button>
          {!isNFL && (
            <button onClick={() => setTab("minors")} className={tabClass(tab === "minors")}>
              Minors
            </button>
          )}
        </div>
        {tab === "startsit" && (
          <div className="flex items-center gap-3 ml-auto">
            {data?.updated_at && (
              <span className="text-xs text-gray-400 whitespace-nowrap">
                Updated {timeAgo(data.updated_at)}
              </span>
            )}
            <button
              onClick={() => refresh(true)}
              disabled={validating}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs border border-gray-200 hover:border-gray-300 disabled:opacity-60 transition"
            >
              {validating && <Spinner />}
              {validating ? "Refreshing…" : "Refresh"}
            </button>
          </div>
        )}
      </div>

      {tab === "minors" && <MinorsPanel leagueId={leagueId} myTeamId={myTeamId} />}

      {/* Loading skeleton */}
      {tab === "startsit" && loading && !data && (
        <div className="space-y-3 animate-pulse">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="flex items-center gap-3">
              <div className="h-4 bg-gray-100 rounded flex-1" />
              <div className="h-6 w-16 bg-gray-100 rounded-full" />
            </div>
          ))}
        </div>
      )}

      {/* No API key (BYOK) */}
      {tab === "startsit" && needsApiKey && <NeedsApiKey feature="Start / Sit" />}

      {/* Error */}
      {tab === "startsit" && error && !needsApiKey && (
        <div className="text-sm text-red-300 bg-red-50 border border-red-500/30 rounded-xl p-3">
          {error}{" "}
          <button onClick={() => refresh()} className="underline">
            Retry
          </button>
        </div>
      )}

      {/* Player rows */}
      {tab === "startsit" && !loading && players.length > 0 && (
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
                {showAll && p.reason && (
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
      {tab === "startsit" && !loading && allPlayers.length > 6 && (
        <button
          onClick={() => setShowAll((s) => !s)}
          className="px-3 py-1.5 rounded-xl text-xs border border-gray-200 hover:border-gray-300 transition"
        >
          {showAll ? "Show less" : `Show all ${allPlayers.length} players`}
        </button>
      )}

      {/* Empty state */}
      {tab === "startsit" && !loading && !error && data && players.length === 0 && (
        <p className="text-sm text-gray-400">No recommendations yet. Try refreshing.</p>
      )}
    </div>
  );
}
