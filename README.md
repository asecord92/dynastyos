<div align="center">

# 🏟️ DynastyOS

**An AI-powered command center for contract-dynasty fantasy sports.**

Roster analytics, start/sit calls, waiver spotlights, and trade evaluation — grounded in live
data and powered by Claude — for deep **Fantrax** baseball and **Sleeper** football dynasty leagues.

<br />

![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=next.js&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-strict-3178C6?logo=typescript&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-Python%203.11-009688?logo=fastapi&logoColor=white)
![Supabase](https://img.shields.io/badge/Supabase-Postgres%20%2B%20Auth-3ECF8E?logo=supabase&logoColor=white)
![Anthropic](https://img.shields.io/badge/Claude-Opus%204.8%20%2F%20Sonnet%205-D97757?logo=anthropic&logoColor=white)

</div>

---

## What is it?

DynastyOS turns the tedious parts of running a dynasty team — checking news, weighing start/sit
decisions, scanning the wire, and evaluating trades — into a fast, mobile-first dashboard. It syncs
your real roster from Fantrax or Sleeper, computes analytics from live MLB/NFL stats, and layers
**Claude** on top for the judgment calls that a spreadsheet can't make.

It was built for a single contract-dynasty baseball league and grew into a tool a whole group can
share — each friend brings their own Claude API key, so nobody foots the bill for anyone else.

## Features

### 📊 Dashboard
- **Player News** — Claude searches the web and summarizes the last two weeks for your roster (IL moves, role changes, injuries).
- **Start / Sit** — start/monitor/sit calls for your active roster, with an injury-aware breakdown.
- **Waiver Spotlight** — free-agent targets ranked against your team's weakest categories.
- **Category Ranks** — where you stand in each scoring category (manual entry **or** auto-computed from rosters + season stats).
- **Injury Ticker** — a rolling feed of IL statuses and expected returns across your roster.
- **Minors** — prospect watch for the players stashed in your farm system.

### 🔁 Trade tools
- **Trade Analyzer** — paste a proposed trade and get a verdict grounded in your league's rules, cap, and team philosophy.
- **Trade Finder** — surfaces realistic trade targets across the league that address your needs.

### 🔗 Roster sync
- **Fantrax** (baseball) via the Fantrax external API, and **Sleeper** (football) — one-click connect and background resolve.
- Players are resolved to MLB/MLB-affiliate IDs and enriched with live stats, roster status, and IL type.

### 🔑 Bring-your-own-key (BYOK)
- Every user supplies their **own Anthropic API key**, stored **encrypted at rest** (Fernet). There is no shared fallback — AI features simply stay off until a key is added, and each person is billed only for their own usage.
- Non-AI features (roster, standings, category ranks, minors) work with no key at all.

### 🛠️ Admin dashboard
- An owner-only page that doubles as **usage metrics** and **troubleshooting**: users, leagues, who has a key set, and last-active / last-sync / last-AI activity per person — so a stuck friend is one glance away from being diagnosed.

## Architecture

```
                    ┌──────────────────────────┐
   Browser ───────► │  Next.js (Vercel)        │   App Router, all client components,
                    │  web/                    │   Tailwind v4, mobile bottom-tab nav
                    └───────────┬──────────────┘
                                │  /api/*  (server-only proxy rewrite → API_URL)
                                ▼
                    ┌──────────────────────────┐
                    │  FastAPI (Railway)       │   api/main.py + engine/
                    │  api/ + engine/          │   roster sync, stats, trade + rank logic
                    └─────┬───────────────┬────┘
                          │               │
                          ▼               ▼
              ┌───────────────────┐   ┌──────────────────┐
              │ Supabase          │   │ Anthropic (Claude)│
              │ Postgres + Auth   │   │ per-user BYOK key │
              └───────────────────┘   └──────────────────┘
                          │
                          ▼
          External data: Fantrax API · Sleeper API · MLB Stats API
```

**Highlights**
- **AI model split** — `claude-opus-4-8` for deep trade reasoning; `claude-sonnet-5` for the high-frequency dashboard widgets (news / start-sit / waiver). All prompts are date-anchored so answers stay current.
- **Caching** — a per-`(league, widget)` `dashboard_cache` table with a 4-hour TTL keeps the expensive AI calls cheap and fast; a `force` flag bypasses it.
- **Category ranks are approximated** — Fantrax's API only exposes overall standings, so per-category ranks are reconstructed from rosters + season stats.
- **Heavy stat work is bounded/backgrounded** so the serverless proxy never times out.

## Tech stack

| Layer      | Tech |
|------------|------|
| Frontend   | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS v4 |
| Backend    | FastAPI, Python 3.11, Pydantic, `ruff` |
| Data / Auth| Supabase (Postgres + Auth), Row-Level Security |
| AI         | Anthropic Claude (Opus 4.8 + Sonnet 5), server-side web search |
| Hosting    | Vercel (frontend) · Railway (backend) |
| Sources    | Fantrax API · Sleeper API · MLB Stats API |

## Getting started (local development)

> Requires **Node 20+**, **Python 3.11**, and a **Supabase** project.

### 1. Backend (FastAPI)

```bash
pip install -r requirements.txt
uvicorn api.main:app --reload      # serves on http://localhost:8000
```

Environment variables (`.env` or your shell):

| Variable | Required | Purpose |
|----------|:--------:|---------|
| `SUPABASE_URL` | ✅ | Your Supabase project URL |
| `SUPABASE_SERVICE_KEY` | ✅ | Service-role key (server-side only) |
| `APP_ENCRYPTION_KEY` | ✅ | Fernet key used to encrypt users' Anthropic keys at rest |
| `ALLOWED_ORIGINS` | — | Comma-separated CORS origins |
| `ADMIN_EMAILS` | — | Comma-separated allowlist for the admin dashboard |

Generate an encryption key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 2. Frontend (Next.js)

```bash
cd web
npm install
npm run dev                        # serves on http://localhost:3000
npm run build                      # the real gate — also type-checks
```

Environment variables (`web/.env.local`):

| Variable | Required | Purpose |
|----------|:--------:|---------|
| `NEXT_PUBLIC_SUPABASE_URL` | ✅ | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | ✅ | Supabase anon/public key |
| `API_URL` | ✅ | Server-only URL the `/api/*` rewrite proxies to (e.g. the FastAPI host) |
| `NEXT_PUBLIC_ADMIN_EMAILS` | — | Cosmetic gate for showing the Admin nav link |

### 3. Database

SQL lives in [`supabase/migrations/`](supabase/migrations) and is applied manually in the Supabase
SQL editor (newest first). Run them in order against a fresh project.

### 4. Add your Claude key

Once running, sign in, connect a league in **Settings**, and add your own Anthropic API key
(`sk-ant-…`) — that turns on all of the AI tools.

## Project structure

```
dynastyops/
├─ api/                    # FastAPI app entrypoint (api/main.py)
├─ engine/                 # domain logic
│  ├─ roster_analyzer.py   #   CSV / roster parsing
│  ├─ fantrax_client.py    #   Fantrax external API
│  ├─ player_resolver.py   #   fantrax_id → MLB id resolution
│  ├─ mlb_stats_client.py  #   MLB Stats API
│  ├─ trade_analyzer.py    #   trade evaluation
│  ├─ category_ranks.py    #   category-rank approximation
│  ├─ crypto.py            #   Fernet encryption for BYOK keys
│  └─ auth.py              #   Supabase JWT verification
├─ supabase/migrations/    # SQL migrations (applied manually)
├─ web/                    # Next.js frontend
│  └─ app/
│     ├─ (app)/            #   auth-gated: dashboard, roster, waivers, trade, settings, admin
│     ├─ (auth)/           #   login, check-email
│     ├─ components/       #   widgets + UI
│     └─ lib/              #   hooks (useLeague, useDashboardWidget), Supabase client
├─ requirements.txt
└─ .github/workflows/ci.yml
```

## Development workflow

Work happens on a branch → PR → **CI** (frontend build + lint, backend `ruff` + import smoke) →
squash-merge to `main` → **Vercel** and **Railway** auto-deploy. The PR history is the changelog.

## Roadmap

- Automatic category-rank computation on every sync (currently an on-demand "Auto" button).
- Deeper usage analytics (per-call token spend / time-series) on top of the admin dashboard.
- Broader test coverage (CI currently runs build, lint, and an import smoke).

---

<div align="center">
<sub>A personal project — built for dynasty degenerates. 🐐</sub>
</div>
