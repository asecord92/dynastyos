# Security audit — 2026-09-01

Full-app review (backend `api/` + `engine/`, frontend `web/`, Supabase config, CI/deploy).
Remove entries as fixes ship.

**Status:** #1, #3, #4, #9, #12, #15 shipped in #132; #5's access-control half in
#132 + #133 (invite list + signup hook). Still open: the rate-limiting half of #5, #6, #7, #8, #10, #11, #13, #14.

## What's already right

Worth stating, because it narrows the blast radius of everything below:

- Every endpoint carries `Depends(get_current_user)`; the JWT is verified against Supabase's
  JWKS pinned to `algorithms=["ES256"]` (no alg confusion, no `verify_signature: False`),
  with hourly key refresh and stale-key fallback.
- The backend uses the service key, so RLS is bypassed — and it knows it:
  `require_league_owner` is called on all 21 league-scoped endpoints. No IDOR found.
- `trade_history` reads/writes are scoped `.eq("user_id", uid)` on top of the league check.
- Anthropic keys are Fernet-encrypted at rest, `user_secrets` has RLS on with no policies,
  and `GET /settings/api-key` returns only last-4.
- No `dangerouslySetInnerHTML` anywhere; the digest email escapes model output before
  applying its mini-markdown. No secrets in the repo or in 324 commits of history.
- `safeRedirectPath` already blocks the open-redirect on `?redirectedFrom`.
- CSV upload is chunk-capped at 2 MB and the temp file is removed in `finally`.

## HIGH

### 1. Next.js 16.1.6 — HTTP request smuggling in rewrites

