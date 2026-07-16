"use client";

import { useEffect, useState } from "react";
import { supabase } from "../lib/supabaseClient";

/** Opt in/out of the morning digest email for this league. Reads and writes
 * leagues.digest_enabled (owner-scoped RLS, same pattern as LeagueRulesEditor);
 * missing column/value (migration not applied yet) is treated as opted in. */
export function DigestToggle({ leagueId }: { leagueId: string }) {
  const [loaded, setLoaded] = useState(false);
  const [enabled, setEnabled] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!leagueId) return;
    let active = true;
    (async () => {
      const { data } = await supabase
        .from("leagues")
        .select("*")
        .eq("id", leagueId)
        .single();
      if (!active) return;
      setEnabled((data as { digest_enabled?: boolean } | null)?.digest_enabled ?? true);
      setLoaded(true);
    })();
    return () => {
      active = false;
    };
  }, [leagueId]);

  async function toggle(next: boolean) {
    setEnabled(next);
    setErr(null);
    const { error } = await supabase
      .from("leagues")
      .update({ digest_enabled: next })
      .eq("id", leagueId);
    if (error) {
      setEnabled(!next);
      setErr(error.message);
    }
  }

  return (
    <div className="bg-gray-50 border rounded-2xl p-6 shadow-sm space-y-2">
      <label className="flex items-center gap-3 text-sm text-gray-700">
        <input
          type="checkbox"
          checked={enabled}
          disabled={!loaded}
          onChange={(e) => toggle(e.target.checked)}
          className="h-4 w-4"
        />
        Daily digest email (~9 AM PT)
      </label>
      <p className="text-xs text-gray-400">
        A morning brief for this league — top news, today&apos;s lineup calls, and the waiver
        move to make — sent to your login email.
      </p>
      {err && <p className="text-xs text-red-500">{err}</p>}
    </div>
  );
}
