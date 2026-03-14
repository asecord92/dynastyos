"use client";

import { useState, useEffect } from "react";
import { supabase } from "../../lib/supabaseClient";
import { useLeague } from "../../lib/useLeague";
import { UploadAnalyze } from "../../components/UploadAnalyze";
import type { AnalyzeResult } from "../../lib/types";

type FantraxLeague = {
  leagueId: string;
  leagueName: string;
  teamName: string;
  sport: string;
};

export default function SettingsPage() {
  const { leagueId, setLeague } = useLeague();
  const [toastVisible, setToastVisible] = useState(false);

  const [secretId, setSecretId] = useState("");
  const [fantraxLeagues, setFantraxLeagues] = useState<FantraxLeague[]>([]);
  const [selectedFantraxLeagueId, setSelectedFantraxLeagueId] = useState("");
  const [connectLoading, setConnectLoading] = useState(false);
  const [connectMsg, setConnectMsg] = useState<string | null>(null);
  const [connectStep, setConnectStep] = useState<"idle" | "pick" | "done">("idle");

  const [mode, setMode] = useState<"in_season" | "offseason">("in_season");

  const [csvLeagueName, setCsvLeagueName] = useState("");
  const [csvMsg, setCsvMsg] = useState<string | null>(null);
  const [leagues, setLeagues] = useState<{ id: string; name: string }[]>([]);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  useEffect(() => {
    if (!leagueId) return;
    supabase
      .from("leagues")
      .select("mode, fantrax_secret_id, fantrax_league_id")
      .eq("id", leagueId)
      .single()
      .then(({ data }) => {
        if (data?.mode) setMode(data.mode as "in_season" | "offseason");
        if (data?.fantrax_league_id) setConnectStep("done");
      });
  }, [leagueId]);

  function showToast() {
    setToastVisible(true);
    setTimeout(() => setToastVisible(false), 2000);
  }

  async function saveMode(newMode: "in_season" | "offseason") {
    setMode(newMode);
    const { error } = await supabase
      .from("leagues")
      .update({ mode: newMode })
      .eq("id", leagueId);
    if (!error) showToast();
  }
  async function loadLeagues() {
  const { data } = await supabase
    .from("leagues")
    .select("id, name")
    .order("created_at", { ascending: false });
  if (data) setLeagues(data);
}

async function deleteLeague(id: string) {
  const { error } = await supabase
    .from("leagues")
    .delete()
    .eq("id", id);

  if (!error) {
    setConfirmDeleteId(null);
    if (id === leagueId) setLeague("");
    window.dispatchEvent(new Event("dynastyos:leagues-updated"));
    await loadLeagues();
  }
}

useEffect(() => {
  loadLeagues();
  window.addEventListener("dynastyos:leagues-updated", loadLeagues);
  return () => window.removeEventListener("dynastyos:leagues-updated", loadLeagues);
}, []);

  async function fetchFantraxLeagues() {
    if (!secretId) return;
    setConnectLoading(true);
    setConnectMsg(null);
    try {
      const res = await fetch(`/api/fantrax/leagues?user_secret_id=${secretId}`);
      if (!res.ok) throw new Error(await res.text());
      const json = await res.json();
      const leagues: FantraxLeague[] = json.leagues ?? [];
      if (leagues.length === 0) {
        setConnectMsg("No leagues found for this Secret ID.");
        return;
      }
      setFantraxLeagues(leagues);
      setSelectedFantraxLeagueId(leagues[0].leagueId);
      setConnectStep("pick");
    } catch (e: any) {
      setConnectMsg(e?.message ?? "Something went wrong.");
    } finally {
      setConnectLoading(false);
    }
  }

  async function connectLeague() {
    if (!selectedFantraxLeagueId) return;
    setConnectLoading(true);
    setConnectMsg(null);

    const picked = fantraxLeagues.find(l => l.leagueId === selectedFantraxLeagueId);
    if (!picked) return;

    try {
      const { data: sessionData } = await supabase.auth.getSession();
      const user = sessionData.session?.user;
      if (!user) throw new Error("Not logged in.");

      // Check for duplicate
      const { data: existing } = await supabase
        .from("leagues")
        .select("id")
        .eq("owner_user_id", user.id)
        .eq("fantrax_league_id", picked.leagueId)
        .single();

      if (existing) {
        setConnectMsg("This league is already connected.");
        setConnectLoading(false);
        return;
      }

      const { data: newLeague, error } = await supabase
        .from("leagues")
        .insert({
          owner_user_id: user.id,
          name: picked.leagueName,
          platform: "fantrax",
          fantrax_secret_id: secretId,
          fantrax_league_id: picked.leagueId,
          sport: picked.sport,
        })
        .select("id")
        .single();

      if (error) throw new Error(error.message);

      setLeague(newLeague.id);
      setConnectStep("done");
      setSecretId("");
      showToast();
      window.dispatchEvent(new Event("dynastyos:leagues-updated"));

      const syncRes = await fetch(
        `/api/roster/sync?user_secret_id=${secretId}&fantrax_league_id=${picked.leagueId}`,
        { method: "POST" }
      );

      if (syncRes.ok) {
        const syncJson = await syncRes.json();
        const { data: sessionData } = await supabase.auth.getSession();
        const { data: syncSessionData } = await supabase.auth.getSession();
        const syncUser = syncSessionData.session?.user;
        if (syncUser) {
          await supabase.from("snapshots").insert({
            league_id: newLeague.id,
            owner_user_id: syncUser.id,
            source: "fantrax",
            data: syncJson,
          });
        }
      }

    } catch (e: any) {
      setConnectMsg(e?.message ?? "Something went wrong.");
    } finally {
      setConnectLoading(false);
    }
  }

  async function createCsvLeague() {
    setCsvMsg(null);
    const { data: sessionData } = await supabase.auth.getSession();
    const user = sessionData.session?.user;
    if (!user) { setCsvMsg("Please log in first."); return; }
    const { error } = await supabase.from("leagues").insert({
      owner_user_id: user.id,
      name: csvLeagueName,
      platform: "fantrax",
    });
    if (error) setCsvMsg(error.message);
    else {
      setCsvLeagueName("");
      setCsvMsg("League created. Select it from the dropdown in the navbar.");
    }
  }

  return (
    <main className="space-y-0">
      <h1 className="text-3xl font-semibold mb-10">Settings</h1>

      {/* Toast */}
      <div
        className={`fixed bottom-6 right-6 bg-gray-900 text-white text-sm px-4 py-2 rounded-xl shadow-lg transition-opacity duration-300 z-50 ${
          toastVisible ? "opacity-100" : "opacity-0 pointer-events-none"
        }`}
      >
        Saved
      </div>

      {/* Fantrax */}
      <div className="grid grid-cols-[200px_1fr] gap-8 py-8 border-t border-gray-200">
        <div>
          <div className="text-xs font-semibold uppercase tracking-widest text-gray-400">Fantrax</div>
          <p className="text-sm text-gray-400 mt-2 leading-relaxed">
            Connect your Fantrax account to enable direct roster sync.
          </p>
        </div>
        <div className="space-y-4">
          <div className="bg-white border rounded-2xl p-6 shadow-sm space-y-4">
            <h3 className="text-lg font-semibold">Connect a League</h3>
            <p className="text-sm text-gray-500">
              Enter your Fantrax Secret ID — found on your Fantrax profile page —
              to import your leagues directly.
            </p>

            {connectStep === "done" && (
              <div className="text-sm text-gray-700 bg-gray-50 border border-gray-200 rounded-xl p-3">
                Fantrax connected. To connect another league, enter a Secret ID below.
              </div>
            )}

            <div className="space-y-2">
              <label className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                Fantrax Secret ID
              </label>
              <input
                value={secretId}
                onChange={(e) => {
                  setSecretId(e.target.value);
                  setConnectStep("idle");
                  setFantraxLeagues([]);
                }}
                placeholder="Found on your Fantrax profile page"
                className="w-full px-3 py-2 rounded-xl border border-gray-200 bg-white text-sm outline-none focus:border-gray-400"
              />
            </div>

            {connectStep === "pick" && fantraxLeagues.length > 0 && (
              <div className="space-y-2">
                <label className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                  Select League
                </label>
                <select
                  value={selectedFantraxLeagueId}
                  onChange={(e) => setSelectedFantraxLeagueId(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl border border-gray-200 bg-white text-sm outline-none focus:border-gray-400"
                >
                  {fantraxLeagues.map((l) => (
                    <option key={l.leagueId} value={l.leagueId}>
                      {l.leagueName} — {l.teamName}
                    </option>
                  ))}
                </select>
              </div>
            )}

            <div className="flex gap-2">
              {connectStep !== "pick" && (
                <button
                  onClick={fetchFantraxLeagues}
                  disabled={!secretId || connectLoading}
                  className="px-4 py-2 rounded-xl bg-black text-white disabled:opacity-40 text-sm"
                >
                  {connectLoading ? "Loading..." : "Find Leagues"}
                </button>
              )}
              {connectStep === "pick" && (
                <button
                  onClick={connectLeague}
                  disabled={!selectedFantraxLeagueId || connectLoading}
                  className="px-4 py-2 rounded-xl bg-black text-white disabled:opacity-40 text-sm"
                >
                  {connectLoading ? "Connecting & syncing..." : "Connect"}
                </button>
              )}
            </div>

            {connectMsg && (
              <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-xl p-3">
                {connectMsg}
              </div>
            )}
          </div>

          {/* Your Leagues card */}
          {leagues.length > 0 && (
            <div className="bg-white border rounded-2xl p-6 shadow-sm space-y-3">
              <h3 className="text-lg font-semibold">Your Leagues</h3>
              <p className="text-sm text-gray-500">
                Manage your connected leagues.
              </p>
              <div className="space-y-2">
                {leagues.map((l) => (
                  <div
                    key={l.id}
                    className="flex items-center justify-between py-2 border-b border-gray-100 last:border-0"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-gray-900">{l.name}</span>
                      {l.id === leagueId && (
                        <span className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">
                          active
                        </span>
                      )}
                    </div>

                    {confirmDeleteId === l.id ? (
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-gray-500">Sure?</span>
                        <button
                          onClick={() => deleteLeague(l.id)}
                          className="text-xs px-3 py-1 rounded-lg bg-red-600 text-white hover:bg-red-700 transition"
                        >
                          Delete
                        </button>
                        <button
                          onClick={() => setConfirmDeleteId(null)}
                          className="text-xs px-3 py-1 rounded-lg border border-gray-200 hover:border-gray-300 transition"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setConfirmDeleteId(l.id)}
                        className="text-xs px-3 py-1 rounded-lg border border-gray-200 text-gray-500 hover:border-red-300 hover:text-red-600 transition"
                      >
                        Delete
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Data */}
      {leagueId && (
        <div className="grid grid-cols-[200px_1fr] gap-8 py-8 border-t border-gray-200">
          <div>
            <div className="text-xs font-semibold uppercase tracking-widest text-gray-400">Data</div>
            <p className="text-sm text-gray-400 mt-2 leading-relaxed">
              Configure how roster data is calculated and displayed.
            </p>
          </div>
          <div className="bg-white border rounded-2xl p-6 shadow-sm space-y-3 ">
            <h3 className="text-lg font-semibold">Cap Mode</h3>
            <p className="text-sm text-gray-500">
              Controls which cap limit is used when analyzing a CSV upload.
              Fantrax sync sets this automatically.
            </p>
            <div className="flex items-center gap-3">
              <span className={`text-sm ${mode === "offseason" ? "text-gray-900 font-medium" : "text-gray-400"}`}>
                Offseason (335)
              </span>
              <button
                onClick={() => saveMode(mode === "in_season" ? "offseason" : "in_season")}
                className="relative inline-flex h-7 w-12 items-center rounded-full bg-black transition-colors duration-200 focus:outline-none"
              >
                <span
                  className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform duration-200 ${
                    mode === "in_season" ? "translate-x-6" : "translate-x-1"
                  }`}
                />
              </button>
              <span className={`text-sm ${mode === "in_season" ? "text-gray-900 font-medium" : "text-gray-400"}`}>
                In-Season (450)
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Manual / CSV */}
      <div className="grid grid-cols-[200px_1fr] gap-8 py-8 border-t border-gray-200">
        <div>
          <div className="text-xs font-semibold uppercase tracking-widest text-gray-400">Manual / CSV</div>
          <p className="text-sm text-gray-400 mt-2 leading-relaxed">
            Fallback option if you're not using Fantrax sync.
          </p>
        </div>
        <div className="space-y-4 ">
          <div className="bg-white border rounded-2xl p-6 shadow-sm space-y-3">
            <h3 className="text-lg font-semibold">Create League Manually</h3>
            <p className="text-sm text-gray-500">
              Not using Fantrax sync? Create a league manually and upload a CSV instead.
            </p>
            <input
              value={csvLeagueName}
              onChange={(e) => setCsvLeagueName(e.target.value)}
              placeholder="e.g., Inglorious Bashers"
              className="w-full px-3 py-2 rounded-xl border border-gray-200 bg-white text-sm outline-none focus:border-gray-400"
            />
            <button
              onClick={createCsvLeague}
              disabled={!csvLeagueName}
              className="px-4 py-2 rounded-xl bg-black text-white disabled:opacity-40 text-sm"
            >
              Create
            </button>
            {csvMsg && (
              <div className="text-sm text-gray-700 bg-gray-50 border border-gray-200 rounded-xl p-3">
                {csvMsg}
              </div>
            )}
          </div>

          {leagueId && (
            <div className="bg-white border rounded-2xl p-6 shadow-sm space-y-3">
              <h3 className="text-lg font-semibold">Upload Roster CSV</h3>
              <p className="text-sm text-gray-500">
                Export your roster from Fantrax and upload it here. This will become
                the latest snapshot for the selected league.
              </p>
              <UploadAnalyze onData={(_data: AnalyzeResult) => {
                setCsvMsg("Snapshot saved! Head to the Dashboard to view your roster.");
              }} />
            </div>
          )}
        </div>
      </div>

      {/* Bottom border */}
      <div className="border-t border-gray-200" />
    </main>
  );
}