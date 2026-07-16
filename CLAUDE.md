# DynastyOS

Assistant for a Fantrax contract-dynasty fantasy baseball league. **Next.js** frontend (`web/`) + **FastAPI** backend (`api/` + `engine/`), **Supabase** (Postgres + auth), **Anthropic** for AI features.

## Run / build / test
- **Backend:** `uvicorn api.main:app --reload`. Env: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `APP_ENCRYPTION_KEY` (Fernet — encrypts users' BYOK keys); optional `ALLOWED_ORIGINS`, `ADMIN_EMAILS`. **No shared `ANTHROPIC_API_KEY`** — Anthropic keys are per-user (BYOK). Python 3.11; deps pinned in `requirements.txt`. Lint: `ruff check .`.
- **Frontend (`web/`):** `npm run dev`; **`npm run build` is the real gate** (it also type-checks — plain `tsc` trips on Next's generated types). Env: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`. `/api/*` is proxied to the backend via `next.config.ts` rewrite to the **server-only** `API_URL`.
- **CI** (`.github/workflows/ci.yml`): frontend build + advisory lint; backend ruff + import smoke. No unit-test suite yet.

## Deploy
Branch → PR → CI green → **squash-merge to main** → **Vercel** (frontend) + **Railway** (backend) auto-deploy. Don't push directly to `main` (blocked). PR history is the changelog.

## Backend shape (`api/main.py` + `engine/`)
- Singletons: `get_supabase()` (`engine/supabase_client.py`, service-role). **BYOK:** `get_ai_client_for_league()` resolves the league owner's own Anthropic key (encrypted in `user_secrets`), raising 402 `NoApiKeyError` when unset — there is no shared key.
- **Models:** `MODEL_TRADE = "claude-opus-4-8"` (trade — **adaptive thinking ON** via `_ADAPTIVE_THINKING`; Opus runs thinking-off when the param is omitted, so don't drop it), `MODEL_DASHBOARD = "claude-sonnet-5"` (news/start_sit/waiver — thinking explicitly disabled via `_NO_THINKING` since Sonnet 5 defaults it on). Web search tool is `web_search_20260209`; `/trade/analyze` gets a bounded `_TRADE_WEB_SEARCH` (`max_uses: 4`) to verify injuries/roster moves — searches bill the owner's BYOK key. All AI prompts are date-anchored via `_today_line()`.
- **Trade/AI streaming protocol:** `/trade/analyze`, `/trade/finder`, and `/waivers/add-drop` all stream **ndjson events** (`meta` → `text` deltas → `done`/`packages`, errors as `error` events with stable codes). The immediate `meta` event commits the response before Opus finishes thinking, avoiding the Vercel proxy timeout.
- **`dashboard_cache`** table: per-`(league_id, widget)` cache, 4h TTL via `_check_cache`/`_upsert_cache`; widgets: `news`, `start_sit`, `waiver`, `category_ranks`, `minors`. `force: true` bypasses.
- **Widget generation is single-flight + threaded** (`_single_flight` + `asyncio.to_thread`): the Anthropic client is sync, so generation must never run inline in an async endpoint (it froze the whole event loop pre-#58), and concurrent requests for the same `(league, widget)` share one generation instead of double-billing the owner's key. Keep new blocking work (Supabase, Fantrax, Sleeper) off the loop the same way (`_db()` in `trade_analyzer`, `_load_blocking()` in `nfl_trade`).
- MLB stat fetches retry transient failures and **never cache an outage** (`fetch_*` return `None` on failure vs `{}` for a legitimately stat-less player) — don't reintroduce unconditional `save_stats`.
- **`player_id_map`** table: `fantrax_id → mlb_id, full_name, mlb_team, player_type, roster_status, il_type, age`. `roster_status`, `mlb_team` **and** `age` are refreshed every sync (`refresh_roster_statuses`). The `age` column ships in `20260711_player_id_map_age.sql`; all reads/writes tolerate it being absent pre-migration (`_select_id_map` / `_update_id_map`).
- Key endpoints: `/roster/sync` (kicks off a background resolve + status refresh of the whole league), `/dashboard/{news,start_sit,waiver,minors}`, `/trade/{analyze,finder}`, `/league/{standings,category-ranks,category-ranks/compute}`, `/admin/overview` (owner-only via `ADMIN_EMAILS`; usage + error/support view).
- **`app_events`** table: best-effort error log written by a **global exception handler** (`_log_event`, logs 5xx only — expected 4xx like the 402 no-key are skipped), surfaced in the admin dashboard. `user_secrets` and `app_events` have RLS **on with no client policies** — backend service-role only.
- `engine/`: `roster_analyzer` (CSV), `fantrax_client` (Fantrax **fxea** API), `player_resolver`, `mlb_stats_client`, `trade_analyzer`, `category_ranks`; also `sleeper_client`/`sleeper_sync`/`nfl_*` for Sleeper football, `crypto` (BYOK Fernet), `auth` (Supabase JWT).

## Frontend shape (`web/app/`)
- App Router, all client components; `(app)/` is auth-gated (`AuthGate`).
- `AppNav` = desktop top bar **+ mobile bottom tab bar** (`lg:hidden`). `useLeague` (selected league in localStorage + URL). `useDashboardWidget` (shared fetch hook + `authedFetch`) — reuse it for any cached widget. `lib/format.tsx` owns `timeAgo` + `MarkdownContent` — don't re-inline them.
- AI streams (trade analyze/finder, add/drop) carry an `AbortController` aborted on unmount/league switch, with loading cleared via a controller-identity guard; `PullToRefresh` (in the `(app)` layout) reloads on a top-of-page pull.
- Dashboard widgets: `StartSitPanel` (has a **Minors** tab → `MinorsPanel`), `CategoryRanksWidget` (manual entry **+ "Auto" compute**), `InjuryTicker`, `NewsWidget`, `WaiverWidget`.
- Tailwind v4. Mobile: bottom tab bar, `viewport-fit=cover` for safe areas, icons generated via `next/og` (`app/apple-icon.tsx`, `app/icon.tsx`).

## Gotchas (hard-won)
- `player_stats` upserts `on_conflict="mlb_id"` (table keyed by `mlb_id`). MLB Stats API `stats` arrays can be `[]` → use the `_splits()` guard.
- **MLB Stats API takes one `sportId` per call** (comma-joined returns nothing). MiLB sport IDs: 11 AAA, 12 AA, 13 A+, 14 A.
- Heavy stat fetches (trade finder, category compute) must be **bounded/backgrounded** or Vercel times out the proxy (`ROUTER_EXTERNAL_TARGET_ERROR`).
- **Fantrax `getStandings` gives overall standings only — no category ranks.** Category ranks are *approximated* from rosters + season stats (`engine/category_ranks.py`).
- NFL roster items embed `age`/`years_exp`/`injury_status` from the Sleeper players dump at sync time — existing leagues only pick these up on their next sync.
- Settings **reconnect** reuses the existing league row by `fantrax_league_id`; **deleting** a league cascade-wipes its cache/ranks/snapshots/rosters.
- DB migrations live in `supabase/migrations/` and are **applied manually** in the Supabase SQL editor.

## League
"Inglorious Bashers" — `fantrax_league_id = nb5ox442mglfjmdp`, team `h0kjoqh8mglfjmji`. The Supabase league UUID changes if the league is disconnected/reconnected.

**Contract rules** (nailed down with Adam 2026-07-15/16, label scheme + offseason confirmed with commish/leaguemate; encoded in `engine/rules.py` + `_contract_block`):
- Salary flat at draft price years 1–2. Option/extend/cut decided in the **offseason after year 2** — **no early extensions**.
- **Contract clock only runs on the majors roster** — prospects stashed in minors slots don't burn contract years (clock starts on call-up).
- EXTEND: under $15 → **exactly $15** (not salary+4); at/over $15 → +$4. Then +$4/yr forever, max **$75** (stays there). Salary never decreases.
- OPTION: +$1 for one final year, then **auto-dropped** to auction (anyone, incl. former owner, can re-bid — it's a known strategy). CUT: anytime, no dead cap.
- **Contract-year labels (commish-confirmed):** extended players are relabeled straight to "4th yr", so **"3rd yr" = optioned lame duck (expiring rental)**; the decision queue flags 2nd-year players.
- Roster: 24 Act / 6 Res / 12 IR / 12 Minors. **Act+Res+IR salaries count vs the cap in BOTH seasons; Minors never do.**
- **Season cap cycle:** offseason cap is **$335** — rosters must get under it *before* the auction draft (cuts / options expiring / trades). The remainder is the auction budget, and a team needs ≥$1 per *open* roster spot ($1 min bid) — majors **and** minors slots are both filled at the auction from the same budget (minors salaries just don't count vs the cap afterward). **After the draft the cap rises to $450** so teams can absorb salary in trades. Teams projected over $335 must shed salary — a trade-leverage signal the AI prompt calls out.
- Trades: salary + contract year travel unchanged (no retention). Waiver adds: contract year 1 at bid price ($1 min); a player dropped mid-contract keeps his contract **year** but re-enters at the claiming **bid price**.

## Roadmap / not done
- Dark theme **shipped** — a "command center" dark theme (canvas `#0a0c11`, `bg-gray-50` cards, Inter, violet accent). Implemented by inverting Tailwind's gray ramp in `web/app/globals.css` `@theme` (gray-50..300 = dark surfaces, 400..900 = light text; `red/amber/green-50` are dark tints). The original Navy/Lora spec was superseded.
- **Agreed next-features order** (re-ranked by value 2026-07-15): 1) contract/cap planner page, 2) daily digest via the `/cron/refresh-widgets` warmer (needs scheduled trigger + push/email), 3) rank trends over time (auto-compute on sync + `category_rank_history` + sparklines), 4) trade outcome tracking on `trade_history`.
- RLS audited 2026-07-14 (`supabase/RLS_AUDIT.sql`): all 10 tables have RLS on; `leagues`/`rosters`/`snapshots` are owner-scoped for authenticated users; `user_secrets`/`app_events`/`trade_history` are service-role only; `player_id_map`/`player_stats`/`fantrax_players` are intentionally public-read. Base-table schemas are captured in `20260715_base_schema_documentation.sql` (no-op documentation migration).
- Frontend lint stays advisory in CI — 26 pre-existing errors (several `react-hooks` rewrites) to clear before enforcing.
- Deeper usage analytics (per-call token spend / time-series) on top of the admin dashboard's `app_events`.
- No automated tests yet (only build/lint/import-smoke in CI). Highest-value first targets: `player_resolver` name matching and `category_ranks` aggregation (pure logic).
