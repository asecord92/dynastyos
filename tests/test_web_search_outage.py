"""Unit tests for `_web_search_failed` (api/main.py).

Web search is a *server-side* tool: an outage doesn't raise, it comes back as
`web_search_tool_result` blocks whose content is an error object. The model then
obeys the widget prompts' hard rule ("don't assert team/role/health you couldn't
verify") and answers with a compliance disclaimer instead of recommendations.
That text used to be cached for the full 8h refresh window and shipped in the
daily digest email — this helper is what keeps it out of `dashboard_cache`.

The fakes below mirror the SDK's `Message.content` block shapes; the distinction
that matters is `.content` being a *list of results* (success) vs an object
typed `web_search_tool_result_error` (failure).
"""
from api.main import _web_search_error_codes, _web_search_failed


class Text:
    type = "text"

    def __init__(self, text=""):
        self.text = text


class SearchError:
    type = "web_search_tool_result_error"

    def __init__(self, code="unavailable"):
        self.error_code = code


class SearchResult:
    """One block of returned search results (success)."""

    type = "web_search_tool_result"

    def __init__(self, ok=True, code="unavailable"):
        self.content = [] if ok else SearchError(code)


class Message:
    def __init__(self, *blocks):
        self.content = list(blocks)


def test_all_searches_errored_is_an_outage():
    """The case that shipped the disclaimer: every attempt came back an error."""
    assert _web_search_failed(
        Message(SearchResult(ok=False), SearchResult(ok=False), Text("I was unable to…"))
    )


def test_single_errored_search_is_an_outage():
    assert _web_search_failed(Message(SearchResult(ok=False), Text("…")))


def test_successful_searches_are_not_an_outage():
    assert not _web_search_failed(Message(SearchResult(), SearchResult(), Text("Adds:")))


def test_partial_failure_is_not_an_outage():
    """One search failing while another returns results is normal — the model
    still had real data to ground its answer, so the generation is cacheable."""
    assert not _web_search_failed(Message(SearchResult(ok=False), SearchResult(), Text("Adds:")))


def test_no_searches_attempted_is_not_an_outage():
    """Critical: a text-only answer means the model chose not to search (it can
    answer from the stat pool alone). Treating that as failure would make the
    warmer re-bill the owner's key on every pass without ever caching."""
    assert not _web_search_failed(Message(Text("Adds: …")))


def test_empty_response_is_not_an_outage():
    assert not _web_search_failed(Message())


def test_unknown_block_types_are_ignored():
    """Fails open on shapes we don't recognize rather than nuking the cache."""

    class Thinking:
        type = "thinking"

    assert not _web_search_failed(Message(Thinking(), Text("answer")))


# --- _web_search_error_codes: the *why* behind an outage ----------------------
# `_web_search_failed` answers yes/no, which was enough to protect the cache but
# left every outage unattributable. These codes distinguish an upstream outage
# from our own budget from the owner's key being throttled.


def test_error_codes_are_extracted_in_order():
    codes = _web_search_error_codes(
        Message(
            SearchResult(ok=False, code="too_many_requests"),
            SearchResult(ok=False, code="unavailable"),
            Text("I was unable to…"),
        )
    )
    assert codes == ["too_many_requests", "unavailable"]


def test_error_codes_ignore_successful_searches():
    """A partial failure still yields its one code — that's the signal that the
    model burned a search-loop iteration for nothing."""
    assert _web_search_error_codes(
        Message(SearchResult(), SearchResult(ok=False, code="max_uses_exceeded"))
    ) == ["max_uses_exceeded"]


def test_no_error_codes_when_everything_succeeded():
    assert _web_search_error_codes(Message(SearchResult(), Text("Adds:"))) == []


def test_no_error_codes_without_searches():
    assert _web_search_error_codes(Message(Text("answer"))) == []


def test_missing_error_code_falls_back_to_unknown():
    """Never drop a failure just because the SDK shape shifted — an
    unattributed outage still needs to reach the admin feed."""

    class Bare:
        type = "web_search_tool_result_error"

    block = SearchResult(ok=False)
    block.content = Bare()
    assert _web_search_error_codes(Message(block)) == ["unknown"]
