"use client";

import { useEffect } from "react";
import { authedFetch } from "../lib/useDashboardWidget";
import { aiIssueFromDetail, useAiStatus } from "../lib/aiStatus";

/**
 * Seeds the app-wide AI banner from the owner's most recent AI call, so an
 * out-of-credits key discovered by a *background* job (the daily digest) shows
 * up on the next app load instead of only when the user trips a fresh failing
 * call. Reads `GET /api/me/ai-status` (latest `ai_usage` row) on mount and when
 * the tab regains focus — the morning-after case, when the digest hit the wall
 * hours before the user opened the app.
 *
 * It only ever *reports* a problem; clearing stays with the live success paths
 * (widget hook + trade page) to avoid a stale read racing a fresh failure.
 */
export function AiStatusSync() {
  const { reportIssue } = useAiStatus();

  useEffect(() => {
    let cancelled = false;

    async function check() {
      try {
        const res = await authedFetch("/api/me/ai-status", { method: "GET" });
        if (!res.ok) return;
        const { issue } = (await res.json()) as { issue?: string | null };
        const mapped = aiIssueFromDetail(issue);
        if (!cancelled && mapped) reportIssue(mapped);
      } catch {
        // Best-effort: never let a status probe surface an error to the user.
      }
    }

    check();
    const onVisible = () => {
      if (document.visibilityState === "visible") check();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [reportIssue]);

  return null;
}
