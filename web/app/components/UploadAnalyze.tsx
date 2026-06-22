"use client";

import { useState } from "react";
import type { AnalyzeResult } from "../lib/types";
import { useLeague } from "../lib/useLeague";
import { supabase } from "../lib/supabaseClient";

export function UploadAnalyze({
  onData,
}: {
  onData: (data: AnalyzeResult) => void;
}) {
  const { leagueId } = useLeague();
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function analyze() {
    if (!file || !leagueId) return;

    setLoading(true);
    setError(null);

    try {
      // Step 1: Fetch the league's current mode
      const { data: leagueData } = await supabase
        .from("leagues")
        .select("mode")
        .eq("id", leagueId)
        .single();

      const mode = leagueData?.mode ?? "in_season";

      // Step 2: Send CSV to FastAPI with mode param
      const form = new FormData();
      form.append("file", file);

      const res = await fetch(`/api/roster/analyze?mode=${mode}`, {
        method: "POST",
        body: form,
      });

      if (!res.ok) throw new Error(await res.text());

      const json = (await res.json()) as AnalyzeResult;

      // Step 3: Save snapshot to Supabase
      const { data: sessionData } = await supabase.auth.getSession();
      const user = sessionData.session?.user;

      if (user) {
        const { error: snapError } = await supabase
          .from("snapshots")
          .insert({
            league_id: leagueId,
            owner_user_id: user.id,
            source: "csv",
            data: json,
          });

        if (snapError) {
          console.error("Failed to save snapshot:", snapError.message);
        }
      }

      // Step 4: Hand result to parent
      onData(json);
    } catch (e: any) {
      setError(e?.message ?? "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-4">
      {!leagueId && (
        <div className="text-sm text-amber-300 bg-amber-50 border border-amber-500/30 rounded-xl p-3">
          Select a league from the nav to analyze your roster.
        </div>
      )}

      <div className="flex items-center gap-4">
        <input
          id="csv-upload"
          type="file"
          accept=".csv"
          className="hidden"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />

        <label
          htmlFor="csv-upload"
          className="px-4 py-2 rounded-xl bg-gray-100 text-gray-900 cursor-pointer hover:bg-gray-200 transition"
        >
          {file ? "Change File" : "Choose File"}
        </label>

        <span className="text-sm text-gray-700">
          {file ? file.name : "No file selected"}
        </span>
      </div>

      <button
        onClick={analyze}
        disabled={!file || !leagueId || loading}
        className="px-4 py-2 rounded-xl bg-violet-600 text-white disabled:opacity-40"
      >
        {loading ? "Analyzing..." : "Analyze"}
      </button>

      {error && (
        <div className="text-sm text-red-300 bg-red-50 border border-red-500/30 rounded-xl p-3">
          {error}
        </div>
      )}
    </div>
  );
}