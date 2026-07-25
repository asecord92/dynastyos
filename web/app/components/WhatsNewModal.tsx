"use client";

import { useEffect, useState } from "react";
import { WHATS_NEW, WHATS_NEW_KEY } from "../lib/whatsNew";
import { ModalShell } from "./ui/ModalShell";

/**
 * Shows the current release's "What's New" note once per person. Reveals only
 * after mount (localStorage is client-only, so this avoids a hydration mismatch)
 * and marks the release seen on dismiss. Bump WHATS_NEW.id to re-show it.
 *
 * Mounted by `FirstRun`, which keeps it away from brand-new accounts.
 */
export function WhatsNewModal() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    try {
      if (localStorage.getItem(WHATS_NEW_KEY) !== WHATS_NEW.id) setOpen(true);
    } catch {
      /* localStorage unavailable — just don't show it */
    }
  }, []);

  function dismiss() {
    try {
      localStorage.setItem(WHATS_NEW_KEY, WHATS_NEW.id);
    } catch {
      /* ignore */
    }
    setOpen(false);
  }

  if (!open) return null;

  return (
    <ModalShell label="What's new" onClose={dismiss}>
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-widest text-violet-500">
            What&apos;s new
          </span>
          <span className="text-xs text-gray-400">{WHATS_NEW.date}</span>
        </div>
        <h2 className="text-xl font-semibold text-gray-900">A few new things</h2>
      </div>

      <ul className="space-y-4">
        {WHATS_NEW.items.map((item) => (
          <li key={item.title} className="flex gap-3">
            <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-violet-500" />
            <div className="space-y-0.5">
              <p className="text-sm font-medium text-gray-900">{item.title}</p>
              <p className="text-sm text-gray-500 leading-relaxed">{item.body}</p>
            </div>
          </li>
        ))}
      </ul>

      <button
        onClick={dismiss}
        className="w-full px-4 py-2.5 rounded-xl bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 transition"
      >
        Got it
      </button>
    </ModalShell>
  );
}
