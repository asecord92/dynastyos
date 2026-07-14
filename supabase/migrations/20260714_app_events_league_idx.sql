-- Admin overview filters app_events by league; without this the query scans
-- the whole table as events accumulate.
create index if not exists app_events_league_created_idx
  on public.app_events (league_id, created_at desc);
