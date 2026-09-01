"""Guards the security-hardening pass (2026-09-01 audit, SECURITY_AUDIT.md).

Each test here pins a decision that is invisible at the call site and easy to
undo by accident — most of all `require_league_owner`, which is the *only* thing
standing between a signed-in stranger and another user's league: the backend
holds the Supabase service key, so RLS is bypassed on every query it makes.
"""
import hmac as _hmac
import inspect

import pytest
from fastapi import HTTPException

import engine.auth as auth
from api.main import _cron_secret_ok, app, require_league_owner


# ── require_league_owner fails closed ────────────────────────────────────────
# It used to fail *open* three ways: a failed lookup returned silently, and a
# null owner or a token without `sub` slipped through an `if owner and sub`
# guard. The first was live — supabase_client documents GOAWAY-poisoned
# connections under load, so transient query failure is an observed condition.

class _FakeQuery:
    def __init__(self, result):
        self._result = result

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        if isinstance(self._result, Exception):
            raise self._result
        return type("Res", (), {"data": self._result})()


class _FakeSB:
    def __init__(self, result):
        self._result = result

    def table(self, _name):
        return _FakeQuery(self._result)


@pytest.fixture(autouse=True)
def _clear_allowlist_cache():
    """`_allowlist_cache` is a module global; left populated it would 403 any
    later test that touches get_current_user."""
    auth.reset_allowlist_cache()
    yield
    auth.reset_allowlist_cache()


OWNER = "11111111-1111-1111-1111-111111111111"
STRANGER = "22222222-2222-2222-2222-222222222222"


def test_owner_passes():
    require_league_owner(_FakeSB([{"owner_user_id": OWNER}]), {"sub": OWNER}, "lg")


def test_stranger_is_blocked():
    with pytest.raises(HTTPException) as e:
        require_league_owner(_FakeSB([{"owner_user_id": OWNER}]), {"sub": STRANGER}, "lg")
    assert e.value.status_code == 403


def test_lookup_failure_denies_rather_than_allows():
    """The regression that matters. A transient Supabase error must not be a
    skeleton key — during a GOAWAY the ownership query can fail while a
    dashboard_cache read on a separate code path still succeeds."""
    with pytest.raises(HTTPException) as e:
        require_league_owner(_FakeSB(RuntimeError("ConnectionTerminated")), {"sub": OWNER}, "lg")
    assert e.value.status_code == 503


def test_missing_league_is_a_404_not_a_pass():
    with pytest.raises(HTTPException) as e:
        require_league_owner(_FakeSB([]), {"sub": OWNER}, "lg")
    assert e.value.status_code == 404


def test_token_without_sub_is_rejected():
    with pytest.raises(HTTPException) as e:
        require_league_owner(_FakeSB([{"owner_user_id": OWNER}]), {}, "lg")
    assert e.value.status_code == 401


def test_null_owner_does_not_grant_access():
    """`leagues.owner_user_id` is `not null`, so this shouldn't arise — but
    "unknown owner -> allow" is precisely the shape of the old bug."""
    with pytest.raises(HTTPException) as e:
        require_league_owner(_FakeSB([{"owner_user_id": None}]), {"sub": OWNER}, "lg")
    assert e.value.status_code == 403


def test_does_not_use_single():
    """`.single()` raises on zero rows, making "no such league" and "the database
    is down" the same exception — the ambiguity that motivated the fail-open."""
    body = inspect.getsource(require_league_owner).replace(require_league_owner.__doc__ or "", "")
    assert ".single()" not in body


# ── Invite allowlist ─────────────────────────────────────────────────────────
# Two layers read the same `allowed_emails` table: the `hook_restrict_signup`
# Postgres hook rejects new signups, and this one 403s accounts that already
# exist. The tests below cover the second; the hook is SQL (migration
# 20260901_allowed_emails.sql).

def _decode_as(monkeypatch, payload):
    monkeypatch.setattr(auth, "_get_jwks", lambda: {})
    monkeypatch.setattr(auth.jwt, "decode", lambda *a, **k: payload)
    return type("Creds", (), {"credentials": "token"})()


def _listed(monkeypatch, emails, *, fail=False):
    """Point the allowlist at a fake `allowed_emails` table."""
    auth.reset_allowlist_cache()
    monkeypatch.delenv("ALLOWED_EMAILS", raising=False)

    class _Tbl:
        def select(self, *_a, **_k):
            return self

        def execute(self):
            if fail:
                raise RuntimeError("supabase down")
            return type("Res", (), {"data": [{"email": e} for e in emails]})()

    class _SB:
        def table(self, _n):
            return _Tbl()

    import engine.supabase_client as sc
    monkeypatch.setattr(sc, "get_supabase", lambda: _SB())


