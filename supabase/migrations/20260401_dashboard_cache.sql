-- Dashboard cache table for AI-generated widget content
create table if not exists dashboard_cache (
  id uuid primary key default gen_random_uuid(),
  league_id uuid not null references leagues(id) on delete cascade,
  widget text not null check (widget in ('news', 'start_sit', 'waiver')),
  content text not null,
  updated_at timestamptz not null default now(),
  unique (league_id, widget)
);

alter table dashboard_cache enable row level security;

-- Users can only read cache for leagues they own
create policy "Users can read their own league dashboard cache"
  on dashboard_cache for select
  to authenticated
  using (
    league_id in (
      select id from leagues
      where owner_user_id = auth.uid()
    )
  );

-- Only service role can write (backend handles all writes)
create policy "Service role can write dashboard cache"
  on dashboard_cache for all
  to service_role
  using (true)
  with check (true);
