"use client";

import Link from "next/link";
import { WELCOME_HIGHLIGHTS, WELCOME_KEY, WELCOME_STEPS } from "../lib/welcome";
import { ModalShell } from "./ui/ModalShell";

/**
 * One-time orientation for a brand-new account: the two setup steps that gate a
 * working app, then what they unlock. Shown by `FirstRun` (which owns the
 * "is this actually a new user" decision), never on its own.
 */
export function WelcomeModal({ onDismiss }: { onDismiss: () => void }) {
  function dismiss() {
    try {
      localStorage.setItem(WELCOME_KEY, "1");
    } catch {
      /* localStorage unavailable — worst case they see this again */
    }
    onDismiss();
  }

  return (
    <ModalShell label="Welcome to DynastyOS" onClose={dismiss}>
      <div className="space-y-1">
        <span className="text-xs font-semibold uppercase tracking-widest text-violet-500">
          Welcome
        </span>
        <h2 className="text-xl font-semibold text-gray-900">
          Let&apos;s get your league in here
        </h2>
        <p className="text-sm text-gray-500 leading-relaxed">
          Two things to set up, then everything below turns on.
        </p>
      </div>

      <ol className="space-y-4">
        {WELCOME_STEPS.map((step, i) => (
          <li key={step.title} className="flex gap-3">
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-violet-600 text-[11px] font-semibold text-white">
              {i + 1}
            </span>
            <div className="space-y-0.5">
              <p className="text-sm font-medium text-gray-900">{step.title}</p>
              <p className="text-sm text-gray-500 leading-relaxed">{step.body}</p>
            </div>
          </li>
        ))}
      </ol>

      <div className="space-y-3 border-t border-gray-200 pt-4">
        <p className="text-xs font-semibold uppercase tracking-widest text-gray-400">
          What you get
        </p>
        <ul className="space-y-3">
          {WELCOME_HIGHLIGHTS.map((item) => (
            <li key={item.title} className="flex gap-3">
              <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-violet-500" />
              <div className="space-y-0.5">
                <p className="text-sm font-medium text-gray-900">{item.title}</p>
                <p className="text-sm text-gray-500 leading-relaxed">{item.body}</p>
              </div>
            </li>
          ))}
        </ul>
      </div>

      <div className="space-y-2">
        <Link
          href="/settings"
          onClick={dismiss}
          className="block w-full px-4 py-2.5 rounded-xl bg-violet-600 text-white text-sm font-medium text-center hover:bg-violet-700 transition"
        >
          Set it up →
        </Link>
        <button
          onClick={dismiss}
          className="w-full px-4 py-2 text-sm text-gray-500 hover:text-gray-300 transition"
        >
          I&apos;ll do it later
        </button>
      </div>
    </ModalShell>
  );
}
