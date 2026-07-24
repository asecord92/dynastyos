/**
 * "What's New" changelog shown once per release. Bump `id` whenever you want the
 * modal to re-appear for everyone (typically after shipping user-facing changes),
 * and rewrite `items` to describe what's new. The last-seen id is stored in
 * localStorage, so each person sees a given release's note exactly once.
 */
export type WhatsNewEntry = {
  id: string; // bump to re-show the modal after a release
  date: string;
  items: { title: string; body: string }[];
};

export const WHATS_NEW: WhatsNewEntry = {
  id: "2026-07-16",
  date: "July 23, 2026",
  items: [
    {
      title: "The football Roster page is now a dynasty asset view",
      body: "Your Sleeper roster with real market values (via FantasyCalc), your full draft-pick inventory with what each pick is worth, and an age-curve read on every player — ascending, prime, aging, or cliff.",
    },
    {
      title: "A one-line window verdict",
      body: "The page reads your whole roster — the value-weighted age of your core plus your pick capital — and calls it: Ascending, Balanced, Win-now, or Aging (sell high).",
    },
    {
      title: "Depth warnings that matter",
      body: "It flags real lineup problems, like being one QB short in a superflex league or having no depth behind a starter — computed from your actual lineup slots.",
    },
    {
      title: "Taxi squad and IR, finally visible",
      body: "Synced rosters now distinguish taxi and IR players from the bench, and the add/drop advisor knows a taxi cut doesn't open a roster spot.",
    },
  ],
};

export const WHATS_NEW_KEY = "dynastyos:whatsnew:seen";
