"use client";

import { useMemo } from "react";
import { money } from "../../lib/rosterUtils";
import { planRow, planTotals, type LeagueRules } from "../../lib/capPlanner";
import type { RosterRow } from "../../lib/types";

/**
 * The free half of the trade builder: a deterministic market-value and salary
 * read that updates on every toggle and costs nothing. No AI call — the paid
 * "Analyze Trade" stays the deliberate escalation for the questions values
 * can't answer (roster fit, categories, health, timing).
 *
 * Values come from POST /dashboard/trade_values (HarryKnowsBall for baseball,
 * FantasyCalc for football) and are already keyed by the ids this page uses.
 */

export type ValueInfo = {
  value: number | null;
  rank?: number | null;
  age?: number | null;
  prospect?: boolean;
  trend?: number | null;
};

export type TradeValues = {
  sport: string;
  source: string;
  available: boolean;
  updated_at: string | null;
  values: Record<string, ValueInfo>;
  matched: number;
  unmatched: number;
};

/** Asset shape the trade page already builds (PlayerOption). */
type Asset = {
  id: string;
  name: string;
  salary: number;
  contract: string;
  status: string;
};

// How far apart two sides can be before the deal stops being "even". A
// judgment call, not a fact — kept in one place so it's tunable and visible.
const EVEN_PCT = 0.07;
const EDGE_PCT = 0.15;

function sumSide(assets: Asset[], values: Record<string, ValueInfo>) {
  let total = 0;
  let unpriced = 0;
  for (const a of assets) {
    const v = values[a.id]?.value;
    if (typeof v === "number") total += v;
    else unpriced += 1;
  }
  return { total, unpriced };
}

type Tone = "muted" | "even" | "good" | "warn" | "bad";

function verdict(give: number, get: number): { label: string; tone: Tone; pct: number } {
  const max = Math.max(give, get);
  if (max === 0) return { label: "No value to compare", tone: "muted", pct: 0 };
  const pct = Math.abs(give - get) / max;
  const favoursYou = get > give;
  const who = favoursYou ? "you" : "them";
  if (pct < EVEN_PCT) return { label: "Even deal", tone: "even", pct };
  if (pct < EDGE_PCT)
    return { label: `Slight edge to ${who}`, tone: favoursYou ? "good" : "warn", pct };
  return { label: `Lopsided toward ${who}`, tone: favoursYou ? "good" : "bad", pct };
}

const TONE_TEXT: Record<Tone, string> = {
  muted: "text-gray-400",
  even: "text-gray-900",
  good: "text-green-600",
  warn: "text-amber-600",
  bad: "text-red-500",
};

/** Contract-league salary read: what the trade does to this season's cap and,
 * more importantly, to next season's committed money against the offseason cap
 * (the number that actually forces cuts before the auction). */
function salaryImpact(
  myRoster: Asset[],
  give: Asset[],
  get: Asset[],
  rules: LeagueRules
) {
  const contract = rules.contract;
  if (!contract) return null;

  const capCounting = (a: Asset) => (a.status ?? "").toUpperCase() !== "MIN";
  const toRow = (a: Asset): RosterRow => ({
    player: a.name,
    status: a.status,
    salary: a.salary,
    contract: a.contract,
  });

  const outIds = new Set(give.map((a) => a.id));
  const after = [...myRoster.filter((a) => !outIds.has(a.id)), ...get];

  const nowSalary = myRoster.filter(capCounting).reduce((s, a) => s + a.salary, 0);
  const afterSalary = after.filter(capCounting).reduce((s, a) => s + a.salary, 0);

  const commit = (assets: Asset[]) =>
    planTotals(
      assets.map((a, i) => planRow(toRow(a), `${a.id}:${i}`, undefined, contract)),
      rules
    ).committed;

  return {
    nowSalary,
    afterSalary,
    inSeasonCap: rules.in_season_cap,
    committedNow: commit(myRoster),
    committedAfter: commit(after),
    offseasonCap: rules.offseason_cap,
  };
}

