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
    }, 4000);
    return () => clearInterval(id);
  }, [alerts.length]);

  if (alerts.length === 0) return null;

  const alert = alerts[index] ?? alerts[0];

  return (
    <div className="flex-1 min-h-0 bg-white border rounded-2xl shadow-sm border-l-4 border-l-orange-400 flex flex-col justify-center px-6 py-5">
      <div
        className={`transition-opacity duration-300 ${visible ? "opacity-100" : "opacity-0"}`}
      >
        <div className="text-xs font-bold text-amber-600 uppercase tracking-wide mb-2">
          Injury Alert — {alert.name}
        </div>
        <p className="text-sm text-gray-500 leading-relaxed">{alert.detail}</p>
      </div>
    </div>
  );
}
