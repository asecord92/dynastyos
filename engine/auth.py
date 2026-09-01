import os
import time
import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from jose.backends import ECKey  # noqa: F401 — registers the EC backend for ES256 verification

_bearer = HTTPBearer()

SUPABASE_URL = os.environ["SUPABASE_URL"]
# Re-fetch the JWKS hourly so a Supabase signing-key rotation doesn't keep an
# old key trusted for the life of the process.
_JWKS_TTL_SECONDS = 3600
_jwks_cache: dict | None = None
_jwks_fetched_at: float = 0.0


def _get_jwks() -> dict:
    global _jwks_cache, _jwks_fetched_at
    if _jwks_cache is None or time.monotonic() - _jwks_fetched_at > _JWKS_TTL_SECONDS:
        url = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
        try:
            resp = httpx.get(url, timeout=10)
            resp.raise_for_status()
            _jwks_cache = resp.json()
            _jwks_fetched_at = time.monotonic()
        except Exception:
            if _jwks_cache is None:
                raise  # no keys at all — auth can't proceed
            # refresh failed — keep serving the last good key set
    return _jwks_cache


_ALLOWLIST_TTL_SECONDS = 60
_allowlist_cache: set[str] | None = None
_allowlist_fetched_at: float = 0.0


def reset_allowlist_cache() -> None:
    """Drop the cached allowlist so the next request re-reads the table. Called
    by the admin add/remove endpoints so a change takes effect immediately
    instead of up to `_ALLOWLIST_TTL_SECONDS` later."""
    global _allowlist_cache, _allowlist_fetched_at
    _allowlist_cache = None
    _allowlist_fetched_at = 0.0


def _env_emails(var: str, default: str = "") -> set[str]:
    return {e.strip().lower() for e in os.getenv(var, default).split(",") if e.strip()}


def _allowed_emails() -> set[str]:
    """The invite allowlist: `allowed_emails` rows ∪ ALLOWED_EMAILS ∪ ADMIN_EMAILS.

    Supabase signup is open to the world (magic link + Google), so for a private
    league app anyone who finds the site can hold a valid session. The table is
    the editable source of truth — managed from the admin page rather than an
    env var, so adding a friend needs no redeploy — and the `hook_restrict_signup`
    Postgres hook reads the same rows to reject new signups at the source. This
    layer is what keeps out people who *already* have an account, which the hook
    cannot help with.

    ADMIN_EMAILS is folded in unconditionally so the operator can never lock
    themselves out. ALLOWED_EMAILS is kept as break-glass for the case where the
    table is unreachable at boot.

    **Empty means allow everyone.** An empty list is "not configured yet", not
    "admit nobody" — failing closed on an unpopulated table would strand every
    user the moment this deploys, and the same reasoning covers the pre-migration
    window where the table doesn't exist at all.

    Cached for a minute, and a failed refresh keeps serving the last good list
    rather than falling back to a smaller one — the same stale-on-error shape as
    `_get_jwks` above. Without it, one transient Supabase blip would silently
    drop the gate to whatever the env vars happen to say.
    """
    global _allowlist_cache, _allowlist_fetched_at

    if _allowlist_cache is None or time.monotonic() - _allowlist_fetched_at > _ALLOWLIST_TTL_SECONDS:
        try:
            from .supabase_client import get_supabase

            rows = get_supabase().table("allowed_emails").select("email").execute().data or []
            _allowlist_cache = {
                (r.get("email") or "").strip().lower() for r in rows if (r.get("email") or "").strip()
            }
            _allowlist_fetched_at = time.monotonic()
        except Exception:
            # Table missing (pre-migration) or Supabase unreachable. Keep the last
            # good list if we have one; otherwise fall back to the env var.
            if _allowlist_cache is None:
                return _combine(_env_emails("ALLOWED_EMAILS"))

    return _combine(_allowlist_cache or set())


def _combine(listed: set[str]) -> set[str]:
    """Union the configured list with the env break-glass, then with the admin
    emails — but only if the gate is on at all. An empty result means the gate
    stays off, so admins are not the *only* people who can get in by default."""
    allowed = set(listed) | _env_emails("ALLOWED_EMAILS")
    if not allowed:
        return set()  # not configured -> gate is off
    return allowed | _env_emails("ADMIN_EMAILS", "asecord92@gmail.com")


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    token = credentials.credentials
    try:
        jwks = _get_jwks()
        payload = jwt.decode(
            token,
            jwks,
            algorithms=["ES256"],
            options={"verify_aud": False},
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Enforced here rather than per-endpoint: every route already depends on
    # get_current_user, so there is no call site to forget. The cron routes are
    # unaffected — they authenticate with CRON_SECRET, not a user JWT.
    allowed = _allowed_emails()
    if allowed:
        email = (payload.get("email") or "").strip().lower()
        if email not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This app is invite-only. Ask Adam to add your email.",
            )
    return payload