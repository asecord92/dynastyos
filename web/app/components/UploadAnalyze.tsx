"use client";

import { useState } from "react";
import type { AnalyzeResult } from "../lib/types";

export function UploadAnalyze({
  onData,
}: {
  onData: (data: AnalyzeResult) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function analyze() {
    if (!file) return;

    setLoading(true);
    setError(null);

    try {
      const form = new FormData();
      form.append("file", file);

      const res = await fetch("/api/roster/analyze", {
        method: "POST",
        body: form,
      });

      if (!res.ok) throw new Error(await res.text());

      const json = (await res.json()) as AnalyzeResult;
      onData(json);
    } catch (e: any) {
      setError(e?.message ?? "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="bg-white border rounded-2xl p-6 shadow-sm space-y-4">
      <div className="flex items-center gap-4">
        <input
          id="csv-upload"
          type="file"
          accept=".csv"
          className="hidden"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />

        <label
          htmlFor="csv-upload"
          className="px-4 py-2 rounded-xl bg-gray-900 text-white cursor-pointer hover:bg-black transition"
        >
          {file ? "Change File" : "Choose File"}
        </label>

        <span className="text-sm text-gray-700">
          {file ? file.name : "No file selected"}
        </span>
      </div>

      <button
        onClick={analyze}
        disabled={!file || loading}
        className="px-4 py-2 rounded-xl bg-black text-white disabled:opacity-40"
      >
        {loading ? "Analyzing..." : "Analyze"}
      </button>

      {error && (
        <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-xl p-3">
          {error}
        </div>
      )}
    </div>
  );
}