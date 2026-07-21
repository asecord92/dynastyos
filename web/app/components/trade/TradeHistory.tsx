"use client";

import { useCallback, useEffect, useState } from "react";
import { authedFetch, isTimeoutError } from "../../lib/useDashboardWidget";
import { timeAgo } from "../../lib/format";
import { AnalysisRenderer, verdictColor } from "./AnalysisRenderer";

type TradeHistoryPlayer = { id: string; name: string };
export type TradeOutcome = "proposed" | "accepted" | "rejected" | "completed";
export type TradeHistoryRow = {
  id: string;
  created_at: string;
  offering: TradeHistoryPlayer[];
  receiving: TradeHistoryPlayer[];
  verdict: string | null;
  analysis: string;
  status?: TradeOutcome | null;
  outcome_note?: string | null;
  outcome_updated_at?: string | null;
};

const OUTCOMES: { key: TradeOutcome; label: string }[] = [
  { key: "proposed", label: "Proposed" },
  { key: "accepted", label: "Accepted" },
  { key: "rejected", label: "Rejected" },
  { key: "completed", label: "Completed" },
];

function outcomeColor(status: TradeOutcome): string {
  switch (status) {
    case "accepted":
    case "completed":
      return "bg-emerald-500/15 text-emerald-300 border-emerald-500/30";
    case "rejected":
      return "bg-rose-500/15 text-rose-300 border-rose-500/30";
    default:
      return "bg-amber-500/15 text-amber-300 border-amber-500/30";
  }
}

/** The user's saved trade analyses — self-contained: fetches on mount. */
export function TradeHistory({ leagueId }: { leagueId: string }) {
  const [items, setItems] = useState<TradeHistoryRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  // Bumped by Retry; the effect re-runs the fetch.
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  // Rows whose outcome is currently expanded for editing.
  const [outcomeOpenId, setOutcomeOpenId] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<string | null>(null);

  // Optimistically apply an outcome change, then persist it. On failure we
  // reload so the UI never drifts from the server.
  const setOutcome = useCallback(
    async (row: TradeHistoryRow, next: { status?: TradeOutcome | null; note?: string }) => {
      const status = next.status !== undefined ? next.status : row.status ?? null;
      const note = next.note !== undefined ? next.note : row.outcome_note ?? "";
      setItems((prev) =>
        prev.map((r) =>
          r.id === row.id ? { ...r, status, outcome_note: note } : r
        )
      );
      setSavingId(row.id);
      try {
        const res = await authedFetch(
          "/api/trade/history/outcome",
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              id: row.id,
              league_id: leagueId,
              status,
              note,
            }),
          },
          { timeoutMs: 12_000 }
        );
        if (!res.ok) throw new Error(String(res.status));
      } catch {
        setAttempt((n) => n + 1); // resync from server on failure
      } finally {
        setSavingId(null);
      }
    },
    [leagueId]
  );

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
          const outcomeOpen = outcomeOpenId === h.id;
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
              <div className="flex items-center gap-4">
                <button
                  onClick={() => setExpandedId(expanded ? null : h.id)}
                  className="text-xs font-medium text-violet-600 hover:text-violet-300"
                >
                  {expanded ? "Hide analysis" : "Show analysis"}
                </button>
                <button
                  onClick={() => setOutcomeOpenId(outcomeOpen ? null : h.id)}
                  className="text-xs font-medium text-gray-400 hover:text-gray-200"
                >
                  {h.status
                    ? "Edit outcome"
                    : outcomeOpen
                    ? "Hide outcome"
                    : "Track outcome"}
                </button>
                {h.status && !outcomeOpen && (
                  <span
                    className={`inline-block px-2 py-0.5 rounded-lg border text-[11px] font-medium capitalize ${outcomeColor(
                      h.status
                    )}`}
                  >
                    {h.status}
                  </span>
                )}
              </div>
              {outcomeOpen && (
                <div className="space-y-2 rounded-xl border border-gray-200 p-3">
                  <div className="flex flex-wrap gap-1.5">
                    {OUTCOMES.map((o) => {
                      const active = h.status === o.key;
                      return (
                        <button
                          key={o.key}
                          disabled={savingId === h.id}
                          onClick={() =>
                            setOutcome(h, { status: active ? null : o.key })
                          }
                          className={`px-2.5 py-1 rounded-lg border text-xs font-medium transition disabled:opacity-40 ${
                            active
                              ? outcomeColor(o.key)
                              : "border-gray-200 text-gray-500 hover:border-gray-300"
                          }`}
                        >
                          {o.label}
                        </button>
                      );
                    })}
                  </div>
                  <textarea
                    defaultValue={h.outcome_note ?? ""}
                    onBlur={(e) => {
                      const note = e.target.value;
                      if (note !== (h.outcome_note ?? "")) setOutcome(h, { note });
                    }}
                    placeholder="How's it aging? (optional note, saved on blur)"
                    rows={2}
                    className="w-full px-2.5 py-2 rounded-lg border border-gray-200 text-sm outline-none focus:border-gray-400 resize-none"
                  />
                </div>
              )}
              {h.outcome_note && !outcomeOpen && (
                <p className="text-xs text-gray-400 italic">“{h.outcome_note}”</p>
              )}
              {expanded && <AnalysisRenderer text={h.analysis} />}
            </div>
          );
        })}
    </div>
  );
}
