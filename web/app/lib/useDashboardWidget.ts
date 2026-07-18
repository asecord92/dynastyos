"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { supabase } from "./supabaseClient";
import { readCache, writeCache } from "./clientCache";
import { aiIssueFromDetail, useAiStatus } from "./aiStatus";

// getSession() can hang forever (auth-lock deadlocks after a suspended tab,
// degraded networks — the 2026-07-17 stuck-loading incident), so it gets a
// short deadline with a localStorage fallback. Fetches get an abort deadline
// too: generous by default because cache-miss widget generation legitimately
// runs tens of seconds — it exists to kill true black holes, not slow work.
// Quick reads pass a tighter timeoutMs; streaming calls bring their own signal.
const SESSION_TIMEOUT_MS = 3_000;
const DEFAULT_TIMEOUT_MS = 120_000;

async function sessionToken(): Promise<string | undefined> {
  const viaSdk = supabase.auth
    .getSession()
    .then(({ data }) => data.session?.access_token)
    .catch(() => undefined);
  const deadline = new Promise<undefined>((resolve) =>
    setTimeout(() => resolve(undefined), SESSION_TIMEOUT_MS)
  );
  const token = await Promise.race([viaSdk, deadline]);
  if (token) return token;
  try {
    // The token supabase-js persists — stale-ish is fine, the backend verifies.
    const key = Object.keys(localStorage).find(
      (k) => k.startsWith("sb-") && k.endsWith("-auth-token")
    );
    if (!key) return undefined;
    return JSON.parse(localStorage.getItem(key) ?? "null")?.access_token ?? undefined;
  } catch {
    return undefined;
  }
}

/** True when a fetch rejection came from our timeout (or an abort). */
export function isTimeoutError(e: unknown): boolean {
  return e instanceof DOMException && (e.name === "TimeoutError" || e.name === "AbortError");
}

/**
 * fetch() wrapper that attaches the Supabase access token and JSON headers.
 * Use for any authenticated call to the backend (GET, POST, streaming).
 */
export async function authedFetch(
  path: string,
  init: RequestInit = {},
  opts?: { timeoutMs?: number }
): Promise<Response> {
  const token = await sessionToken();
  const { signal, ...rest } = init;
  const fallbackSignal =
    typeof AbortSignal !== "undefined" && "timeout" in AbortSignal
      ? AbortSignal.timeout(opts?.timeoutMs ?? DEFAULT_TIMEOUT_MS)
      : undefined;
  return fetch(path, {
    ...rest,
    signal: signal ?? fallbackSignal,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers ?? {}),
    },
  });
}

/**
 * Shared loading/error/data state for the cached dashboard widgets
 * (news, start_sit, waiver, minors). POSTs { league_id, my_team_id, force }
 * to /api/dashboard/<widget> and fetches once when league/team change.
 *
 * Pass `onSuccess` for a per-widget side effect (e.g. surfacing alerts). It is
 * held in a ref so an inline callback does not retrigger the fetch each render.
 */
export function useDashboardWidget<T>(
  widget: string,
  leagueId: string,
  myTeamId: string,
  options?: { onSuccess?: (data: T) => void }
) {
  const cacheKey =
    leagueId && myTeamId ? `dynastyos:widget:${widget}:${leagueId}:${myTeamId}` : null;

  // Paint the last-known response immediately (stale-while-revalidate).
  const [data, setData] = useState<T | null>(() =>
    cacheKey ? readCache<T>(cacheKey) : null
  );
  const [validating, setValidating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 402 no_api_key = the league owner hasn't set an Anthropic key (BYOK).
  // Surfaced separately so widgets can show an "add your key" prompt, not an error.
  const [needsApiKey, setNeedsApiKey] = useState(false);
  // Key-level failures (out of credits / rejected key) go to the app-wide banner.
  const { reportIssue, clearIssue } = useAiStatus();

  const onSuccessRef = useRef(options?.onSuccess);
  useEffect(() => {
    onSuccessRef.current = options?.onSuccess;
  });

  // Re-hydrate from cache when the league/team (and thus key) changes.
  useEffect(() => {
    setData(cacheKey ? readCache<T>(cacheKey) : null);
  }, [cacheKey]);

  const refresh = useCallback(
    async (force = false) => {
      if (!leagueId || !myTeamId) return;
      setValidating(true);
      setError(null);
      try {
        const res = await authedFetch(`/api/dashboard/${widget}`, {
          method: "POST",
          body: JSON.stringify({
            league_id: leagueId,
            my_team_id: myTeamId,
            force,
          }),
        });
        if (res.status === 402 || res.status === 429) {
          const detail = await res
            .json()
            .then((j) => j?.detail as string | undefined)
            .catch(() => undefined);
          const issue = aiIssueFromDetail(detail);
          if (issue) {
            reportIssue(issue);
          } else if (res.status === 429) {
            setError("Anthropic is rate-limiting your key — try again in a moment.");
          } else {
            setNeedsApiKey(true);
          }
          return;
        }
        // A healthy response means the owner's key works — clear any stale banner.
        setNeedsApiKey(false);
        clearIssue();
        if (!res.ok) throw new Error(await res.text());
        const json = (await res.json()) as T;
        setData(json);
        if (cacheKey) writeCache(cacheKey, json);
        onSuccessRef.current?.(json);
      } catch (e: unknown) {
        if (isTimeoutError(e)) setError("Request timed out — try again.");
        else setError(e instanceof Error ? e.message : "Something went wrong.");
      } finally {
        setValidating(false);
      }
    },
    [widget, leagueId, myTeamId, cacheKey, reportIssue, clearIssue]
  );

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Only surface a blocking spinner when there's nothing cached to show yet;
  // a background revalidation over existing data stays silent.
  return { data, loading: validating && data === null, validating, error, needsApiKey, refresh };
}
