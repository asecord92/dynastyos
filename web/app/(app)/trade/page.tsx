"use client";

import { useState, useEffect, useRef } from "react";
import { supabase } from "../../lib/supabaseClient";
import { useLeague } from "../../lib/useLeague";
import { authedFetch } from "../../lib/useDashboardWidget";

const CATEGORIES = ["R", "HR", "RBI", "SB", "OBP", "QS", "SV", "K", "ERA", "WHIP"];

type Candidate = {
  fantrax_id: string;
  name: string;
  position: string;
  salary: number;
  contract: string;
  owner_team_id: string;
  owner_team_name: string;
  stat_value: number;
  value?: number | null;
};

type PackagePlayer = { fantrax_id: string; name: string };

type TradePackage = {
  owner_team_id: string;
  owner_team_name: string;
  target_ids: string[];
  offer_ids: string[];
  targets: PackagePlayer[];
  offer: PackagePlayer[];
  rationale: string;
};

type FinderResult = {
  target_category: string;
  candidates: Candidate[];
  packages: TradePackage[];
  analysis: string;
};

type TeamRoster = {
  fantrax_team_id: string;
  team_name: string;
  roster_items: RosterItem[];
};

type RosterItem = {
  id: string;
  position: string;
  salary: number;
  status: string;
  contract: { name: string; smallId: string };
};

type PlayerOption = {
  id: string;
  name: string;
  position: string;
  salary: number;
  contract: string;
  status: string;
};

function PlayerSearch({
  label,
  players,
  selected,
  onToggle,
}: {
  label: string;
  players: PlayerOption[];
  selected: string[];
  onToggle: (id: string) => void;
}) {
  const [query, setQuery] = useState("");

  const filtered = players.filter((p) =>
    p.name.toLowerCase().includes(query.toLowerCase()) ||
    p.position.toLowerCase().includes(query.toLowerCase())
  );

  return (
    <div className="space-y-2">
      <label className="text-xs font-medium text-gray-500 uppercase tracking-wide">
        {label}
      </label>
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search players..."
        className="w-full px-3 py-2 rounded-xl border border-gray-200 bg-white text-sm outline-none focus:border-gray-400"
      />
      <div className="border border-gray-200 rounded-xl overflow-hidden max-h-64 overflow-y-auto">
        {filtered.length === 0 && (
          <div className="px-4 py-3 text-sm text-gray-400">No players found.</div>
        )}
        {filtered.map((p) => (
          <button
            key={p.id}
            onClick={() => onToggle(p.id)}
            className={`w-full flex items-center justify-between px-4 py-2.5 text-sm border-b border-gray-100 last:border-0 transition hover:bg-gray-50 ${
              selected.includes(p.id) ? "bg-gray-950 text-white hover:bg-gray-800" : ""
            }`}
          >
            <div className="flex items-center gap-3 text-left">
              <span className={`font-medium ${selected.includes(p.id) ? "text-white" : "text-gray-900"}`}>
                {p.name}
              </span>
              <span className="text-xs text-gray-400">
                {p.position}
              </span>
              <span className="text-xs text-gray-400">
                {p.contract} yr
              </span>
            </div>
            <span className={`text-xs font-medium ${selected.includes(p.id) ? "text-gray-300" : "text-gray-500"}`}>
              ${p.salary}
            </span>
          </button>
        ))}
      </div>
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-1">
          {selected.map((id) => {
            const p = players.find((x) => x.id === id);
            if (!p) return null;
            return (
              <span
                key={id}
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-gray-900 text-white text-xs font-medium"
              >
                {p.name}
                <button
                  onClick={() => onToggle(id)}
                  className="ml-0.5 text-gray-400 hover:text-white transition"
                >
                  ×
                </button>
              </span>
            );
          })}
        </div>
      )}
    </div>
  );
}

