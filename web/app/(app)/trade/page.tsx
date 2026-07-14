"use client";

import { useState, useEffect, useRef } from "react";
import { supabase } from "../../lib/supabaseClient";
import { useLeague } from "../../lib/useLeague";
import { authedFetch } from "../../lib/useDashboardWidget";
import { aiIssueFromDetail, useAiStatus } from "../../lib/aiStatus";
import { NeedsApiKey } from "../../components/ui/NeedsApiKey";

const CATEGORIES = ["R", "HR", "RBI", "SB", "OBP", "QS", "SV", "K", "ERA", "WHIP"];
const NFL_POSITIONS = ["QB", "RB", "WR", "TE"];

/** First line of the VERDICT section (both MLB and NFL prompts emit one). */
function extractVerdict(text: string): string {
  const m = text.match(/VERDICT\s*([\s\S]*?)(?=ANALYSIS|$)/i);
  return m ? m[1].trim().split("\n")[0].trim() : "";
}

function timeAgo(iso: string): string {
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

/** Tailwind classes for a verdict pill, by its leading word. */
function verdictColor(verdict: string): string {
  const word = verdict.split(/[\s—–-]/)[0].toUpperCase();
  if (word === "ACCEPT") return "bg-green-50 border-green-500/30 text-green-900";
  if (word === "DECLINE") return "bg-red-50 border-red-500/30 text-red-900";
  return "bg-amber-50 border-amber-500/30 text-amber-900";
}

type TradeHistoryPlayer = { id: string; name: string };
type TradeHistoryRow = {
  id: string;
  created_at: string;
  offering: TradeHistoryPlayer[];
  receiving: TradeHistoryPlayer[];
  verdict: string | null;
  analysis: string;
};

type Candidate = {
  fantrax_id: string;
  name: string;
  position: string;
  salary?: number;
  contract?: string;
  team?: string;
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

type FinderEvent =
  | { type: "meta"; target_category: string; candidates: Candidate[] }
  | { type: "text"; delta: string }
  | { type: "packages"; packages: TradePackage[]; analysis: string }
  | { type: "error"; detail: string };

type DraftPick = { season: number; round: number; label: string; original_roster_id: number };

type TeamRoster = {
  fantrax_team_id: string;
  team_name: string;
  roster_items: RosterItem[];
  draft_picks?: DraftPick[];
};

type RosterItem = {
  id: string;
  position: string;
  salary?: number;
  status: string;
  contract?: { name: string; smallId: string };
  name?: string;   // embedded for Sleeper/NFL
  team?: string;   // embedded for Sleeper/NFL
};

type PlayerOption = {
  id: string;
  name: string;
  position: string;
  salary: number;
  contract: string;
  status: string;
  detail?: string;  // right-aligned label (NFL: position/team); MLB falls back to salary
  isPick?: boolean;
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
        className="w-full px-3 py-2 rounded-xl border border-gray-200 bg-gray-50 text-sm outline-none focus:border-gray-400"
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
              selected.includes(p.id) ? "bg-violet-600 text-white hover:bg-violet-700" : ""
            }`}
          >
            <div className="flex items-center gap-3 text-left">
              <span className={`font-medium ${selected.includes(p.id) ? "text-white" : "text-gray-900"}`}>
                {p.name}
              </span>
              <span className="text-xs text-gray-400">
                {p.position}
              </span>
              {!p.detail && (
                <span className="text-xs text-gray-400">
                  {p.contract} yr
                </span>
              )}
            </div>
            <span className={`text-xs font-medium ${selected.includes(p.id) ? "text-gray-300" : "text-gray-500"}`}>
              {p.detail ?? `$${p.salary}`}
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
                className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-gray-100 text-gray-900 text-xs font-medium"
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
      ? "bg-green-50 border-green-500/30 text-green-900"
      : verdictWord === "DECLINE"
      ? "bg-red-50 border-red-500/30 text-red-900"
      : "bg-amber-50 border-amber-500/30 text-amber-900";

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
        <div className="bg-gray-50 border rounded-2xl p-5 shadow-sm">
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
        <div className="bg-gray-50 border rounded-2xl p-5 shadow-sm">
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
  const { leagueId, sport } = useLeague();
  const isNFL = sport === "NFL";

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
  // 402 from the backend = no Anthropic key on file (BYOK). Shared across both flows.
  const [needsApiKey, setNeedsApiKey] = useState(false);

  // Key-level failures (out of credits / rejected key) go to the app-wide banner.
  const { reportIssue, clearIssue } = useAiStatus();

  const [mode, setMode] = useState<"build" | "find" | "history">("build");
  const [historyItems, setHistoryItems] = useState<TradeHistoryRow[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [expandedHistoryId, setExpandedHistoryId] = useState<string | null>(null);
  const [finderLoading, setFinderLoading] = useState(false);
  const [finderError, setFinderError] = useState<string | null>(null);
  const [finder, setFinder] = useState<FinderResult | null>(null);
  // Carries a prefill target across the opponent-change effect (which clears receiving).
  const pendingReceiveRef = useRef<string[] | null>(null);

  // Cancel in-flight analysis/finder streams on unmount or league switch —
  // the read loops would otherwise keep running and setState on a dead
  // component. Separate controllers: the two streams can run concurrently.
  const analyzeAbortRef = useRef<AbortController | null>(null);
  const finderAbortRef = useRef<AbortController | null>(null);
  useEffect(() => {
    return () => {
      analyzeAbortRef.current?.abort();
      finderAbortRef.current?.abort();
    };
  }, [leagueId]);

  useEffect(() => {
    if (!leagueId) return;
    let cancelled = false;

    // A league switch invalidates everything selected under the old league,
    // plus any streamed analysis/finder output that was still on screen.
    setOpponentTeamId("");
    setOffering([]);
    setReceiving([]);
    pendingReceiveRef.current = null;
    setStreamText("");
    setError(null);
    setLoading(false);
    setFinder(null);
    setFinderError(null);
    setFinderLoading(false);

    async function load() {
      // Get my team ID from leagues table
      const { data: leagueRow } = await supabase
        .from("leagues")
        .select("fantrax_team_id")
        .eq("id", leagueId)
        .single();

      if (cancelled) return;
      if (leagueRow?.fantrax_team_id) {
        setMyTeamId(leagueRow.fantrax_team_id);
      }

      // Load all rosters (draft_picks is NFL-only)
      const { data: rosterRows } = await supabase
        .from("rosters")
        .select("fantrax_team_id, team_name, roster_items, draft_picks")
        .eq("league_id", leagueId);

      if (cancelled) return;
      if (rosterRows) setTeams(rosterRows as TeamRoster[]);

      // Base name map from embedded roster data (Sleeper/NFL carries names inline).
      const map: Record<string, string> = {};
      (rosterRows as TeamRoster[])?.forEach((r) =>
        r.roster_items.forEach((item) => {
          if (item.name) map[item.id] = item.name;
        })
      );

      // For Fantrax/MLB, resolve names from the id maps (NFL ids aren't there).
      const allRosterIds = (rosterRows as TeamRoster[])?.flatMap(
        (r) => r.roster_items.map((item) => item.id)
      ) ?? [];
      const { data: idMapRows } = await supabase
        .from("player_id_map")
        .select("fantrax_id, full_name")
        .in("fantrax_id", allRosterIds);
      const { data: fantraxPlayerRows } = await supabase
        .from("fantrax_players")
        .select("fantrax_id, name")
        .in("fantrax_id", allRosterIds);
      if (cancelled) return;
      fantraxPlayerRows?.forEach((r) => { map[r.fantrax_id] = r.name; });
      idMapRows?.forEach((r) => { map[r.fantrax_id] = r.full_name; });
      setPlayerNameMap(map);
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [leagueId]);

  useEffect(() => {
    if (!myTeamId || teams.length === 0) return;
    const myTeam = teams.find((t) => t.fantrax_team_id === myTeamId);
    if (myTeam) {
      setMyPlayers(buildPlayerOptions(myTeam.roster_items, playerNameMap, myTeam.draft_picks));
    }
  }, [myTeamId, teams, playerNameMap]);

  useEffect(() => {
    if (!opponentTeamId || teams.length === 0) return;
    const oppTeam = teams.find((t) => t.fantrax_team_id === opponentTeamId);
    if (oppTeam) {
      setOppPlayers(buildPlayerOptions(oppTeam.roster_items, playerNameMap, oppTeam.draft_picks));
    }
    // Preserve a prefilled target (from the Trade Finder), else clear selection.
    if (pendingReceiveRef.current) {
      setReceiving(pendingReceiveRef.current);
      pendingReceiveRef.current = null;
    } else {
      setReceiving([]);
    }
  }, [opponentTeamId, teams, playerNameMap]);

  // Load the user's saved analyses when the History tab is opened.
  useEffect(() => {
    if (mode !== "history" || !leagueId) return;
    let cancelled = false;
    (async () => {
      setHistoryLoading(true);
      try {
        const res = await authedFetch(`/api/trade/history?league_id=${leagueId}`);
        const json = await res.json();
        if (!cancelled) setHistoryItems(json.items ?? []);
      } catch {
        if (!cancelled) setHistoryItems([]);
      } finally {
        if (!cancelled) setHistoryLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [mode, leagueId]);

  // Persist a completed analysis to the user's private history (best-effort).
  async function saveHistory(analysis: string) {
    if (!leagueId || !analysis.trim()) return;
    try {
      await authedFetch("/api/trade/history", {
        method: "POST",
        body: JSON.stringify({
          league_id: leagueId,
          offering: offering.map((id) => ({ id, name: playerNameMap[id] || id })),
          receiving: receiving.map((id) => ({ id, name: playerNameMap[id] || id })),
          verdict: extractVerdict(analysis),
          analysis,
        }),
      });
    } catch {
      /* best-effort — never disrupt the analysis the user just saw */
    }
  }

  async function runFinder(category?: string) {
    if (!leagueId || !myTeamId) return;
    finderAbortRef.current?.abort();
    const ac = new AbortController();
    finderAbortRef.current = ac;
    setFinderLoading(true);
    setFinderError(null);
    setNeedsApiKey(false);
    setFinder(null);
    try {
      const res = await authedFetch("/api/trade/finder", {
        method: "POST",
        signal: ac.signal,
        body: JSON.stringify({
          league_id: leagueId,
          my_team_id: myTeamId,
          target_category: category ?? null,
        }),
      });
      if (res.status === 402 || res.status === 429) {
        const detail = await res.json().then((j) => j?.detail as string | undefined).catch(() => undefined);
        const issue = aiIssueFromDetail(detail);
        if (issue) reportIssue(issue);
        else if (res.status === 429) setFinderError("Anthropic is rate-limiting your key — try again in a moment.");
        else setNeedsApiKey(true);
        return;
      }
      if (!res.ok || !res.body) throw new Error(await res.text());
      clearIssue();

      let analysisText = "";
      const apply = (evt: FinderEvent) => {
        if (evt.type === "meta") {
          // Targets arrive before the AI — render them and drop the spinner.
          setFinder({
            target_category: evt.target_category,
            candidates: evt.candidates ?? [],
            packages: [],
            analysis: "",
          });
          setFinderLoading(false);
        } else if (evt.type === "text") {
          analysisText += evt.delta ?? "";
          setFinder((prev) => (prev ? { ...prev, analysis: analysisText } : prev));
        } else if (evt.type === "packages") {
          setFinder((prev) =>
            prev
              ? { ...prev, packages: evt.packages ?? [], analysis: evt.analysis ?? analysisText }
              : prev
          );
        } else if (evt.type === "error") {
          // Key/billing errors surface mid-stream (after the 200) as an event.
          const issue = aiIssueFromDetail(evt.detail);
          if (issue) reportIssue(issue);
          else if (evt.detail === "rate_limited")
            setFinderError("Anthropic is rate-limiting your key — try again in a moment.");
          else setFinderError(evt.detail ?? "Something went wrong.");
        }
      };

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      const flush = (line: string) => {
        const t = line.trim();
        if (!t) return;
        try {
          apply(JSON.parse(t) as FinderEvent);
        } catch {
          /* ignore a partial/garbled line */
        }
      };
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";
        for (const line of lines) flush(line);
      }
      flush(buf);
    } catch (e: unknown) {
      if (!ac.signal.aborted) {
        setFinderError(e instanceof Error ? e.message : "Something went wrong.");
      }
    } finally {
      // Clear loading unless a newer run has taken over (its own spinner is
      // up); on abort-while-mounted this still clears, on unmount React no-ops.
      if (finderAbortRef.current === ac) setFinderLoading(false);
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
    nameMap: Record<string, string>,
    picks?: DraftPick[]
  ): PlayerOption[] {
    const players: PlayerOption[] = items.map((item) => ({
      id: item.id,
      name: nameMap[item.id] || item.name || `Unknown (${item.id})`,
      position: item.position,
      salary: item.salary ?? 0,
      contract: item.contract?.name ?? "?",
      status: item.status,
      detail: isNFL ? (item.team || "FA") : undefined,
    }));
    if (!isNFL) return players.sort((a, b) => b.salary - a.salary);
    // NFL: players A-Z, then draft picks as tradeable assets.
    players.sort((a, b) => a.name.localeCompare(b.name));
    const pickOptions: PlayerOption[] = (picks ?? []).map((pk) => ({
      id: `pick:${pk.season}:${pk.round}:${pk.original_roster_id}`,
      name: pk.label,
      position: "PICK",
      salary: 0,
      contract: "?",
      status: "",
      detail: "draft pick",
      isPick: true,
    }));
    return [...players, ...pickOptions];
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

    analyzeAbortRef.current?.abort();
    const ac = new AbortController();
    analyzeAbortRef.current = ac;
    setLoading(true);
    setStreamText("");
    setError(null);
    setNeedsApiKey(false);

    try {
      const res = await authedFetch("/api/trade/analyze", {
        method: "POST",
        signal: ac.signal,
        body: JSON.stringify({
          league_id: leagueId,
          my_team_id: myTeamId,
          opponent_team_id: opponentTeamId,
          offering_ids: offering.join(","),
          receiving_ids: receiving.join(","),
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

      // ndjson events (same protocol as the finder): `meta` commits the stream
      // before the model finishes thinking, `text` deltas carry the analysis,
      // and key/billing errors arrive as `error` events after the 200.
      let full = "";
      let failed = false;
      const apply = (evt: { type?: string; delta?: string; detail?: string }) => {
        if (evt.type === "text") {
          full += evt.delta ?? "";
          setStreamText(full);
        } else if (evt.type === "error") {
          failed = true;
          const issue = aiIssueFromDetail(evt.detail);
          if (issue) reportIssue(issue);
          else if (evt.detail === "rate_limited")
            setError("Anthropic is rate-limiting your key — try again in a moment.");
          else setError(evt.detail ?? "Something went wrong.");
        }
      };

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      const flush = (line: string) => {
        const t = line.trim();
        if (!t) return;
        try {
          apply(JSON.parse(t));
        } catch {
          /* ignore a partial/garbled line */
        }
      };
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";
        for (const line of lines) flush(line);
      }
      flush(buf);
      if (!failed && full) saveHistory(full);
    } catch (e: unknown) {
      if (!ac.signal.aborted) {
        setError(e instanceof Error ? e.message : "Something went wrong.");
      }
    } finally {
      // Clear loading unless a newer run has taken over (its own spinner is
      // up); on abort-while-mounted this still clears, on unmount React no-ops.
      if (analyzeAbortRef.current === ac) setLoading(false);
    }
  }

  const canAnalyze = !!(leagueId && myTeamId && opponentTeamId && offering.length > 0 && receiving.length > 0 && !loading);

  const modeClass = (active: boolean) =>
    `px-3 py-1.5 rounded-xl text-sm border transition ${
      active
        ? "bg-violet-600 text-white border-violet-600"
        : "bg-gray-50 text-gray-700 border-gray-200 hover:border-gray-300"
    }`;

  return (
    <main className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold">Trade Analyzer</h1>
        <p className="text-sm text-gray-600">
          Build a specific trade, or find targets for a category you need.
        </p>
      </header>

      {!leagueId && (
        <div className="text-sm text-amber-300 bg-amber-50 border border-amber-500/30 rounded-xl p-4">
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
            <button onClick={() => setMode("history")} className={modeClass(mode === "history")}>
              History
            </button>
          </div>

          {mode === "build" && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
          {/* Left — trade builder */}
          <div className="bg-gray-50 border rounded-2xl p-5 shadow-sm space-y-5 lg:sticky lg:top-6">
            <h2 className="text-lg font-semibold">Build Trade</h2>

            <div className="space-y-2">
              <label className="text-xs font-medium text-gray-500 uppercase tracking-wide">
                Opponent Team
              </label>
              <select
                value={opponentTeamId}
                onChange={(e) => setOpponentTeamId(e.target.value)}
                className="w-full px-3 py-2 rounded-xl border border-gray-200 bg-gray-50 text-sm outline-none focus:border-gray-400"
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
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
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
              </div>
            )}

            <button
              onClick={analyze}
              disabled={!canAnalyze}
              className="w-full px-4 py-3 rounded-xl bg-violet-600 text-white text-sm font-medium disabled:opacity-30 disabled:cursor-not-allowed transition hover:bg-violet-700"
            >
              {loading ? "Analyzing..." : "Analyze Trade"}
            </button>

            {error && (
              <div className="text-sm text-red-300 bg-red-50 border border-red-500/30 rounded-xl p-3">
                {error}
              </div>
            )}
          </div>

          {/* Right — analysis output */}
          <div className="space-y-4">
            {needsApiKey && <NeedsApiKey feature="Trade analysis" />}

            {!streamText && !loading && !needsApiKey && (
              <div className="bg-gray-50 border rounded-2xl p-6 shadow-sm text-sm text-gray-400">
                Select an opponent, pick players, and hit Analyze Trade to get a recommendation.
              </div>
            )}

            {loading && !streamText && (
              <div className="bg-gray-50 border rounded-2xl p-6 shadow-sm text-sm text-gray-400 animate-pulse">
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
              <div className="bg-gray-50 border rounded-2xl p-5 shadow-sm space-y-4 lg:sticky lg:top-6">
                <h2 className="text-lg font-semibold">Find Targets</h2>
                <p className="text-sm text-gray-500">
                  {isNFL
                    ? "Pick a position you need help at. We'll rank the best targets across the league by last season's fantasy points."
                    : "Pick a category you need help in. We'll rank the best targets across the league by their production in that category."}
                </p>
                <div className="flex flex-wrap gap-2">
                  {(isNFL ? NFL_POSITIONS : CATEGORIES).map((cat) => (
                    <button
                      key={cat}
                      onClick={() => runFinder(cat)}
                      disabled={finderLoading || !myTeamId}
                      className={`px-3 py-1.5 rounded-xl text-sm border transition disabled:opacity-40 ${
                        finder?.target_category === cat
                          ? "bg-violet-600 text-white border-violet-600"
                          : "bg-gray-50 text-gray-700 border-gray-200 hover:border-gray-300"
                      }`}
                    >
                      {cat}
                    </button>
                  ))}
                </div>
                <button
                  onClick={() => runFinder()}
                  disabled={finderLoading || !myTeamId}
                  className="w-full px-4 py-3 rounded-xl bg-violet-600 text-white text-sm font-medium disabled:opacity-30 disabled:cursor-not-allowed transition hover:bg-violet-700"
                >
                  {finderLoading
                    ? "Finding..."
                    : isNFL
                    ? "Find my weakest position"
                    : "Find my weakest category"}
                </button>
                {finderError && (
                  <div className="text-sm text-red-300 bg-red-50 border border-red-500/30 rounded-xl p-3">
                    {finderError}
                  </div>
                )}
              </div>

              {/* Right — results */}
              <div className="space-y-4">
                {needsApiKey && <NeedsApiKey feature="Trade Finder" />}

                {!finder && !finderLoading && !needsApiKey && (
                  <div className="bg-gray-50 border rounded-2xl p-6 shadow-sm text-sm text-gray-400">
                    Pick a {isNFL ? "position" : "category"} to see acquisition targets.
                  </div>
                )}
                {finderLoading && (
                  <div className="bg-gray-50 border rounded-2xl p-6 shadow-sm text-sm text-gray-400 animate-pulse">
                    Scanning the league...
                  </div>
                )}
                {finder && !finderLoading && (
                  <>
                    <div className="bg-gray-50 border rounded-2xl p-6 shadow-sm space-y-3">
                      <div className="text-xs font-semibold uppercase tracking-widest text-gray-400">
                        Targets for {finder.target_category}
                      </div>
                      <div className="divide-y divide-gray-50 max-h-80 overflow-y-auto">
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
                                <span className="text-xs text-gray-400">
                                  {isNFL ? c.team : `$${c.salary}`}
                                </span>
                              </div>
                              <p className="text-xs text-gray-400 mt-0.5">{c.owner_team_name}</p>
                            </div>
                            <span className="shrink-0 text-right">
                              <span className="block text-sm font-semibold text-gray-900">
                                {isNFL ? `${c.stat_value} pts` : `${finder.target_category} ${c.stat_value}`}
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
                      <div className="bg-gray-50 border rounded-2xl p-5 shadow-sm space-y-3">
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
                                className="text-xs font-medium text-violet-600 hover:text-violet-300"
                              >
                                Load into Build Trade →
                              </button>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                    {finder.analysis ? (
                      <div className="bg-gray-50 border rounded-2xl p-5 shadow-sm">
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
                    ) : (
                      <div className="bg-gray-50 border rounded-2xl p-5 shadow-sm text-sm text-gray-400 animate-pulse">
                        Analyzing targets and building offers…
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          )}

          {mode === "history" && (
            <div className="space-y-4">
              {historyLoading && (
                <div className="bg-gray-50 border rounded-2xl p-6 shadow-sm text-sm text-gray-400 animate-pulse">
                  Loading your recent analyses…
                </div>
              )}
              {!historyLoading && historyItems.length === 0 && (
                <div className="bg-gray-50 border rounded-2xl p-6 shadow-sm text-sm text-gray-400">
                  No analyzed trades yet. Build a trade and hit Analyze — it&apos;ll show up here.
                </div>
              )}
              {!historyLoading &&
                historyItems.map((h) => {
                  const expanded = expandedHistoryId === h.id;
                  return (
                    <div key={h.id} className="bg-gray-50 border rounded-2xl p-5 shadow-sm space-y-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="text-sm text-gray-900">
                          <span className="font-medium">Gave</span>{" "}
                          {h.offering.map((p) => p.name).join(", ") || "—"}{" "}
                          <span className="text-gray-400">→</span>{" "}
                          <span className="font-medium">Got</span>{" "}
                          {h.receiving.map((p) => p.name).join(", ") || "—"}
                        </div>
                        <span className="shrink-0 text-xs text-gray-400">
                          {timeAgo(h.created_at)}
                        </span>
                      </div>
                      {h.verdict && (
                        <span
                          className={`inline-block px-3 py-1.5 rounded-xl border text-sm font-medium ${verdictColor(
                            h.verdict
                          )}`}
                        >
                          {h.verdict}
                        </span>
                      )}
                      <div>
                        <button
                          onClick={() => setExpandedHistoryId(expanded ? null : h.id)}
                          className="text-xs font-medium text-violet-600 hover:text-violet-300"
                        >
                          {expanded ? "Hide analysis" : "Show analysis"}
                        </button>
                      </div>
                      {expanded && <AnalysisRenderer text={h.analysis} />}
                    </div>
                  );
                })}
            </div>
          )}
        </div>
      )}
    </main>
  );
}