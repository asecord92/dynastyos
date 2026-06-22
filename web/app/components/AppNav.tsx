"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useState, useCallback, useRef } from "react";
import { supabase } from "../lib/supabaseClient";
import { useLeague } from "../lib/useLeague";

type League = { id: string; name: string };

// Bottom nav tabs (mobile only). Icons are inline 24x24 stroke SVGs.
const MOBILE_TABS: { href: string; label: string; icon: React.ReactNode }[] = [
  {
    href: "/",
    label: "Dashboard",
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" />
        <rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" />
      </svg>
    ),
  },
  {
    href: "/roster",
    label: "Roster",
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" /><line x1="8" y1="18" x2="21" y2="18" />
        <circle cx="3.5" cy="6" r="1" /><circle cx="3.5" cy="12" r="1" /><circle cx="3.5" cy="18" r="1" />
      </svg>
    ),
  },
  {
    href: "/waivers",
    label: "Waivers",
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
      </svg>
    ),
  },
  {
    href: "/trade",
    label: "Trade",
    icon: (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="17 1 21 5 17 9" /><path d="M3 11V9a4 4 0 0 1 4-4h14" />
        <polyline points="7 23 3 19 7 15" /><path d="M21 13v2a4 4 0 0 1-4 4H3" />
      </svg>
    ),
  },
];

function initials(email: string) {
  const left = email.split("@")[0] ?? email;
  const parts = left.replace(/[^a-zA-Z0-9]/g, " ").trim().split(/\s+/).filter(Boolean);
  const a = parts[0]?.[0] ?? left[0] ?? "?";
  const b = parts[1]?.[0] ?? parts[0]?.[1] ?? "";
  return (a + b).toUpperCase();
}

