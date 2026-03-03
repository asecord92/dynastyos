"use client";

import { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { supabase } from "../lib/supabaseClient";

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const [ready, setReady] = useState(false);
  const [hasSession, setHasSession] = useState(false);

  const isAuthCallbackMoment = useMemo(() => {
    // Supabase OAuth (PKCE) commonly returns with ?code=...
    const code = searchParams.get("code");
    const accessToken = searchParams.get("access_token");
    const refreshToken = searchParams.get("refresh_token");
    return Boolean(code || accessToken || refreshToken);
  }, [searchParams]);

  useEffect(() => {
    let mounted = true;

    async function check() {
      // Give OAuth a tiny grace window so we don't bounce back to /login
      if (isAuthCallbackMoment) {
        await new Promise((r) => setTimeout(r, 800));
      }

      const { data } = await supabase.auth.getSession();
      if (!mounted) return;

      const sessionExists = Boolean(data.session);
      setHasSession(sessionExists);
      setReady(true);

      if (!sessionExists) {
        const dest = pathname || "/";
        router.replace(`/login?redirectedFrom=${encodeURIComponent(dest)}`);
      }
    }

    check();

    const { data: sub } = supabase.auth.onAuthStateChange((_event, session) => {
      if (!mounted) return;
      const sessionExists = Boolean(session);
      setHasSession(sessionExists);
      setReady(true);

      if (!sessionExists) {
        const dest = pathname || "/";
        router.replace(`/login?redirectedFrom=${encodeURIComponent(dest)}`);
      }
    });

    return () => {
      mounted = false;
      sub.subscription.unsubscribe();
    };
  }, [router, pathname, isAuthCallbackMoment]);

  // While checking session / redirecting
  if (!ready || !hasSession) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-100 text-gray-900">
        <div className="text-sm text-gray-500">Checking session…</div>
      </div>
    );
  }

  return <>{children}</>;
}