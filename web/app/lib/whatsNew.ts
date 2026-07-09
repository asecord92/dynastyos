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
  id: "2026-07-09",
  date: "July 9, 2026",
  items: [
    {
      title: "Add / Drop Analyzer",
      body: "New on the Waivers page (baseball & football). Tell it who you're adding — off IL, from waivers, or in a lopsided trade — and it ranks who to drop to make room.",
    },
    {
      title: "Trade History",
      body: "The Trade page has a History tab now. Every trade you analyze is saved with its verdict and full write-up, so you can look back at past advice.",
    },
    {
      title: "Out-of-credits alerts",
      body: "If your Anthropic key runs out of credits, you'll get a clear heads-up instead of features quietly failing to load.",
    },
    {
      title: "Sharper suggestions",
      body: "Player valuation got an overhaul under the hood — better-balanced trade packages and smarter drop rankings.",
    },
  ],
};

export const WHATS_NEW_KEY = "dynastyos:whatsnew:seen";
