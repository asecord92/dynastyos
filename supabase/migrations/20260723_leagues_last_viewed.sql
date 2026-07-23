-- Track when a league's owner last opened its dashboard, so the standalone
-- widget warmer (/cron/refresh-widgets, every ~3h) only keeps AI widgets fresh
-- for leagues in active use instead of regenerating them round the clock for
-- dormant leagues. The opt-in daily digest warms independently (it's meant to
-- reach owners who aren't currently in the app), so it does NOT read this.
--
-- Backend tolerates this column being absent (best-effort touch + a warmer that
-- falls back to warming all leagues), so it can ship before this is applied.
-- Apply manually in the Supabase SQL editor.

alter table public.leagues
  add column if not exists last_viewed_at timestamptz;

-- The warmer filters leagues by recency each run; index the lookup.
create index if not exists leagues_last_viewed_idx
  on public.leagues (last_viewed_at desc);
