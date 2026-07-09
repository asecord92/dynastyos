"use client";

import { useEffect, useMemo, useState } from "react";
import { supabase } from "../lib/supabaseClient";
import { authedFetch } from "../lib/useDashboardWidget";
import { aiIssueFromDetail, useAiStatus } from "../lib/aiStatus";
import { NeedsApiKey } from "./ui/NeedsApiKey";
import { Spinner } from "./ui/Spinner";

type RosterItem = {
  id: string;
  position: string;
  salary?: number;
  status: string;
  contract?: { name: string };
  name?: string;
};

type PlayerOption = {
  id: string;
  name: string;
  position: string;
  salary: number;
  contract: string;
  owner: string;
};

type Incoming = { id?: string; name: string };

/** Renders the streamed ranked-drop text: **bold** names + numbered lines. */
function DropRenderer({ text }: { text: string }) {
  return (
    <div className="space-y-1.5">
      {text.split("\n").map((line, i) => {
        const parts = line.split(/\*\*(.*?)\*\*/g);
        return (
          <p
            key={i}
            className={line.trim() === "" ? "h-1.5" : "text-sm text-gray-700 leading-relaxed"}
          >
            {parts.map((part, j) => (j % 2 === 1 ? <strong key={j}>{part}</strong> : part))}
          </p>
        );
      })}
    </div>
  );
}

