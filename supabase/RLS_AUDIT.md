# RLS + schema audit — one paste, one run

Open the Supabase **SQL Editor**, paste the **entire block below**, and hit Run.
It first applies the pending `app_events` index (idempotent — safe to re-run),
then returns a single result table with everything the audit needs. Export or
copy the full result and paste it back into a Claude Code session — it will
write the follow-up migration (owner-scoped policies if any are missing, plus
a documentation migration capturing the base-table schemas).

Background: an anon-key probe (2026-07-14) already confirmed anonymous requests
get **zero rows** from every user-data table; only the shared reference tables
(`player_id_map`, `player_stats`, `fantrax_players`) are readable, which the
frontend depends on. What's left to verify is whether *logged-in* users are
owner-scoped on `leagues`/`rosters`, and to capture the hand-created base-table
schemas somewhere recoverable.

```sql
-- Pending migration (idempotent): admin-view index on app_events.
create index if not exists app_events_league_created_idx
  on public.app_events (league_id, created_at desc);

-- Full audit in one result set. Sections:
--   1_rls     — RLS on/off per table
--   2_policy  — every policy (who can do what, with its USING / CHECK)
--   3_column  — base-table columns in order (for the documentation migration)
--   4_index   — every index on public tables
select '1_rls' as section,
       relname as item,
       case when relrowsecurity then 'RLS ENABLED' else 'RLS DISABLED' end as detail
from pg_class
where relnamespace = 'public'::regnamespace and relkind = 'r'

union all

select '2_policy',
       tablename || ' / ' || policyname,
       'roles=' || array_to_string(roles, ',')
         || ' | cmd=' || cmd
         || ' | using=' || coalesce(qual, '—')
         || ' | check=' || coalesce(with_check, '—')
from pg_policies
where schemaname = 'public'

union all

select '3_column',
       table_name || '.' || lpad(ordinal_position::text, 2, '0') || ' ' || column_name,
       data_type
         || case when is_nullable = 'YES' then '' else ' not null' end
         || coalesce(' default ' || column_default, '')
from information_schema.columns
where table_schema = 'public'
  and table_name in ('leagues','rosters','player_id_map','player_stats',
                     'fantrax_players','snapshots')

union all

select '4_index',
       tablename || ' / ' || indexname,
       indexdef
from pg_indexes
where schemaname = 'public'

order by section, item;
```