export function TradeBalance({
  data,
  give,
  get,
  myRoster,
  rules,
}: {
  data: TradeValues | null;
  give: Asset[];
  get: Asset[];
  myRoster: Asset[];
  rules: LeagueRules | null;
}) {
  const read = useMemo(() => {
    const values = data?.values ?? {};
    const g = sumSide(give, values);
    const r = sumSide(get, values);
    return { give: g, get: r, v: verdict(g.total, r.total) };
  }, [give, get, data]);

  const salary = useMemo(
    () => (rules ? salaryImpact(myRoster, give, get, rules) : null),
    [myRoster, give, get, rules]
  );

  if (give.length === 0 && get.length === 0) return null;

  const unpriced = read.give.unpriced + read.get.unpriced;
  const total = read.give.total + read.get.total;
  const givePct = total > 0 ? (read.give.total / total) * 100 : 50;

  return (
    <div className="bg-gray-50 border rounded-2xl p-5 shadow-sm space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <div className="text-xs font-semibold uppercase tracking-widest text-gray-400">
          Balance check · free
        </div>
        {data?.available && (
          <div className="text-xs text-gray-400">
            {data.source} market values
            {data.updated_at ? ` · ${new Date(data.updated_at).toLocaleDateString()}` : ""}
          </div>
        )}
      </div>

      {!data?.available ? (
        <p className="text-sm text-gray-400">
          Market values are unavailable right now — the salary read below still applies.
        </p>
      ) : (
        <div className="space-y-2">
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <div>
              <span className="text-gray-400">You give </span>
              <span className="font-semibold text-gray-900 tabular-nums">
                {Math.round(read.give.total).toLocaleString()}
              </span>
            </div>
            <div className="text-right">
              <span className="text-gray-400">You get </span>
              <span className="font-semibold text-gray-900 tabular-nums">
                {Math.round(read.get.total).toLocaleString()}
              </span>
            </div>
          </div>

          <div className="flex h-2 overflow-hidden rounded-full bg-gray-100" aria-hidden>
            <div className="bg-gray-400" style={{ width: `${givePct}%` }} />
            <div className="bg-violet-600" style={{ width: `${100 - givePct}%` }} />
          </div>

          <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
            <span className={`font-medium ${TONE_TEXT[unpriced > 0 ? "muted" : read.v.tone]}`}>
              {unpriced > 0 ? "Incomplete" : read.v.label}
            </span>
            {read.v.pct > 0 && (
              <span className="text-xs text-gray-400">
                {Math.round(read.v.pct * 100)}% apart
              </span>
            )}
          </div>

          {unpriced > 0 && (
            // Never show a confident verdict over a partial sum — a missing
            // prospect can be the whole trade.
            <p className="text-xs text-amber-600">
              {unpriced} {unpriced === 1 ? "asset has" : "assets have"} no market value
              (usually deep minors) — these totals exclude them.
            </p>
          )}
        </div>
      )}

      {salary && (
        <div className="space-y-1 border-t border-gray-100 pt-3 text-sm">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3">
            <span className="text-gray-400">Salary this season</span>
            <span className="tabular-nums text-gray-900">
              {money(salary.nowSalary)} → {money(salary.afterSalary)}
              <span className="text-gray-400"> of {money(salary.inSeasonCap)}</span>
            </span>
          </div>
          <div className="flex flex-wrap items-baseline justify-between gap-x-3">
            <span className="text-gray-400">Committed next season</span>
            <span className="tabular-nums text-gray-900">
              {money(salary.committedNow)} → {money(salary.committedAfter)}
              <span className="text-gray-400"> of {money(salary.offseasonCap)}</span>
            </span>
          </div>
          {salary.committedAfter > salary.offseasonCap && (
            // The finding a value-only check misses: an even trade you can't
            // actually fit under the offseason cap.
            <p className="text-xs text-amber-600">
              Puts you {money(salary.committedAfter - salary.offseasonCap)} over the offseason
              cap — you&apos;d have to shed salary before the auction.
            </p>
          )}
        </div>
      )}

      <p className="text-xs text-gray-400">
        Market value only — it can&apos;t see your categories, roster holes, or injuries. Run
        Analyze Trade for that.
      </p>
    </div>
  );
}
