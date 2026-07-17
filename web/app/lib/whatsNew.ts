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
  date: "July 16, 2026",
  items: [
    {
      title: "Your morning digest (opt-in)",
      body: "DynastyOS can email you a daily brief for your team around 9 AM PT: a punchy AI-written lead, today's start/sit calls, the news that matters, and the waiver move to make. It's off by default — turn it on from the dashboard banner or in Settings.",
    },
    {
      title: "The Roster page is now the Cap Planner",
      body: "Every player grouped by contract situation with live what-ifs: toggle extend/option/cut on your 2nd-years and keep/cut on everyone else, and watch next season's committed salary, your room under the $335 offseason cap, and your real auction budget (after $1 holds for open spots) update instantly.",
    },
    {
      title: "The app knows your real contract rules now",
      body: "Extensions under $15 jump to exactly $15, the max is $75, a 3rd-year player is understood for what he is — an optioned rental in his final season — and prospects in minors slots don't burn contract years. Every trade and add/drop recommendation now prices contracts correctly.",
    },
    {
      title: "It thinks about the offseason too",
      body: "The AI knows the full cap cycle: get under $335 before the draft, whatever's left is your auction budget, then $450 in-season. It'll even spot when a rival is projected over the number and has to dump salary.",
    },
    {
      title: "Honest cap math",
      body: "IL salaries count against your in-season cap (as the league actually plays it), so the numbers on the Cap Planner match reality.",
    },
  ],
};

export const WHATS_NEW_KEY = "dynastyos:whatsnew:seen";