def test_gate_is_off_when_list_is_empty(monkeypatch):
    """An empty list means "not configured yet", not "admit nobody". Failing
    closed on an unpopulated table would strand every user on deploy."""
    _listed(monkeypatch, [])
    monkeypatch.delenv("ADMIN_EMAILS", raising=False)
    creds = _decode_as(monkeypatch, {"sub": OWNER, "email": "rando@example.com"})
    assert auth.get_current_user(creds)["sub"] == OWNER


def test_listed_email_passes(monkeypatch):
    _listed(monkeypatch, ["friend@example.com"])
    creds = _decode_as(monkeypatch, {"sub": OWNER, "email": "Friend@Example.com"})
    assert auth.get_current_user(creds)["sub"] == OWNER


def test_stranger_is_turned_away(monkeypatch):
    _listed(monkeypatch, ["friend@example.com"])
    creds = _decode_as(monkeypatch, {"sub": STRANGER, "email": "rando@example.com"})
    with pytest.raises(HTTPException) as e:
        auth.get_current_user(creds)
    assert e.value.status_code == 403


def test_admin_is_always_allowed(monkeypatch):
    """ADMIN_EMAILS is unioned in so an empty or mistyped table can't lock the
    operator out of the app that administers the table."""
    _listed(monkeypatch, ["friend@example.com"])
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    creds = _decode_as(monkeypatch, {"sub": OWNER, "email": "boss@example.com"})
    assert auth.get_current_user(creds)["sub"] == OWNER


def test_env_var_still_works_as_break_glass(monkeypatch):
    """ALLOWED_EMAILS survives from #132 for the case where the table can't be
    read at boot."""
    _listed(monkeypatch, [], fail=True)
    monkeypatch.setenv("ALLOWED_EMAILS", "friend@example.com")
    creds = _decode_as(monkeypatch, {"sub": STRANGER, "email": "rando@example.com"})
    with pytest.raises(HTTPException) as e:
        auth.get_current_user(creds)
    assert e.value.status_code == 403


def test_failed_refresh_keeps_serving_the_last_good_list(monkeypatch):
    """The regression this guards: without stale-on-error, one Supabase blip
    drops the gate to whatever the env vars say — which is usually nothing —
    and silently readmits everyone."""
    _listed(monkeypatch, ["friend@example.com"])
    creds = _decode_as(monkeypatch, {"sub": OWNER, "email": "friend@example.com"})
    assert auth.get_current_user(creds)["sub"] == OWNER  # populates the cache

    # Table goes away; the TTL is forced to expire so the next call refetches.
    auth._allowlist_fetched_at = 0.0
    _fail = type("SB", (), {"table": lambda self, n: (_ for _ in ()).throw(RuntimeError("down"))})
    import engine.supabase_client as sc
    monkeypatch.setattr(sc, "get_supabase", lambda: _fail())

    stranger = _decode_as(monkeypatch, {"sub": STRANGER, "email": "rando@example.com"})
    with pytest.raises(HTTPException) as e:
        auth.get_current_user(stranger)
    assert e.value.status_code == 403


def test_missing_email_claim_is_denied_when_gate_is_on(monkeypatch):
    _listed(monkeypatch, ["friend@example.com"])
    creds = _decode_as(monkeypatch, {"sub": OWNER})
    with pytest.raises(HTTPException) as e:
        auth.get_current_user(creds)
    assert e.value.status_code == 403


# ── Cron shared secret ───────────────────────────────────────────────────────

def test_cron_secret_matches_and_rejects(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "s3cret")
    assert _cron_secret_ok("s3cret")
    assert not _cron_secret_ok("s3cre")
    assert not _cron_secret_ok("")


def test_unset_cron_secret_rejects_everything(monkeypatch):
    """An unconfigured secret must not mean "no check" — that would leave the
    billed AI endpoints open to anyone who guessed the path."""
    monkeypatch.delenv("CRON_SECRET", raising=False)
    assert not _cron_secret_ok("")
    assert not _cron_secret_ok("anything")


def test_comparison_is_constant_time():
    assert "compare_digest" in inspect.getsource(_cron_secret_ok)
    assert _hmac.compare_digest  # the import the source above relies on


# ── Deploy surface ───────────────────────────────────────────────────────────

def test_docs_are_off_by_default():
    """Set DOCS_ENABLED=true locally if you want them; prod shouldn't publish
    the full endpoint list and request schemas."""
    assert app.docs_url is None
    assert app.openapi_url is None
    assert app.redoc_url is None


def test_cors_does_not_default_to_wildcard():
    """Starlette computes `not allow_all_origins or allow_credentials`, so "*"
    with allow_credentials=True doesn't send a literal "*" — it echoes whatever
    Origin asked and marks the response credentialed."""
    import api.main

    assert "*" not in api.main.allow_origins
