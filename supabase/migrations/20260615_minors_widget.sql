-- Add minors to allowed widget types in dashboard_cache (Minor League Tracker)
alter table dashboard_cache
  drop constraint if exists dashboard_cache_widget_check;

alter table dashboard_cache
  add constraint dashboard_cache_widget_check
  check (widget in ('news', 'start_sit', 'waiver', 'category_ranks', 'minors'));
