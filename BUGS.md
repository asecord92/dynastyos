# Known Bugs & Proposed Fixes

Working list of diagnosed-but-not-yet-fixed bugs. Each entry: symptoms, diagnosis,
proposed fix, and how to verify. Remove entries when the fix ships (the PR is the
record). Roadmap features live in CLAUDE.md — this file is only for defects.

---

## 1. Trade analyzer: "Load failed" on phone, very slow on desktop

**Reported:** 2026-07-16 (Adam). Analyze took forever; failed with "Load failed —
Retry" on iPhone (resync didn't help); succeeded on desktop but took minutes.

**Diagnosis — two stacking silent-gap problems in `/trade/analyze`:**

1. **Time-to-first-byte gap.** `build_trade_context` (live MLB stat fetches for
   every player in the trade, with retries) runs *before* the streaming response
   starts — the protective immediate `meta` event only fires after context build.
   A slow MLB Stats API night pushes TTFB past the Vercel proxy's kill window
   (~30s, `ROUTER_EXTERNAL_TARGET_ERROR`) → "Load failed" before any AI call.
2. **Mid-stream idle gap.** After `meta`, Opus 4.8 thinks + runs up to 4 web
   searches with zero bytes forwarded until answer text begins — minutes of
   silence. Desktop connections tolerate it; mobile Safari / cell networks /
   screen-lock kill idle streams → phone-only failures.
3. (Not a bug, context:) the analyzer legitimately got heavier — longer contract
   system prompt, dynamic-filtering web search variant — so multi-minute runs on
   complex trades are partly real work.

**Proposed fix (both parts, one PR):**

1. Yield the `meta` event **before** building context — move the stat fetching
   inside the stream generator so first byte is milliseconds regardless of MLB
   API latency. (Same treatment for `/trade/finder` and `/waivers/add-drop` if
   they share the shape — verify.)
2. **Heartbeats:** while the model is thinking/searching, emit a small ndjson
   `ping`/status event every ~10s (iterate raw stream events instead of only
   `text_stream`; on thinking/web-search events emit "searching the web…" /
   "crunching stats…"). Keeps proxies + phones alive and doubles as progress UX.
   Frontend: render the status line; ignore unknown event types gracefully.

**Diagnostics before/after:** `ai_usage` rows for `trade_analyze` carry exact
`duration_ms` + `ok`/`error` per attempt (admin → AI usage) — the failed phone
attempts from 2026-07-16 show whether they died pre-AI (TTFB) or mid-stream.
Verify the fix on a phone, ideally with the screen locked mid-analysis.

---

## 2. Trade history + Admin page stuck on "Loading…" forever (no client timeout)

**Reported:** 2026-07-17 (Adam). Two symptoms, same session: (a) trade History
tab stuck pulsing "Loading your recent analyses…", never resolves; (b) Admin
from the avatar dropdown stuck loading; refresh appends `?league=<id>` and
still doesn't load. (The `?league=` append is `useLeague` syncing the stored
league into the URL — cosmetic, unrelated.)

**Diagnosis — verified live against prod 2026-07-17 (~14:00 UTC):**