export function AddDropPanel({
  leagueId,
  myTeamId,
}: {
  leagueId: string;
  myTeamId: string;
}) {
  const { reportIssue, clearIssue } = useAiStatus();

  const [myPlayers, setMyPlayers] = useState<PlayerOption[]>([]);
  const [allPlayers, setAllPlayers] = useState<PlayerOption[]>([]);

  const [incoming, setIncoming] = useState<Incoming[]>([]);
  const [outgoing, setOutgoing] = useState<string[]>([]);
  const [incomingQuery, setIncomingQuery] = useState("");
  const [freeText, setFreeText] = useState("");

  const [loading, setLoading] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [needsApiKey, setNeedsApiKey] = useState(false);

  // Load rosters + resolve names (mirrors the trade page).
  useEffect(() => {
    if (!leagueId || !myTeamId) return;
    let cancelled = false;

    async function load() {
      const { data: rosterRows } = await supabase
        .from("rosters")
        .select("fantrax_team_id, team_name, roster_items")
        .eq("league_id", leagueId);
      if (!rosterRows || cancelled) return;

      const map: Record<string, string> = {};
      rosterRows.forEach((r) =>
        (r.roster_items as RosterItem[]).forEach((it) => {
          if (it.name) map[it.id] = it.name;
        })
      );
      const allIds = rosterRows.flatMap((r) =>
        (r.roster_items as RosterItem[]).map((it) => it.id)
      );
      const [{ data: idMapRows }, { data: fantraxRows }] = await Promise.all([
        supabase.from("player_id_map").select("fantrax_id, full_name").in("fantrax_id", allIds),
        supabase.from("fantrax_players").select("fantrax_id, name").in("fantrax_id", allIds),
      ]);
      fantraxRows?.forEach((r) => (map[r.fantrax_id] = r.name));
      idMapRows?.forEach((r) => (map[r.fantrax_id] = r.full_name));
      if (cancelled) return;

      const toOption = (it: RosterItem, owner: string): PlayerOption => ({
        id: it.id,
        name: map[it.id] || it.name || `Unknown (${it.id})`,
        position: it.position,
        salary: it.salary ?? 0,
        contract: it.contract?.name ?? "?",
        owner,
      });

      const all: PlayerOption[] = [];
      let mine: PlayerOption[] = [];
      rosterRows.forEach((r) => {
        const opts = (r.roster_items as RosterItem[]).map((it) =>
          toOption(it, r.team_name as string)
        );
        all.push(...opts);
        if (r.fantrax_team_id === myTeamId) mine = opts;
      });
      setAllPlayers(all.sort((a, b) => a.name.localeCompare(b.name)));
      setMyPlayers(mine.sort((a, b) => b.salary - a.salary));
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [leagueId, myTeamId]);

  const incomingIds = useMemo(
    () => new Set(incoming.map((i) => i.id).filter(Boolean)),
    [incoming]
  );

  const incomingResults = useMemo(() => {
    const q = incomingQuery.trim().toLowerCase();
    if (!q) return [];
    return allPlayers
      .filter(
        (p) =>
          !incomingIds.has(p.id) &&
          (p.name.toLowerCase().includes(q) || p.position.toLowerCase().includes(q))
      )
      .slice(0, 8);
  }, [incomingQuery, allPlayers, incomingIds]);

  const spotsNeeded = Math.max(0, incoming.length - outgoing.length);

  function addIncoming(p: PlayerOption) {
    setIncoming((prev) => [...prev, { id: p.id, name: p.name }]);
    setIncomingQuery("");
  }
  function addFreeText() {
    const name = freeText.trim();
    if (!name) return;
    setIncoming((prev) => [...prev, { name }]);
    setFreeText("");
  }
  function removeIncoming(idx: number) {
    setIncoming((prev) => prev.filter((_, i) => i !== idx));
  }
  function toggleOutgoing(id: string) {
    setOutgoing((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  async function analyze() {
    if (incoming.length === 0 && outgoing.length === 0) return;
    setLoading(true);
    setStreamText("");
    setError(null);
    setNeedsApiKey(false);
    try {
      const res = await authedFetch("/api/waivers/add-drop", {
        method: "POST",
        body: JSON.stringify({
          league_id: leagueId,
          my_team_id: myTeamId,
          incoming,
          outgoing_ids: outgoing,
        }),
      });
      if (res.status === 402 || res.status === 429) {
        const detail = await res.json().then((j) => j?.detail as string | undefined).catch(() => undefined);
        const issue = aiIssueFromDetail(detail);
        if (issue) reportIssue(issue);
        else if (res.status === 429) setError("Anthropic is rate-limiting your key — try again in a moment.");
        else setNeedsApiKey(true);
        return;
      }
      if (!res.ok) throw new Error(await res.text());
      if (!res.body) throw new Error("No response body");
      clearIssue();

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        setStreamText((prev) => prev + decoder.decode(value));
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  const canAnalyze = incoming.length > 0 && !loading;

  return (
    <div className="bg-gray-50 border rounded-2xl p-6 shadow-sm space-y-5">
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">Add / Drop Analyzer</h2>
        <p className="text-sm text-gray-500">
          Adding a player off IL, from waivers, or in a lopsided trade? Pick who&apos;s coming in
          (and anyone already leaving) and get a ranked list of who to drop.
        </p>
      </div>

      {/* Incoming */}
      <div className="space-y-2">
        <label className="text-xs font-medium text-gray-500 uppercase tracking-wide">
          Adding
        </label>
        <input
          value={incomingQuery}
          onChange={(e) => setIncomingQuery(e.target.value)}
          placeholder="Search any player in the league…"
          className="w-full px-3 py-2 rounded-xl border border-gray-200 bg-gray-50 text-sm outline-none focus:border-gray-400"
        />
        {incomingResults.length > 0 && (
          <div className="border border-gray-200 rounded-xl overflow-hidden max-h-56 overflow-y-auto">
            {incomingResults.map((p) => (
              <button
                key={p.id}
                onClick={() => addIncoming(p)}
                className="w-full flex items-center justify-between px-4 py-2.5 text-sm border-b border-gray-100 last:border-0 hover:bg-gray-50 transition text-left"
              >
                <span className="flex items-center gap-2">
                  <span className="font-medium text-gray-900">{p.name}</span>
                  <span className="text-xs text-gray-400">{p.position}</span>
                </span>
                <span className="text-xs text-gray-400">{p.owner}</span>
              </button>
            ))}
          </div>
        )}
        {/* Free-text add for a waiver pickup / prospect not on any roster */}
        <div className="flex gap-2">
          <input
            value={freeText}
            onChange={(e) => setFreeText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addFreeText()}
            placeholder="…or type a name (waiver/prospect)"
            className="flex-1 px-3 py-2 rounded-xl border border-gray-200 bg-gray-50 text-sm outline-none focus:border-gray-400"
          />
          <button
            onClick={addFreeText}
            disabled={!freeText.trim()}
            className="px-3 py-2 rounded-xl text-sm border border-gray-200 hover:border-gray-300 disabled:opacity-40 transition"
          >
            Add
          </button>
        </div>
        {incoming.length > 0 && (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {incoming.map((inc, i) => (
              <span
                key={`${inc.id ?? inc.name}-${i}`}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-violet-600 text-white text-xs font-medium"
              >
                {inc.name}
                {!inc.id && <span className="opacity-60">(FA)</span>}
                <button onClick={() => removeIncoming(i)} className="ml-0.5 hover:text-gray-300">
                  ×
                </button>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Already leaving (optional) */}
      <div className="space-y-2">
        <label className="text-xs font-medium text-gray-500 uppercase tracking-wide">
          Already dropping / trading away (optional)
        </label>
        <div className="border border-gray-200 rounded-xl overflow-hidden max-h-48 overflow-y-auto">
          {myPlayers.map((p) => (
            <button
              key={p.id}
              onClick={() => toggleOutgoing(p.id)}
              className={`w-full flex items-center justify-between px-4 py-2 text-sm border-b border-gray-100 last:border-0 transition hover:bg-gray-50 ${
                outgoing.includes(p.id) ? "bg-red-50 text-red-900" : ""
              }`}
            >
              <span className="flex items-center gap-2">
                <span className="font-medium">{p.name}</span>
                <span className="text-xs text-gray-400">{p.position}</span>
              </span>
              <span className="text-xs text-gray-400">${p.salary}</span>
            </button>
          ))}
          {myPlayers.length === 0 && (
            <div className="px-4 py-3 text-sm text-gray-400">Loading your roster…</div>
          )}
        </div>
      </div>

      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-gray-400">
          {incoming.length === 0
            ? "Add at least one incoming player."
            : spotsNeeded > 0
            ? `Need to clear ${spotsNeeded} spot${spotsNeeded > 1 ? "s" : ""}.`
            : "No drop strictly required — you'll still get the most-expendable list."}
        </p>
        <button
          onClick={analyze}
          disabled={!canAnalyze}
          className="px-4 py-2.5 rounded-xl bg-violet-600 text-white text-sm font-medium disabled:opacity-30 disabled:cursor-not-allowed transition hover:bg-violet-700 inline-flex items-center gap-2"
        >
          {loading && <Spinner />}
          {loading ? "Analyzing…" : "Who should I drop?"}
        </button>
      </div>

      {needsApiKey && <NeedsApiKey feature="The add/drop analyzer" />}

      {error && (
        <div className="text-sm text-red-300 bg-red-50 border border-red-500/30 rounded-xl p-3">
          {error}
        </div>
      )}

      {loading && !streamText && (
        <div className="text-sm text-gray-400 animate-pulse">Weighing your roster…</div>
      )}

      {streamText && (
        <div className="border-t border-gray-100 pt-4">
          <DropRenderer text={streamText} />
        </div>
      )}
    </div>
  );
}
