"""Guards the widget web-search budget (api/main.py).

The expensive bug this prevents: the widget prompts said "search for each
player" while `_WEB_SEARCH` granted `max_uses: 3`. The model queued a search per
player, every attempt past the third was refused, and each refusal still cost a
full re-send of the accumulated conversation — server-side tool loops re-send
everything each iteration. Waiver averaged 13.1 search requests per call against
a cap of 3, reaching ~301k input tokens per call and ~$0.78 a call.

The fix is structural rather than editorial: the number lives in
`_WEB_SEARCH_MAX_USES`, the tool config and the prompt instruction both derive
from it, and the tests below fail if they ever drift apart again.
"""
import inspect

import api.main
from api.main import (
    _SEARCH_BUDGET_INSTRUCTION,
    _WEB_SEARCH,
    _WEB_SEARCH_MAX_USES,
    _with_search_budget,
)


def test_tool_config_uses_the_shared_budget():
    assert _WEB_SEARCH[0]["max_uses"] == _WEB_SEARCH_MAX_USES


def test_instruction_states_the_same_number_the_tool_enforces():
    """The anti-drift guard, and the reason the constant exists. A prompt that
    promises more searches than the tool grants is what caused the blowup."""
    assert str(_WEB_SEARCH_MAX_USES) in _SEARCH_BUDGET_INSTRUCTION


def test_instruction_says_overflow_is_refused_not_queued():
    """The model has to know extra attempts are rejected, not deferred —
    otherwise it still plans a search per player and pays for the refusals."""
    text = _SEARCH_BUDGET_INSTRUCTION.lower()
    assert "refused" in text
    assert "not plan one search per player" in text.replace("do not", "not")


def test_appends_without_disturbing_the_prompt():
    out = _with_search_budget("PROMPT BODY")
    assert out.startswith("PROMPT BODY")
    assert out.endswith(_SEARCH_BUDGET_INSTRUCTION)


def _web_search_call_sites() -> list[int]:
    """Line indices of widget calls attaching `_WEB_SEARCH`. Deliberately does
    not match `_TRADE_WEB_SEARCH`: the trade prompts already say "a few targeted
    searches at most" and measured 3.7 requests against their cap of 4 — they
    never had the drift."""
    src = inspect.getsource(api.main).splitlines()
    return [i for i, line in enumerate(src) if "tools=_WEB_SEARCH," in line]


def test_all_six_widgets_are_covered():
    """MLB + NFL x news / start_sit / waiver."""
    assert len(_web_search_call_sites()) == 6


def test_every_web_search_widget_states_its_budget():
    src = inspect.getsource(api.main).splitlines()
    for i in _web_search_call_sites():
        # The prompt rides in the `messages=` line right below `tools=`.
        window = "\n".join(src[i:i + 4])
        assert "_with_search_budget(" in window, (
            f"web-search widget call site near line {i + 1} sends a prompt that "
            "never states the search budget — the model will queue a search per "
            "player and pay for the refused attempts"
        )


def test_no_widget_prompt_asks_for_a_search_per_player():
    """The exact phrasings that caused the blowup. Kept as a literal check so
    the regression is caught at review time, not on next month's bill."""
    src = inspect.getsource(api.main)
    for banned in (
        "search each of your top candidates",
        "for each, search for the injury",
        "summarize recent news (last 2 weeks) for each player",
    ):
        assert banned not in src, f"per-player search instruction is back: {banned!r}"
