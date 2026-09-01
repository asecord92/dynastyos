"use client";

import { useCallback, useEffect, useState } from "react";
import { authedFetch } from "../../lib/useDashboardWidget";
import { timeAgo } from "../../lib/format";

// Mirrors `ago` on the admin page: these timestamps are nullable.
const ago = (ts: string | null) => (ts ? timeAgo(ts) : "—");

type AllowedRow = { email: string; note: string | null; created_at: string | null };
type BlockedRow = { created_at: string | null; message: string | null };

type Payload = {
  available: boolean;
  enforcing?: boolean;
  emails: AllowedRow[];
  blocked: BlockedRow[];
  admins: string[];
};

export default function AllowedEmails() {
  const [data, setData] = useState<Payload | null>(null);
  const [email, setEmail] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await authedFetch("/api/admin/allowed-emails", {}, { timeoutMs: 15_000 });
      if (res.ok) setData((await res.json()) as Payload);
    } catch {
      // section just doesn't render
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function add(value: string, noteValue = "") {
    const target = value.trim().toLowerCase();
    if (!target) return;
    setBusy(true);
    setMsg(null);
    try {
      const res = await authedFetch("/api/admin/allowed-emails", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: target, note: noteValue }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setMsg(body.detail || "Couldn't add that email.");
      } else {
        setEmail("");
        setNote("");
        await load();
      }
    } finally {
      setBusy(false);
    }
  }

  async function remove(target: string) {
    setBusy(true);
    setMsg(null);
    try {
      const res = await authedFetch(
        `/api/admin/allowed-emails?email=${encodeURIComponent(target)}`,
        { method: "DELETE" }
      );
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setMsg(body.detail || "Couldn't remove that email.");
      } else {
        await load();
      }
    } finally {
      setBusy(false);
    }
  }

  if (!data) return null;

  // Admins the backend lets in (ADMIN_EMAILS is unioned in) but the signup hook
  // would reject, because the hook only reads the allowed_emails table.
  const missingAdmins = data.admins.filter(
    (a) => !data.emails.some((r) => r.email === a)
  );

  if (!data.available) {
    return (
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Invite list</h2>
        <div className="text-sm text-amber-300 bg-amber-50 border border-amber-500/30 rounded-xl p-4">
          The <code>allowed_emails</code> table doesn&apos;t exist yet. Run{" "}
          <code>supabase/migrations/20260901_allowed_emails.sql</code> in the Supabase SQL
          editor, then reload.
        </div>
      </section>
    );
  }

  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <h2 className="text-lg font-semibold">Invite list</h2>
        <span className="text-xs text-gray-400">
          {data.enforcing
            ? `${data.emails.length} invited · signups restricted`
            : "empty — anyone can sign up"}
        </span>
      </div>

      {!data.enforcing && (
        <div className="text-sm text-amber-300 bg-amber-50 border border-amber-500/30 rounded-xl p-4">
          An empty list means <strong>everyone is allowed</strong> — that&apos;s the
          &ldquo;not configured yet&rdquo; state, not a lockout. Add the first address to
          switch the app to invite-only.
        </div>
      )}

      {/* The two gates don't read the same source: the backend unions ADMIN_EMAILS
          in, but the signup hook is a Postgres function that can only see this
          table. An admin missing from it can use the app yet couldn't re-register. */}
      {data.enforcing && missingAdmins.length > 0 && (
        <div className="text-sm text-amber-300 bg-amber-50 border border-amber-500/30 rounded-xl p-4 space-y-2">
          <p>
            {missingAdmins.length === 1 ? "Your admin email isn't" : "Some admin emails aren't"}{" "}
            on the invite list. You can still use the app — the backend always allows
            admins — but the <strong>signup hook can&apos;t see that</strong>, so you
            couldn&apos;t create the account again if you ever deleted it.
          </p>
          <button
            onClick={() => missingAdmins.forEach((a) => add(a, "admin"))}
            disabled={busy}
            className="underline font-medium disabled:opacity-40"
          >
            Add {missingAdmins.length === 1 ? missingAdmins[0] : "them"} to the list
          </button>
        </div>
      )}

      <div className="bg-gray-50 border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            add(email, note);
          }}
          className="flex flex-col sm:flex-row gap-2 p-4 border-b border-gray-200"
        >
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="friend@example.com"
            className="flex-1 min-w-0 bg-gray-100 border border-gray-200 rounded-xl px-3 py-2 text-sm"
          />
          <input
            type="text"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="note (optional)"
            className="sm:w-44 bg-gray-100 border border-gray-200 rounded-xl px-3 py-2 text-sm"
          />
          <button
            type="submit"
            disabled={busy || !email.trim()}
            className="bg-violet-600 text-white rounded-xl px-4 py-2 text-sm font-medium disabled:opacity-40"
          >
            Add
          </button>
        </form>

        {msg && <div className="px-4 py-2 text-sm text-red-300 bg-red-50">{msg}</div>}

        <ul className="divide-y divide-gray-100">
          {data.admins.map((a) => {
            const onList = data.emails.some((r) => r.email === a);
            return (
              <li key={a} className="flex items-center justify-between gap-3 px-4 py-3">
                <div className="min-w-0">
                  <div className="text-gray-900 truncate">{a}</div>
                  <div
                    className={`text-xs ${onList ? "text-gray-400" : "text-amber-300"}`}
                  >
                    {onList
                      ? "admin · on the invite list"
                      : "admin — allowed to use the app, but the signup hook can't see this"}
                  </div>
                </div>
                {!onList && (
                  <button
                    onClick={() => add(a, "admin")}
                    disabled={busy}
                    className="text-xs text-violet-600 hover:underline disabled:opacity-40 shrink-0"
                  >
                    Add to list
                  </button>
                )}
              </li>
            );
          })}
          {data.emails
            .filter((r) => !data.admins.includes(r.email))
            .map((r) => (
              <li key={r.email} className="flex items-center justify-between gap-3 px-4 py-3">
                <div className="min-w-0">
                  <div className="text-gray-900 truncate">{r.email}</div>
                  <div className="text-xs text-gray-400">
                    {r.note ? `${r.note} · ` : ""}
                    added {ago(r.created_at)}
                  </div>
                </div>
                <button
                  onClick={() => remove(r.email)}
                  disabled={busy}
                  className="text-xs text-gray-500 hover:text-red-400 disabled:opacity-40 shrink-0"
                >
                  Remove
                </button>
              </li>
            ))}
          {data.emails.length === 0 && data.admins.length === 0 && (
            <li className="px-4 py-6 text-sm text-gray-400">Nobody on the list yet.</li>
          )}
        </ul>
      </div>

      {data.blocked.length > 0 && (
        <div className="bg-gray-50 border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-200 text-xs font-semibold uppercase tracking-widest text-gray-400">
            Blocked signups
          </div>
          <ul className="divide-y divide-gray-100">
            {data.blocked.map((b, i) => (
              <li
                key={`${b.message}-${b.created_at}-${i}`}
                className="flex items-center justify-between gap-3 px-4 py-3"
              >
                <div className="min-w-0">
                  <div className="text-gray-700 truncate">{b.message ?? "—"}</div>
                  <div className="text-xs text-gray-400">{ago(b.created_at)}</div>
                </div>
                {b.message && (
                  <button
                    onClick={() => add(b.message as string, "from blocked signup")}
                    disabled={busy}
                    className="text-xs text-violet-600 hover:underline disabled:opacity-40 shrink-0"
                  >
                    Allow
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
