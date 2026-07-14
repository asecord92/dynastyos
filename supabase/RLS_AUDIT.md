# RLS + schema audit (run in the Supabase SQL editor)

The base tables (`leagues`, `rosters`, `player_id_map`, `player_stats`,
`fantrax_players`, `snapshots`) were created by hand and are not captured in
`supabase/migrations/`. An anon-key probe (2026-07-14) confirmed anonymous
requests get **zero rows** from every user-data table; only the shared
reference tables (`player_id_map`, `player_stats`, `fantrax_players`) are
readable, which the frontend depends on. Two things remain to verify with the
queries below — paste the output back into a Claude Code session and it will
write the follow-up migration:

1. **Cross-user reads**: whether a *logged-in* user's policies on `leagues` /
   `rosters` are scoped to the owner (`owner_user_id = auth.uid()` and a
   league-ownership join) or just `authenticated`.
2. **Base-table schema capture**: a documentation migration so the schema is
   recoverable without the live DB.

```sql
-- 1) RLS on/off per table
select relname as table, relrowsecurity as rls_enabled
from pg_class
where relnamespace = 'public'::regnamespace and relkind = 'r'
order by relname;

-- 2) All policies (who can do what)
select tablename, policyname, roles, cmd, qual, with_check
from pg_policies
where schemaname = 'public'
order by tablename, policyname;

-- 3) Base-table schemas (for the documentation migration)
select table_name, column_name, data_type, is_nullable, column_default
from information_schema.columns
where table_schema = 'public'
  and table_name in ('leagues','rosters','player_id_map','player_stats',
                     'fantrax_players','snapshots')
order by table_name, ordinal_position;

-- 4) Indexes on the base tables
select tablename, indexname, indexdef
from pg_indexes
where schemaname = 'public'
order by tablename, indexname;
```

Also apply the new migration in this folder:
`20260714_app_events_league_idx.sql`.
