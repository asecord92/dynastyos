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
  };
  users: UserRow[];
};

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
                    <div className="text-gray-900">{u.email ?? "—"}</div>
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

      <p className="text-xs text-gray-400">
        Derived live from existing data (no event logging yet). &ldquo;Last AI&rdquo; = most
        recent widget generation.
      </p>
    </main>
  );
}
