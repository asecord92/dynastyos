"use client";

import Link from "next/link";

/**
 * Shown in place of an AI-powered widget/tool when the league owner hasn't added
 * their own Anthropic API key (the backend returns 402). DynastyOS is BYOK — there
 * is no shared key — so AI features stay off until a key is set in Settings.
 */
export function NeedsApiKey({ feature = "This feature" }: { feature?: string }) {
  return (
    <div className="text-sm text-gray-600 bg-gray-50 border border-gray-200 rounded-xl p-4 space-y-2">
      <p className="font-medium text-gray-800">{feature} needs your Anthropic API key.</p>
      <p className="text-gray-500 leading-relaxed">
        DynastyOS uses your own Anthropic key for AI features, so you&apos;re only
        billed for your own usage. Add one to turn this on.
      </p>
      <Link
        href="/settings"
        className="inline-block mt-1 px-3 py-1.5 rounded-xl bg-violet-600 text-white text-xs font-medium hover:bg-violet-700 transition"
      >
        Add your key in Settings →
      </Link>
    </div>
  );
}
