type StatCardProps = {
  label: string;
  value: string | number | null;
  subtext?: string;
  subtextColor?: "green" | "amber" | "red" | "muted";
  loading?: boolean;
};

const subtextColors = {
  green: "text-green-600",
  amber: "text-amber-600",
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
    <div className="bg-white border rounded-2xl p-5 shadow-sm">
      <div className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-2">
        {label}
      </div>
      {loading ? (
        <div className="h-8 w-20 bg-gray-100 rounded animate-pulse" />
      ) : (
        <div className="text-3xl font-semibold text-gray-900 leading-none">
          {value ?? "—"}
        </div>
      )}
      {subtext && !loading && (
        <div className={`text-xs mt-1.5 ${subtextColors[subtextColor]}`}>
          {subtext}
        </div>
      )}
    </div>
  );
}
