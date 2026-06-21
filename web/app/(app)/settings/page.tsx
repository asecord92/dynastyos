"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "../../lib/supabaseClient";
import { useLeague } from "../../lib/useLeague";
import { UploadAnalyze } from "../../components/UploadAnalyze";
import { LeagueRulesEditor } from "../../components/LeagueRulesEditor";
import { authedFetch } from "../../lib/useDashboardWidget";
import type { AnalyzeResult } from "../../lib/types";

type FantraxLeague = {
  leagueId: string;
  leagueName: string;
  teamName?: string;
  sport: string;
  season?: string;
};

type LeagueRow = {
  mode: string;
  fantrax_league_id: string | null;
  name: string;
  competitive_window: string | null;
  cap_philosophy: string | null;
  goals: string | null;
};

const COMPETITIVE_WINDOWS = ["contending", "building", "rebuilding"] as const;

function UnsavedModal({ onSave, onDiscard, onCancel }: {
  onSave: () => void;
  onDiscard: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onCancel} />
      <div className="relative bg-white rounded-2xl shadow-xl p-6 w-full max-w-sm mx-4 space-y-4">
        <h2 className="text-lg font-semibold text-gray-900">Unsaved changes</h2>
        <p className="text-sm text-gray-500">
          You have unsaved changes to your Team Philosophy. What would you like to do?
        </p>
        <div className="flex flex-col gap-2">
          <button
            onClick={onSave}
            className="w-full px-4 py-2 rounded-xl bg-black text-white text-sm font-medium hover:bg-gray-800 transition"
          >
            Save and continue
          </button>
          <button
            onClick={onDiscard}
            className="w-full px-4 py-2 rounded-xl border border-gray-200 text-gray-700 text-sm font-medium hover:border-gray-400 transition"
          >
            Discard changes
          </button>
          <button
            onClick={onCancel}
            className="w-full px-4 py-2 rounded-xl text-gray-400 text-sm hover:text-gray-600 transition"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

export default function SettingsPage() {
  const { leagueId, setLeague } = useLeague();
  const router = useRouter();
  const [toastVisible, setToastVisible] = useState(false);

  // Saved (server) values — used to detect dirty state
  const [savedWindow, setSavedWindow] = useState<string | null>(null);
  const [savedCapPhilosophy, setSavedCapPhilosophy] = useState("");
  const [savedGoals, setSavedGoals] = useState("");

  // Working (local) values
  const [leagueName, setLeagueName] = useState("");
  const [competitiveWindow, setCompetitiveWindow] = useState<string | null>(null);
  const [capPhilosophy, setCapPhilosophy] = useState("");
  const [goals, setGoals] = useState("");

  // Dirty state
  const isDirty =
    competitiveWindow !== savedWindow ||
    capPhilosophy !== savedCapPhilosophy ||
    goals !== savedGoals;

  // View vs edit mode for the philosophy card
  const [editing, setEditing] = useState(false);

  // Unsaved modal state
  const [showModal, setShowModal] = useState(false);
  const pendingNavRef = useRef<string | null>(null);

  // Connect state (Fantrax + Sleeper share the league picker)
  const [platform, setPlatform] = useState<"fantrax" | "sleeper">("fantrax");
  const [secretId, setSecretId] = useState("");
  const [sleeperUsername, setSleeperUsername] = useState("");
  const [sleeperUserId, setSleeperUserId] = useState("");
  const [fantraxLeagues, setFantraxLeagues] = useState<FantraxLeague[]>([]);
  const [selectedFantraxLeagueId, setSelectedFantraxLeagueId] = useState("");
  const [connectLoading, setConnectLoading] = useState(false);
  const [connectMsg, setConnectMsg] = useState<string | null>(null);
  const [connectStep, setConnectStep] = useState<"idle" | "pick" | "done">("idle");

  // Data state
  const [mode, setMode] = useState<"in_season" | "offseason">("in_season");

  // CSV state
  const [csvLeagueName, setCsvLeagueName] = useState("");
  const [csvMsg, setCsvMsg] = useState<string | null>(null);
  const [leagues, setLeagues] = useState<{ id: string; name: string }[]>([]);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  // Load league row
  useEffect(() => {
    if (!leagueId) return;
    setEditing(false); // switching leagues returns the card to view mode
    supabase
      .from("leagues")
      .select("mode, fantrax_league_id, name, competitive_window, cap_philosophy, goals")
      .eq("id", leagueId)
      .single()
      .then(({ data }: { data: LeagueRow | null }) => {
        if (!data) return;
        if (data.mode) setMode(data.mode as "in_season" | "offseason");
        if (data.fantrax_league_id) setConnectStep("done");
        setLeagueName(data.name ?? "");

        const cw = data.competitive_window ?? null;
        const cp = data.cap_philosophy ?? "";
        const g = data.goals ?? "";

        setCompetitiveWindow(cw);
        setCapPhilosophy(cp);
        setGoals(g);

        setSavedWindow(cw);
        setSavedCapPhilosophy(cp);
        setSavedGoals(g);
      });
  }, [leagueId]);

  // Browser unload guard
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (isDirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [isDirty]);

  // Intercept nav link clicks when dirty
  useEffect(() => {
    if (!isDirty) return;
    const handler = (e: MouseEvent) => {
      const target = (e.target as HTMLElement).closest("a");
      if (!target || !target.href) return;
      const url = new URL(target.href);
      if (url.pathname === window.location.pathname) return;
      e.preventDefault();
      pendingNavRef.current = url.pathname + url.search;
      setShowModal(true);
    };
    document.addEventListener("click", handler, true);
    return () => document.removeEventListener("click", handler, true);
  }, [isDirty]);

  function showToast() {
    setToastVisible(true);
    setTimeout(() => setToastVisible(false), 2000);
  }

  async function savePhilosophy() {
    if (!leagueId) return;
    const { error } = await supabase
      .from("leagues")
      .update({
        competitive_window: competitiveWindow,
        cap_philosophy: capPhilosophy || null,
        goals: goals || null,
      })
      .eq("id", leagueId);
    if (!error) {
      setSavedWindow(competitiveWindow);
      setSavedCapPhilosophy(capPhilosophy);
      setSavedGoals(goals);
      setEditing(false);
      showToast();
    }
  }

  function cancelEdit() {
    setCompetitiveWindow(savedWindow);
    setCapPhilosophy(savedCapPhilosophy);
    setGoals(savedGoals);
    setEditing(false);
  }

  // Modal actions
  async function handleModalSave() {
    await savePhilosophy();
    setShowModal(false);
    if (pendingNavRef.current) {
      router.push(pendingNavRef.current);
      pendingNavRef.current = null;
    }
  }

  function handleModalDiscard() {
    setCompetitiveWindow(savedWindow);
    setCapPhilosophy(savedCapPhilosophy);
    setGoals(savedGoals);
    setEditing(false);
    setShowModal(false);
    if (pendingNavRef.current) {
      router.push(pendingNavRef.current);
      pendingNavRef.current = null;
    }
  }

  function handleModalCancel() {
    setShowModal(false);
    pendingNavRef.current = null;
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
    const { error } = await supabase.from("leagues").delete().eq("id", id);
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
      const fetched: FantraxLeague[] = json.leagues ?? [];
      if (fetched.length === 0) {
        setConnectMsg("No leagues found for this Secret ID.");
        return;
      }
      setFantraxLeagues(fetched);
      setSelectedFantraxLeagueId(fetched[0].leagueId);
      setConnectStep("pick");
    } catch (e: any) {
      setConnectMsg(e?.message ?? "Something went wrong.");
    } finally {
      setConnectLoading(false);
    }
  }

  function findLeagues() {
    return platform === "sleeper" ? fetchSleeperLeagues() : fetchFantraxLeagues();
  }

  async function fetchSleeperLeagues() {
    if (!sleeperUsername) return;
    setConnectLoading(true);
    setConnectMsg(null);
    try {
      const res = await fetch(`/api/sleeper/leagues?username=${encodeURIComponent(sleeperUsername)}`);
      if (!res.ok) throw new Error(await res.text());
      const json = await res.json();
      setSleeperUserId(json.user_id ?? "");
      const fetched: FantraxLeague[] = (json.leagues ?? []).map(
        (l: { leagueId: string; leagueName: string; sport: string; season?: string }) => ({
          leagueId: l.leagueId,
          leagueName: l.leagueName,
          sport: l.sport,
          season: l.season,
          teamName: l.season ? `${l.season}` : undefined,
        })
      );
      if (fetched.length === 0) {
        setConnectMsg("No NFL leagues found for that username.");
        return;
      }
      setFantraxLeagues(fetched);
      setSelectedFantraxLeagueId(fetched[0].leagueId);
      setConnectStep("pick");
    } catch (e: any) {
      setConnectMsg(e?.message ?? "Something went wrong.");
    } finally {
      setConnectLoading(false);
    }
  }

  async function connectSleeperLeague() {
    if (!selectedFantraxLeagueId) return;
    setConnectLoading(true);
    setConnectMsg(null);
    const picked = fantraxLeagues.find((l) => l.leagueId === selectedFantraxLeagueId);
    if (!picked) { setConnectLoading(false); return; }
    try {
      const { data: sessionData } = await supabase.auth.getSession();
      const user = sessionData.session?.user;
      if (!user) throw new Error("Not logged in.");

      const { data: existing } = await supabase
        .from("leagues")
        .select("id")
        .eq("owner_user_id", user.id)
        .eq("sleeper_league_id", picked.leagueId)
        .maybeSingle();

      const fields = {
        name: picked.leagueName,
        platform: "sleeper",
        sleeper_username: sleeperUsername,
        sleeper_user_id: sleeperUserId,
        sleeper_league_id: picked.leagueId,
        sport: "NFL",
      };

      let leagueRowId: string;
      if (existing) {
        leagueRowId = existing.id;
        await supabase.from("leagues").update(fields).eq("id", existing.id);
      } else {
        const { data: newLeague, error } = await supabase
          .from("leagues")
          .insert({ owner_user_id: user.id, ...fields })
          .select("id")
          .single();
        if (error) throw new Error(error.message);
        leagueRowId = newLeague.id;
      }

      setLeague(leagueRowId);
      setConnectStep("done");
      setSleeperUsername("");
      showToast();
      window.dispatchEvent(new Event("dynastyos:leagues-updated"));

      const syncRes = await authedFetch("/api/sleeper/sync", {
        method: "POST",
        body: JSON.stringify({ league_id: leagueRowId, sleeper_league_id: picked.leagueId }),
      });
      if (!syncRes.ok) {
        setConnectMsg("Connected, but the roster sync failed: " + (await syncRes.text()));
      }
    } catch (e: any) {
      setConnectMsg(e?.message ?? "Something went wrong.");
    } finally {
      setConnectLoading(false);
    }
  }

  async function connectLeague() {
    if (platform === "sleeper") return connectSleeperLeague();
    if (!selectedFantraxLeagueId) return;
    setConnectLoading(true);
    setConnectMsg(null);
    const picked = fantraxLeagues.find((l) => l.leagueId === selectedFantraxLeagueId);
    if (!picked) return;
    try {
      const { data: sessionData } = await supabase.auth.getSession();
      const user = sessionData.session?.user;
      if (!user) throw new Error("Not logged in.");

      // Reuse an existing row for this Fantrax league rather than inserting a new one.
      // A new row means a new UUID, which orphans (and cascade-deletes) the league's
      // cache, category ranks, and snapshots. Reconnecting should be non-destructive.
      const { data: existing } = await supabase
        .from("leagues")
        .select("id")
        .eq("owner_user_id", user.id)
        .eq("fantrax_league_id", picked.leagueId)
        .maybeSingle();

      let leagueRowId: string;
      if (existing) {
        leagueRowId = existing.id;
        await supabase
          .from("leagues")
          .update({
            fantrax_secret_id: secretId,
            name: picked.leagueName,
            sport: picked.sport,
          })
          .eq("id", existing.id);
      } else {
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
        leagueRowId = newLeague.id;
      }

      setLeague(leagueRowId);
      setConnectStep("done");
      setSecretId("");
      showToast();
      window.dispatchEvent(new Event("dynastyos:leagues-updated"));

      const syncRes = await fetch("/api/roster/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_secret_id: secretId, fantrax_league_id: picked.leagueId }),
      });
      if (syncRes.ok) {
        const syncJson = await syncRes.json();
        await supabase.from("snapshots").upsert({
          league_id: leagueRowId,
          owner_user_id: user.id,
          source: "fantrax",
          data: syncJson,
        }, { onConflict: "league_id,source" });
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

      {/* Unsaved modal */}
      {showModal && (
        <UnsavedModal
          onSave={handleModalSave}
          onDiscard={handleModalDiscard}
          onCancel={handleModalCancel}
        />
      )}

      {/* Team Philosophy */}
      {leagueId && (
        <div className="grid grid-cols-1 md:grid-cols-[200px_1fr] gap-4 md:gap-8 py-8 border-t border-gray-200">
          <div>
            <div className="text-xs font-semibold uppercase tracking-widest text-gray-400">Team Philosophy</div>
            <p className="text-sm text-gray-400 mt-2 leading-relaxed">
              Context used by the AI advisor across all tools.
            </p>
          </div>
          <div className="bg-white border rounded-2xl p-6 shadow-sm space-y-5">

            {/* Card header: which league + edit toggle */}
            <div className="flex items-start justify-between gap-3 pb-1">
              <div className="min-w-0">
                <div className="text-[11px] font-medium uppercase tracking-wide text-gray-400">
                  {editing ? "Editing philosophy for" : "Philosophy for"}
                </div>
                <div className="text-base font-semibold text-gray-900 truncate">
                  {leagueName || "Your league"}
                </div>
              </div>
              {!editing && (
                <button
                  onClick={() => setEditing(true)}
                  className="shrink-0 px-3 py-1.5 rounded-xl text-sm border border-gray-200 text-gray-700 hover:border-gray-400 transition"
                >
                  Edit
                </button>
              )}
            </div>

            {editing ? (
              <>
                {/* Competitive Window */}
                <div className="space-y-2">
                  <label className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                    Competitive Window
                  </label>
                  <div className="flex gap-2">
                    {COMPETITIVE_WINDOWS.map((w) => (
                      <button
                        key={w}
                        onClick={() => setCompetitiveWindow(w)}
                        className={`px-4 py-2 rounded-xl text-sm font-medium border transition ${
                          competitiveWindow === w
                            ? "bg-black text-white border-black"
                            : "bg-white text-gray-600 border-gray-200 hover:border-gray-400"
                        }`}
                      >
                        {w.charAt(0).toUpperCase() + w.slice(1)}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Cap Philosophy */}
                <div className="space-y-2">
                  <label className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                    Cap Philosophy
                  </label>
                  <textarea
                    value={capPhilosophy}
                    onChange={(e) => setCapPhilosophy(e.target.value)}
                    placeholder="e.g. Stay aggressive under cap, prioritize upside over floor, avoid long commitments to injury-prone players"
                    rows={3}
                    className="w-full px-3 py-2 rounded-xl border border-gray-200 bg-white text-sm outline-none focus:border-gray-400 resize-none"
                  />
                </div>

                {/* Goals */}
                <div className="space-y-2">
                  <label className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                    Season Goals
                  </label>
                  <textarea
                    value={goals}
                    onChange={(e) => setGoals(e.target.value)}
                    placeholder="e.g. Win the championship this year, upgrade SB and QS before the deadline"
                    rows={3}
                    className="w-full px-3 py-2 rounded-xl border border-gray-200 bg-white text-sm outline-none focus:border-gray-400 resize-none"
                  />
                </div>

                {/* Save / Cancel */}
                <div className="flex justify-end gap-2 pt-2">
                  <button
                    onClick={cancelEdit}
                    className="px-4 py-2 rounded-xl border border-gray-200 text-gray-600 text-sm font-medium hover:border-gray-400 transition"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={savePhilosophy}
                    disabled={!isDirty}
                    className="px-5 py-2 rounded-xl bg-black text-white text-sm font-medium disabled:opacity-30 disabled:cursor-not-allowed transition"
                  >
                    Save
                  </button>
                </div>
              </>
            ) : (
              <>
                {/* Read-only view */}
                <div className="space-y-1.5">
                  <div className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                    Competitive Window
                  </div>
                  {competitiveWindow ? (
                    <span className="inline-block px-3 py-1 rounded-lg bg-gray-100 text-gray-700 text-sm font-medium capitalize">
                      {competitiveWindow}
                    </span>
                  ) : (
                    <p className="text-sm text-gray-300 italic">Not set</p>
                  )}
                </div>

                <div className="space-y-1.5">
                  <div className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                    Cap Philosophy
                  </div>
                  {capPhilosophy ? (
                    <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-line">{capPhilosophy}</p>
                  ) : (
                    <p className="text-sm text-gray-300 italic">Not set</p>
                  )}
                </div>

                <div className="space-y-1.5">
                  <div className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                    Season Goals
                  </div>
                  {goals ? (
                    <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-line">{goals}</p>
                  ) : (
                    <p className="text-sm text-gray-300 italic">Not set</p>
                  )}
                </div>
              </>
            )}

          </div>
        </div>
      )}

      {/* League Rules */}
      {leagueId && (
        <div className="grid grid-cols-1 md:grid-cols-[200px_1fr] gap-4 md:gap-8 py-8 border-t border-gray-200">
          <div>
            <div className="text-xs font-semibold uppercase tracking-widest text-gray-400">League Rules</div>
            <p className="text-sm text-gray-400 mt-2 leading-relaxed">
              The league setup the AI uses to judge trades.
            </p>
          </div>
          <LeagueRulesEditor leagueId={leagueId} />
        </div>
      )}

      {/* Fantrax */}
      <div className="grid grid-cols-1 md:grid-cols-[200px_1fr] gap-4 md:gap-8 py-8 border-t border-gray-200">
        <div>
          <div className="text-xs font-semibold uppercase tracking-widest text-gray-400">Fantrax</div>
          <p className="text-sm text-gray-400 mt-2 leading-relaxed">
            Connect your Fantrax account to enable direct roster sync.
          </p>
        </div>
        <div className="space-y-4">
          <div className="bg-white border rounded-2xl p-6 shadow-sm space-y-4">
            <h3 className="text-lg font-semibold">Connect a League</h3>

            <div className="space-y-2">
              <label className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                Platform
              </label>
              <select
                value={platform}
                onChange={(e) => {
                  setPlatform(e.target.value as "fantrax" | "sleeper");
                  setConnectStep("idle");
                  setFantraxLeagues([]);
                  setConnectMsg(null);
                }}
                className="w-full px-3 py-2 rounded-xl border border-gray-200 bg-white text-sm outline-none focus:border-gray-400"
              >
                <option value="fantrax">Fantrax (baseball)</option>
                <option value="sleeper">Sleeper (football)</option>
              </select>
            </div>

            {connectStep === "done" && (
              <div className="text-sm text-gray-700 bg-gray-50 border border-gray-200 rounded-xl p-3">
                Connected. To connect another league, pick a platform and find leagues below.
              </div>
            )}

            {platform === "fantrax" ? (
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
            ) : (
              <div className="space-y-2">
                <label className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                  Sleeper Username
                </label>
                <input
                  value={sleeperUsername}
                  onChange={(e) => {
                    setSleeperUsername(e.target.value);
                    setConnectStep("idle");
                    setFantraxLeagues([]);
                  }}
                  placeholder="Your public Sleeper username"
                  className="w-full px-3 py-2 rounded-xl border border-gray-200 bg-white text-sm outline-none focus:border-gray-400"
                />
              </div>
            )}

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
                      {l.leagueName}{l.teamName ? ` — ${l.teamName}` : ""}
                    </option>
                  ))}
                </select>
              </div>
            )}

            <div className="flex gap-2">
              {connectStep !== "pick" && (
                <button
                  onClick={findLeagues}
                  disabled={connectLoading || (platform === "fantrax" ? !secretId : !sleeperUsername)}
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

          {leagues.length > 0 && (
            <div className="bg-white border rounded-2xl p-6 shadow-sm space-y-3">
              <h3 className="text-lg font-semibold">Your Leagues</h3>
              <p className="text-sm text-gray-500">Manage your connected leagues.</p>
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
                        <span className="text-xs text-red-600">Erases ranks, history &amp; cache</span>
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
        <div className="grid grid-cols-1 md:grid-cols-[200px_1fr] gap-4 md:gap-8 py-8 border-t border-gray-200">
          <div>
            <div className="text-xs font-semibold uppercase tracking-widest text-gray-400">Data</div>
            <p className="text-sm text-gray-400 mt-2 leading-relaxed">
              Configure how roster data is calculated and displayed.
            </p>
          </div>
          <div className="bg-white border rounded-2xl p-6 shadow-sm space-y-3">
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
      <div className="grid grid-cols-1 md:grid-cols-[200px_1fr] gap-4 md:gap-8 py-8 border-t border-gray-200">
        <div>
          <div className="text-xs font-semibold uppercase tracking-widest text-gray-400">Manual / CSV</div>
          <p className="text-sm text-gray-400 mt-2 leading-relaxed">
            Fallback option if you're not using Fantrax sync.
          </p>
        </div>
        <div className="space-y-4">
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

      <div className="border-t border-gray-200" />
    </main>
  );
}