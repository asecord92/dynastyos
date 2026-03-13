"use client";

import { useEffect, useState } from "react";
import { supabase } from "./supabaseClient";
import { useLeague } from "./useLeague";
import type { AnalyzeResult } from "./types";

export function useSnapshot() {
  const { leagueId } = useLeague();
  const [data, setData] = useState<AnalyzeResult | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!leagueId) {
      setData(null);
      return;
    }

    async function loadLatestSnapshot() {
      setLoading(true);
      setData(null);

      const { data: rows, error } = await supabase
        .from("snapshots")
        .select("data")
        .eq("league_id", leagueId)
        .order("created_at", { ascending: false })
        .limit(1);

      if (!error && rows && rows.length > 0) {
        setData(rows[0].data as AnalyzeResult);
      }

      setLoading(false);
    }

    loadLatestSnapshot();
  }, [leagueId]);

  return { data, loading, leagueId };
}