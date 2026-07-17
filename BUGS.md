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
