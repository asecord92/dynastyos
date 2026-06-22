"use client";

export const dynamic = "force-dynamic"

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { supabase } from "../../lib/supabaseClient";

function safeRedirectPath(input: string | null): string {
  if (!input) return "/";
  if (!input.startsWith("/")) return "/";
  if (input.startsWith("//")) return "/";
  return input;
}

export default function LoginPage() {
  const router = useRouter();
  const params = useSearchParams();

  const redirectedFrom = useMemo(
    () => safeRedirectPath(params.get("redirectedFrom")),
    [params]
  );

  const [email, setEmail] = useState("");
  const [loadingMagic, setLoadingMagic] = useState(false);
  const [loadingGoogle, setLoadingGoogle] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    supabase.auth.getSession().then(({ data }) => {
      if (!mounted) return;
      if (data.session) router.replace(redirectedFrom);
    });
    return () => {
      mounted = false;
    };
  }, [router, redirectedFrom]);

  async function sendMagicLink() {
    setErrorMsg(null);
    setLoadingMagic(true);

    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: {
        emailRedirectTo: `${window.location.origin}${redirectedFrom}`,
      },
    });

    setLoadingMagic(false);

    if (error) {
      setErrorMsg(error.message);
      return;
    }

    router.push(
      `/check-email?email=${encodeURIComponent(email)}&redirectedFrom=${encodeURIComponent(
        redirectedFrom
      )}`
    );
  }

  async function signInWithGoogle() {
    setErrorMsg(null);
    setLoadingGoogle(true);

    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: `${window.location.origin}${redirectedFrom}`,
      },
    });

    if (error) {
      setLoadingGoogle(false);
      setErrorMsg(error.message);
    }
  }

  const disabled = loadingMagic || loadingGoogle;

  return (
    <main className="min-h-screen flex items-center justify-center bg-gray-100 px-4">
      <div className="w-full max-w-[420px]">
        {/* Logo */}
        <div className="flex justify-center mb-6">
          <div className="h-12 w-12 rounded-full bg-indigo-600 text-white flex items-center justify-center font-semibold text-lg">
            D
          </div>
        </div>

        {/* Title */}
        <h1 className="text-3xl font-semibold text-center text-gray-900">
          Sign in to DynastyOS
        </h1>
        <p className="text-center text-gray-500 mt-1">Secord Labs</p>

        {/* Card */}
        <div className="mt-8 bg-gray-50 border border-gray-200 rounded-xl shadow-sm p-6">
          {errorMsg && (
            <div className="mb-4 rounded-lg border border-red-500/30 bg-red-50 px-3 py-2 text-sm text-red-300">
              {errorMsg}
            </div>
          )}

          {/* Email Input */}
          <div className="space-y-2">
            <label className="text-sm font-medium text-gray-700">
              Email address
            </label>

            <input
              type="email"
              placeholder="you@email.com"
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm
                         focus:outline-none focus:ring-2 focus:ring-gray-200"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={disabled}
            />
          </div>

          {/* Magic Link Button */}
          <button
            onClick={sendMagicLink}
            disabled={!email || disabled}
            className="mt-4 w-full rounded-md py-2 text-sm font-semibold text-white
                       bg-emerald-600 hover:bg-emerald-700
                       transition active:scale-[0.98] active:translate-y-[1px]
                       disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loadingMagic ? "Sending…" : "Send magic link"}
          </button>

          {/* Divider */}
          <div className="flex items-center my-6 text-sm text-gray-500">
            <div className="flex-grow border-t border-gray-200" />
            <span className="px-3">OR</span>
            <div className="flex-grow border-t border-gray-200" />
          </div>

          {/* Google Button */}
          <button
            onClick={signInWithGoogle}
            disabled={disabled}
            className="w-full flex items-center justify-center gap-3 rounded-md py-2 text-sm font-semibold
                       border border-gray-300 bg-gray-50 hover:bg-gray-50 text-gray-900
                       transition active:scale-[0.98] active:translate-y-[1px]
                       disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loadingGoogle ? (
              "Opening Google…"
            ) : (
              <>
                {/* Google SVG */}
                <svg
                  className="h-5 w-5"
                  viewBox="0 0 48 48"
                  xmlns="http://www.w3.org/2000/svg"
                >
                  <path
                    fill="#EA4335"
                    d="M24 9.5c3.1 0 5.9 1.1 8.1 3.2l6-6C34.6 3.2 29.7 1 24 1 14.6 1 6.5 6.6 2.7 14.7l7.5 5.8C12.1 14 17.6 9.5 24 9.5z"
                  />
                  <path
                    fill="#34A853"
                    d="M46.1 24.6c0-1.6-.1-3.1-.4-4.6H24v9h12.4c-.5 2.7-2 5-4.2 6.6l6.5 5c3.8-3.5 6-8.7 6-16z"
                  />
                  <path
                    fill="#FBBC05"
                    d="M10.2 28.5c-.6-1.8-.6-3.7 0-5.5l-7.5-5.8C.9 20.5 0 22.2 0 24c0 1.8.9 3.5 2.7 6.8l7.5-2.3z"
                  />
                  <path
                    fill="#4285F4"
                    d="M24 47c6.5 0 12-2.1 16-6.3l-6.5-5c-1.8 1.2-4.2 2-9.5 2-6.4 0-11.9-4.5-13.8-10.5l-7.5 5.8C6.5 41.4 14.6 47 24 47z"
                  />
                </svg>

                Continue with Google
              </>
            )}
          </button>

          <p className="text-xs text-center text-gray-500 mt-6">
            Built for dynasty degenerates
          </p>
        </div>
      </div>
    </main>
  );
}