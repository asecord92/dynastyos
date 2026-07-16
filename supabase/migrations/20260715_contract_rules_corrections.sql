-- Contract-rule corrections nailed down with Adam (2026-07-15). Apply in the
-- Supabase SQL editor. Idempotent — safe to re-run.
--
-- 1. There is no year-2 raise (salary is flat at draft price for years 1-2);
--    drop the fictional year2_raise key.
-- 2. The extension max salary is $75, not $70 (only rows still at the old
--    backfilled 70 are touched, in case another league genuinely uses 70).
-- 3. Add roster slot counts (24 active / 6 reserve / 12 IR / 12 minors) so the
--    AI prompts and cap math know the roster construction. Only added when
--    absent so a hand-edited value survives a re-run.

-- 1. Remove year2_raise wherever a contract object exists.
update leagues
set rules = rules #- '{contract,year2_raise}'
where jsonb_typeof(rules -> 'contract') = 'object'
  and rules -> 'contract' ? 'year2_raise';

-- 2. Correct the old backfilled max salary.
update leagues
set rules = jsonb_set(rules, '{contract,extend_cap}', to_jsonb(75))
where jsonb_typeof(rules -> 'contract') = 'object'
  and (rules -> 'contract' ->> 'extend_cap')::numeric = 70;

-- 3. Add roster slots to MLB leagues that don't have them yet.
update leagues
set rules = rules || jsonb_build_object(
  'slots', jsonb_build_object('active', 24, 'reserve', 6, 'ir', 12, 'minors', 12)
)
where rules is not null
  and not rules ? 'slots'
  and coalesce(sport, 'MLB') = 'MLB';
