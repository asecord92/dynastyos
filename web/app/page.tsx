"use client";

import { useState } from "react";

function money(n: number) {
  if (!Number.isFinite(n)) return "—";
  return `$${n.toFixed(0)}`;
}

function isPitcher(eligible: string | undefined) {
  const e = (eligible ?? "").toUpperCase();
  // Common Fantrax pitcher eligibility markers
  return e.includes("SP") || e.includes("RP") || e === "P" || e.includes(" P");
}

function isMinors(status: string | undefined) {
  return (status ?? "").toUpperCase() === "MIN";
}

function RosterTable({
  rows,
}: {
  rows: Array<{
    player?: string;
    team?: string;
    eligible?: string;
    status?: string;
    contract?: string;
    salary?: number;
  }>;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead className="border-b text-left text-gray-500">
          <tr>
            <th className="py-2 pr-6">Player</th>
            <th className="py-2 pr-6">Team</th>
            <th className="py-2 pr-6">Eligible</th>
            <th className="py-2 pr-6">Status</th>
            <th className="py-2 pr-6">Contract</th>
            <th className="py-2 pr-6">Salary</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p, i) => (
            <tr key={i} className="border-b last:border-0">
              <td className="py-2 pr-6 font-medium">{p.player ?? "—"}</td>
              <td className="py-2 pr-6">{p.team ?? "—"}</td>
              <td className="py-2 pr-6 whitespace-nowrap">{p.eligible ?? "—"}</td>
              <td className="py-2 pr-6">{p.status ?? "—"}</td>
              <td className="py-2 pr-6">{p.contract ?? "—"}</td>
              <td className="py-2 pr-6">{money(Number(p.salary))}</td>
            </tr>
          ))}

          {rows.length === 0 && (
            <tr>
              <td colSpan={6} className="py-4 text-gray-500">
                No players found.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<any>(null);

  const [rosterTab, setRosterTab] = useState<
    "hitting" | "pitching" | "minors"
  >("hitting");

  async function analyze() {
    if (!file) return;

    setLoading(true);
    setError(null);
    setData(null);

    try {
      const form = new FormData();
      form.append("file", file); // change if your FastAPI expects a different key

      const res = await fetch("/api/roster/analyze", {
        method: "POST",
        body: form,
      });

      if (!res.ok) {
        const text = await res.text();
        throw new Error(text);
      }

      const json = await res.json();
      setData(json);
      setRosterTab("hitting");
    } catch (e: any) {
      setError(e?.message ?? "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  const roster = data?.roster ?? [];

  const minors = roster.filter((p: any) => isMinors(p.status));
  const majors = roster.filter((p: any) => !isMinors(p.status));

  const majorsHitting = majors.filter((p: any) => !isPitcher(p.eligible));
  const majorsPitching = majors.filter((p: any) => isPitcher(p.eligible));

  const minorsHitting = minors.filter((p: any) => !isPitcher(p.eligible));
  const minorsPitching = minors.filter((p: any) => isPitcher(p.eligible));

  return (
    <main className="min-h-screen bg-gray-50 p-8">
      <div className="max-w-5xl mx-auto space-y-8">
        <header>
          <h1 className="text-3xl font-semibold">DynastyOS</h1>
          <p className="text-gray-600">
            Upload Fantrax CSV → Cap summary + Decision Queue + Roster Tabs
          </p>
        </header>

        {/* Upload Section */}
        <div className="bg-white border rounded-2xl p-6 shadow-sm space-y-4">
          <div className="flex items-center gap-4">
            <input
              id="csv-upload"
              type="file"
              accept=".csv,text/csv"
              className="hidden"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />

            <label
              htmlFor="csv-upload"
              className="px-4 py-2 rounded-xl bg-gray-900 text-white cursor-pointer hover:bg-black transition"
            >
              {file ? "Change File" : "Choose File"}
            </label>

            <span className="text-sm text-gray-600">
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

        {data && (
          <>
            {/* Cap Summary */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="bg-white border rounded-2xl p-6 shadow-sm">
                <div className="text-sm text-gray-500">Cap Used</div>
                <div className="text-2xl font-semibold">
                  {money(Number(data.cap?.used))}
                </div>
              </div>

              <div className="bg-white border rounded-2xl p-6 shadow-sm">
                <div className="text-sm text-gray-500">Cap Limit</div>
                <div className="text-2xl font-semibold">
                  {money(Number(data.cap?.limit))}
                </div>
              </div>

              <div className="bg-white border rounded-2xl p-6 shadow-sm">
                <div className="text-sm text-gray-500">Cap Remaining</div>
                <div
                  className={`text-2xl font-semibold ${
                    Number(data.cap?.remaining) < 0
                      ? "text-red-600"
                      : "text-green-600"
                  }`}
                >
                  {money(Number(data.cap?.remaining))}
                </div>
              </div>
            </div>

            {/* Decision Queue */}
            <div className="bg-white border rounded-2xl p-6 shadow-sm">
              <div className="flex justify-between items-center mb-4">
                <h2 className="text-xl font-semibold">
                  Decision Queue (3rd Year)
                </h2>
                <span className="text-sm text-gray-500">
                  {data.decision_queue.length} players
                </span>
              </div>

              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead className="border-b text-left text-gray-500">
                    <tr>
                      <th className="py-2 pr-6">Player</th>
                      <th className="py-2 pr-6">Status</th>
                      <th className="py-2 pr-6">Contract</th>
                      <th className="py-2 pr-6">Salary</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.decision_queue.map((p: any, i: number) => (
                      <tr key={i} className="border-b last:border-0">
                        <td className="py-2 pr-6 font-medium">{p.player}</td>
                        <td className="py-2 pr-6">{p.status}</td>
                        <td className="py-2 pr-6">{p.contract}</td>
                        <td className="py-2 pr-6">{money(Number(p.salary))}</td>
                      </tr>
                    ))}
                    {data.decision_queue.length === 0 && (
                      <tr>
                        <td colSpan={4} className="py-4 text-gray-500">
                          No 3rd-year contracts found.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Roster Tabs */}
            <div className="bg-white border rounded-2xl p-6 shadow-sm space-y-4">
              <div className="flex items-center justify-between gap-4">
                <h2 className="text-xl font-semibold">Roster</h2>

                <div className="flex gap-2">
                  <button
                    onClick={() => setRosterTab("hitting")}
                    className={`px-3 py-1.5 rounded-xl text-sm border transition ${
                      rosterTab === "hitting"
                        ? "bg-black text-white border-black"
                        : "bg-white text-gray-700 border-gray-200 hover:border-gray-300"
                    }`}
                  >
                    Hitting ({majorsHitting.length})
                  </button>

                  <button
                    onClick={() => setRosterTab("pitching")}
                    className={`px-3 py-1.5 rounded-xl text-sm border transition ${
                      rosterTab === "pitching"
                        ? "bg-black text-white border-black"
                        : "bg-white text-gray-700 border-gray-200 hover:border-gray-300"
                    }`}
                  >
                    Pitching ({majorsPitching.length})
                  </button>

                  <button
                    onClick={() => setRosterTab("minors")}
                    className={`px-3 py-1.5 rounded-xl text-sm border transition ${
                      rosterTab === "minors"
                        ? "bg-black text-white border-black"
                        : "bg-white text-gray-700 border-gray-200 hover:border-gray-300"
                    }`}
                  >
                    Minors ({minors.length})
                  </button>
                </div>
              </div>

              {rosterTab === "hitting" && <RosterTable rows={majorsHitting} />}
              {rosterTab === "pitching" && <RosterTable rows={majorsPitching} />}

              {rosterTab === "minors" && (
                <div className="space-y-6">
                  <div>
                    <div className="flex justify-between items-center mb-3">
                      <h3 className="text-lg font-semibold">Minors Hitting</h3>
                      <span className="text-sm text-gray-500">
                        {minorsHitting.length}
                      </span>
                    </div>
                    <RosterTable rows={minorsHitting} />
                  </div>

                  <div>
                    <div className="flex justify-between items-center mb-3">
                      <h3 className="text-lg font-semibold">Minors Pitching</h3>
                      <span className="text-sm text-gray-500">
                        {minorsPitching.length}
                      </span>
                    </div>
                    <RosterTable rows={minorsPitching} />
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </main>
  );
}