> **SHIPPED (#132).** `next@16.3.4` + `npm audit fix`: 0 vulnerabilities, dev included.

`npm audit` reports 14 advisories against `next@16.1.6`, including
[GHSA-ggv3-7p47-pfv8](https://github.com/advisories/GHSA-ggv3-7p47-pfv8) (request
smuggling in rewrites), middleware/proxy bypass, cache poisoning, and CSP-nonce XSS.

This one is not theoretical for us: **100% of authenticated API traffic goes through a
rewrite** (`web/next.config.ts` → `/api/:path*` → `API_URL`). Smuggling against that path
is smuggling against the whole backend.

Also flagged transitively: `nanoid`, `postcss`, `sharp` (libvips CVEs), `ws` — all resolve
with the same upgrade.

**Fix:** `next@16.3.4` + `eslint-config-next@16.3.4`, then `npm run build` as the gate.

### 2. The Fantrax Secret ID is a plaintext credential that round-trips through the browser

> **SHIPPED (#135).** All three steps: `/fantrax/leagues` is POST so the ID leaves
> the URL, the sync endpoints read it off the league row instead of the browser,
> and it's Fernet-encrypted at rest via a new `POST /fantrax/secret` (the client
> has no key, so the write had to move server-side). Encryption rolls forward
> without a backfill — `crypto.decrypt_tolerant` returns legacy plaintext as-is,
> and each successful sync re-writes the row as ciphertext *after* Fantrax has
> confirmed the secret authenticates, so a bad secret can't overwrite a good one.
> **Does not scrub history:** IDs already written to Vercel/Railway logs stay
> there. Regenerating the Secret IDs in Fantrax is the only thing that retires
> those, and that's a user action.

`leagues.fantrax_secret_id` is a long-lived credential granting API access to that user's
Fantrax account. Today it is:

- **stored unencrypted** in `leagues` — unlike the Anthropic key, which gets Fernet;
- **selected client-side** by the browser (`AppNav.tsx:156`, `AutoSync.tsx:30`,
  `settings/page.tsx`), so it lives in page memory and any client-side error path;
- **sent back as a URL query parameter** — `GET /api/fantrax/leagues?user_secret_id=…`
  (`web/app/(app)/settings/page.tsx:277`, `api/main.py:2503`).

Query strings are recorded in Vercel edge logs, Railway request logs, and browser history.
That is a credential sitting in three log stores in cleartext, indefinitely.

RLS keeps other users out of the row, so this is not a live cross-tenant leak — it's a
credential-handling design that diverges from the (correct) pattern already used for BYOK.

**Fix, in order of value:**
1. `POST /fantrax/leagues` with the id in the body — stops the log bleed, ~10 lines.
2. Encrypt at rest with `engine/crypto.py`, same as the Anthropic key.
3. Stop shipping it to the client: have the backend read it from the league row by
   `league_id` (it already resolves ownership) so `/roster/sync` needs no secret in the body.

## MEDIUM

### 3. CORS defaults to `*` with `allow_credentials=True`

> **SHIPPED (#132).** Defaults to the prod + localhost list and logs a warning on fallback.
> Safe by construction: the browser never calls the backend cross-origin — it calls
> same-origin `/api/*`, which the Next rewrite proxies server-side (no Origin header).

`api/main.py:76` — `os.getenv("ALLOWED_ORIGINS", "*")`. Confirmed against the installed
Starlette: `preflight_explicit_allow_origin = not allow_all_origins or allow_credentials`,
so with `*` + credentials it **echoes the requesting Origin back** and sets
`Access-Control-Allow-Credentials: true`. Any origin gets a credentialed read.

Impact is bounded because auth is a Bearer header, not a cookie — an attacker page has no
ambient credential to ride. But it is a defense-in-depth layer set to off, and the failure
mode is silent: if `ALLOWED_ORIGINS` is ever unset on Railway, nothing breaks and nothing
warns.

**Fix:** default to the known-good list rather than `*`, and log a warning on fallback.

### 4. `require_league_owner` fails open on three paths

> **SHIPPED (#132).** Fails closed on all three; `.single()` dropped so a missing league
> (404) is distinguishable from an infrastructure failure (503).

```python
try:
    row = sb.table("leagues").select("owner_user_id").eq("id", league_id).single().execute()
except Exception:
    return              # (a) lookup failed -> ALLOW
...
if owner and sub and owner != sub:   # (b) owner null -> ALLOW  (c) sub missing -> ALLOW
    raise HTTPException(403, ...)
```

Path (a) is the live one. `engine/supabase_client.py` documents that Supabase sends GOAWAY
under concurrent load and poisons the pooled connection — i.e. transient query failure is a
*known, observed* condition here, and during it the ownership gate is open while a
`dashboard_cache` read on a different path may still succeed.

(b) and (c) are defensive-only today (`leagues.owner_user_id` is `not null`, and an ES256
Supabase user token always carries `sub`), but they encode "unknown identity → allow".

**Fix:** deny on all three. `sub` missing → 401; lookup error → 503; owner null → 403.
The comment's "never lock out on legacy rows" concern is moot — the column is `not null`.

### 5. No rate limiting, and signup is open to the world

> **ACCESS CONTROL SHIPPED (#132, #133). Rate limiting still open.**
> #132 added the backend gate; #133 moved the list into the `allowed_emails` table
> (managed at `/admin`, no redeploy to add a friend) and added the **Before User
> Created** Postgres hook, so signups are now rejected at the source rather than
> merely rendered useless. Two layers because they cover different people: the hook
> only fires at account creation, so the backend check is what handles accounts that
> already exist. Empty list = allow-everyone in both, deliberately.
> Still gates the *backend* only — a signed-up stranger can read the intentionally
> public reference tables via the anon key. **Rate limiting is untouched.**

Auth is magic-link + Google OAuth with no allowlist, so anyone who finds the app can hold a
valid session. There is no rate limiting anywhere in the stack. An authenticated stranger can
hammer:

- `/roster/sync` and `/fantrax/leagues` → unbounded outbound load on Fantrax under our IP
  (an open proxy to Fantrax, effectively);
- `/sleeper/leagues` → same for Sleeper, including the multi-MB players dump;
- `/roster/analyze` → pandas CPU burn, 2 MB per request;
- `/trade/history` → `analysis` has no length cap (see #11), so unbounded row growth.

AI spend is protected by BYOK — they'd burn their own key — so the exposure is infra and
third-party reputation, not dollars.

**Fix:** two things, both cheap. (1) An email allowlist for signup — this is a league app for
friends, not a public product; enforce it in a Supabase auth hook or a `require_allowlisted`
dependency. (2) `slowapi` per-user limits on the sync/analyze/proxy endpoints.

### 6. RLS policies exist only in the live database

`supabase/migrations/` contains tables and columns but **no `CREATE POLICY` statements** —
the only artifacts are `RLS_AUDIT.sql`, which is a query, and prose in
`20260715_base_schema_documentation.sql`.

The entire multi-tenant boundary for client-side reads is therefore unversioned,
unreviewable in a PR, and unrestorable. The frontend does direct
`supabase.from("leagues").insert/update/delete` — a policy loosened by hand in the dashboard
would open cross-tenant writes with zero signal in code review, and nothing in CI would fail.

**Fix:** dump live policies (`pg_policies`) into a `20260901_rls_policies.sql` migration as
the source of truth, and re-run `RLS_AUDIT.sql` after any dashboard change. Verify while
you're there that the `leagues` UPDATE policy has an explicit `WITH CHECK` (without one,
Postgres reuses `USING`, which is correct here — but make it deliberate, not incidental).

## LOW

### 7. 22 endpoints return `detail=str(e)` to the client

The global handler correctly returns a generic `"Internal Server Error"` — but 22 explicit
`raise HTTPException(500, detail=str(e))` sites bypass it and hand the caller raw PostgREST
errors (table names, column names, constraint names) or upstream messages. `api/main.py`
lines 630, 641, 2199, 2215, 2243, 2327, 2352, 2626, 2686, 2751, 2901, 3123, 3210, 3282, 3285,
3567, 3616, 3823, 3864, 4080, 4119, 4173.

`/fantrax/leagues` already does this right (`"Couldn't reach Fantrax."` + `traceback.print_exc()`).
Apply that shape everywhere.

### 8. No security headers

`next.config.ts` sets no `headers()`. Missing `Content-Security-Policy`,
`X-Frame-Options`/`frame-ancestors` (clickjacking on the settings page, where the API key
field lives), `Referrer-Policy`, `X-Content-Type-Options`, `Permissions-Policy`. Vercel
supplies HSTS; the rest are ours.

### 9. FastAPI docs are public

> **SHIPPED (#132).** Off unless `DOCS_ENABLED=true`.

`FastAPI(title="DynastyOS API")` leaves `/docs`, `/redoc`, and `/openapi.json` open, giving
anyone who finds the Railway URL the full endpoint list, request schemas, and auth shape.
Endpoints are authenticated, so this is reconnaissance value only.

**Fix:** `docs_url=None, redoc_url=None, openapi_url=None` in production.

### 10. Admin is gated on the `email` claim, not `sub`

`require_admin` compares `user["email"]` against `ADMIN_EMAILS`. Magic-link auth means an
attacker can't sign in as that address without inbox access, so this holds today — but it
inherits its strength from a Supabase setting ("Secure email change") that lives outside this
repo. If confirmations were ever relaxed, `updateUser({email})` becomes privilege escalation.

**Fix:** pin to the user UUID (`sub`) via an `ADMIN_USER_IDS` env var. Identity, not a
mutable attribute.

### 11. No length caps on any request model

None of the 11 Pydantic models declare `max_length`. The one that matters is
`TradeHistoryItem.analysis` — unbounded and stored verbatim (`verdict` is capped at 500,
`analysis` isn't). Repeated posts of multi-MB strings are cheap DB-storage abuse.
`AddDropPlayer.name` is unbounded free text flowing into an AI prompt — injection there is
self-inflicted (own key, own output), so it's a cost issue, not a trust boundary.

### 12. Cron secret compared with `!=`

> **SHIPPED (#132).** `_cron_secret_ok` uses `hmac.compare_digest`; an unset secret now
> rejects everything rather than being a no-op check.

`api/main.py:1422` and `:2129`. Use `hmac.compare_digest`. Timing attacks across the public
internet against a high-entropy secret are near-unexploitable — but it's a one-line change
and the endpoints it guards can trigger billed AI work.

### 13. Unvalidated `username` interpolated into the Sleeper URL path

`engine/sleeper_client.py:25` — `f"{SLEEPER_BASE}/user/{username}"` from a raw query param.
The host is fixed, so this can't be redirected off-domain; worst case is path/query
manipulation within `api.sleeper.app`. Validate against `^[A-Za-z0-9_-]{1,64}$` anyway.

### 14. `_ai_client_cache` is keyed by plaintext API keys and never evicted

Decrypted BYOK keys accumulate as dict keys in process memory for the life of the container,
and the dict is unbounded. It's cleared on key set/delete only. Key it by `user_id` and add
an LRU bound; that also shrinks what a memory-disclosure bug would yield.

### 15. Root `.env.local` is not gitignored

> **SHIPPED (#132).** `.gitignore` now uses `.env*`.

`web/.env.local` is covered by `web/.gitignore` (create-next-app) and root `.env` is covered
— but a root `.env.local` is not. One line: change `.env` to `.env*` in `.gitignore`.

## Suggested order

1. `next@16.3.4` (#1) — one command, highest exposure, CI-verifiable.
2. Fail closed in `require_league_owner` (#4), `compare_digest` (#12), CORS default (#3),
   `docs_url=None` (#9), `.env*` (#15) — a single small hardening PR.
3. Fantrax secret handling (#2) — POST first, then encrypt, then stop shipping it client-side.
4. Signup allowlist + rate limiting (#5).
5. RLS policies into version control (#6).
6. Error-detail sweep (#7) and security headers (#8).
