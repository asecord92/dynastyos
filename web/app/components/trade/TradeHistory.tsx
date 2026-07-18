"use client";

import { useCallback, useEffect, useState } from "react";
import { authedFetch, isTimeoutError } from "../../lib/useDashboardWidget";
import { timeAgo } from "../../lib/format";
import { AnalysisRenderer, verdictColor } from "./AnalysisRenderer";

type TradeHistoryPlayer = { id: string; name: string };
export type TradeHistoryRow = {
  id: string;
  created_at: string;
  offering: TradeHistoryPlayer[];
  receiving: TradeHistoryPlayer[];
  verdict: string | null;
  analysis: string;
};

/** The user's saved trade analyses — self-contained: fetches on mount. */
export function TradeHistory({ leagueId }: { leagueId: string }) {
  const [items, setItems] = useState<TradeHistoryRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  // Bumped by Retry; the effect re-runs the fetch.
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  useEffect(() => {
    if (!leagueId) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await authedFetch(
          `/api/trade/history?league_id=${leagueId}`,
          {},
          { timeoutMs: 15_000 }
        );
        if (!res.ok) throw new Error(`History unavailable (${res.status}).`);
        const json = await res.json();
        if (!cancelled) setItems(json.items ?? []);
      } catch (e: unknown) {
        // A failure must never masquerade as an empty history.
        if (!cancelled) {
          setError(
            isTimeoutError(e)
              ? "Loading your history timed out."
              : "Couldn't load your history."
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [leagueId, attempt]);

  return (
    <div className="space-y-4">
      {loading && (
        <div className="bg-gray-50 border rounded-2xl p-6 shadow-sm text-sm text-gray-400 animate-pulse">
          Loading your recent analyses…
        </div>
      )}
      {!loading && error && (
        <div className="bg-red-50 border border-red-500/30 rounded-2xl p-6 shadow-sm text-sm text-red-300">
          {error}{" "}
          <button onClick={retry} className="underline font-medium">
            Retry
          </button>
        </div>
      )}
      {!loading && !error && items.length === 0 && (
        <div className="bg-gray-50 border rounded-2xl p-6 shadow-sm text-sm text-gray-400">
          No analyzed trades yet. Build a trade and hit Analyze — it&apos;ll show up here.
        </div>
      )}
      {!loading &&
        !error &&
        items.map((h) => {
          const expanded = expandedId === h.id;
          return (
            <div key={h.id} className="bg-gray-50 border rounded-2xl p-5 shadow-sm space-y-3">
              <div className="flex items-start justify-between gap-3">
                <div className="text-sm text-gray-900">
                  <span className="font-medium">Gave</span>{" "}
                  {h.offering.map((p) => p.name).join(", ") || "—"}{" "}
                  <span className="text-gray-400">→</span>{" "}
                  <span className="font-medium">Got</span>{" "}
                  {h.receiving.map((p) => p.name).join(", ") || "—"}
                </div>
                <span className="shrink-0 text-xs text-gray-400">
                  {timeAgo(h.created_at)}
                </span>
              </div>
              {h.verdict && (
                <span
                  className={`inline-block px-3 py-1.5 rounded-xl border text-sm font-medium ${verdictColor(
                    h.verdict
                  )}`}
                >
                  {h.verdict.replace(/\*\*/g, "")}
                </span>
              )}
              <div>
                <button
                  onClick={() => setExpandedId(expanded ? null : h.id)}
                  className="text-xs font-medium text-violet-600 hover:text-violet-300"
                >
                  {expanded ? "Hide analysis" : "Show analysis"}
                </button>
              </div>
              {expanded && <AnalysisRenderer text={h.analysis} />}
            </div>
          );
        })}
    </div>
  );
}
