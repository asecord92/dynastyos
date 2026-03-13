"use client";

import { useState } from "react";
import { supabase } from "../../lib/supabaseClient";
import { useLeague } from "../../lib/useLeague";
import { UploadAnalyze } from "../../components/UploadAnalyze";
import type { AnalyzeResult } from "../../lib/types";

export default function SettingsPage() {
  const { leagueId } = useLeague();
  const [name, setName] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  async function createLeague() {
    setMsg(null);

    const { data: sessionData } = await supabase.auth.getSession();
    const user = sessionData.session?.user;

    if (!user) {
      setMsg("Please log in first.");
      return;
    }

    const { error } = await supabase.from("leagues").insert({
      owner_user_id: user.id,
      name,
      platform: "fantrax",
    });

    if (error) setMsg(error.message);
    else {
      setName("");
      setMsg("League created. Select it from the dropdown in the navbar.");
    }
  }

  return (
    <main className="space-y-6">
      <h1 className="text-3xl font-semibold">Settings</h1>

      {/* League Management */}
      <div className="space-y-2">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-gray-400">
          League Management
        </h2>

        <div className="bg-white border rounded-2xl p-6 shadow-sm space-y-3 max-w-lg">
          <h3 className="text-lg font-semibold">Create League</h3>
          <p className="text-sm text-gray-500">
            Add a new league to your account.
          </p>

          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g., Inglorious Bastards"
            className="w-full px-3 py-2 rounded-xl border border-gray-200 bg-white text-sm outline-none focus:border-gray-400"
          />

          <button
            onClick={createLeague}
            disabled={!name}
            className="px-4 py-2 rounded-xl bg-black text-white disabled:opacity-40 text-sm"
          >
            Create
          </button>

          {msg && (
            <div className="text-sm text-gray-700 bg-gray-50 border border-gray-200 rounded-xl p-3">
              {msg}
            </div>
          )}
        </div>
      </div>

      {/* Data */}
      <div className="space-y-2">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-gray-400">
          Data
        </h2>

        <div className="bg-white border rounded-2xl p-6 shadow-sm space-y-3 max-w-lg">
          <h3 className="text-lg font-semibold">Upload Roster CSV</h3>
          <p className="text-sm text-gray-500">
            Export your roster from Fantrax and upload it here. This will become
            the latest snapshot for the selected league.
          </p>

          <UploadAnalyze onData={(_data: AnalyzeResult) => {
            setMsg("Snapshot saved! Head to the Dashboard to view your roster.");
          }} />
        </div>
      </div>
    </main>
  );
}