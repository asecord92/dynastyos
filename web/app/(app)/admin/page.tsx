"use client";

import { useEffect, useState } from "react";
import { authedFetch } from "../../lib/useDashboardWidget";

type UserRow = {
  user_id: string;
  email: string | null;
  created_at: string | null;
  last_sign_in_at: string | null;
  league_count: number;
  leagues: { name: string | null; sport: string | null }[];
  has_key: boolean;
  key_last4: string | null;
  last_sync_at: string | null;
  last_widget_at: string | null;
  errors_7d: number;
};

type ErrorRow = {
  created_at: string | null;
  email: string | null;
  kind: string | null;
  status: number | null;
  message: string | null;
};

type Overview = {
  generated_at: string;
  totals: {
    users: number;
    leagues: number;
    keys_set: number;
    active_7d: number;
    synced_7d: number;
    widgets_refreshed_7d: number;
    errors_7d: number;
  };
  users: UserRow[];
  recent_errors: ErrorRow[];
};

type UsageBucket = {
  calls: number;
  errors: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  web_searches: number;
  duration_ms: number;
  cost: number;
  calls_7d: number;
  cost_7d: number;
  avg_duration_ms?: number;
  tool?: string;
  email?: string;
};

type Usage = {
  available: boolean;
  generated_at?: string;
  window_days?: number;
  totals?: UsageBucket;
  tools?: UsageBucket[];
  users?: UsageBucket[];
};

function usd(n: number): string {
  if (!Number.isFinite(n) || n === 0) return "$0.00";
  if (n < 0.01) return "<$0.01";
  if (n < 1) return `$${n.toFixed(3)}`;
  return `$${n.toFixed(2)}`;
}

