"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "../../lib/supabaseClient";

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
      <path
        fill="#FFC107"
        d="M43.611 20.083H42V20H24v8h11.303C33.647 32.657 29.221 36 24 36c-6.627 0-12-5.373-12-12s5.373-12 12-12c3.059 0 5.842 1.154 7.961 3.039l5.657-5.657C34.047 6.053 29.221 4 24 4 12.955 4 4 12.955 4 24s8.955 20 20 20 20-8.955 20-20c0-1.341-.138-2.651-.389-3.917z"
      />
      <path
        fill="#FF3D00"
        d="M6.306 14.691l6.571 4.819C14.655 16.108 19.001 12 24 12c3.059 0 5.842 1.154 7.961 3.039l5.657-5.657C34.047 6.053 29.221 4 24 4c-7.682 0-14.31 4.337-17.694 10.691z"
      />
      <path
        fill="#4CAF50"
        d="M24 44c5.117 0 9.86-1.965 13.409-5.164l-6.198-5.243C29.154 35.118 26.715 36 24 36c-5.199 0-9.613-3.317-11.272-7.946l-6.517 5.02C9.561 39.556 16.229 44 24 44z"
      />
      <path
        fill="#1976D2"
        d="M43.611 20.083H42V20H24v8h11.303c-.785 2.22-2.271 4.103-4.092 5.346l.002-.001 6.198 5.243C36.971 39.205 44 34 44 24c0-1.341-.138-2.651-.389-3.917z"
      />
    </svg>
  );
}

export default function LoginPage() {
  const router = useRouter();

  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [errorMsg, setErrorMsg] = useState<string>("");

  const canSend = useMemo(() => {
    const trimmed = email.trim();
    return trimmed.length > 3 && trimmed.includes("@");
  }, [email]);

  // Redirect logged-in users away from /login
  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      if (data.session) router.replace("/");
    });
  }, [router]);

  async function sendMagicLink() {
    setErrorMsg("");
    setStatus("sending");

    const { error } = await supabase.auth.signInWithOtp({
      email: email.trim(),
      options: {
        // after clicking the email link, user returns to the app
        emailRedirectTo: `${window.location.origin}/`,
      },
    });

    if (error) {
      setStatus("error");
      // common: email rate limit exceeded
      setErrorMsg(error.message || "Something went wrong.");
      return;
    }

    setStatus("sent");
    router.push(`/check-email?email=${encodeURIComponent(email.trim())}`);
  }

  async function signInWithGoogle() {
    setErrorMsg("");
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${window.location.origin}/` },
    });

    if (error) {
      setStatus("error");
      setErrorMsg(error.message || "Google sign-in failed.");
    }
  }

  return (
    <main className="min-h-screen bg-[#f6f8fa] flex items-center justify-center px-4">
      <div className="w-full max-w-[340px]">
        {/* Header */}
        <div className="text-center mb-4">
          <div className="mx-auto mb-3 h-12 w-12 rounded-full bg-black text-white flex items-center justify-center text-lg font-semibold">
            D
          </div>
          <h1 className="text-2xl font-semibold text-gray-900">Sign in to DynastyOS</h1>
          <p className="text-sm text-gray-600 mt-1">Secord Labs</p>
        </div>

        {/* Card */}
        <div className="bg-white border border-gray-300 rounded-md p-4 shadow-sm">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Email address
          </label>

          <input
            type="email"
            placeholder="you@email.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm
                       focus:outline-none focus:ring-2 focus:ring-gray-200"
          />

          <button
            onClick={sendMagicLink}
            disabled={!canSend || status === "sending"}
            className="mt-4 w-full rounded-md bg-[#2da44e] hover:bg-[#2c974b]
                       text-white text-sm font-medium py-2
                       transition active:scale-[0.98] active:translate-y-[1px]
                       disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {status === "sending" ? "Sending…" : "Send magic link"}
          </button>

          {/* Inline error */}
          {status === "error" && (
            <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {errorMsg}
            </div>
          )}

          {/* Divider */}
          <div className="flex items-center my-5 text-xs text-gray-500">
            <div className="flex-grow border-t border-gray-200" />
            <span className="px-3">OR</span>
            <div className="flex-grow border-t border-gray-200" />
          </div>

          <button
            onClick={signInWithGoogle}
            className="w-full rounded-md border border-gray-300 bg-white hover:bg-gray-50
                       text-sm font-medium py-2 flex items-center justify-center gap-2
                       transition active:scale-[0.98] active:translate-y-[1px]"
          >
            <GoogleIcon />
            Continue with Google
          </button>

          <p className="mt-4 text-xs text-gray-500 text-center">
            Built for dynasty degenerates
          </p>
        </div>
      </div>
    </main>
  );
}