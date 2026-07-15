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
  id: "2026-07-15",
  date: "July 15, 2026",
  items: [
    {
      title: "Pull to refresh",
      body: "Drag down from the top of any page to refresh — just like every other app on your phone.",
    },
    {
      title: "Smarter waiver picks",
      body: "Waiver Spotlight now works from real season stat lines for every available player, plus your remaining cap space — recommendations are sharper, faster, and always affordable.",
    },
    {
      title: "News that knows your team",
      body: "Player news now prioritizes your weakest categories and factors in each player's salary and contract year, instead of treating all 40 guys the same.",
    },
    {
      title: "Faster and steadier everywhere",
      body: "A big under-the-hood pass: the app no longer stalls while a widget generates, syncs finish in seconds instead of half a minute, and double-tapping refresh can't bill your API key twice.",
    },
    {
      title: "Little things",
      body: "Live progress while category ranks auto-calculate, a Show/Hide toggle on your API key, retry buttons on trade errors, and bigger tap targets on mobile.",
    },
  ],
};

export const WHATS_NEW_KEY = "dynastyos:whatsnew:seen";
