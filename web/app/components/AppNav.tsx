"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { supabase } from "../lib/supabaseClient";

type League = { id: string; name: string };
const LEAGUE_KEY = "dynastyos:selected_league_id";

function initials(email: string) {
  const left = email.split("@")[0] ?? email;
  const parts = left.replace(/[^a-zA-Z0-9]/g, " ").trim().split(/\s+/).filter(Boolean);
  const a = parts[0]?.[0] ?? left[0] ?? "?";
  const b = parts[1]?.[0] ?? parts[0]?.[1] ?? "";
  return (a + b).toUpperCase();
}

export function AppNav() {
  const [email, setEmail] = useState<string | null>(null);
  const [leagues, setLeagues] = useState<League[]>([]);
  const [leagueId, setLeagueId] = useState<string>("");
  const [ready, setReady] = useState(false);

  const badge = useMemo(() => (email ? initials(email) : "?"), [email]);

  useEffect(() => {
    const saved = localStorage.getItem(LEAGUE_KEY);
    if (saved) setLeagueId(saved);

    supabase.auth.getSession().then(({ data }) => {
      setEmail(data.session?.user?.email ?? null);
      setReady(true);
    });

    const { data: sub } = supabase.auth.onAuthStateChange((_evt, session) => {
      setEmail(session?.user?.email ?? null);
      setReady(true);
    });

    return () => sub.subscription.unsubscribe();
  }, []);

  useEffect(() => {
    async function loadLeagues() {
      const { data, error } = await supabase
        .from("leagues")
        .select("id,name")
        .order("created_at", { ascending: false });

      if (!error && data) setLeagues(data as League[]);
    }

    if (email) loadLeagues();
    else setLeagues([]);
  }, [email]);

  function onSelectLeague(id: string) {
    setLeagueId(id);
    localStorage.setItem(LEAGUE_KEY, id);
  }

  async function logout() {
    const ok = window.confirm("Log out of DynastyOS?");
    if (!ok) return;

    await supabase.auth.signOut();
    setEmail(null);
    setLeagueId("");
    localStorage.removeItem(LEAGUE_KEY);
  }

  return (
    <div className="border-b bg-white">
      <div className="max-w-5xl mx-auto px-6 py-4 flex flex-col md:flex-row md:items-center md:justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="font-semibold text-lg">DynastyOS</div>
          <div className="text-sm text-gray-600">Secord Labs</div>

          {/* session indicator */}
          <div className="flex items-center gap-2 ml-2">
            <span
              className={[
                "inline-block w-2.5 h-2.5 rounded-full",
                ready ? (email ? "bg-green-500" : "bg-gray-300") : "bg-yellow-400",
              ].join(" ")}
              title={
                ready
                  ? email
                    ? "Signed in"
                    : "Signed out"
                  : "Connecting…"
              }
            />
            <span className="text-xs text-gray-500">
              {ready ? (email ? "signed in" : "signed out") : "connecting…"}
            </span>
          </div>
        </div>

        <div className="flex flex-col md:flex-row md:items-center gap-3">
          <nav className="flex items-center gap-2 text-sm">
            <Link className="px-3 py-1.5 rounded-xl border border-gray-200 hover:border-gray-300" href="/">
              Dashboard
            </Link>
            <Link className="px-3 py-1.5 rounded-xl border border-gray-200 hover:border-gray-300" href="/cap-relief">
              Cap Relief
            </Link>
            <Link className="px-3 py-1.5 rounded-xl border border-gray-200 hover:border-gray-300" href="/trade">
              Trade
            </Link>
            <Link className="px-3 py-1.5 rounded-xl border border-gray-200 hover:border-gray-300" href="/settings">
              Settings
            </Link>
          </nav>

          {email ? (
            <div className="flex items-center gap-2">
              <select
                value={leagueId}
                onChange={(e) => onSelectLeague(e.target.value)}
                className="px-3 py-2 rounded-xl border border-gray-200 bg-white text-sm"
                title="Select league"
              >
                <option value="">Select league…</option>
                {leagues.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name}
                  </option>
                ))}
              </select>

              {/* avatar */}
              <div
                className="w-9 h-9 rounded-full bg-black text-white flex items-center justify-center text-xs font-semibold"
                title={email}
              >
                {badge}
              </div>

              <button
                onClick={logout}
                className="px-3 py-2 rounded-xl text-sm border border-gray-200 bg-white hover:border-gray-300"
              >
                Log out
              </button>
            </div>
          ) : (
            <Link
              href="/login"
              className="px-3 py-2 rounded-xl text-sm border border-gray-200 bg-white hover:border-gray-300"
            >
              Log in
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}