import { useMemo, useState } from "react";

export type SortKey = "player" | "salary" | "contract";
export type SortDir = "asc" | "desc";

export type RosterRow = {
  player?: string;
  team?: string;
  eligible?: string;
  status?: string;
  contract?: string;
  salary?: number;
};

export function useRosterFilterSort<T extends RosterRow>(rows: T[]) {
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("salary");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  const filteredSortedRows = useMemo(() => {
    const q = query.trim().toLowerCase();

    let out = q
      ? rows.filter((p) => (p.player ?? "").toLowerCase().includes(q))
      : [...rows];

    const dir = sortDir === "asc" ? 1 : -1;

    out.sort((a, b) => {
      if (sortKey === "salary") {
        return (Number(a.salary ?? 0) - Number(b.salary ?? 0)) * dir;
      }

      const av = String((a as any)[sortKey] ?? "");
      const bv = String((b as any)[sortKey] ?? "");
      return av.localeCompare(bv) * dir;
    });

    return out;
  }, [rows, query, sortKey, sortDir]);

  return {
    query,
    setQuery,

    sortKey,
    sortDir,
    setSortKey,
    setSortDir,
    toggleSort,

    rows: filteredSortedRows,
  };
}