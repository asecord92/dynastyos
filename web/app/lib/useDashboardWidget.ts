"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { supabase } from "./supabaseClient";

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
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSuccessRef = useRef(options?.onSuccess);
  useEffect(() => {
    onSuccessRef.current = options?.onSuccess;
  });

  const refresh = useCallback(
    async (force = false) => {
      if (!leagueId || !myTeamId) return;
      setLoading(true);
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
        if (!res.ok) throw new Error(await res.text());
        const json = (await res.json()) as T;
        setData(json);
        onSuccessRef.current?.(json);
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Something went wrong.");
      } finally {
        setLoading(false);
      }
    },
    [widget, leagueId, myTeamId]
  );

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { data, loading, error, refresh };
}
