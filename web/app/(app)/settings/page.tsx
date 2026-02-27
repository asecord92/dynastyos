"use client";

import { useState } from "react";
import { supabase } from "../../lib/supabaseClient";

export default function SettingsPage() {
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

      <div className="bg-white border rounded-2xl p-6 shadow-sm space-y-3 max-w-lg">
        <h2 className="text-lg font-semibold">Create League</h2>

        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g., Inglorious Bashers"
          className="w-full px-3 py-2 rounded-xl border border-gray-200 bg-white text-sm outline-none focus:border-gray-400"
        />

        <button
          onClick={createLeague}
          disabled={!name}
          className="px-4 py-2 rounded-xl bg-black text-white disabled:opacity-40"
        >
          Create
        </button>

        {msg && (
          <div className="text-sm text-gray-700 bg-gray-50 border border-gray-200 rounded-xl p-3">
            {msg}
          </div>
        )}
      </div>
    </main>
  );
}