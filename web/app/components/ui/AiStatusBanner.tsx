"use client";

import Link from "next/link";
import { useAiStatus } from "../../lib/aiStatus";

/**
 * App-wide banner shown when the league owner's Anthropic key is out of credits
 * or was rejected. Every AI feature shares that one key, so this is surfaced once
 * at the top of the app rather than repeated in each widget. Set/cleared by the
 * dashboard widget hook and the trade page as AI calls succeed or fail.
 */
export function AiStatusBanner() {
  const { issue } = useAiStatus();
  if (!issue) return null;

  const copy =
    issue === "out_of_credits"
      ? {
          title: "Your Anthropic API key is out of credits.",
          body: "AI features are paused until you add credits to your Anthropic account.",
          cta: "Add credits at Anthropic Console →",
          href: "https://console.anthropic.com/settings/billing",
          external: true,
        }
      : {
          title: "Your Anthropic API key was rejected.",
          body: "It may have been revoked or mistyped. Update it to turn AI features back on.",
          cta: "Update your key in Settings →",
          href: "/settings",
          external: false,
        };

  const ctaClass =
    "shrink-0 inline-block px-3 py-1.5 rounded-xl bg-amber-600 text-white text-xs font-medium hover:bg-amber-700 transition";

  return (
    <div className="border-b border-amber-500/30 bg-amber-50">
      <div className="max-w-5xl mx-auto px-6 py-3 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <p className="text-sm">
          <span className="font-semibold text-amber-900">{copy.title}</span>{" "}
          <span className="text-amber-800/80">{copy.body}</span>
        </p>
        {copy.external ? (
          <a href={copy.href} target="_blank" rel="noopener noreferrer" className={ctaClass}>
            {copy.cta}
          </a>
        ) : (
          <Link href={copy.href} className={ctaClass}>
            {copy.cta}
          </Link>
        )}
      </div>
    </div>
  );
}
