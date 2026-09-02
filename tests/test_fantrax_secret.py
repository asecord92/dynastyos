"""The Fantrax Secret ID is a live credential to a user's Fantrax account.

It used to be stored in the clear, handed to the browser on every page load, and
sent back as a URL query parameter — which wrote it verbatim into Vercel's edge
logs, Railway's request logs and browser history (SECURITY_AUDIT.md #2).

The riskiest part of fixing that is the encryption-in-place: rows written before
the change hold plaintext, and getting the read wrong means every user has to go
dig their Secret ID out of Fantrax again. These tests pin the tolerant read and
the rolling upgrade that avoid a backfill migration.
"""
import inspect

from cryptography.fernet import Fernet

import api.main
from engine import crypto


def _with_key(monkeypatch):
    """A real Fernet key, so encrypt/decrypt round-trip for real rather than
    against a stub that could hide an encoding bug."""
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(crypto, "_fernet", None)


PLAINTEXT_SECRET = "abcd1234efgh5678"  # shape of a real Fantrax Secret ID


def test_round_trip(monkeypatch):
    _with_key(monkeypatch)
    assert crypto.decrypt_tolerant(crypto.encrypt(PLAINTEXT_SECRET)) == PLAINTEXT_SECRET


def test_legacy_plaintext_is_returned_unchanged(monkeypatch):
    """The whole point: a row written before the column was encrypted keeps
    working, with no backfill and no re-entry."""
    _with_key(monkeypatch)
    assert crypto.decrypt_tolerant(PLAINTEXT_SECRET) == PLAINTEXT_SECRET


def test_empty_stays_empty(monkeypatch):
    _with_key(monkeypatch)
    assert crypto.decrypt_tolerant(None) is None
    assert crypto.decrypt_tolerant("") is None


def test_undecryptable_ciphertext_returns_none_rather_than_raising(monkeypatch):
    """A token encrypted under a *different* key (a rotated APP_ENCRYPTION_KEY)
    must degrade to "Fantrax rejects it", not a 500 that leaves the user unable
    to reconnect."""
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(crypto, "_fernet", None)
    foreign = Fernet(Fernet.generate_key()).encrypt(b"secret").decode()
    assert crypto.decrypt_tolerant(foreign) is None


def test_looks_encrypted_discriminates(monkeypatch):
    _with_key(monkeypatch)
    assert crypto.looks_encrypted(crypto.encrypt(PLAINTEXT_SECRET))
    assert not crypto.looks_encrypted(PLAINTEXT_SECRET)
    assert not crypto.looks_encrypted("")


def test_secret_is_never_a_query_parameter():
    """The log-bleed regression. `/fantrax/leagues` took the Secret ID as a
    query param; anything that puts it back in a URL puts it back in the logs."""
    src = inspect.getsource(api.main.fantrax_leagues)
    assert "Query(" not in src
    routes = {r.path: sorted(r.methods) for r in api.main.app.routes if getattr(r, "methods", None)}
    assert routes.get("/fantrax/leagues") == ["POST"]


def test_sync_accepts_a_request_with_no_secret():
    """The frontend stops sending it — the backend reads the encrypted value off
    the league row instead."""
    assert api.main.RosterSyncRequest(fantrax_league_id="abc").user_secret_id is None


def test_sync_still_accepts_one(monkeypatch):
    """Deploy-skew tolerance: Vercel and Railway deploy independently, so a
    browser on the previous bundle keeps syncing."""
    body = api.main.RosterSyncRequest(fantrax_league_id="abc", user_secret_id="legacy")
    assert body.user_secret_id == "legacy"


def test_reencrypt_only_after_fantrax_accepts_the_secret():
    """The rolling upgrade must not overwrite a good stored secret with a bad
    submitted one, so the re-write sits after the get_leagues() call that proves
    the secret authenticates."""
    src = inspect.getsource(api.main.roster_sync)
    assert src.index("get_leagues(user_secret_id)") < src.index("_store_fantrax_secret")
