"use client";

import { useEffect } from "react";
import { supabase } from "../lib/supabaseClient";

const STORAGE_KEY = "dynastyos:selected_league_id";
const FOUR_HOURS_MS = 4 * 60 * 60 * 1000;

export function AutoSync() {
  useEffect(() => {
    async function checkAndSync() {
      const leagueId = localStorage.getItem(STORAGE_KEY);
      if (!leagueId) return;

      // Check synced_at on any roster row for this league
      const { data: rosterRow } = await supabase
        .from("rosters")
        .select("synced_at")
        .eq("league_id", leagueId)
        .limit(1)
        .single();

      const synced_at = rosterRow?.synced_at;
      const isStale = !synced_at || Date.now() - new Date(synced_at).getTime() > FOUR_HOURS_MS;
      if (!isStale) return;

      // Fetch Fantrax credentials from leagues table
      const { data: leagueData } = await supabase
        .from("leagues")
        .select("fantrax_secret_id,fantrax_league_id")
        .eq("id", leagueId)
        .single();

      if (!leagueData?.fantrax_secret_id || !leagueData?.fantrax_league_id) return;

      const { data: sessionData } = await supabase.auth.getSession();
      const accessToken = sessionData.session?.access_token;

      // Fire and forget — no await, no error handling shown to user
      fetch("/api/roster/sync", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
        body: JSON.stringify({
          user_secret_id: leagueData.fantrax_secret_id,
          fantrax_league_id: leagueData.fantrax_league_id,
        }),
      }).catch(() => {});
    }

    checkAndSync();
  }, []);

  return null;
}
