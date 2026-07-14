"use client";

/** "just now" / "5m ago" / "3h ago" / "2d ago" — accepts an ISO string or Date. */
export function timeAgo(when: string | Date): string {
  const t = when instanceof Date ? when.getTime() : new Date(when).getTime();
  const seconds = Math.floor((Date.now() - t) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

/**
 * Renders the lightweight markdown the AI widgets emit: `**bold**` spans,
 * blank-line spacing, and headings (either `## Heading` or a fully-bold line).
 */
export function MarkdownContent({ text }: { text: string }) {
  return (
    <div className="space-y-1">
      {text.split("\n").map((line, i) => {
        const isHashHeading = line.startsWith("##");
        const isBoldHeading = line.startsWith("**") && line.endsWith("**") && line.length > 4;
        const cleanLine = isHashHeading ? line.replace(/^#+\s*/, "") : line;
        const parts = cleanLine.split(/\*\*(.*?)\*\*/g);
        return (
          <p
            key={i}
            className={
              isHashHeading || isBoldHeading
                ? "font-semibold text-gray-900 mt-3 mb-1"
                : line.trim() === ""
                ? "h-2"
                : "text-sm text-gray-700 leading-relaxed"
            }
          >
            {parts.map((part, j) =>
              j % 2 === 1 ? <strong key={j}>{part}</strong> : part
            )}
          </p>
        );
      })}
    </div>
  );
}
