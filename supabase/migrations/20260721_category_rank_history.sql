-- Rank trends over time: one daily snapshot of a league's approximated category
-- ranks, so the dashboard can draw week-over-week sparklines. Written by the
-- category-ranks compute (auto-run on sync + the manual "Auto" button), upserted
-- by (league_id, snapshot_date) so repeated syncs update the day's point rather
-- than spamming it. Backend-only: RLS is enabled with NO client policies, so
-- only the service role reads/writes it (surfaced via /league/category-ranks/history).

create table if not exists category_rank_history (
  id            uuid primary key default gen_random_uuid(),
  league_id     uuid not null references leagues(id) on delete cascade,
  snapshot_date date not null default (now() at time zone 'utc')::date,
  ranks         jsonb not null default '{}'::jsonb,  -- {"R": 4, "HR": 2, ...} (1 = best)
  num_teams     int,                                  -- league size at snapshot time
  created_at    timestamptz not null default now(),
  unique (league_id, snapshot_date)
);

create index if not exists category_rank_history_lookup_idx
  on category_rank_history (league_id, snapshot_date desc);

alter table category_rank_history enable row level security;
