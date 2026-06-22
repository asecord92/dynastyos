"use client";

export const dynamic = "force-dynamic"

import { useSearchParams, useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { supabase } from "../../lib/supabaseClient";

export default function CheckEmailPage() {
  const params = useSearchParams();
  const router = useRouter();
  const email = useMemo(() => params.get("email") || "", [params]);

  const [sending, setSending] = useState(false);
  const [msg, setMsg] = useState<string>("");

  async function resend() {
    if (!email) return;
    setMsg("");
    setSending(true);

    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: { emailRedirectTo: `${window.location.origin}/` },
    });

    setSending(false);
    setMsg(error ? error.message : "Sent another magic link.");
  }

  return (
    <main className="min-h-screen bg-[#f6f8fa] flex items-center justify-center px-4">
      <div className="w-full max-w-[360px] text-center">
        <h1 className="text-2xl font-semibold text-gray-900">Check your email</h1>
        <p className="text-sm text-gray-600 mt-2">
          We sent a magic link to{" "}
          <span className="font-medium text-gray-900">{email || "your inbox"}</span>.
        </p>

        <div className="mt-6 bg-white border border-gray-300 rounded-md p-4 shadow-sm text-left">
          <ul className="text-sm text-gray-700 space-y-2">
            <li>• Check spam/promotions if you don’t see it.</li>
            <li>• The link can take a minute to arrive.</li>
          </ul>

          <button
            onClick={resend}
            disabled={!email || sending}
            className="mt-4 w-full rounded-md border border-gray-300 bg-white hover:bg-gray-50
                       text-sm font-medium py-2 transition active:scale-[0.98] active:translate-y-[1px]
                       disabled:opacity-50"
          >
            {sending ? "Sending…" : "Resend email"}
          </button>

          {msg && (
            <div className="mt-3 text-xs text-gray-600">{msg}</div>
          )}

          <button
            onClick={() => router.push("/login")}
            className="mt-3 w-full rounded-md bg-indigo-600 text-white hover:bg-indigo-700
                       text-sm font-medium py-2 transition active:scale-[0.98] active:translate-y-[1px]"
          >
            Back to login
          </button>
        </div>

        <p className="text-xs text-gray-500 mt-6">DynastyOS — Secord Labs</p>
      </div>
    </main>
  );
}