function AnalysisRenderer({ text }: { text: string }) {
  const sections = {
    verdict: "",
    analysis: "",
    counter: "",
  };

  const verdictMatch = text.match(/VERDICT\s*([\s\S]*?)(?=ANALYSIS|$)/i);
  const analysisMatch = text.match(/ANALYSIS\s*([\s\S]*?)(?=COUNTER OFFER|$)/i);
  const counterMatch = text.match(/COUNTER OFFER\s*([\s\S]*?)$/i);

  if (verdictMatch) sections.verdict = verdictMatch[1].trim();
  if (analysisMatch) sections.analysis = analysisMatch[1].trim();
  if (counterMatch) sections.counter = counterMatch[1].trim();

  const verdictWord = sections.verdict.split(/[\s—–-]/)[0].toUpperCase();
  const verdictColor =
    verdictWord === "ACCEPT"
      ? "bg-green-50 border-green-200 text-green-900"
      : verdictWord === "DECLINE"
      ? "bg-red-50 border-red-200 text-red-900"
      : "bg-amber-50 border-amber-200 text-amber-900";

  return (
    <div className="space-y-4">
      {sections.verdict && (
        <div className={`border rounded-2xl p-5 ${verdictColor}`}>
          <div className="text-xs font-semibold uppercase tracking-widest mb-1 opacity-60">
            Verdict
          </div>
          <p className="font-semibold text-lg leading-snug">{sections.verdict}</p>
        </div>
      )}

      {sections.analysis && (
        <div className="bg-white border rounded-2xl p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-widest text-gray-400 mb-3">
            Analysis
          </div>
          <div className="space-y-3">
            {sections.analysis.split("\n\n").map((para, i) => (
              <p key={i} className="text-sm text-gray-700 leading-relaxed">
                {para.trim()}
              </p>
            ))}
          </div>
        </div>
      )}

      {sections.counter && (
        <div className="bg-white border rounded-2xl p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-widest text-gray-400 mb-3">
            Counter Offer
          </div>
          <div className="space-y-3">
            {sections.counter.split("\n\n").map((para, i) => (
              <p key={i} className="text-sm text-gray-700 leading-relaxed">
                {para.trim()}
              </p>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function TradePage() {
  const { leagueId } = useLeague();

  const [myTeamId, setMyTeamId] = useState("");
  const [teams, setTeams] = useState<TeamRoster[]>([]);
  const [playerNameMap, setPlayerNameMap] = useState<Record<string, string>>({});
  const [opponentTeamId, setOpponentTeamId] = useState("");
  const [myPlayers, setMyPlayers] = useState<PlayerOption[]>([]);
  const [oppPlayers, setOppPlayers] = useState<PlayerOption[]>([]);
  const [offering, setOffering] = useState<string[]>([]);
  const [receiving, setReceiving] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [error, setError] = useState<string | null>(null);

  const [mode, setMode] = useState<"build" | "find">("build");
  const [finderLoading, setFinderLoading] = useState(false);
  const [finderError, setFinderError] = useState<string | null>(null);
  const [finder, setFinder] = useState<FinderResult | null>(null);
  // Carries a prefill target across the opponent-change effect (which clears receiving).
  const pendingReceiveRef = useRef<string[] | null>(null);

  useEffect(() => {
    if (!leagueId) return;

    async function load() {
      // Get my team ID from leagues table
      const { data: leagueRow } = await supabase
        .from("leagues")
        .select("fantrax_team_id")
        .eq("id", leagueId)
        .single();

      if (leagueRow?.fantrax_team_id) {
        setMyTeamId(leagueRow.fantrax_team_id);
      }

      // Load all rosters
      const { data: rosterRows } = await supabase
        .from("rosters")
        .select("fantrax_team_id, team_name, roster_items")
        .eq("league_id", leagueId);

      if (rosterRows) setTeams(rosterRows as TeamRoster[]);

      // Get all fantrax IDs from loaded rosters
      const allRosterIds = (rosterRows as TeamRoster[])?.flatMap(
        (r) => r.roster_items.map((item) => item.id)
      ) ?? [];

      // Load player name map — resolved players first, fill gaps from fantrax_players
      const { data: idMapRows } = await supabase
        .from("player_id_map")
        .select("fantrax_id, full_name")
        .in("fantrax_id", allRosterIds);

      const { data: fantraxPlayerRows } = await supabase
        .from("fantrax_players")
        .select("fantrax_id, name")
        .in("fantrax_id", allRosterIds);

      if (idMapRows || fantraxPlayerRows) {
        const map: Record<string, string> = {};
        // fantrax_players first (lower priority)
        fantraxPlayerRows?.forEach((r) => { map[r.fantrax_id] = r.name; });
        // resolved players override (higher priority — better names)
        idMapRows?.forEach((r) => { map[r.fantrax_id] = r.full_name; });
        setPlayerNameMap(map);
      }
    }

    load();
  }, [leagueId]);

  useEffect(() => {
    if (!myTeamId || teams.length === 0) return;
    const myTeam = teams.find((t) => t.fantrax_team_id === myTeamId);
    if (myTeam) {
      setMyPlayers(buildPlayerOptions(myTeam.roster_items, playerNameMap));
    }
  }, [myTeamId, teams, playerNameMap]);

  useEffect(() => {
    if (!opponentTeamId || teams.length === 0) return;
    const oppTeam = teams.find((t) => t.fantrax_team_id === opponentTeamId);
    if (oppTeam) {
      setOppPlayers(buildPlayerOptions(oppTeam.roster_items, playerNameMap));
    }
    // Preserve a prefilled target (from the Trade Finder), else clear selection.
    if (pendingReceiveRef.current) {
      setReceiving(pendingReceiveRef.current);
      pendingReceiveRef.current = null;
    } else {
      setReceiving([]);
    }
  }, [opponentTeamId, teams, playerNameMap]);

  async function runFinder(category?: string) {
    if (!leagueId || !myTeamId) return;
    setFinderLoading(true);
    setFinderError(null);
    try {
      const res = await authedFetch("/api/trade/finder", {
        method: "POST",
        body: JSON.stringify({
          league_id: leagueId,
          my_team_id: myTeamId,
          target_category: category ?? null,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      setFinder((await res.json()) as FinderResult);
    } catch (e: unknown) {
      setFinderError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setFinderLoading(false);
    }
  }

  function targetPlayer(c: Candidate) {
    setMode("build");
    if (opponentTeamId === c.owner_team_id) {
      setReceiving([c.fantrax_id]);
    } else {
      pendingReceiveRef.current = [c.fantrax_id];
      setOpponentTeamId(c.owner_team_id);
    }
  }

  // Load a full Finder-suggested package into the trade builder: my players to
  // send (offering), the opponent + their players to receive.
  function loadPackage(pkg: TradePackage) {
    setMode("build");
    setOffering(pkg.offer_ids);
    if (opponentTeamId === pkg.owner_team_id) {
      setReceiving(pkg.target_ids);
    } else {
      pendingReceiveRef.current = pkg.target_ids;
      setOpponentTeamId(pkg.owner_team_id);
    }
  }

  function buildPlayerOptions(
    items: RosterItem[],
    nameMap: Record<string, string>
  ): PlayerOption[] {
    return items
      .map((item) => ({
        id: item.id,
        name: nameMap[item.id] || `Unknown (${item.id})`,
        position: item.position,
        salary: item.salary,
        contract: item.contract?.name ?? "?",
        status: item.status,
      }))
      .sort((a, b) => b.salary - a.salary);
  }

  function toggleOffering(id: string) {
    setOffering((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  }

  function toggleReceiving(id: string) {
    setReceiving((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  }

  async function analyze() {
    if (!leagueId || !myTeamId || !opponentTeamId || offering.length === 0 || receiving.length === 0) return;

    setLoading(true);
    setStreamText("");
    setError(null);

    try {
      const { data: sessionData } = await supabase.auth.getSession();
      const accessToken = sessionData.session?.access_token;

      const res = await fetch("/api/trade/analyze", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
        body: JSON.stringify({
          league_id: leagueId,
          my_team_id: myTeamId,
          opponent_team_id: opponentTeamId,
          offering_ids: offering.join(","),
          receiving_ids: receiving.join(","),
        }),
      });

      if (!res.ok) throw new Error(await res.text());
      if (!res.body) throw new Error("No response body");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        setStreamText((prev) => prev + decoder.decode(value));
      }
    } catch (e: any) {
      setError(e?.message ?? "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  const canAnalyze = !!(leagueId && myTeamId && opponentTeamId && offering.length > 0 && receiving.length > 0 && !loading);

  const modeClass = (active: boolean) =>
    `px-3 py-1.5 rounded-xl text-sm border transition ${
      active
        ? "bg-black text-white border-black"
        : "bg-white text-gray-700 border-gray-200 hover:border-gray-300"
    }`;

  return (
    <main className="space-y-8">
      <header className="space-y-1">
        <h1 className="text-3xl font-semibold">Trade Analyzer</h1>
        <p className="text-gray-700">
          Build a specific trade, or find targets for a category you need.
        </p>
      </header>

      {!leagueId && (
        <div className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-xl p-4">
          Select a league from the nav to use the trade analyzer.
        </div>
      )}

      {leagueId && (
        <div className="space-y-6">
          {/* Mode toggle */}
          <div className="flex gap-2">
            <button onClick={() => setMode("build")} className={modeClass(mode === "build")}>
              Build Trade
            </button>
            <button onClick={() => setMode("find")} className={modeClass(mode === "find")}>
              Find Targets
            </button>
          </div>

          {mode === "build" && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
          {/* Left — trade builder */}
          <div className="bg-white border rounded-2xl p-6 shadow-sm space-y-6">
            <h2 className="text-lg font-semibold">Build Trade</h2>

            <div className="space-y-2">
              <label className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                Opponent Team
              </label>
              <select
                value={opponentTeamId}
                onChange={(e) => setOpponentTeamId(e.target.value)}
                className="w-full px-3 py-2 rounded-xl border border-gray-200 bg-white text-sm outline-none focus:border-gray-400"
              >
                <option value="">Select a team...</option>
                {teams
                  .filter((t) => t.fantrax_team_id !== myTeamId)
                  .map((t) => (
                    <option key={t.fantrax_team_id} value={t.fantrax_team_id}>
                      {t.team_name}
                    </option>
                  ))}
              </select>
            </div>

            {opponentTeamId && (
              <>
                <PlayerSearch
                  label="They Offer"
                  players={oppPlayers}
                  selected={receiving}
                  onToggle={toggleReceiving}
                />
                <PlayerSearch
                  label="You Give Up"
                  players={myPlayers}
                  selected={offering}
                  onToggle={toggleOffering}
                />
              </>
            )}

            <button
              onClick={analyze}
              disabled={!canAnalyze}
              className="w-full px-4 py-3 rounded-xl bg-black text-white text-sm font-medium disabled:opacity-30 disabled:cursor-not-allowed transition hover:bg-gray-800"
            >
              {loading ? "Analyzing..." : "Analyze Trade"}
            </button>

            {error && (
              <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-xl p-3">
                {error}
              </div>
            )}
          </div>

          {/* Right — analysis output */}
          <div className="space-y-4">
            {!streamText && !loading && (
              <div className="bg-white border rounded-2xl p-6 shadow-sm text-sm text-gray-400">
                Select an opponent, pick players, and hit Analyze Trade to get a recommendation.
              </div>
            )}

            {loading && !streamText && (
              <div className="bg-white border rounded-2xl p-6 shadow-sm text-sm text-gray-400 animate-pulse">
                Analyzing trade...
              </div>
            )}

            {streamText && <AnalysisRenderer text={streamText} />}
          </div>
          </div>
          )}

          {mode === "find" && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
              {/* Left — category picker */}
              <div className="bg-white border rounded-2xl p-6 shadow-sm space-y-4">
                <h2 className="text-lg font-semibold">Find Targets</h2>
                <p className="text-sm text-gray-500">
                  Pick a category you need help in. We&apos;ll rank the best targets across
                  the league by their production in that category.
                </p>
                <div className="flex flex-wrap gap-2">
                  {CATEGORIES.map((cat) => (
                    <button
                      key={cat}
                      onClick={() => runFinder(cat)}
                      disabled={finderLoading || !myTeamId}
                      className={`px-3 py-1.5 rounded-xl text-sm border transition disabled:opacity-40 ${
                        finder?.target_category === cat
                          ? "bg-black text-white border-black"
                          : "bg-white text-gray-700 border-gray-200 hover:border-gray-300"
                      }`}
                    >
                      {cat}
                    </button>
                  ))}
                </div>
                <button
                  onClick={() => runFinder()}
                  disabled={finderLoading || !myTeamId}
                  className="w-full px-4 py-3 rounded-xl bg-black text-white text-sm font-medium disabled:opacity-30 disabled:cursor-not-allowed transition hover:bg-gray-800"
                >
                  {finderLoading ? "Finding..." : "Find my weakest category"}
                </button>
                {finderError && (
                  <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-xl p-3">
                    {finderError}
                  </div>
                )}
              </div>

              {/* Right — results */}
              <div className="space-y-4">
                {!finder && !finderLoading && (
                  <div className="bg-white border rounded-2xl p-6 shadow-sm text-sm text-gray-400">
                    Pick a category to see acquisition targets.
                  </div>
                )}
                {finderLoading && (
                  <div className="bg-white border rounded-2xl p-6 shadow-sm text-sm text-gray-400 animate-pulse">
                    Scanning the league...
                  </div>
                )}
                {finder && !finderLoading && (
                  <>
                    <div className="bg-white border rounded-2xl p-6 shadow-sm space-y-3">
                      <div className="text-xs font-semibold uppercase tracking-widest text-gray-400">
                        Targets for {finder.target_category}
                      </div>
                      <div className="divide-y divide-gray-50">
                        {finder.candidates.map((c) => (
                          <button
                            key={c.fantrax_id}
                            onClick={() => targetPlayer(c)}
                            className="w-full py-2.5 flex items-center justify-between gap-3 text-left hover:bg-gray-50 rounded-lg px-2 transition"
                          >
                            <div className="min-w-0">
                              <div className="flex items-center gap-2 flex-wrap">
                                <span className="text-sm font-medium text-gray-900">{c.name}</span>
                                <span className="text-xs text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">
                                  {c.position}
                                </span>
                                <span className="text-xs text-gray-400">${c.salary}</span>
                              </div>
                              <p className="text-xs text-gray-400 mt-0.5">{c.owner_team_name}</p>
                            </div>
                            <span className="shrink-0 text-right">
                              <span className="block text-sm font-semibold text-gray-900">
                                {finder.target_category} {c.stat_value}
                              </span>
                              {c.value != null && (
                                <span className="block text-xs text-gray-400">val {c.value}</span>
                              )}
                            </span>
                          </button>
                        ))}
                        {finder.candidates.length === 0 && (
                          <p className="text-sm text-gray-400 py-2">No candidates found.</p>
                        )}
                      </div>
                      <p className="text-xs text-gray-400">
                        Click a target to prefill the trade builder.
                      </p>
                    </div>
                    {finder.packages?.length > 0 && (
                      <div className="bg-white border rounded-2xl p-5 shadow-sm space-y-3">
                        <div className="text-xs font-semibold uppercase tracking-widest text-gray-400">
                          Suggested packages
                        </div>
                        <div className="space-y-2.5">
                          {finder.packages.map((pkg, i) => (
                            <div key={i} className="border border-gray-100 rounded-xl p-3 space-y-1.5">
                              <div className="text-sm text-gray-900">
                                <span className="font-medium">Send</span>{" "}
                                {pkg.offer.map((p) => p.name).join(", ")}{" "}
                                <span className="text-gray-400">→</span>{" "}
                                <span className="font-medium">Get</span>{" "}
                                {pkg.targets.map((p) => p.name).join(", ")}
                              </div>
                              <div className="text-xs text-gray-400">
                                {pkg.owner_team_name}
                                {pkg.rationale ? ` · ${pkg.rationale}` : ""}
                              </div>
                              <button
                                onClick={() => loadPackage(pkg)}
                                className="text-xs font-medium text-indigo-600 hover:text-indigo-700"
                              >
                                Load into Build Trade →
                              </button>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                    {finder.analysis && (
                      <div className="bg-white border rounded-2xl p-5 shadow-sm">
                        <div className="text-xs font-semibold uppercase tracking-widest text-gray-400 mb-3">
                          Recommendation
                        </div>
                        <div className="space-y-3">
                          {finder.analysis.split("\n\n").map((para, i) => (
                            <p key={i} className="text-sm text-gray-700 leading-relaxed">
                              {para.trim()}
                            </p>
                          ))}
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </main>
  );
}