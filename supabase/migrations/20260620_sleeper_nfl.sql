-- Football via Sleeper: connect an NFL (Sleeper) league alongside Fantrax/MLB.
-- NFL player metadata + season points are fetched from Sleeper's public API and
-- cached in-process (no new player tables); player names/positions are embedded
-- into rosters.roster_items at sync time. The MLB tables are left untouched.
-- Apply in the Supabase SQL editor.

-- Sleeper connection identifiers on the shared leagues table.
alter table leagues add column if not exists sleeper_username text;
alter table leagues add column if not exists sleeper_user_id text;
alter table leagues add column if not exists sleeper_league_id text;

-- Per-roster future rookie-pick inventory (NFL only; null for Fantrax rosters).
-- Shape: [{ "season": 2027, "round": 1, "label": "2027 1st", "original_roster_id": 3 }, ...]
alter table rosters add column if not exists draft_picks jsonb;
