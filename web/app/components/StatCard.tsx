import { Card } from "./ui/Card";

type StatCardProps = {
  label: string;
  value: string | number | null;
  subtext?: string;
  subtextColor?: "green" | "amber" | "red" | "muted";
  loading?: boolean;
};

const subtextColors = {
  green: "text-green-400",
  amber: "text-amber-400",
  red: "text-red-500",
  muted: "text-gray-400",
};

export function StatCard({
  label,
  value,
  subtext,
  subtextColor = "muted",
  loading = false,
}: StatCardProps) {
  return (
    <Card padding="p-5">
      <div className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
        {label}
      </div>
      {loading ? (
        <div className="h-8 w-20 bg-gray-100 rounded animate-pulse" />
      ) : (
        <div className="text-3xl font-semibold text-gray-900 leading-none tracking-tight tabular-nums">
          {value ?? "—"}
        </div>
      )}
      {subtext && !loading && (
        <div className={`text-xs mt-1.5 ${subtextColors[subtextColor]}`}>
          {subtext}
        </div>
      )}
    </Card>
  );
}
