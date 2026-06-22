"use client";

import { useEffect, useState } from "react";
import { supabase } from "../lib/supabaseClient";
import { readCache, writeCache } from "../lib/clientCache";

const CATEGORIES = ["R", "HR", "RBI", "SB", "OBP", "QS", "SV", "K", "ERA", "WHIP"];
const TOTAL_TEAMS = 10;

type Ranks = Partial<Record<string, number>>;

function rankColor(rank: number): string {
  if (rank <= 3) return "bg-green-500";
  if (rank <= 7) return "bg-amber-400";
  return "bg-red-500";
}

function rankTextColor(rank: number): string {
  if (rank <= 3) return "text-green-300";
  if (rank <= 7) return "text-amber-300";
  return "text-red-400";
}

function barWidth(rank: number): string {
  const pct = Math.round(((TOTAL_TEAMS - rank + 1) / TOTAL_TEAMS) * 100);
  return `${Math.max(pct, 8)}%`;
}

export function CategoryRanksWidget({
  leagueId,
  myTeamId,
  initialRanks,
  initialUpdatedAt,
}: {
  leagueId: string;
  myTeamId: string;
  initialRanks?: { [k: string]: number };
  initialUpdatedAt?: string | null;
}) {
  const cacheKey = leagueId ? `dynastyos:catranks:${leagueId}` : null;
  const seeded = cacheKey
    ? readCache<{ ranks: Ranks; updatedAt: string | null }>(cacheKey)
    : null;

  const [ranks, setRanks] = useState<Ranks>(
    (initialRanks && Object.keys(initialRanks).length ? initialRanks : seeded?.ranks) ?? {}
  );
  const [loading, setLoading] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [computing, setComputing] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<string | null>(
    initialUpdatedAt ?? seeded?.updatedAt ?? null
  );

  function cacheRanks(r: Ranks, u: string | null) {
    if (cacheKey) writeCache(cacheKey, { ranks: r, updatedAt: u });
  }

  async function fetchRanks() {
    if (!leagueId) return;
    setLoading(true);
    try {
      const { data: sessionData } = await supabase.auth.getSession();
      const token = sessionData.session?.access_token;
      const res = await fetch(`/api/league/category-ranks?league_id=${leagueId}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (res.ok) {
        const json = await res.json();
        setRanks(json.ranks ?? {});
        setUpdatedAt(json.updated_at ?? null);
        cacheRanks(json.ranks ?? {}, json.updated_at ?? null);
      }
    } catch {}
    finally { setLoading(false); }
  }

  useEffect(() => { fetchRanks(); }, [leagueId]);

  // Seed from the dashboard summary if it resolves first and we have nothing yet.
  useEffect(() => {
    if (initialRanks && Object.keys(initialRanks).length > 0 && Object.keys(ranks).length === 0) {
      setRanks(initialRanks);
      if (initialUpdatedAt) setUpdatedAt(initialUpdatedAt);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialRanks, initialUpdatedAt]);

  // Kick off the background approximation, then poll until the stored ranks change.
  async function autoCalc() {
    if (!leagueId || !myTeamId || computing) return;
    setComputing(true);
    try {
      const { data: sessionData } = await supabase.auth.getSession();
      const token = sessionData.session?.access_token;
      const authHeader: Record<string, string> = token
        ? { Authorization: `Bearer ${token}` }
        : {};
      const before = updatedAt;

      const res = await fetch("/api/league/category-ranks/compute", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeader },
        body: JSON.stringify({ league_id: leagueId, my_team_id: myTeamId }),
      });
      if (!res.ok) throw new Error(await res.text());

      for (let i = 0; i < 15; i++) {
        await new Promise((r) => setTimeout(r, 6000));
        const poll = await fetch(`/api/league/category-ranks?league_id=${leagueId}`, {
          headers: authHeader,
        });
        if (poll.ok) {
          const json = await poll.json();
          if (json.updated_at && json.updated_at !== before) {
            setRanks(json.ranks ?? {});
            setUpdatedAt(json.updated_at);
            cacheRanks(json.ranks ?? {}, json.updated_at);
            break;
          }
        }
      }
    } catch {}
    finally { setComputing(false); }
  }

  function openEdit() {
    const current: Record<string, string> = {};
    for (const cat of CATEGORIES) {
      current[cat] = ranks[cat] != null ? String(ranks[cat]) : "";
    }
    setDraft(current);
    setEditOpen(true);
  }

  async function saveRanks() {
    setSaving(true);
    try {
      const { data: sessionData } = await supabase.auth.getSession();
      const token = sessionData.session?.access_token;
      const payload: Ranks = {};
      for (const cat of CATEGORIES) {
        const v = parseInt(draft[cat] ?? "", 10);
        if (!isNaN(v) && v >= 1 && v <= TOTAL_TEAMS) payload[cat] = v;
      }
      await fetch("/api/league/category-ranks", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ league_id: leagueId, ranks: payload }),
      });
      setRanks(payload);
      setUpdatedAt(new Date().toISOString());
      cacheRanks(payload, new Date().toISOString());
      setEditOpen(false);
    } catch {}
    finally { setSaving(false); }
  }

  const hasRanks = CATEGORIES.some((c) => ranks[c] != null);

  return (
    <>
      <div className="bg-gray-50 border rounded-2xl p-6 shadow-sm space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Category Ranks</h2>
          <div className="flex items-center gap-1">
          <button
            onClick={autoCalc}
            disabled={computing || !myTeamId}
            className="px-2 py-1 rounded-lg text-xs border border-gray-200 text-gray-500 hover:border-gray-300 disabled:opacity-40 transition"
            title="Estimate ranks from current rosters"
          >
            {computing ? "Calculating…" : "Auto"}
          </button>
          <button
            onClick={openEdit}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition"
            title="Edit ranks"
          >
            {/* Pencil icon */}
            <svg width="15" height="15" viewBox="0 0 15 15" fill="none">
              <path
                d="M11.89 1.11a1.5 1.5 0 012.12 2.12L4.5 12.75l-2.83.71.71-2.83L11.89 1.11z"
                stroke="currentColor"
                strokeWidth="1.25"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
          </div>
        </div>

        {loading && !hasRanks && (
          <div className="space-y-2 animate-pulse">
            {CATEGORIES.map((c) => (
              <div key={c} className="flex items-center gap-2">
                <div className="w-10 h-3 bg-gray-100 rounded" />
                <div className="flex-1 h-4 bg-gray-100 rounded" />
              </div>
            ))}
          </div>
        )}

        {!loading && !hasRanks && (
          <p className="text-sm text-gray-400">
            No ranks set.{" "}
            <button onClick={openEdit} className="underline text-gray-500">
              Add your ranks
            </button>{" "}
            or{" "}
            <button
              onClick={autoCalc}
              disabled={computing || !myTeamId}
              className="underline text-gray-500 disabled:opacity-40"
            >
              {computing ? "calculating…" : "auto-calculate"}
            </button>{" "}
            from your rosters.
          </p>
        )}

        {hasRanks && (
          <div className="space-y-2">
            {CATEGORIES.map((cat) => {
              const rank = ranks[cat];
              if (rank == null) return null;
              return (
                <div key={cat} className="flex items-center gap-3">
                  <span className="w-10 text-xs font-medium text-gray-500 text-right shrink-0">
                    {cat}
                  </span>
                  <div className="flex-1 bg-gray-100 rounded-full h-4 overflow-hidden">
                    <div
                      className={`h-full rounded-full ${rankColor(rank)} transition-all`}
                      style={{ width: barWidth(rank) }}
                    />
                  </div>
                  <span
                    className={`w-6 text-xs font-semibold text-right shrink-0 ${rankTextColor(rank)}`}
                  >
                    {rank}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Edit modal */}
      {editOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/40 backdrop-blur-sm"
            onClick={() => setEditOpen(false)}
          />
          <div className="relative bg-gray-50 rounded-2xl shadow-xl p-6 w-full max-w-sm mx-4 space-y-5">
            <h2 className="text-lg font-semibold">Edit Category Ranks</h2>
            <p className="text-xs text-gray-500">
              Enter your rank for each category (1 = best, {TOTAL_TEAMS} = worst).
            </p>
            <div className="grid grid-cols-2 gap-3">
              {CATEGORIES.map((cat) => (
                <div key={cat} className="space-y-1">
                  <label className="text-xs font-medium text-gray-500">{cat}</label>
                  <input
                    type="number"
                    min={1}
                    max={TOTAL_TEAMS}
                    value={draft[cat] ?? ""}
                    onChange={(e) => setDraft((d) => ({ ...d, [cat]: e.target.value }))}
                    className="w-full px-2.5 py-1.5 rounded-lg border border-gray-200 text-sm outline-none focus:border-gray-400"
                    placeholder="—"
                  />
                </div>
              ))}
            </div>
            <div className="flex gap-2 pt-1">
              <button
                onClick={saveRanks}
                disabled={saving}
                className="flex-1 px-4 py-2 rounded-xl bg-indigo-600 text-white text-sm font-medium disabled:opacity-40 transition"
              >
                {saving ? "Saving..." : "Save"}
              </button>
              <button
                onClick={() => setEditOpen(false)}
                className="px-4 py-2 rounded-xl border border-gray-200 text-sm text-gray-600 hover:border-gray-300 transition"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
