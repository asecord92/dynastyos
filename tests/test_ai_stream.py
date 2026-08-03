"""Unit tests for _ai_ndjson_lines' truncation detection (api/main.py).

A `max_tokens` stop ends an Anthropic stream *cleanly* — no exception — so
nothing downstream notices unless we check `stop_reason` explicitly. That makes
this a silent-failure path: before the check, a finder run that blew the token
cap mid-```json emitted a `done`, and the caller then reported the resulting
parse failure as if the parser were at fault.

The fakes below stand in for the SDK's stream manager; we assert on the ndjson
event types, which are the actual contract with the frontends.
"""
import json

from api.main import PausedTurnError, TruncatedResponseError, _ai_ndjson_lines


def fake_ai(stop_reason, deltas=(), *, snapshot=True):
    """Minimal stand-in for `client.messages` — yields `deltas` as text events,
    then exposes `stop_reason` the way the SDK's accumulated snapshot does."""
    class TextEvent:
        def __init__(self, text):
            self.type = "text"
            self.text = text

    class Snapshot:
        pass

    snap = Snapshot()
    snap.stop_reason = stop_reason

    class Stream:
        def __iter__(self):
            return iter([TextEvent(d) for d in deltas])

    if snapshot:
        Stream.current_message_snapshot = snap

    class Manager:
        def __enter__(self):
            return Stream()

        def __exit__(self, *exc):
            return False

    class Messages:
        def stream(self, **kwargs):
            return Manager()

    class AI:
        messages = Messages()

    return AI()


def events(ai, **kwargs):
    return [json.loads(line) for line in _ai_ndjson_lines(ai, **kwargs)]


def types(ai, **kwargs):
    return [e["type"] for e in events(ai, **kwargs)]


def test_truncation_emits_error_not_done():
    failed: list = []
    evts = events(
        fake_ai("max_tokens", ["half an answ"]),
        status_label="Building trade packages…",
        failed=failed,
        done_event=False,
    )
    assert [e["type"] for e in evts] == ["status", "text", "error"]
    # Stable code — the frontends key their copy off this string.
    assert evts[-1]["detail"] == "truncated"
    # Non-empty `failed` is what stops the finder parsing a half-written block.
    assert len(failed) == 1
    assert isinstance(failed[0], TruncatedResponseError)


def test_truncation_suppresses_done_event():
    """Even on the done_event=True callers (analyze, add/drop), a truncated
    answer must not be reported as a completed one."""
    assert "done" not in types(
        fake_ai("max_tokens", ["cut off"]), status_label="x", done_event=True
    )


def test_partial_text_still_streams():
    """The truncated answer is real, just short — the user keeps what arrived."""
    evts = events(fake_ai("max_tokens", ["kept"]), status_label="x", done_event=False)
    assert [e["delta"] for e in evts if e["type"] == "text"] == ["kept"]


def test_pause_turn_emits_error_not_done():
    """`pause_turn` means the server-side web-search loop hit its iteration cap,
    so the answer stops wherever the last search left it. Like max_tokens it
    ends the stream cleanly, so without the check /trade/analyze reports a
    half-finished analysis as `done`."""
    failed: list = []
    evts = events(
        fake_ai("pause_turn", ["I checked two sources and"]),
        status_label="Weighing the deal…",
        failed=failed,
        done_event=True,
    )
    assert [e["type"] for e in evts] == ["status", "text", "error"]
    # Distinct from "truncated": different cause, different user-facing copy.
    assert evts[-1]["detail"] == "paused"
    assert len(failed) == 1
    assert isinstance(failed[0], PausedTurnError)


def test_pause_turn_keeps_partial_text():
    """The research so far is real — the user keeps what arrived."""
    evts = events(
        fake_ai("pause_turn", ["partial"]), status_label="x", done_event=False
    )
    assert [e["delta"] for e in evts if e["type"] == "text"] == ["partial"]


def test_pause_turn_and_truncation_stay_distinct():
    """Both are clean stops with a partial answer, but the frontends word them
    differently — a regression that collapsed them would be invisible above."""
    def detail(reason):
        return [
            e for e in events(fake_ai(reason, ["x"]), status_label="x")
            if e["type"] == "error"
        ][0]["detail"]

    assert detail("pause_turn") == "paused"
    assert detail("max_tokens") == "truncated"


def test_clean_stop_is_untouched():
    failed: list = []
    assert types(
        fake_ai("end_turn", ["all of it"]),
        status_label="x",
        failed=failed,
        done_event=True,
    ) == ["status", "text", "done"]
    assert failed == []


def test_missing_snapshot_fails_open():
    """If the SDK ever stops exposing the snapshot, degrade to the old
    behavior (assume success) rather than erroring on every call."""
    failed: list = []
    assert types(
        fake_ai("end_turn", ["text"], snapshot=False),
        status_label="x",
        failed=failed,
        done_event=True,
    ) == ["status", "text", "done"]
    assert failed == []
