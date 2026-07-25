"use client";

import { useEffect, ReactNode } from "react";

/**
 * Backdrop + dialog chrome for the app's first-run modals (What's New, Welcome).
 * Owns the bits that are easy to get subtly wrong in a copy: click-outside and
 * Escape both close, clicks inside don't bubble out to the backdrop, and tall
 * content scrolls inside the card instead of the page.
 */
export function ModalShell({
  label,
  onClose,
  children,
}: {
  label: string;
  onClose: () => void;
  children: ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={label}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md bg-gray-50 border rounded-2xl shadow-xl p-6 space-y-5 max-h-[85vh] overflow-y-auto"
      >
        {children}
      </div>
    </div>
  );
}