function timeAgo(date: Date): string {
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function AppNav() {
  const [email, setEmail] = useState<string | null>(null);
  const [leagues, setLeagues] = useState<League[]>([]);
  const [ready, setReady] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncToast, setSyncToast] = useState<string | null>(null);
  const [lastSynced, setLastSynced] = useState<Date | null>(null);
  const [showTooltip, setShowTooltip] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const { leagueId, setLeague, buildHref } = useLeague();
  const pathname = usePathname();

  const badge = useMemo(() => (email ? initials(email) : "?"), [email]);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  useEffect(() => {
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

    window.addEventListener("dynastyos:leagues-updated", loadLeagues);
    return () => window.removeEventListener("dynastyos:leagues-updated", loadLeagues);
  }, [email]);

  useEffect(() => {
    if (!leagueId) { setLastSynced(null); return; }
    supabase
      .from("snapshots")
      .select("created_at")
      .eq("league_id", leagueId)
      .eq("source", "fantrax")
      .order("created_at", { ascending: false })
      .limit(1)
      .single()
      .then(({ data }) => {
        if (data?.created_at) setLastSynced(new Date(data.created_at));
        else setLastSynced(null);
      });
  }, [leagueId]);

  function showSyncToast(msg: string) {
    setSyncToast(msg);
    setTimeout(() => setSyncToast(null), 3000);
  }

  const sync = useCallback(async () => {
    if (!leagueId || syncing) return;
    setSyncing(true);
    try {
      const { data: leagueData, error: leagueError } = await supabase
        .from("leagues")
        .select("platform, sport, fantrax_secret_id, fantrax_league_id, sleeper_league_id")
        .eq("id", leagueId)
        .single();

      if (leagueError || !leagueData) {
        showSyncToast("League not found.");
        return;
      }

      const { data: sessionData } = await supabase.auth.getSession();
      const accessToken = sessionData.session?.access_token;
      const authHeaders = {
        "Content-Type": "application/json",
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      };

      const isSleeper =
        leagueData.platform === "sleeper" || leagueData.sport === "NFL";

      if (isSleeper) {
        if (!leagueData.sleeper_league_id) {
          showSyncToast("Reconnect this Sleeper league in Settings.");
          return;
        }
        const res = await fetch("/api/sleeper/sync", {
          method: "POST",
          headers: authHeaders,
          body: JSON.stringify({
            league_id: leagueId,
            sleeper_league_id: leagueData.sleeper_league_id,
          }),
        });
        if (!res.ok) throw new Error(await res.text());
      } else {
        if (!leagueData.fantrax_secret_id || !leagueData.fantrax_league_id) {
          showSyncToast("Connect Fantrax in Settings first.");
          return;
        }
        const res = await fetch("/api/roster/sync", {
          method: "POST",
          headers: authHeaders,
          body: JSON.stringify({
            user_secret_id: leagueData.fantrax_secret_id,
            fantrax_league_id: leagueData.fantrax_league_id,
          }),
        });
        if (!res.ok) throw new Error(await res.text());
        const json = await res.json();
        const user = sessionData.session?.user;
        if (user) {
          const { error: snapError } = await supabase
            .from("snapshots")
            .upsert({
              league_id: leagueId,
              owner_user_id: user.id,
              source: "fantrax",
              data: json,
            }, { onConflict: "league_id,source" });
          if (snapError) throw new Error(snapError.message);
        }
      }

      const now = new Date();
      setLastSynced(now);
      showSyncToast("Synced!");
    } catch (e: any) {
      showSyncToast(e?.message ?? "Sync failed.");
    } finally {
      setSyncing(false);
    }
  }, [leagueId, syncing]);

  async function logout() {
    const ok = window.confirm("Log out of DynastyOS?");
    if (!ok) return;
    setDropdownOpen(false);
    await supabase.auth.signOut();
    setEmail(null);
  }

  return (
    <>
    <div className="border-b bg-gray-50 sticky top-0 z-40">
      <div className="w-full px-6 py-3 flex lg:grid items-center justify-between gap-3 lg:gap-4" style={{gridTemplateColumns: "1fr auto 1fr"}}>

        {/* Left — Logo */}
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-bold text-lg lg:text-xl tracking-tight truncate">DynastyOS</span>
          <span
            className={[
              "inline-block w-2 h-2 rounded-full flex-shrink-0",
              ready ? (email ? "bg-green-500" : "bg-gray-300") : "bg-yellow-400",
            ].join(" ")}
            title={ready ? (email ? "Signed in" : "Signed out") : "Connecting…"}
          />
        </div>

        {/* Center — Nav links (desktop; mobile uses the bottom tab bar) */}
        <nav className="hidden lg:flex items-center justify-center gap-1 text-sm">
          {[
            { href: "/", label: "Dashboard" },
            { href: "/roster", label: "Roster" },
            { href: "/waivers", label: "Waivers" },
            { href: "/trade", label: "Trade" },
          ].map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={buildHref(item.href)}
                className={`px-3 py-1.5 rounded-xl border transition whitespace-nowrap ${
                  active
                    ? "bg-violet-50 text-violet-300 border-violet-100"
                    : "text-gray-600 border-gray-200 hover:border-gray-300"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>

        {/* Right — Actions */}
        <div className="flex items-center justify-end gap-2 shrink-0">
          {email ? (
            <>
              <select
                value={leagueId}
                onChange={(e) => setLeague(e.target.value)}
                className="px-3 py-1.5 rounded-xl border border-gray-200 bg-gray-50 text-sm truncate max-w-[40vw] lg:max-w-none"
                title="Select league"
              >
                <option value="">Select league…</option>
                {leagues.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name}
                  </option>
                ))}
              </select>

              {leagueId && (
                <div className="relative flex-shrink-0">
                  <button
                    onClick={sync}
                    onMouseEnter={() => setShowTooltip(true)}
                    onMouseLeave={() => setShowTooltip(false)}
                    disabled={syncing}
                    className="w-8 h-8 rounded-full border border-gray-200 bg-gray-50 hover:border-gray-300 flex items-center justify-center disabled:opacity-40 transition"
                  >
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      width="14"
                      height="14"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      className={syncing ? "animate-spin" : ""}
                    >
                      <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/>
                      <path d="M21 3v5h-5"/>
                    </svg>
                  </button>
                  {showTooltip && !syncing && (
                    <div className="absolute right-0 top-10 bg-gray-100 text-gray-900 text-xs px-3 py-1.5 rounded-lg whitespace-nowrap z-50">
                      {lastSynced ? `Last synced ${timeAgo(lastSynced)}` : "Never synced"}
                    </div>
                  )}
                </div>
              )}

              {/* Avatar with dropdown */}
              <div className="relative flex-shrink-0" ref={dropdownRef}>
  <button
    onClick={() => setDropdownOpen((o) => !o)}
    className="flex items-center gap-1 hover:opacity-80 transition"
    title={email}
  >
    <div className="w-8 h-8 rounded-full bg-violet-600 text-white flex items-center justify-center text-xs font-semibold">
      {badge}
    </div>
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`text-gray-400 transition-transform duration-200 ${dropdownOpen ? "rotate-180" : ""}`}
    >
      <path d="M6 9l6 6 6-6"/>
    </svg>
  </button>

                {dropdownOpen && (
                  <div className="absolute right-0 top-10 w-52 bg-gray-50 border border-gray-200 rounded-xl shadow-lg z-50 overflow-hidden">
                    {/* Email */}
                    <div className="px-4 py-3 border-b border-gray-100">
                      <p className="text-xs text-gray-400 truncate">{email}</p>
                    </div>
                    {/* Settings */}
                    <Link
                      href={buildHref("/settings")}
                      onClick={() => setDropdownOpen(false)}
                      className="flex items-center px-4 py-2.5 text-sm text-gray-700 hover:bg-gray-50 transition"
                    >
                      Settings
                    </Link>
                    {/* Log out */}
                    <button
                      onClick={logout}
                      className="w-full text-left flex items-center px-4 py-2.5 text-sm text-red-400 hover:bg-red-50 transition"
                    >
                      Log out
                    </button>
                  </div>
                )}
              </div>
            </>
          ) : (
            <Link
              href="/login"
              className="px-3 py-1.5 rounded-xl text-sm border border-gray-200 bg-gray-50 hover:border-gray-300 transition whitespace-nowrap"
            >
              Log in
            </Link>
          )}
        </div>
      </div>

      {/* Sync toast */}
      <div
        className={`fixed bottom-6 right-6 bg-gray-100 text-gray-900 text-sm px-4 py-2 rounded-xl shadow-lg transition-opacity duration-300 z-50 ${
          syncToast ? "opacity-100" : "opacity-0 pointer-events-none"
        }`}
      >
        {syncToast}
      </div>
    </div>

    {/* Mobile bottom tab bar — hidden on desktop */}
    {email && (
      <nav className="lg:hidden fixed bottom-0 left-0 right-0 z-40 flex border-t border-gray-200 bg-gray-50 pb-[env(safe-area-inset-bottom)]">
        {MOBILE_TABS.map((tab) => {
          const active = pathname === tab.href;
          return (
            <Link
              key={tab.href}
              href={buildHref(tab.href)}
              className={`flex-1 flex flex-col items-center justify-center gap-0.5 py-2 text-[11px] font-medium transition ${
                active ? "text-violet-600" : "text-gray-400"
              }`}
            >
              {tab.icon}
              {tab.label}
            </Link>
          );
        })}
      </nav>
    )}
    </>
  );
}