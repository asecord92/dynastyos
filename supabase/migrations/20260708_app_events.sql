-- Lightweight app-event log powering the admin dashboard's error / support view.
-- Backend-only: RLS is enabled with NO client policies, so the anon/authenticated
-- keys can read nothing here — only the backend service role (which bypasses RLS)
-- ever writes or reads it. Errors are logged best-effort by a global exception
-- handler; a stuck user shows up as a row instead of a text message to the owner.

create table if not exists app_events (
  id          bigint generated always as identity primary key,
  created_at  timestamptz not null default now(),
  user_id     uuid references auth.users(id) on delete set null,
  league_id   uuid,
  kind        text not null,                 -- request path or named event, e.g. '/roster/sync'
  level       text not null default 'error', -- 'error' | 'warn' | 'info'
  status      int,                           -- HTTP status when applicable
  message     text,
  meta        jsonb
);

create index if not exists app_events_created_at_idx on app_events (created_at desc);
create index if not exists app_events_user_id_idx on app_events (user_id);

alter table app_events enable row level security;
