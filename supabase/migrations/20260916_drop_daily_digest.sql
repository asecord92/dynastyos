-- Remove the daily digest email (shipped 2026-07-16, retired 2026-09-16).
--
-- The feature is gone from the backend, the frontend and the GitHub Actions
-- schedule; this drops what it left in the database. The email's content was
-- stitched from widget caches that lag reality (players shown on old teams)
-- and it had no notion of which sport is actually in season, so it shipped
-- football calls in July and baseball calls in December. Not worth fixing.
--
-- Safe to re-run. Nothing reads either object any more, so applying this late
-- (or never) breaks nothing — it's cleanup, not a gate on the deploy.

-- The per-league opt-in flag. Only DigestToggle/DigestPromo wrote it.
alter table leagues drop column if exists digest_enabled;

-- Yesterday's stitched digest, kept per league so the next morning's email
-- could drop sections that hadn't changed. Dead rows in the widget cache.
delete from dashboard_cache where widget = 'digest_prev';
