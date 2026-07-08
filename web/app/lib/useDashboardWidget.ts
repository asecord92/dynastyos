"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { supabase } from "./supabaseClient";
import { readCache, writeCache } from "./clientCache";

/**
 * fetch() wrapper that attaches the Supabase access token and JSON headers.
 * Use for any authenticated call to the backend (GET, POST, streaming).
 */
export async function authedFetch(
  path: string,
  init: RequestInit = {}
): Promise<Response> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return fetch(path, {
    ...init,
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
  // 402 from the backend = the league owner hasn't set an Anthropic key (BYOK).
  // Surfaced separately so widgets can show an "add your key" prompt, not an error.
  const [needsApiKey, setNeedsApiKey] = useState(false);

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
        if (res.status === 402) {
          setNeedsApiKey(true);
          return;
        }
        setNeedsApiKey(false);
        if (!res.ok) throw new Error(await res.text());
        const json = (await res.json()) as T;
        setData(json);
        if (cacheKey) writeCache(cacheKey, json);
        onSuccessRef.current?.(json);
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Something went wrong.");
      } finally {
        setValidating(false);
      }
    },
    [widget, leagueId, myTeamId, cacheKey]
  );

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Only surface a blocking spinner when there's nothing cached to show yet;
  // a background revalidation over existing data stays silent.
  return { data, loading: validating && data === null, validating, error, needsApiKey, refresh };
}
