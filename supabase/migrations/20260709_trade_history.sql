-- Per-user history of Trade Analyzer runs, powering the trade page's History tab.
-- Backend-only: RLS is enabled with NO client policies, so the anon/authenticated
-- keys can read nothing here — only the backend service role (which bypasses RLS)
-- reads/writes it. Each row is one analyzed trade the user built, with the parsed
-- verdict and the full streamed recommendation. Scoped per (league_id, user_id).

create table if not exists trade_history (
  id          uuid primary key default gen_random_uuid(),
  created_at  timestamptz not null default now(),
  user_id     uuid not null references auth.users(id) on delete cascade,
  league_id   uuid not null references leagues(id) on delete cascade,
  offering    jsonb not null default '[]'::jsonb,  -- players given up: [{id, name}]
  receiving   jsonb not null default '[]'::jsonb,  -- players received:  [{id, name}]
  verdict     text,                                 -- short parsed verdict line
  analysis    text                                  -- full streamed recommendation
);

create index if not exists trade_history_lookup_idx
  on trade_history (league_id, user_id, created_at desc);

alter table trade_history enable row level security;