- **Server side is healthy.** Probed `www.dynastyos.app` directly: unauthenticated
  `GET /api/trade/history` and `/api/admin/overview` return 401 in <0.6s;
  authenticated (from Adam's own Chrome session) `/trade/history` returns 200 in
  ~1.4s with a valid 4.3KB payload, and both `/admin/overview` + `/admin/usage`
  render fully on desktop. Routing, Vercel proxy, JWKS auth, Supabase queries,
  admin rollups: all fine. Not reproducible on desktop Chrome.
- **The symptom (pulse animates forever, content never arrives) means the
  `authedFetch` promise never settles in the affected session.** The pulse is a
  CSS animation (compositor thread) so it keeps running even when the fetch —
  or all of JS — is wedged. Any server error would have resolved the promise
  and shown the empty/error state instead.
- **Root defect: the app has zero client-side deadlines.** `authedFetch` =
  `await supabase.auth.getSession()` then `fetch()` with no timeout on either,
  and both pages render a loading state with no failure path. So ANY
  environmental hang shows as an eternal pulse. Candidate hangs, most likely
  first:
  1. `supabase.auth.getSession()` never resolving — known supabase-js failure
     mode (navigator-lock contention / token auto-refresh after a suspended
     tab or PWA resume, worst on iOS Safari). Hangs EVERY authed call in that
     session — dashboard masks it via clientCache stale-while-revalidate, so
     only cache-less pages (trade history, admin) LOOK broken. Fits "both
     pages at once + refresh doesn't help" perfectly.
  2. Stale deployed bundle in a long-lived tab/PWA: 5 deploys shipped 07-15 →
     07-17; old clients navigating client-side can fetch dead hashed chunks.
  3. Transient network black hole between the device and Vercel (fetch with no
     timeout waits minutes).

**Proposed fix (one PR — harden `authedFetch`, give every loader a deadline):**

1. In `authedFetch`: race `getSession()` against a ~3s timeout; on timeout fall
   back to reading the token straight from the supabase localStorage key (this
   exact fallback was verified working in prod during diagnosis).
2. Add `AbortSignal.timeout(15_000)` to non-streaming `authedFetch` calls (keep
   streaming endpoints on their existing AbortControllers).
3. TradeHistory + admin page (and any loader without one): on
   timeout/rejection show an error card with a Retry button — never an
   indefinite pulse.
4. Optional diagnostics: log a breadcrumb to `app_events` (kind `client_hang`)
   when the getSession fallback fires, so recurrences are visible in admin.

**Verify:** confirm which device/browser Adam saw this on; reproduce there
(open app → background/suspend it a while → return → tap History / Admin).
With the fix, the worst case is a 15s wait then a Retry card.

---

## 3. Trade history verdict pill shows "`.VERDICT`" garbage (regex matches
prose + research narration leaks into saved analyses)

**Reported:** found 2026-07-17 while diagnosing bug 2, on Adam's real
Casas/Adames analysis (saved 14:00 UTC).

**Diagnosis — two stacking problems, confirmed against the stored row:**

1. The saved analysis begins with **web-search narration**: `"I'll verify the
   current status of both players before giving my verdict.VERDICT\nCOUNTER —
   Selling…"`. `/trade/analyze` streams raw model text — the `===ANSWER===`
   marker convention (`_ANSWER_MARKER_INSTRUCTION`, added for the web-search
   widgets in #68/#69) was never applied to the trade analyzer, so narration
   lands in the stream, the UI, and the saved history row.
2. `extractVerdict` (`trade/page.tsx`) and `AnalysisRenderer`'s section split
   both use `/VERDICT\s*([\s\S]*?)…/i` — case-insensitive and unanchored, so
   the first match is the word "verdict" inside that narration sentence.
   Captured verdict: `".VERDICT"` → amber garbage pill in history; the
   AnalysisRenderer verdict card degrades the same way.

**Proposed fix:**

1. Backend: give `/trade/analyze` (and `/trade/finder` if it narrates) the same
   answer-marker treatment as the widgets — instruct the model to emit
   `===ANSWER===` before VERDICT and strip everything before the marker from
   the streamed deltas server-side. Fixes UI, history, and stored rows going
   forward in one place.
2. Frontend belt-and-braces: anchor the section regexes to a line start
   (`/^\s*VERDICT\b/m` etc.) so prose mentions of "verdict"/"analysis" can
   never shift the split again.

**Verify:** run an analysis on a trade with an injured player (forces web
search → narration); verdict pill should show the real verdict word (ACCEPT /
DECLINE / COUNTER) and the analysis should start at VERDICT. Existing bad rows
will still render better once the regex is anchored.
