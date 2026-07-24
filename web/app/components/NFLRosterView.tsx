"use client";

import { useEffect, useState } from "react";
import { supabase } from "../lib/supabaseClient";
import { useDashboardWidget } from "../lib/useDashboardWidget";
import { timeAgo } from "../lib/format";
import { Spinner } from "./ui/Spinner";

type DynastyPlayer = {
  id: string;
  name?: string;
  position?: string;
  team?: string;
  status: string;
  injury_status?: string | null;
  age?: number | null;
  band?: "ascending" | "prime" | "aging" | "cliff" | null;
  rookie_tag?: string | null;
  value?: number | null;
  overall_rank?: number | null;
  pos_rank?: number | null;
  tier?: number | null;
  trend?: number | null;
};

type DynastyPick = {
  label?: string;
  season?: number;
  round?: number;
  value?: number | null;
  trend?: number | null;
};

type NflRosterPayload = {
  fc_available: boolean;
  players: {
    starter: DynastyPlayer[];
    bench: DynastyPlayer[];
    taxi: DynastyPlayer[];
    ir: DynastyPlayer[];
  };
  picks: DynastyPick[];
  pick_capital: { total: number; valued: number; unvalued: number };
  window: { verdict: string | null; detail: string };
  depth_flags: { level: "critical" | "warn"; text: string }[];
  team_name: string;
  values_updated_at: string | null;
};

const bandChip: Record<string, { label: string; cls: string }> = {
  ascending: { label: "Ascending", cls: "bg-green-500/15 text-green-300" },
  prime: { label: "Prime", cls: "bg-violet-500/15 text-violet-300" },
  aging: { label: "Aging", cls: "bg-amber-500/15 text-amber-300" },
  cliff: { label: "Cliff", cls: "bg-red-500/15 text-red-300" },
};

const verdictCls: Record<string, string> = {
  Ascending: "bg-green-500/15 text-green-300",
  Balanced: "bg-violet-500/15 text-violet-300",
  "Win-now": "bg-blue-500/15 text-blue-300",
  "Aging — sell high": "bg-red-500/15 text-red-300",
};

function fmtValue(v?: number | null): string {
  return v ? v.toLocaleString() : "—";
}

/** 30-day market movement arrow — only meaningful swings get ink. */
function TrendArrow({ trend }: { trend?: number | null }) {
  if (!trend || Math.abs(trend) < 100) return null;
  return trend > 0 ? (
    <span className="text-green-400 text-xs">▲</span>
  ) : (
    <span className="text-red-400 text-xs">▼</span>
  );
}

function InjuryBadge({ status }: { status?: string | null }) {
  if (!status) return null;
  const bad = ["IR", "Out", "Doubtful", "PUP", "Sus"].some((s) =>
    status.toLowerCase().startsWith(s.toLowerCase())
  );
  return (
    <span
      className={`inline-block px-1.5 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wide ${
        bad ? "bg-red-100 text-red-800" : "bg-amber-100 text-amber-800"
      }`}
    >
      {status}
    </span>
  );
}

function PlayerRow({ p }: { p: DynastyPlayer }) {
  const chip = p.band ? bandChip[p.band] : null;
  const sub = [p.team || "FA", p.age != null ? `age ${p.age}` : null]
    .filter(Boolean)
    .join(" · ");
  // Rank leads: "#3 overall" reads instantly, the raw trade value doesn't.
  // Value stays visible (it's what you sum across a trade) but subordinate.
  const posRank = p.pos_rank != null ? `${p.position}${p.pos_rank}` : null;
  return (
    <div className="flex items-center gap-3 py-2.5 border-b last:border-0">
      <span className="w-9 shrink-0 text-[11px] font-semibold text-gray-500">
        {p.position ?? "—"}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-medium truncate">{p.name ?? "—"}</span>
          {p.rookie_tag && (
            <span className="px-1.5 py-0.5 rounded-md text-[10px] font-semibold bg-blue-500/15 text-blue-300">
              {p.rookie_tag}
            </span>
          )}
          <InjuryBadge status={p.injury_status} />
        </div>
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <span>{sub}</span>
          {chip && (
            <span className={`px-1.5 py-0.5 rounded-md text-[10px] font-semibold ${chip.cls}`}>
              {chip.label}
            </span>
          )}
        </div>
      </div>
      <div className="shrink-0 text-right">
        <div className="text-sm font-semibold tabular-nums">
          {p.overall_rank != null ? `#${p.overall_rank} overall` : "—"}
        </div>
        {p.value != null && (
          <div className="text-xs text-gray-500 tabular-nums">
            {posRank && <span className="font-medium">{posRank}</span>}
            {posRank && " · "}
            {fmtValue(p.value)} <TrendArrow trend={p.trend} />
          </div>
        )}
      </div>
    </div>
  );
}

function RosterGroup({ title, items }: { title: string; items: DynastyPlayer[] }) {
  if (items.length === 0) return null;
  return (
    <div className="bg-gray-50 border rounded-2xl p-4 md:p-6 shadow-sm">
      <div className="flex items-baseline justify-between mb-1">
        <h2 className="text-lg font-semibold">{title}</h2>
        <span className="text-sm text-gray-500">{items.length}</span>
      </div>
      <div>
        {items.map((p) => (
          <PlayerRow key={p.id} p={p} />
        ))}
      </div>
    </div>
  );
}

/** Dynasty roster view for Sleeper football leagues: pick capital first, the
 * roster-window read, then the roster with FantasyCalc market values and
 * age-curve chips. All reads are computed server-side (/dashboard/nfl_roster) —
 * no AI call, so refresh is free. */
