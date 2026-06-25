-- Bring-your-own-key (BYOK): each user stores their own Anthropic API key so
-- friends sharing the app are billed for their own AI usage.
--
-- The key is encrypted at rest by the backend (Fernet, engine/crypto.py); only
-- ciphertext + the last 4 chars (for display) live here. RLS is enabled with NO
-- policies, so the anon/authenticated client keys can read nothing in this table
-- — only the backend service role (which bypasses RLS) ever touches it.

create table if not exists user_secrets (
  user_id                   uuid primary key references auth.users(id) on delete cascade,
  anthropic_key_ciphertext  text,
  anthropic_key_last4       text,
  updated_at                timestamptz not null default now()
);

alter table user_secrets enable row level security;
