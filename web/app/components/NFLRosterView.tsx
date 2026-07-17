"use client";

import { useEffect, useState } from "react";
import { supabase } from "../lib/supabaseClient";

type NFLItem = {
  id: string;
  name?: string;
  position?: string;
  team?: string;
  status?: string; // "starter" | "bench"
  injury_status?: string | null;
  age?: number | null;
  years_exp?: number | null;
};

const POS_ORDER: Record<string, number> = { QB: 0, RB: 1, WR: 2, TE: 3, K: 4, DEF: 5 };

function byPosThenName(a: NFLItem, b: NFLItem): number {
  const pa = POS_ORDER[a.position ?? ""] ?? 9;
  const pb = POS_ORDER[b.position ?? ""] ?? 9;
  if (pa !== pb) return pa - pb;
  return (a.name ?? "").localeCompare(b.name ?? "");
}

function InjuryBadge({ status }: { status?: string | null }) {
  if (!status) return null;
  const bad = ["IR", "Out", "Doubtful", "PUP", "Sus"].some((s) =>
    status.toLowerCase().startsWith(s.toLowerCase())
  );
  return (
    <span
      className={`ml-2 inline-block px-1.5 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wide ${
        bad ? "bg-red-100 text-red-800" : "bg-amber-100 text-amber-800"
      }`}
    >
      {status}
    </span>
  );
}

function RosterGroup({ title, items }: { title: string; items: NFLItem[] }) {
  if (items.length === 0) return null;
  return (
    <div className="bg-gray-50 border rounded-2xl p-4 md:p-6 shadow-sm space-y-3">
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-semibold">{title}</h2>
        <span className="text-sm text-gray-500">{items.length}</span>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="border-b text-left text-gray-600">
            <tr>
              <th className="py-2 pr-4">Player</th>
              <th className="py-2 pr-4">Pos</th>
              <th className="py-2 pr-4">Team</th>
              <th className="py-2 pr-4">Age</th>
              <th className="py-2">Exp</th>
            </tr>
          </thead>
          <tbody>
            {items.map((p) => (
              <tr key={p.id} className="border-b last:border-0">
                <td className="py-2 pr-4 font-medium whitespace-nowrap">
                  {p.name ?? "—"}
                  <InjuryBadge status={p.injury_status} />
                </td>
                <td className="py-2 pr-4">{p.position ?? "—"}</td>
                <td className="py-2 pr-4">{p.team || "FA"}</td>
                <td className="py-2 pr-4">{p.age ?? "—"}</td>
                <td className="py-2">
                  {p.years_exp === 0 ? "R" : p.years_exp != null ? `${p.years_exp} yr` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Roster view for Sleeper football leagues — points-based, no salaries or
 * contracts, so the /roster tab shows the synced roster instead of the Cap
 * Planner. Reads the owner-scoped rosters row directly. */
export function NFLRosterView({ leagueId }: { leagueId: string }) {
  const [teamName, setTeamName] = useState<string>("");
  const [items, setItems] = useState<NFLItem[] | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!leagueId) return;
    let active = true;
    (async () => {
      setLoading(true);
      setItems(null);
      const { data: lg } = await supabase
        .from("leagues")
        .select("fantrax_team_id")
        .eq("id", leagueId)
        .single();
      const teamId = lg?.fantrax_team_id;
      if (!teamId) {
        if (active) setLoading(false);
        return;
      }
      const { data: rows } = await supabase
        .from("rosters")
        .select("team_name, roster_items")
        .eq("league_id", leagueId)
        .eq("fantrax_team_id", teamId)
        .limit(1);
      if (!active) return;
      const row = rows?.[0];
      setTeamName((row?.team_name as string) ?? "");
      setItems(((row?.roster_items as NFLItem[]) ?? []).slice());
      setLoading(false);
    })();
    return () => {
      active = false;
    };
  }, [leagueId]);

  if (loading) return <div className="text-sm text-gray-500">Loading roster...</div>;

  if (!items || items.length === 0) {
    return (
      <div className="text-sm text-gray-500 bg-gray-50 border rounded-2xl p-6 shadow-sm">
        No synced roster yet — hit Sync in the nav to pull it from Sleeper.
      </div>
    );
  }

  const starters = items.filter((p) => p.status === "starter").sort(byPosThenName);
  const bench = items.filter((p) => p.status !== "starter").sort(byPosThenName);

  return (
    <div className="space-y-6">
      {teamName && <div className="text-sm text-gray-500">{teamName}</div>}
      <RosterGroup title="Starters" items={starters} />
      <RosterGroup title="Bench" items={bench} />
    </div>
  );
}