export function NFLRosterView({ leagueId }: { leagueId: string }) {
  // Resolve the owner's roster id from the league row (same pattern as the
  // waivers page); the widget hook no-ops until it settles.
  const [myTeamId, setMyTeamId] = useState("");
  useEffect(() => {
    if (!leagueId) {
      setMyTeamId("");
      return;
    }
    supabase
      .from("leagues")
      .select("fantrax_team_id")
      .eq("id", leagueId)
      .single()
      .then(({ data }) => setMyTeamId(data?.fantrax_team_id ?? ""));
  }, [leagueId]);

  const { data, loading, validating, error, refresh } = useDashboardWidget<NflRosterPayload>(
    "nfl_roster",
    leagueId,
    myTeamId
  );

  if ((loading || !myTeamId) && !data) {
    return (
      <div className="space-y-4 animate-pulse">
        <div className="h-24 bg-gray-50 border rounded-2xl" />
        <div className="h-16 bg-gray-50 border rounded-2xl" />
        <div className="h-64 bg-gray-50 border rounded-2xl" />
      </div>
    );
  }

  if (error && !data) {
    const needsSync = error.toLowerCase().includes("sync");
    return (
      <div className="text-sm text-gray-500 bg-gray-50 border rounded-2xl p-6 shadow-sm space-y-3">
        <p>
          {needsSync
            ? "No synced roster yet — hit Sync in the nav to pull it from Sleeper."
            : `Couldn't load the roster: ${error}`}
        </p>
        {!needsSync && (
          <button
            onClick={() => refresh()}
            className="px-3 py-1.5 rounded-xl text-xs border border-gray-200 hover:border-gray-300 transition"
          >
            Retry
          </button>
        )}
      </div>
    );
  }

  if (!data) return null;

  const { players, picks, pick_capital, window, depth_flags } = data;

  return (
    <div className="space-y-4 md:space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm text-gray-500">{data.team_name}</div>
        <div className="flex items-center gap-3">
          {data.values_updated_at && (
            <span className="text-xs text-gray-400 whitespace-nowrap">
              Values {timeAgo(data.values_updated_at)}
            </span>
          )}
          <button
            onClick={() => refresh(true)}
            disabled={validating}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs border border-gray-200 hover:border-gray-300 disabled:opacity-60 transition"
          >
            {validating && <Spinner />}
            {validating ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>

      {!data.fc_available && (
        <div className="text-xs text-amber-300 bg-amber-500/10 border border-amber-500/20 rounded-xl px-4 py-2.5">
          Market values are unavailable right now — showing roster reads without values.
        </div>
      )}

      {/* The value scale is arbitrary and unlabeled everywhere it appears —
          say so once, up front, before the first number shows up. */}
      {data.fc_available && (
        <p className="text-xs text-gray-400 leading-relaxed">
          Ranks and values come from FantasyCalc&apos;s dynasty market.{" "}
          <span className="text-gray-500">Value</span> is a relative trade-value scale
          where the best asset in football sits around 10,000 — it&apos;s meant for
          comparing <em>totals</em> (both sides of a trade, your pick pile), not for
          reading one player in isolation. ▲▼ flag a big 30-day move; “—” means the
          market doesn&apos;t price that asset.
        </p>
      )}

      {/* Draft pick inventory */}
      <div className="bg-gray-50 border rounded-2xl p-4 md:p-6 shadow-sm">
        <div className="flex items-baseline justify-between mb-3">
          <h2 className="text-lg font-semibold">Draft Picks</h2>
          {pick_capital.total > 0 && (
            <span className="text-sm text-gray-500">
              Total value{" "}
              <span className="tabular-nums font-medium">
                {pick_capital.total.toLocaleString()}
              </span>
            </span>
          )}
        </div>
        {picks.length === 0 ? (
          <p className="text-sm text-gray-500">No future picks — they&apos;ve been traded away.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {picks.map((pk, i) => (
              <span
                key={`${pk.label}-${i}`}
                className="inline-flex items-center gap-2 px-3 py-1.5 rounded-xl border bg-gray-100 text-sm"
              >
                <span className="font-medium">{pk.label}</span>
                <span className="text-gray-500 tabular-nums text-xs">
                  {fmtValue(pk.value)} <TrendArrow trend={pk.trend} />
                </span>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Window verdict + depth flags */}
      {(window.verdict || depth_flags.length > 0) && (
        <div className="bg-gray-50 border rounded-2xl p-4 md:p-6 shadow-sm space-y-3">
          {window.verdict && (
            <div className="flex items-center gap-3 flex-wrap">
              <span
                className={`px-2.5 py-1 rounded-lg text-sm font-semibold ${
                  verdictCls[window.verdict] ?? "bg-gray-100 text-gray-700"
                }`}
              >
                {window.verdict}
              </span>
              <span className="text-sm text-gray-500">{window.detail}</span>
            </div>
          )}
          {depth_flags.length > 0 && (
            <ul className="space-y-1.5">
              {depth_flags.map((f, i) => (
                <li
                  key={i}
                  className={`text-sm ${
                    f.level === "critical" ? "text-red-300" : "text-amber-300"
                  }`}
                >
                  {f.level === "critical" ? "⚠ " : "△ "}
                  {f.text}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Roster */}
      <RosterGroup title="Starters" items={players.starter} />
      <RosterGroup title="Bench" items={players.bench} />
      <RosterGroup title="Taxi Squad" items={players.taxi} />
      <RosterGroup title="IR" items={players.ir} />
    </div>
  );
}
