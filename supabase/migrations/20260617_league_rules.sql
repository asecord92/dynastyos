-- Per-league rules so the trade system prompt is generated from each league's
-- actual rules instead of hardcoded constants. Prerequisite for sharing the app
-- (friends' leagues) and for a second sport. Apply in the Supabase SQL editor.

alter table leagues add column if not exists rules jsonb;

-- Backfill existing MLB league(s) with the previously-hardcoded defaults so the
-- generated prompt is unchanged for the current league.
update leagues
set rules = jsonb_build_object(
  'sport', 'MLB',
  'league_size', 10,
  'in_season_cap', 450,
  'offseason_cap', 335,
  'scoring', jsonb_build_object(
    'hitting', jsonb_build_array('R', 'HR', 'RBI', 'SB', 'OBP'),
    'pitching', jsonb_build_array('QS', 'SV', 'K', 'ERA', 'WHIP')
  ),
  'contract', jsonb_build_object(
    'year2_raise', 1,
    'option_raise', 1,
    'extend_raise', 4,
    'extend_floor', 15,
    'extend_cap', 70
  )
)
where coalesce(sport, 'MLB') = 'MLB' and rules is null;
