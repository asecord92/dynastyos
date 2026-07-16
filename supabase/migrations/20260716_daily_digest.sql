-- Daily digest email opt-out flag (roadmap item 2). Default ON: the digest is
-- the point of the feature, and Settings grows a toggle to turn it off.
-- Apply in the Supabase SQL editor.

alter table leagues add column if not exists digest_enabled boolean not null default true;
