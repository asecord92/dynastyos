-- Invite-only signups.
--
-- Two layers, because they cover different people:
--   * the Before User Created auth hook below rejects a *new* signup outright,
--     so a stranger never gets an account at all;
--   * the backend's get_current_user check (engine/auth.py) reads this same
--     table and 403s anyone who *already* has an account. The hook can't help
--     there — it only fires at creation time.
-- One table feeds both, so there's a single list to maintain.
--
-- Replaces the ALLOWED_EMAILS env var from #132: same behaviour, but editable
-- from the admin page instead of Railway, and no service restart to add a friend.

create table if not exists allowed_emails (
  email      text primary key,
  note       text,                                                  -- "league mate", "brother", ...
  added_by   uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);

-- Service-role only, same as user_secrets / app_events: RLS on, no client
-- policies. The list is administered through the backend's /admin endpoints
-- (owner-gated by ADMIN_EMAILS), never straight from the browser.
alter table allowed_emails enable row level security;

-- Emails are compared case-insensitively everywhere; store them folded so the
-- primary key does the de-duplication for us.
create or replace function allowed_emails_normalize()
returns trigger
language plpgsql
as $$
begin
  new.email := lower(trim(new.email));
  return new;
end;
$$;

drop trigger if exists allowed_emails_normalize_trg on allowed_emails;
create trigger allowed_emails_normalize_trg
  before insert or update on allowed_emails
  for each row execute function allowed_emails_normalize();


-- ── Before User Created hook ─────────────────────────────────────────────────
-- Wire it up in Dashboard → Authentication → Hooks → "Before User Created",
-- choosing this Postgres function. Returning `{}` allows the signup; returning
-- an `error` object rejects it and the message is shown to the person signing up.
--
-- An EMPTY TABLE DELIBERATELY ALLOWS EVERYONE. If this ran before the list was
-- populated, or if the table were emptied by accident, a fail-closed hook would
-- lock out every future signup including the operator's own re-registration,
-- with no way in. Allow-all is the safer failure here precisely because the
-- backend gate is the layer that actually protects data.
create or replace function public.hook_restrict_signup(event jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  candidate text := lower(trim(event -> 'user' ->> 'email'));
  listed    boolean;
  any_rows  boolean;
begin
  select exists (select 1 from allowed_emails) into any_rows;
  if not any_rows then
    return '{}'::jsonb;  -- list not configured yet — don't lock the door on an empty room
  end if;

  select exists (
    select 1 from allowed_emails where email = candidate
  ) into listed;

  if listed then
    return '{}'::jsonb;
  end if;

  -- Surface the attempt on the admin page. Best-effort: a logging failure must
  -- never turn into an allowed signup, so it's wrapped rather than left to
  -- abort the transaction.
  begin
    insert into app_events (kind, level, status, message, meta)
    values (
      'signup_blocked', 'info', 403,
      coalesce(candidate, '(no email)'),
      jsonb_build_object('ip', event -> 'metadata' ->> 'ip_address')
    );
  exception when others then
    null;
  end;

  return jsonb_build_object(
    'error', jsonb_build_object(
      'http_code', 403,
      'message', 'DynastyOS is invite-only. Ask Adam to add your email address.'
    )
  );
end;
$$;

-- The hook is invoked by GoTrue as `supabase_auth_admin`, which by default can
-- see nothing in `public`. Grant exactly what the function body touches.
grant usage on schema public to supabase_auth_admin;
grant execute on function public.hook_restrict_signup(jsonb) to supabase_auth_admin;
grant select on table public.allowed_emails to supabase_auth_admin;
grant insert on table public.app_events to supabase_auth_admin;
-- No sequence grant needed: app_events.id is GENERATED ALWAYS AS IDENTITY, and
-- Postgres does the permission check on the owning column rather than on the
-- underlying sequence (unlike a `serial`). The select/insert grants above are
-- likewise belt-and-braces — the function is SECURITY DEFINER, so its body runs
-- as the owner, which also bypasses the RLS on allowed_emails.

-- Nobody else should be able to call it (it's security definer).
revoke execute on function public.hook_restrict_signup(jsonb) from authenticated, anon, public;
