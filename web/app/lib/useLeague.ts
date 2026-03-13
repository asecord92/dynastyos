"use client";

import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "dynastyos:selected_league_id";

export function useLeague() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const urlLeagueId = searchParams.get("league") ?? "";

  const [leagueId, setLeagueIdState] = useState<string>(() => {
    if (urlLeagueId) return urlLeagueId;
    if (typeof window !== "undefined") {
      return localStorage.getItem(STORAGE_KEY) ?? "";
    }
    return "";
  });

  // If URL has a league ID, keep local state in sync
  useEffect(() => {
    if (urlLeagueId && urlLeagueId !== leagueId) {
      setLeagueIdState(urlLeagueId);
      localStorage.setItem(STORAGE_KEY, urlLeagueId);
    }
  }, [urlLeagueId]);

  // If no URL param but we have one in localStorage, push it to the URL
  useEffect(() => {
    if (!urlLeagueId && leagueId) {
      const params = new URLSearchParams(searchParams.toString());
      params.set("league", leagueId);
      router.replace(`${pathname}?${params.toString()}`);
    }
  }, []);

  const setLeague = useCallback((id: string) => {
    setLeagueIdState(id);
    localStorage.setItem(STORAGE_KEY, id);
    const params = new URLSearchParams(searchParams.toString());
    params.set("league", id);
    router.push(`${pathname}?${params.toString()}`);
  }, [pathname, searchParams, router]);

  const buildHref = useCallback((path: string) => {
    if (!leagueId) return path;
    return `${path}?league=${leagueId}`;
  }, [leagueId]);

  return { leagueId, setLeague, buildHref };
}