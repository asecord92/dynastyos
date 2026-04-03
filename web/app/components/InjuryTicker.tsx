"use client";

import { useEffect, useState } from "react";
import type { Alert } from "./StartSitPanel";

export function InjuryTicker({ alerts }: { alerts: Alert[] }) {
  const [index, setIndex] = useState(0);
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    if (alerts.length <= 1) return;
    const id = setInterval(() => {
      setVisible(false);
      setTimeout(() => {
        setIndex((i) => (i + 1) % alerts.length);
        setVisible(true);
      }, 300);
    }, 8000);
    return () => clearInterval(id);
  }, [alerts.length]);

  if (alerts.length === 0) return null;

  const alert = alerts[index] ?? alerts[0];

  function headerLabel(status: string | undefined): string {
    if (!status) return "Status Alert";
    if (status === "MiLB") return "Minor League";
    if (status === "DTD") return "Day-to-Day";
    if (status.includes("IL")) return "Injured List";
    return "Status Alert";
  }

  return (
    <div className="h-[120px] bg-white border rounded-2xl shadow-sm border-l-4 border-l-orange-400 flex flex-col justify-center px-6 py-5">
      <div
        className={`transition-opacity duration-300 ${visible ? "opacity-100" : "opacity-0"}`}
      >
        <div className="flex items-center gap-2 mb-1.5">
          <span className="text-xs font-bold text-amber-600 uppercase tracking-wide">
            {headerLabel(alert.status)} — {alert.name}
          </span>
          {alert.status && (
            <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-orange-100 text-orange-700 shrink-0">
              {alert.status}
            </span>
          )}
        </div>
        <p className="text-sm text-gray-500 leading-relaxed">{alert.detail}</p>
      </div>
    </div>
  );
}
