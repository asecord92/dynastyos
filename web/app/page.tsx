"use client";

import { useMemo, useState } from "react";

function money(n: number) {
  if (!Number.isFinite(n)) return "—";
  return `$${n.toFixed(0)}`;
}

function isPitcher(eligible: string | undefined) {
  const e = (eligible ?? "").toUpperCase();
  return e.includes("SP") || e.includes("RP") || e === "P" || e.includes(" P");
}

function isMinors(status: string | undefined) {
  return (status ?? "").toUpperCase() === "MIN";
}

type RosterRow = {
  player?: string;
  team?: string;
  eligible?: string;
  status?: string;
  contract?: string;
  salary?: number;
};

function RosterTable({ rows }: { rows: RosterRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead className="border-b text-left text-gray-600">
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
              <td colSpan={6} className="py-4 text-gray-600">
                No players found.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

type SortMode = "salary_desc" | "salary_asc" | "player_asc" | "contract_asc";

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<any>(null);

  const [rosterTab, setRosterTab] = useState<"hitting" | "pitching" | "minors">(
    "hitting"
  );
  const [rosterQuery, setRosterQuery] = useState("");
  const [rosterSort, setRosterSort] = useState<SortMode>("salary_desc");

  async function analyze() {
    if (!file) return;

    setLoading(true);
    setError(null);
    setData(null);

    try {
      const form = new FormData();
      form.append("file", file);

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

      // reset UX
      setRosterTab("hitting");
      setRosterQuery("");
      setRosterSort("salary_desc");
    } catch (e: any) {
      setError(e?.message ?? "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  const roster: RosterRow[] = data?.roster ?? [];

  const minors = useMemo(() => roster.filter((p) => isMinors(p.status)), [roster]);
  const majors = useMemo(() => roster.filter((p) => !isMinors(p.status)), [roster]);

  const majorsHitting = useMemo(
    () => majors.filter((p) => !isPitcher(p.eligible)),
    [majors]
  );
  const majorsPitching = useMemo(
    () => majors.filter((p) => isPitcher(p.eligible)),
    [majors]
  );

  const minorsHitting = useMemo(
    () => minors.filter((p) => !isPitcher(p.eligible)),
    [minors]
  );
  const minorsPitching = useMemo(
    () => minors.filter((p) => isPitcher(p.eligible)),
    [minors]
  );

  const applyQueryAndSort = (rows: RosterRow[]) => {
    const q = rosterQuery.trim().toLowerCase();

    let out = q
      ? rows.filter((p) => (p.player ?? "").toLowerCase().includes(q))
      : [...rows];

    switch (rosterSort) {
      case "salary_desc":
        out.sort((a, b) => Number(b.salary ?? 0) - Number(a.salary ?? 0));
        break;
      case "salary_asc":
        out.sort((a, b) => Number(a.salary ?? 0) - Number(b.salary ?? 0));
        break;
      case "player_asc":
        out.sort((a, b) =>
          String(a.player ?? "").localeCompare(String(b.player ?? ""))
        );
        break;
      case "contract_asc":
        out.sort((a, b) =>
          String(a.contract ?? "").localeCompare(String(b.contract ?? ""))
        );
        break;
    }

    return out;
  };

  const hittingRows = useMemo(
    () => applyQueryAndSort(majorsHitting),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [majorsHitting, rosterQuery, rosterSort]
  );
  const pitchingRows = useMemo(
    () => applyQueryAndSort(majorsPitching),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [majorsPitching, rosterQuery, rosterSort]
  );
  const minorsHitRows = useMemo(
    () => applyQueryAndSort(minorsHitting),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [minorsHitting, rosterQuery, rosterSort]
  );
  const minorsPitchRows = useMemo(
    () => applyQueryAndSort(minorsPitching),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [minorsPitching, rosterQuery, rosterSort]
  );

  return (
    <main className="min-h-screen bg-gray-100 text-gray-900 p-8">
      <div className="max-w-5xl mx-auto space-y-8">
        <header>
          <h1 className="text-3xl font-semibold">DynastyOS</h1>
          <p className="text-gray-700">
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

        {data && (
          <>
            {/* Cap Summary */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="bg-white border rounded-2xl p-6 shadow-sm">
                <div className="text-sm text-gray-700">Cap Used</div>
                <div className="text-2xl font-semibold">
                  {money(Number(data.cap?.used))}
                </div>
              </div>

              <div className="bg-white border rounded-2xl p-6 shadow-sm">
                <div className="text-sm text-gray-700">Cap Limit</div>
                <div className="text-2xl font-semibold">
                  {money(Number(data.cap?.limit))}
                </div>
              </div>

              <div className="bg-white border rounded-2xl p-6 shadow-sm">
                <div className="text-sm text-gray-700">Cap Remaining</div>
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
                <span className="text-sm text-gray-700">
                  {data.decision_queue.length} players
                </span>
              </div>

              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead className="border-b text-left text-gray-600">
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
                        <td colSpan={4} className="py-4 text-gray-700">
                          No 3rd-year contracts found.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Roster Tabs + Search/Sort */}
            <div className="bg-white border rounded-2xl p-6 shadow-sm space-y-4">
              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <h2 className="text-xl font-semibold">Roster</h2>

                <div className="flex flex-col gap-2 md:flex-row md:items-center">
                  <input
                    value={rosterQuery}
                    onChange={(e) => setRosterQuery(e.target.value)}
                    placeholder="Search player..."
                    className="w-full md:w-64 px-3 py-2 rounded-xl border border-gray-200 bg-white text-sm outline-none focus:border-gray-400"
                  />

                  <select
                    value={rosterSort}
                    onChange={(e) => setRosterSort(e.target.value as SortMode)}
                    className="w-full md:w-auto px-3 py-2 rounded-xl border border-gray-200 bg-white text-sm outline-none focus:border-gray-400"
                  >
                    <option value="salary_desc">Salary ↓</option>
                    <option value="salary_asc">Salary ↑</option>
                    <option value="player_asc">Player A–Z</option>
                    <option value="contract_asc">Contract A–Z</option>
                  </select>

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
              </div>

              {rosterTab === "hitting" && <RosterTable rows={hittingRows} />}
              {rosterTab === "pitching" && <RosterTable rows={pitchingRows} />}

              {rosterTab === "minors" && (
                <div className="space-y-6">
                  <div>
                    <div className="flex justify-between items-center mb-3">
                      <h3 className="text-lg font-semibold">Minors Hitting</h3>
                      <span className="text-sm text-gray-700">
                        {minorsHitting.length}
                      </span>
                    </div>
                    <RosterTable rows={minorsHitRows} />
                  </div>

                  <div>
                    <div className="flex justify-between items-center mb-3">
                      <h3 className="text-lg font-semibold">Minors Pitching</h3>
                      <span className="text-sm text-gray-700">
                        {minorsPitching.length}
                      </span>
                    </div>
                    <RosterTable rows={minorsPitchRows} />
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