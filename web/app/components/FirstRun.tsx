"use client";

import { useEffect, useState } from "react";
import { supabase } from "../lib/supabaseClient";
import { WHATS_NEW, WHATS_NEW_KEY } from "../lib/whatsNew";
import { WELCOME_KEY } from "../lib/welcome";
import { WelcomeModal } from "./WelcomeModal";
import { WhatsNewModal } from "./WhatsNewModal";

/**
 * Picks the one first-load modal that fits, so a new account never opens to a
 * changelog about features it has never seen. Someone with no league connected
 * gets the Welcome; everyone else gets What's New.
 *
 * Showing the Welcome also marks the current What's New as seen — the release
 * isn't "new" to someone who wasn't here for the old version, and without this
 * the changelog would fire the moment they connected their first league.
 */
export function FirstRun() {
  // null = still loading; we render nothing until we know, so neither modal flashes.
  const [hasLeagues, setHasLeagues] = useState<boolean | null>(null);
  const [welcomeDone, setWelcomeDone] = useState(false);

  useEffect(() => {
    let cancelled = false;
    supabase
      .from("leagues")
      .select("id")
      .limit(1)
      .then(({ data }: { data: { id: string }[] | null }) => {
        if (!cancelled) setHasLeagues((data?.length ?? 0) > 0);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const showWelcome =
    hasLeagues === false && !welcomeDone && readSeen(WELCOME_KEY) !== "1";

  useEffect(() => {
    if (!showWelcome) return;
    try {
      localStorage.setItem(WHATS_NEW_KEY, WHATS_NEW.id);
    } catch {
      /* ignore — the worst case is they also see the changelog */
    }
  }, [showWelcome]);

  if (hasLeagues === null) return null;
  if (showWelcome) return <WelcomeModal onDismiss={() => setWelcomeDone(true)} />;
  // No league yet but the welcome is already dismissed — stay out of their way.
  if (!hasLeagues) return null;
  return <WhatsNewModal />;
}

function readSeen(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
