"use client";

import { useState } from "react";
import { useDashboardWidget } from "../lib/useDashboardWidget";
import { Spinner } from "./ui/Spinner";
import { NeedsApiKey } from "./ui/NeedsApiKey";

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
  const [expanded, setExpanded] = useState(false);
  const { data, loading, validating, error, needsApiKey, refresh } = useDashboardWidget<WidgetData>(
    "waiver",
    leagueId,
    myTeamId,
    { onSuccess: () => setExpanded(false) }
  );

  return (
    <div className="bg-gray-50 border rounded-2xl p-6 shadow-sm space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Waiver Spotlight</h2>
        <div className="flex items-center gap-3">
          {data?.updated_at && (
            <span className="text-xs text-gray-400">
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
      </div>

      {loading && !data && (
        <div className="space-y-2 animate-pulse">
          {[...Array(8)].map((_, i) => (
            <div key={i} className="h-4 bg-gray-100 rounded" style={{ width: `${65 + (i % 3) * 10}%` }} />
          ))}
        </div>
      )}

      {needsApiKey && <NeedsApiKey feature="Waiver Spotlight" />}

      {error && !needsApiKey && (
        <div className="text-sm text-red-300 bg-red-50 border border-red-500/30 rounded-xl p-3">
          {error}{" "}
          <button onClick={() => refresh()} className="underline">
            Retry
          </button>
        </div>
      )}

      {data && !loading && (
        <>
          <div className={`relative ${expanded ? "" : "max-h-48 overflow-hidden"}`}>
            <ContentRenderer text={data.content} />
            {!expanded && (
              <div className="absolute bottom-0 left-0 right-0 h-12 bg-gradient-to-t from-gray-50 to-transparent" />
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
