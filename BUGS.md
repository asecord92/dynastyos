# Known Bugs & Proposed Fixes

Working list of diagnosed-but-not-yet-fixed bugs. Each entry: symptoms, diagnosis,
proposed fix, and how to verify. Remove entries when the fix ships (the PR is the
record). Roadmap features live in CLAUDE.md — this file is only for defects.

---

## 1. Trade history + Admin page stuck on "Loading…" forever (no client timeout)

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
  environmental hang shows as an eternal pulse.
- **2026-07-17 follow-up (Adam):** it hit Chrome on BOTH phone and desktop in
  the same window (last night → morning PDT), and self-resolved by midday.
  Simultaneous cross-device failure points to a shared upstream, not per-device
  session state. Ruled out by code inspection: backend event-loop starvation
  (MLB stat pipeline is fully async httpx + `to_thread` around sync Supabase;
  the AI stream generators are sync, so Starlette iterates them in a
  threadpool). Best environmental fit found: Vercel incident **"Increased
  invocation failures for Hobby Team functions"** opened 2026-07-17 14:12 UTC
  (7:12am PDT, still "monitoring" at time of writing) — DynastyOS is on Hobby.
  Candidate hangs when it recurs: (1) upstream/platform degradation like the
  above, (2) supabase-js `getSession()` never resolving (navigator-lock /
  token-refresh hang after tab suspend — dashboard masks it via clientCache,
  so only cache-less pages LOOK broken), (3) stale deployed bundle in a
  long-lived tab (5 deploys 07-15 → 07-17). The timeout fix below is the right
  defense against all three — the app must never render an undying pulse.

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
