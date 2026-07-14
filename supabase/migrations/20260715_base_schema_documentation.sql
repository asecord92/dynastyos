-- Documentation migration: the hand-created base tables, captured verbatim
-- from the live database (RLS_AUDIT.sql output, 2026-07-14). These tables
-- predate the migrations folder; this file exists so the schema is recoverable
-- without the live DB. Everything is IF NOT EXISTS, so running it against the
-- live project is a harmless no-op — there is nothing to apply.
--
-- Not captured here: foreign-key constraints (the audit didn't query them).
-- Known behavior: deleting a league cascade-wipes its cache/ranks/snapshots/
-- rosters, so rosters.league_id / snapshots.league_id reference leagues(id)
-- on delete cascade.

-- Fantrax league connections + per-league profile/rules. Owner-scoped RLS
-- (select/insert/update/delete where auth.uid() = owner_user_id) is live.
create table if not exists public.leagues (
  id uuid primary key default uuid_generate_v4(),
  owner_user_id uuid not null,
  name text not null,
  platform text not null default 'fantrax',
  fantrax_league_id text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  mode text not null default 'in_season',
  fantrax_secret_id text,
  sport text not null default 'MLB',
  fantrax_team_id text,
  draft_budget integer,
  season_year integer,
  season_start date,
  season_end date,
  roster_max integer,
  roster_active integer,
  roster_reserve integer,
  competitive_window text,
  cap_philosophy text,
  team_weaknesses text[],
  goals text,
  rules jsonb,
  sleeper_username text,
  sleeper_user_id text,
  sleeper_league_id text
);
create index if not exists idx_leagues_owner on public.leagues (owner_user_id);

-- One row per team per league (every team, not just the user's). League-owner-
-- scoped RLS via a leagues subquery is live on all four commands.
create table if not exists public.rosters (
  id uuid primary key default gen_random_uuid(),
  league_id uuid,
  fantrax_team_id text not null,
  team_name text not null,
  roster_items jsonb not null,
  salary_cap integer,
  synced_at timestamptz default now(),
  draft_picks jsonb,
  unique (league_id, fantrax_team_id)
);

-- fantrax_id -> MLB Stats API identity + daily-refreshed roster status.
-- Public-read RLS (shared reference data; the frontend reads it client-side).
create table if not exists public.player_id_map (
  fantrax_id text primary key,
  mlb_id integer not null,
  full_name text not null,
  mlb_team text,
  confidence text not null,
  resolved_at timestamptz default now(),
  player_type text,
  roster_status text,
  il_type text,
  age integer
);

-- 24h-cached MLB season/recent stats, keyed by mlb_id only (one row per
-- player — upserts use on_conflict="mlb_id"). Public-read RLS.
create table if not exists public.player_stats (
  mlb_id integer primary key,
  season integer not null,
  player_type text not null,
  season_stats jsonb,
  recent_stats jsonb,
  refreshed_at timestamptz default now()
);

-- 24h-cached Fantrax player-id dump (id -> name), per sport. Public-read RLS.
create table if not exists public.fantrax_players (
  fantrax_id text primary key,
  name text not null,
  sport text not null,
  updated_at timestamptz default now()
);

-- One roster snapshot per (league, source) — upserted, not appended.
-- Owner-scoped RLS (auth.uid() = owner_user_id) is live.
create table if not exists public.snapshots (
  id uuid primary key default uuid_generate_v4(),
  league_id uuid not null,
  owner_user_id uuid not null,
  created_at timestamptz not null default now(),
  source text not null default 'csv',
  data jsonb not null,
  unique (league_id, source)
);
create index if not exists idx_snapshots_league_created
  on public.snapshots (league_id, created_at desc);
