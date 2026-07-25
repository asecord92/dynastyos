"use client";

import { useEffect, useState } from "react";
import { supabase } from "../lib/supabaseClient";

const DISMISS_KEY = "dynastyos:digest-promo:dismissed";

/** One-time dashboard callout for the (opt-in, default-off) daily digest.
 * Shows until the user either enables the digest for this league or dismisses
 * the card; enabling happens right here with one tap. */
export function DigestPromo({ leagueId }: { leagueId: string }) {
  const [visible, setVisible] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!leagueId) return;
    if (typeof window !== "undefined" && localStorage.getItem(DISMISS_KEY)) return;
    let active = true;
    (async () => {
      const { data } = await supabase
        .from("leagues")
        .select("*")
        .eq("id", leagueId)
        .single();
      if (!active) return;
      const on = (data as { digest_enabled?: boolean } | null)?.digest_enabled === true;
      setVisible(!on);
    })();
    return () => {
      active = false;
    };
  }, [leagueId]);

  if (!visible) return null;

  async function enable() {
    setErr(null);
    const { error } = await supabase
      .from("leagues")
      .update({ digest_enabled: true })
      .eq("id", leagueId);
    if (error) {
      setErr(error.message);
      return;
    }
    setEnabled(true);
    setTimeout(() => setVisible(false), 4000);
  }

  function dismiss() {
    localStorage.setItem(DISMISS_KEY, "1");
    setVisible(false);
  }

  if (enabled) {
    return (
      <div className="bg-green-50 border border-green-500/30 rounded-2xl p-4 text-sm text-green-400">
        You&apos;re in — your first digest lands tomorrow around 9 AM PT. Change your mind any
        time in Settings.
      </div>
    );
  }

  return (
    <div className="bg-gray-50 border border-violet-500/30 rounded-2xl p-4 md:p-5 shadow-sm">
      <div className="flex flex-col md:flex-row md:items-center gap-3 md:gap-4">
        <div className="flex-1">
          <div className="text-sm font-semibold">
            <span className="inline-block px-1.5 py-0.5 mr-2 rounded-md bg-violet-600 text-white text-[10px] font-bold uppercase tracking-wide align-middle">
              New
            </span>
            Daily Digest
          </div>
          <p className="text-sm text-gray-500 mt-1 leading-relaxed">
            A morning email brief for this league — top news, today&apos;s lineup calls, and the
            waiver move to make, around 9 AM PT. Off by default; one tap to join. It&apos;s
            written fresh daily, so it uses your Anthropic key each morning.
          </p>
          {err && <p className="text-xs text-red-500 mt-1">{err}</p>}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            onClick={enable}
            className="px-4 py-2 rounded-xl bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 transition"
          >
            Turn it on
          </button>
          <button
            type="button"
            onClick={dismiss}
            className="px-3 py-2 rounded-xl text-sm text-gray-500 border border-gray-200 hover:border-gray-300 transition"
          >
            No thanks
          </button>
        </div>
      </div>
    </div>
  );
}
