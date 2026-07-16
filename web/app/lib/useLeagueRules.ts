"use client";

import { useEffect, useState } from "react";
import { supabase } from "./supabaseClient";
import { DEFAULT_RULES, type LeagueRules } from "./capPlanner";

/** Load the league's stored rules blob (see engine/rules.py for semantics),
 * falling back to the Inglorious Bashers defaults for MLB leagues and to
 * no-contract rules for other sports — mirroring the backend's load_rules. */
export function useLeagueRules(leagueId: string | null) {
  const [rules, setRules] = useState<LeagueRules | null>(null);

  useEffect(() => {
    if (!leagueId) {
      setRules(null);
      return;
    }
    let active = true;
    (async () => {
      const { data } = await supabase
        .from("leagues")
        .select("rules, sport")
        .eq("id", leagueId)
        .single();
      if (!active) return;
      const sport = (data?.sport as string) ?? "MLB";
      const raw = (data?.rules ?? {}) as Partial<LeagueRules>;
      if (sport !== "MLB" && !data?.rules) {
        setRules({ ...DEFAULT_RULES, sport, contract: null, slots: null });
        return;
      }
      setRules({
        sport,
        in_season_cap: raw.in_season_cap ?? DEFAULT_RULES.in_season_cap,
        offseason_cap: raw.offseason_cap ?? DEFAULT_RULES.offseason_cap,
        contract:
          raw.contract === null
            ? null
            : { ...DEFAULT_RULES.contract!, ...(raw.contract ?? {}) },
        slots: raw.slots === null ? null : { ...DEFAULT_RULES.slots!, ...(raw.slots ?? {}) },
      });
    })();
    return () => {
      active = false;
    };
  }, [leagueId]);

  return rules;
}
