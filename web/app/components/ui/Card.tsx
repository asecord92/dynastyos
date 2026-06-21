import type { ReactNode } from "react";

/**
 * Canonical surface. Mirrors the app's existing card pattern (white, hairline
 * border, soft shadow, rounded-2xl) so it's a drop-in, with an optional hover
 * lift for interactive cards.
 */
export function Card({
  children,
  className = "",
  padding = "p-6",
  hover = false,
}: {
  children: ReactNode;
  className?: string;
  padding?: string;
  hover?: boolean;
}) {
  return (
    <div
      className={`bg-white rounded-2xl border border-gray-200/80 shadow-sm ${
        hover ? "transition-shadow hover:shadow-md" : ""
      } ${padding} ${className}`}
    >
      {children}
    </div>
  );
}
