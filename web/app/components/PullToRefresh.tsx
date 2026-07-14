"use client";

import { useEffect, useRef, useState } from "react";

const THRESHOLD = 80;

/**
 * Phone-style pull-to-refresh for the whole app: drag down from the top of the
 * page and release to reload. Reload is the right refresh here — every widget
 * paints instantly from its localStorage cache and revalidates in the
 * background, so it feels like a data refresh, not a cold load. No-op on
 * desktop (mouse input never fires touch events).
 */
export function PullToRefresh() {
  const [pull, setPull] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const startY = useRef<number | null>(null);

  useEffect(() => {
    const onTouchStart = (e: TouchEvent) => {
      // Only arm when the page is scrolled to the very top.
      startY.current = window.scrollY <= 0 ? e.touches[0].clientY : null;
    };
    const onTouchMove = (e: TouchEvent) => {
      if (startY.current == null) return;
      const dy = e.touches[0].clientY - startY.current;
      if (dy > 10 && window.scrollY <= 0) {
        // Dampen so the indicator trails the finger.
        setPull(Math.min(dy * 0.5, THRESHOLD * 1.4));
      } else {
        setPull(0);
      }
    };
    const onTouchEnd = () => {
      startY.current = null;
      setPull((p) => {
        if (p >= THRESHOLD) {
          setRefreshing(true);
          window.location.reload();
          return p; // keep the spinner up while the reload lands
        }
        return 0;
      });
    };
    document.addEventListener("touchstart", onTouchStart, { passive: true });
    document.addEventListener("touchmove", onTouchMove, { passive: true });
    document.addEventListener("touchend", onTouchEnd);
    return () => {
      document.removeEventListener("touchstart", onTouchStart);
      document.removeEventListener("touchmove", onTouchMove);
      document.removeEventListener("touchend", onTouchEnd);
    };
  }, []);

  if (pull <= 0 && !refreshing) return null;

  const armed = refreshing || pull >= THRESHOLD;
  return (
    <div
      className="fixed top-0 inset-x-0 z-50 flex justify-center pointer-events-none"
      style={{
        transform: `translateY(${Math.min(pull, THRESHOLD)}px)`,
        opacity: Math.min(pull / THRESHOLD, 1),
      }}
    >
      <div className="mt-2 w-9 h-9 rounded-full bg-gray-50 border border-gray-200 shadow-lg flex items-center justify-center">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={armed ? "animate-spin text-violet-400" : "text-gray-400"}
          style={armed ? undefined : { transform: `rotate(${pull * 2.5}deg)` }}
        >
          <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8" />
          <path d="M21 3v5h-5" />
        </svg>
      </div>
    </div>
  );
}
