-- Daily digest email opt-IN flag (roadmap item 2). Default OFF — the digest
-- emails people, so nobody gets one without asking. Users enable it via the
-- dashboard promo card or the Settings toggle. Safe to re-run, and re-running
-- also corrects any rows created under this migration's earlier default-on
-- draft (nobody has opted in yet at that point, so the blanket reset is safe).

alter table leagues add column if not exists digest_enabled boolean not null default false;
alter table leagues alter column digest_enabled set default false;
update leagues set digest_enabled = false;
