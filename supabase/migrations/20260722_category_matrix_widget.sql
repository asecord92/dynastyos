-- Add category_matrix to allowed widget types in dashboard_cache.
-- category_matrix stores the full league category matrix (per-team ranks + role
-- counts) computed alongside category_ranks; the trade builder/finder read it to
-- ground each rival's posture (need vs. deliberate punt).
alter table dashboard_cache
  drop constraint if exists dashboard_cache_widget_check;

alter table dashboard_cache
  add constraint dashboard_cache_widget_check
  check (widget in ('news', 'start_sit', 'waiver', 'category_ranks', 'category_matrix', 'minors'));
