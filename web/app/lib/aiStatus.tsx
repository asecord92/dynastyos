"use client";

import { createContext, useCallback, useContext, useState, ReactNode } from "react";

/**
 * A key-level AI problem that affects *every* AI feature at once (they all use
 * the league owner's single Anthropic key), so it's surfaced as one app-wide
 * banner rather than per-widget. Distinct from the per-widget "no key set" 402
 * (`needsApiKey`), which is a first-run prompt, not a failure.
 */
export type AiIssue = "out_of_credits" | "invalid_api_key";

type AiStatusValue = {
  issue: AiIssue | null;
  reportIssue: (issue: AiIssue) => void;
  clearIssue: () => void;
};

// No-op default so components/hooks that read this outside the provider (or in
// tests) never throw.
const AiStatusContext = createContext<AiStatusValue>({
  issue: null,
  reportIssue: () => {},
  clearIssue: () => {},
});

export function AiStatusProvider({ children }: { children: ReactNode }) {
  const [issue, setIssue] = useState<AiIssue | null>(null);
  const reportIssue = useCallback((i: AiIssue) => setIssue(i), []);
  const clearIssue = useCallback(() => setIssue(null), []);
  return (
    <AiStatusContext.Provider value={{ issue, reportIssue, clearIssue }}>
      {children}
    </AiStatusContext.Provider>
  );
}

export function useAiStatus() {
  return useContext(AiStatusContext);
}

/**
 * Map a backend 402/429 `detail` (or a finder `error` event's detail) to a
 * global AI issue, or null if it's something else (e.g. `no_api_key`,
 * `rate_limited`, or a raw error string) that the caller should handle locally.
 */
export function aiIssueFromDetail(detail: string | null | undefined): AiIssue | null {
  if (detail === "out_of_credits" || detail === "invalid_api_key") return detail;
  return null;
}

/**
 * Human copy for an `error` event's detail that `aiIssueFromDetail` didn't
 * claim — the stable codes the AI streams can end on. Shared so the trade
 * analyzer, the finder, and add/drop word the same failure the same way.
 */
export function aiErrorMessage(detail: string | null | undefined): string {
  if (detail === "rate_limited")
    return "Anthropic is rate-limiting your key — try again in a moment.";
  // The answer above this banner is real, just cut off mid-thought, so say
  // that rather than implying nothing came back.
  if (detail === "truncated")
    return "The answer was cut off before it finished — retry to get the full one.";
  // Same shape as `truncated` — real answer above, just unfinished — but the
  // cause is the web-search loop running out of steps, not the token budget.
  if (detail === "paused")
    return "The analysis stopped early while researching — retry to get the full one.";
  return detail || "Something went wrong.";
}
