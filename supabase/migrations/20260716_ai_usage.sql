-- AI usage metering (roadmap item: usage/cost tracking). One row per Anthropic
-- API call, written best-effort by the backend — token counts and web-search
-- counts come straight from the API response; dollar costs are computed at
-- display time from a pricing map so history stays truthful if prices change.
-- No prompt content is stored. Apply in the Supabase SQL editor.

create table if not exists public.ai_usage (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  league_id uuid,
  user_id uuid,              -- the league owner whose BYOK key was billed
  tool text not null,        -- trade_analyze | trade_finder | add_drop | news | start_sit | waiver
  model text,
  input_tokens integer not null default 0,
  output_tokens integer not null default 0,
  cache_read_tokens integer not null default 0,
  cache_creation_tokens integer not null default 0,
  web_searches integer not null default 0,
  duration_ms integer,
  ok boolean not null default true,
  error text
);

-- Service-role only, like app_events: RLS on with no client policies.
alter table public.ai_usage enable row level security;

create index if not exists ai_usage_created_idx
  on public.ai_usage (created_at desc);
create index if not exists ai_usage_league_created_idx
  on public.ai_usage (league_id, created_at desc);
