"use client";

import { useEffect, useMemo, useState } from "react";
import type { AnalyzeResult } from "../lib/types";
import { UploadAnalyze } from "../components/UploadAnalyze";
import { CapCards } from "../components/CapCards";
import { DecisionQueueTable } from "../components/DecisionQueueTable";
import { RosterTable } from "../components/RosterTable";
import { isMinors, isPitcher } from "../lib/rosterUtils";
import { useRosterFilterSort } from "../useRosterFilterSort";

export default function DashboardPage() {
  const [data, setData] = useState<AnalyzeResult | null>(null);

  const roster = data?.roster ?? [];

  const [rosterTab, setRosterTab] = useState<"hitting" | "pitching" | "minors">(
    "hitting"
  );

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

  const hittingFS = useRosterFilterSort(majorsHitting);
  const pitchingFS = useRosterFilterSort(majorsPitching);
  const minorsHitFS = useRosterFilterSort(minorsHitting);
  const minorsPitchFS = useRosterFilterSort(minorsPitching);

  // sync minors search/sort (so one control drives both minors tables)
  useEffect(() => {
    minorsPitchFS.setQuery(minorsHitFS.query);
  }, [minorsHitFS.query]);

  useEffect(() => {
    minorsPitchFS.setSortKey(minorsHitFS.sortKey);
    minorsPitchFS.setSortDir(minorsHitFS.sortDir);
  }, [minorsHitFS.sortKey, minorsHitFS.sortDir]);

  const activeFS =
    rosterTab === "hitting"
      ? hittingFS
      : rosterTab === "pitching"
      ? pitchingFS
      : minorsHitFS;

  return (
    <main className="space-y-8">
      <header className="space-y-1">
        <h1 className="text-3xl font-semibold">Dashboard</h1>
        <p className="text-gray-700">
          Upload Fantrax CSV → cap summary, decision queue, roster view.
        </p>
      </header>

      <UploadAnalyze
        onData={(d) => {
          setData(d);
          setRosterTab("hitting");
        }}
      />

      {data && (
        <>
          <CapCards cap={data.cap} />

          <DecisionQueueTable items={data.decision_queue} />

          <div className="bg-white border rounded-2xl p-6 shadow-sm space-y-4">
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <h2 className="text-xl font-semibold">Roster</h2>

              <div className="flex flex-col gap-2 md:flex-row md:items-center">
                <input
                  value={activeFS.query}
                  onChange={(e) => activeFS.setQuery(e.target.value)}
                  placeholder="Search player..."
                  className="w-full md:w-64 px-3 py-2 rounded-xl border border-gray-200 bg-white text-sm outline-none focus:border-gray-400"
                />

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

            {rosterTab === "hitting" && (
              <RosterTable
                rows={hittingFS.rows}
                sortKey={hittingFS.sortKey}
                sortDir={hittingFS.sortDir}
                onToggleSort={hittingFS.toggleSort}
              />
            )}

            {rosterTab === "pitching" && (
              <RosterTable
                rows={pitchingFS.rows}
                sortKey={pitchingFS.sortKey}
                sortDir={pitchingFS.sortDir}
                onToggleSort={pitchingFS.toggleSort}
              />
            )}

            {rosterTab === "minors" && (
              <div className="space-y-6">
                <div>
                  <div className="flex justify-between items-center mb-3">
                    <h3 className="text-lg font-semibold">Minors Hitting</h3>
                    <span className="text-sm text-gray-700">
                      {minorsHitting.length}
                    </span>
                  </div>
                  <RosterTable
                    rows={minorsHitFS.rows}
                    sortKey={minorsHitFS.sortKey}
                    sortDir={minorsHitFS.sortDir}
                    onToggleSort={minorsHitFS.toggleSort}
                  />
                </div>

                <div>
                  <div className="flex justify-between items-center mb-3">
                    <h3 className="text-lg font-semibold">Minors Pitching</h3>
                    <span className="text-sm text-gray-700">
                      {minorsPitching.length}
                    </span>
                  </div>
                  <RosterTable
                    rows={minorsPitchFS.rows}
                    sortKey={minorsPitchFS.sortKey}
                    sortDir={minorsPitchFS.sortDir}
                    onToggleSort={minorsPitchFS.toggleSort}
                  />
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </main>
  );
}