function tok(n: number): string {
  if (!Number.isFinite(n) || n === 0) return "0";
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}k`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}

function ago(ts: string | null): string {
  if (!ts) return "—";
  const s = Math.floor((Date.now() - new Date(ts).getTime()) / 1000);
  if (s < 0) return "just now";
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  return `${Math.floor(d / 30)}mo ago`;
}

function Stat({ label, value, sub }: { label: string; value: number; sub?: string }) {
  return (
    <div className="bg-gray-50 border border-gray-200 rounded-2xl p-5 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-widest text-gray-400">{label}</div>
      <div className="text-3xl font-semibold mt-1">{value}</div>
      {sub && <div className="text-xs text-gray-400 mt-1">{sub}</div>}
    </div>
  );
}

export default function AdminPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [error, setError] = useState<"forbidden" | string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await authedFetch("/api/admin/overview");
        if (res.status === 403) {
          setError("forbidden");
          return;
        }
        if (!res.ok) throw new Error(await res.text());
        setData((await res.json()) as Overview);
      } catch (e: any) {
        setError(e?.message ?? "Failed to load.");
      } finally {
        setLoading(false);
      }
      try {
        const res = await authedFetch("/api/admin/usage");
        if (res.ok) setUsage((await res.json()) as Usage);
      } catch {
        // usage section just doesn't render
      }
    })();
  }, []);

  if (loading) {
    return <main className="text-sm text-gray-500">Loading…</main>;
  }

  if (error === "forbidden") {
    return (
      <main className="space-y-3">
        <h1 className="text-3xl font-semibold">Admin</h1>
        <p className="text-sm text-gray-500">You don&apos;t have access to this page.</p>
      </main>
    );
  }

  if (error) {
    return (
      <main className="space-y-3">
        <h1 className="text-3xl font-semibold">Admin</h1>
        <div className="text-sm text-red-300 bg-red-50 border border-red-500/30 rounded-xl p-4">
          {error}
        </div>
      </main>
    );
  }

  if (!data) return null;
  const t = data.totals;

  return (
    <main className="space-y-6">
      <div className="flex items-baseline justify-between">
        <h1 className="text-3xl font-semibold">Admin</h1>
        <span className="text-xs text-gray-400">as of {ago(data.generated_at)}</span>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
        <Stat label="Users" value={t.users} sub={`${t.active_7d} active this week`} />
        <Stat label="Leagues" value={t.leagues} />
        <Stat
          label="API keys set"
          value={t.keys_set}
          sub={`${t.users - t.keys_set} without a key`}
        />
        <Stat label="Synced (7d)" value={t.synced_7d} />
        <Stat label="Widgets refreshed (7d)" value={t.widgets_refreshed_7d} />
        <Stat label="Issues (7d)" value={t.errors_7d} sub={t.errors_7d ? "needs a look" : "all clear"} />
      </div>

      <div className="bg-gray-50 border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-gray-400 border-b border-gray-200">
                <th className="px-4 py-3 font-medium">User</th>
                <th className="px-4 py-3 font-medium">Leagues</th>
                <th className="px-4 py-3 font-medium">Key</th>
                <th className="px-4 py-3 font-medium">Last active</th>
                <th className="px-4 py-3 font-medium">Last sync</th>
                <th className="px-4 py-3 font-medium">Last AI</th>
              </tr>
            </thead>
            <tbody>
              {data.users.map((u) => (
                <tr key={u.user_id} className="border-b border-gray-100 last:border-0">
                  <td className="px-4 py-3">
                    <div className="text-gray-900">
                      {u.email ?? "—"}
                      {u.errors_7d > 0 && (
                        <span className="ml-2 text-xs text-red-400">
                          {u.errors_7d} issue{u.errors_7d === 1 ? "" : "s"}
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-gray-400">joined {ago(u.created_at)}</div>
                  </td>
                  <td className="px-4 py-3">
                    {u.league_count === 0 ? (
                      <span className="text-amber-300">none</span>
                    ) : (
                      <span
                        className="text-gray-700"
                        title={u.leagues.map((l) => l.name).filter(Boolean).join(", ")}
                      >
                        {u.league_count}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {u.has_key ? (
                      <span className="text-green-400">••••{u.key_last4}</span>
                    ) : (
                      <span className="text-amber-300">not set</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-gray-600">{ago(u.last_sign_in_at)}</td>
                  <td className="px-4 py-3 text-gray-600">{ago(u.last_sync_at)}</td>
                  <td className="px-4 py-3 text-gray-600">{ago(u.last_widget_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {usage?.available && usage.totals && (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold">AI usage (last {usage.window_days} days)</h2>

          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="bg-gray-50 border border-gray-200 rounded-2xl p-5 shadow-sm">
              <div className="text-xs font-semibold uppercase tracking-widest text-gray-400">Est. cost</div>
              <div className="text-3xl font-semibold mt-1">{usd(usage.totals.cost)}</div>
              <div className="text-xs text-gray-400 mt-1">{usd(usage.totals.cost_7d)} this week</div>
            </div>
            <Stat label="AI calls" value={usage.totals.calls} sub={`${usage.totals.calls_7d} this week`} />
            <Stat label="Web searches" value={usage.totals.web_searches} sub="$10 per 1k" />
            <Stat
              label="Failed calls"
              value={usage.totals.errors}
              sub={usage.totals.errors ? "check recent issues" : "all clear"}
            />
          </div>

          {(usage.tools ?? []).length > 0 && (
            <div className="bg-gray-50 border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs uppercase tracking-wide text-gray-400 border-b border-gray-200">
                      <th className="px-4 py-3 font-medium">Tool</th>
                      <th className="px-4 py-3 font-medium">Calls</th>
                      <th className="px-4 py-3 font-medium">In</th>
                      <th className="px-4 py-3 font-medium">Out</th>
                      <th className="px-4 py-3 font-medium">Searches</th>
                      <th className="px-4 py-3 font-medium">Avg time</th>
                      <th className="px-4 py-3 font-medium">Est. cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(usage.tools ?? []).map((t2) => (
                      <tr key={t2.tool} className="border-b border-gray-100 last:border-0">
                        <td className="px-4 py-3 font-mono text-xs text-gray-800">{t2.tool}</td>
                        <td className="px-4 py-3 text-gray-700">
                          {t2.calls}
                          {t2.errors > 0 && <span className="ml-1 text-xs text-red-400">({t2.errors} failed)</span>}
                        </td>
                        <td className="px-4 py-3 text-gray-600">{tok(t2.input_tokens)}</td>
                        <td className="px-4 py-3 text-gray-600">{tok(t2.output_tokens)}</td>
                        <td className="px-4 py-3 text-gray-600">{t2.web_searches || "—"}</td>
                        <td className="px-4 py-3 text-gray-600">
                          {t2.avg_duration_ms ? `${(t2.avg_duration_ms / 1000).toFixed(1)}s` : "—"}
                        </td>
                        <td className="px-4 py-3 text-gray-800">
                          {usd(t2.cost)}
                          <span className="ml-1 text-xs text-gray-400">({usd(t2.cost_7d)} 7d)</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {(usage.users ?? []).length > 0 && (
            <div className="bg-gray-50 border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs uppercase tracking-wide text-gray-400 border-b border-gray-200">
                      <th className="px-4 py-3 font-medium">User (billed key)</th>
                      <th className="px-4 py-3 font-medium">Calls</th>
                      <th className="px-4 py-3 font-medium">In</th>
                      <th className="px-4 py-3 font-medium">Out</th>
                      <th className="px-4 py-3 font-medium">Est. cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(usage.users ?? []).map((u2) => (
                      <tr key={u2.email} className="border-b border-gray-100 last:border-0">
                        <td className="px-4 py-3 text-gray-800">{u2.email}</td>
                        <td className="px-4 py-3 text-gray-700">{u2.calls}</td>
                        <td className="px-4 py-3 text-gray-600">{tok(u2.input_tokens)}</td>
                        <td className="px-4 py-3 text-gray-600">{tok(u2.output_tokens)}</td>
                        <td className="px-4 py-3 text-gray-800">
                          {usd(u2.cost)}
                          <span className="ml-1 text-xs text-gray-400">({usd(u2.cost_7d)} 7d)</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <p className="text-xs text-gray-400">
            Estimated from exact token counts in ai_usage, priced at current API rates (Sonnet 5
            intro pricing applied through Aug 31). Costs bill each user&apos;s own key.
          </p>
        </section>
      )}

      {data.recent_errors.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold">Recent issues</h2>
          <div className="bg-gray-50 border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wide text-gray-400 border-b border-gray-200">
                    <th className="px-4 py-3 font-medium">When</th>
                    <th className="px-4 py-3 font-medium">User</th>
                    <th className="px-4 py-3 font-medium">Where</th>
                    <th className="px-4 py-3 font-medium">Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {data.recent_errors.map((e, i) => (
                    <tr key={i} className="border-b border-gray-100 last:border-0 align-top">
                      <td className="px-4 py-3 text-gray-600 whitespace-nowrap">{ago(e.created_at)}</td>
                      <td className="px-4 py-3 text-gray-700">{e.email ?? "—"}</td>
                      <td className="px-4 py-3 text-gray-500 font-mono text-xs whitespace-nowrap">
                        {e.kind ?? "—"}
                        {e.status ? ` · ${e.status}` : ""}
                      </td>
                      <td className="px-4 py-3 text-gray-500 max-w-md truncate" title={e.message ?? ""}>
                        {e.message ?? "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      )}

      <p className="text-xs text-gray-400">
        Usage is derived live from existing data; issues are captured by a global error
        handler. &ldquo;Last AI&rdquo; = most recent widget generation.
      </p>
    </main>
  );
}
