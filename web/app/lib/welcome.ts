/**
 * First-run content for people who have just signed up and have no league
 * connected yet. Deliberately separate from `whatsNew.ts`: a changelog is for
 * people who already know the app, and showing it to someone on their very
 * first load explains what changed about features they have never seen.
 * `FirstRun` picks exactly one of the two.
 *
 * Unlike the What's New id, this key is never bumped — the welcome is a
 * one-time orientation, not a release note.
 */
export const WELCOME_KEY = "dynastyos:welcome:seen";

/** The two things that actually gate a working app, in the order they matter. */
export const WELCOME_STEPS: { title: string; body: string }[] = [
  {
    title: "Add your Anthropic API key",
    body: "Settings → paste a key from console.anthropic.com (it starts with sk-ant-). Every AI feature runs on your own key, so you only ever pay for your own usage.",
  },
  {
    title: "Connect your league",
    body: "Fantrax needs your Secret ID, Sleeper just needs your username. Rosters, standings, and contracts pull in from there — and re-sync on their own after that.",
  },
];

/** What's waiting once those two are done. Kept short — this is a teaser. */
export const WELCOME_HIGHLIGHTS: { title: string; body: string }[] = [
  {
    title: "Trade tools",
    body: "Build a trade and get a straight verdict — checked against live stats, injuries, and what the other side actually needs. Or let it scan every roster and find targets for you.",
  },
  {
    title: "Contracts & cap",
    body: "Baseball gets a cap planner that projects next season's salaries and your auction budget. Football gets a dynasty asset view with market values for players and picks.",
  },
  {
    title: "Waivers & start/sit",
    body: "Who to add, who to drop, and who to start — with the reasoning, not just a ranking.",
  },
  {
    title: "A daily digest, if you want it",
    body: "One morning email with your league's news. Off by default; turn it on from the dashboard.",
  },
];
