"""The digest is fired twice a day and must still send exactly once.

On 2026-08-06 the scheduled digest never ran: GitHub cancelled the job after 15
minutes with zero steps executed and the annotation "The job was not acquired by
Runner of type hosted even after multiple attempts". The backend was never
called, so nobody got an email and nothing in app_events recorded a failure.

A step-level retry can't fix that — no runner ever executes the step — so the
workflow now has a second scheduled attempt. That is only safe if the job can't
double-send, which is what `_digest_claim` guarantees. These tests pin the
guarantee in both directions: a second attempt must no-op, and a day that never
sent must not be blocked.
"""
import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path

import api.main
from api.main import _digest_claim


class FakeTable:
    """Records the filters applied so tests can assert what was queried."""

    def __init__(self, data, log, fail=False):
        self._data = data
        self._log = log
        self._fail = fail

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self._log.setdefault("eq", []).append((col, val))
        return self

    def gte(self, col, val):
        self._log.setdefault("gte", []).append((col, val))
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        if self._fail:
            raise RuntimeError("supabase unreachable")
        return type("R", (), {"data": self._data})()


class FakeSB:
    def __init__(self, events=None, fail=False):
        self.events = events if events is not None else []
        self.fail = fail
        self.log: dict = {}

    def table(self, name):
        assert name == "app_events", f"unexpected table {name}"
        return FakeTable(self.events, self.log, self.fail)


def capture_events(monkeypatch) -> list:
    """Intercept _log_event so the claim marker is observable."""
    written: list = []
    monkeypatch.setattr(api.main, "_log_event", lambda **kw: written.append(kw))
    return written


def test_first_attempt_of_the_day_claims_it(monkeypatch):
    written = capture_events(monkeypatch)
    assert _digest_claim(FakeSB(events=[])) is True
    assert len(written) == 1
    assert written[0]["kind"] == "digest_run"


def test_second_attempt_no_ops(monkeypatch):
    """The backstop firing after a successful primary must send nothing."""
    written = capture_events(monkeypatch)
    assert _digest_claim(FakeSB(events=[{"id": "already-claimed"}])) is False
    assert written == [], "a skipped run must not write a claim of its own"


def test_claim_is_scoped_to_today_and_to_claim_rows(monkeypatch):
    """Yesterday's claim must not block today, and the unrelated `digest`
    outcome rows the job already writes must not be mistaken for a claim."""
    capture_events(monkeypatch)
    sb = FakeSB(events=[])
    _digest_claim(sb)
    assert ("kind", "digest_run") in sb.log["eq"]
    (col, since), = sb.log["gte"]
    assert col == "created_at"
    assert since.startswith(datetime.now(timezone.utc).date().isoformat())
    # A window that starts today can't match a marker written yesterday.
    assert since > (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


def test_force_overrides_an_existing_claim(monkeypatch):
    """The manual re-send escape hatch, used when a day genuinely needs a
    second send — it must still be possible."""
    written = capture_events(monkeypatch)
    assert _digest_claim(FakeSB(events=[{"id": "already-claimed"}]), force=True) is True
    assert written[0]["kind"] == "digest_run"


def test_unverifiable_claim_fails_closed(monkeypatch):
    """If the claim can't be read, skip. A silent double-send to every owner is
    worse than a missed day, and the other scheduled attempt retries."""
    written = capture_events(monkeypatch)
    assert _digest_claim(FakeSB(fail=True)) is False
    assert written == []


def test_job_claims_before_doing_any_work():
    """The gate has to sit ahead of the league fan-out, or it protects nothing."""
    src = inspect.getsource(api.main._daily_digest_job)
    assert "_digest_claim" in src, "the digest job no longer claims the day"
    assert src.index("_digest_claim") < src.index('table("leagues")'), (
        "the claim must happen before the digest starts assembling leagues"
    )


def test_config_abort_does_not_burn_the_days_attempt():
    """A missing BREVO key returns before claiming, so fixing the env var and
    letting the backstop fire still delivers that day."""
    src = inspect.getsource(api.main._daily_digest_job)
    assert src.index("BREVO_API_KEY") < src.index("_digest_claim")


def test_workflow_still_has_a_backstop_schedule():
    """The claim only earns its keep if a second attempt actually fires."""
    wf = Path(__file__).resolve().parents[1] / ".github/workflows/daily-digest.yml"
    crons = [ln for ln in wf.read_text(encoding="utf-8").splitlines() if "- cron:" in ln]
    assert len(crons) == 2, f"expected a primary and a backstop schedule, found {crons}"
