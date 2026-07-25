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
  id: "2026-07-24",
  date: "July 24, 2026",
  items: [
    {
      title: "The football Roster page is now a dynasty asset view",
      body: "Your Sleeper roster with real market values (via FantasyCalc), your full draft-pick inventory with what each pick is worth, and an age-curve read on every player — ascending, prime, aging, or cliff.",
    },
    {
      title: "A window verdict, and depth warnings that matter",
      body: "The page reads your whole roster — the value-weighted age of your core plus your pick capital — and calls it: Ascending, Balanced, Win-now, or Aging. It also flags real lineup holes, like being a QB short in superflex.",
    },
    {
      title: "Taxi squad and IR, finally visible",
      body: "Synced rosters now separate taxi and IR from the bench, and the add/drop advisor knows a taxi cut doesn't open a roster spot.",
    },
    {
      title: "Football trades now read the other side",
      body: "The trade tools work out each team's stance — contending or rebuilding, which positions they're thin at, where they have surplus, whether they're rich or poor on picks — so suggestions are things the other owner might actually want.",
    },
    {
      title: "Sharper trade analysis",
      body: "Trade analysis and the target finder now run on Claude Opus 5, and the finder has more room to work. A cut-off answer also says so now instead of failing quietly.",
    },
  ],
};

export const WHATS_NEW_KEY = "dynastyos:whatsnew:seen";
