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


def _allowed_emails() -> set[str]:
    """The signup allowlist, read fresh each call so it can be changed on the
    host without a redeploy.

    Supabase signup is open to the world (magic link + Google, no gate), which
    for a private league app means anyone who finds the site can hold a valid
    session and reach the sync/proxy endpoints. ADMIN_EMAILS is folded in
    unconditionally so the operator can never lock themselves out with a typo.

    **Empty means allow everyone** — the pre-existing behaviour. That keeps
    deploying this code a no-op and makes turning it on a deliberate, reversible
    config change rather than something that can strand users mid-rollout.
    """
    allowed = {
        e.strip().lower()
        for e in os.getenv("ALLOWED_EMAILS", "").split(",")
        if e.strip()
    }
    if not allowed:
        return set()  # not configured -> gate is off
    allowed |= {
        e.strip().lower()
        for e in os.getenv("ADMIN_EMAILS", "asecord92@gmail.com").split(",")
        if e.strip()
    }
    return allowed


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