import type { Cap } from "../lib/types";
import { money } from "../lib/rosterUtils";

export function CapCards({ cap }: { cap: Cap }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      <div className="bg-white border rounded-2xl p-6 shadow-sm">
        <div className="text-sm text-gray-700">Cap Used</div>
        <div className="text-2xl font-semibold">{money(Number(cap.used))}</div>
      </div>

      <div className="bg-white border rounded-2xl p-6 shadow-sm">
        <div className="text-sm text-gray-700">Cap Limit</div>
        <div className="text-2xl font-semibold">{money(Number(cap.limit))}</div>
      </div>

      <div className="bg-white border rounded-2xl p-6 shadow-sm">
        <div className="text-sm text-gray-700">Cap Remaining</div>
        <div
          className={`text-2xl font-semibold ${
            Number(cap.remaining) < 0 ? "text-red-600" : "text-green-600"
          }`}
        >
          {money(Number(cap.remaining))}
        </div>
      </div>
    </div>
  );
}