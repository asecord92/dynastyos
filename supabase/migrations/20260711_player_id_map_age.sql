-- Player age for dynasty valuation in trade prompts. Populated from the MLB
-- Stats API (people.currentAge) during the roster-status refresh on every sync.
-- Apply manually in the Supabase SQL editor. The backend tolerates this column
-- being absent, so deploy order doesn't matter.
alter table player_id_map add column if not exists age int;
