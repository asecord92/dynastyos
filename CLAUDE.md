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
- **Models:** `MODEL_TRADE = "claude-opus-4-8"` (trade), `MODEL_DASHBOARD = "claude-sonnet-5"` (news/start_sit/waiver — thinking explicitly disabled via `_NO_THINKING` since Sonnet 5 defaults it on). All AI prompts are date-anchored via `_today_line()`.
- **`dashboard_cache`** table: per-`(league_id, widget)` cache, 4h TTL via `_check_cache`/`_upsert_cache`; widgets: `news`, `start_sit`, `waiver`, `category_ranks`, `minors`. `force: true` bypasses.
- **`player_id_map`** table: `fantrax_id → mlb_id, full_name, mlb_team, player_type, roster_status, il_type`. `roster_status` **and** `mlb_team` are refreshed every sync (`refresh_roster_statuses`).
- Key endpoints: `/roster/sync` (kicks off a background resolve + status refresh of the whole league), `/dashboard/{news,start_sit,waiver,minors}`, `/trade/{analyze,finder}`, `/league/{standings,category-ranks,category-ranks/compute}`, `/admin/overview` (owner-only via `ADMIN_EMAILS`; usage + error/support view).
- **`app_events`** table: best-effort error log written by a **global exception handler** (`_log_event`, logs 5xx only — expected 4xx like the 402 no-key are skipped), surfaced in the admin dashboard. `user_secrets` and `app_events` have RLS **on with no client policies** — backend service-role only.
- `engine/`: `roster_analyzer` (CSV), `fantrax_client` (Fantrax **fxea** API), `player_resolver`, `mlb_stats_client`, `trade_analyzer`, `category_ranks`; also `sleeper_client`/`sleeper_sync`/`nfl_*` for Sleeper football, `crypto` (BYOK Fernet), `auth` (Supabase JWT).

## Frontend shape (`web/app/`)
- App Router, all client components; `(app)/` is auth-gated (`AuthGate`).
- `AppNav` = desktop top bar **+ mobile bottom tab bar** (`lg:hidden`). `useLeague` (selected league in localStorage + URL). `useDashboardWidget` (shared fetch hook + `authedFetch`) — reuse it for any cached widget.
- Dashboard widgets: `StartSitPanel` (has a **Minors** tab → `MinorsPanel`), `CategoryRanksWidget` (manual entry **+ "Auto" compute**), `InjuryTicker`, `NewsWidget`, `WaiverWidget`.
- Tailwind v4. Mobile: bottom tab bar, `viewport-fit=cover` for safe areas, icons generated via `next/og` (`app/apple-icon.tsx`, `app/icon.tsx`).

## Gotchas (hard-won)
- `player_stats` upserts `on_conflict="mlb_id"` (table keyed by `mlb_id`). MLB Stats API `stats` arrays can be `[]` → use the `_splits()` guard.
- **MLB Stats API takes one `sportId` per call** (comma-joined returns nothing). MiLB sport IDs: 11 AAA, 12 AA, 13 A+, 14 A.
- Heavy stat fetches (trade finder, category compute) must be **bounded/backgrounded** or Vercel times out the proxy (`ROUTER_EXTERNAL_TARGET_ERROR`).
- **Fantrax `getStandings` gives overall standings only — no category ranks.** Category ranks are *approximated* from rosters + season stats (`engine/category_ranks.py`).
- Settings **reconnect** reuses the existing league row by `fantrax_league_id`; **deleting** a league cascade-wipes its cache/ranks/snapshots/rosters.
- DB migrations live in `supabase/migrations/` and are **applied manually** in the Supabase SQL editor.

## League
"Inglorious Bashers" — `fantrax_league_id = nb5ox442mglfjmdp`, team `h0kjoqh8mglfjmji`. The Supabase league UUID changes if the league is disconnected/reconnected.

## Roadmap / not done
- Dark theme **shipped** — a "command center" dark theme (canvas `#0a0c11`, `bg-gray-50` cards, Inter, violet accent). Implemented by inverting Tailwind's gray ramp in `web/app/globals.css` `@theme` (gray-50..300 = dark surfaces, 400..900 = light text; `red/amber/green-50` are dark tints). The original Navy/Lora spec was superseded.
- Optional: auto-compute category ranks on every sync (currently an on-demand "Auto" button).
- Deeper usage analytics (per-call token spend / time-series) on top of the admin dashboard's `app_events`.
- No automated tests yet (only build/lint/import-smoke in CI).
