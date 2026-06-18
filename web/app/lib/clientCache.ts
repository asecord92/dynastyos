"use client";

/**
 * Tiny localStorage-backed cache for stale-while-revalidate rendering. Widgets
 * paint the last-known response instantly on mount, then refetch in the
 * background — so navigating back to a page (or a cold backend waking up) no
 * longer shows an empty spinner. Best-effort: any storage/JSON error is ignored.
 */
export function readCache<T>(key: string): T | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

export function writeCache<T>(key: string, value: T): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // quota / serialization errors are non-fatal for a cache
  }
}
