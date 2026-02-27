"use client";

import { useState } from "react";
import type { AnalyzeResult } from "../../lib/types";
import { UploadAnalyze } from "../../components/UploadAnalyze";
import { CapReliefTool } from "../../components/CapReliefTool";

export default function CapReliefPage() {
  const [data, setData] = useState<AnalyzeResult | null>(null);

  return (
    <main className="space-y-8">
      <header className="space-y-1">
        <h1 className="text-3xl font-semibold">Cap Relief</h1>
        <p className="text-gray-700">
          Focused cap tool: pick cuts and see the live cap result.
        </p>
      </header>

      <UploadAnalyze onData={setData} />

      {data && <CapReliefTool data={data} />}
    </main>
  );
}