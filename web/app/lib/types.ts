export type Cap = {
  used: number;
  limit: number;
  remaining: number;
};

export type DecisionItem = {
  player: string;
  status: string;
  salary: number;
  contract: string;

  // new fields (optional so UI doesn't explode if missing)
  recommendation?: string;
  rationale?: string[];
  cap_relief_if_cut?: number;
  cap_remaining_if_cut?: number;
};

export type RosterRow = {
  player?: string;
  team?: string;
  eligible?: string;
  status?: string;
  salary?: number;
  contract?: string;
};

export type AnalyzeResult = {
  cap: Cap;
  decision_queue: DecisionItem[];
  roster: RosterRow[];
};