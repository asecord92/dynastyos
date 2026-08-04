"""Guards the search-first nudge on the web-search widgets (api/main.py).

Sonnet 5 reaches for tools LESS when thinking is disabled, and that's exactly
how the dashboard widgets run (`_NO_THINKING`, a deliberate BYOK cost choice).
Their prompts also hard-forbid asserting a team/role/health status that wasn't
confirmed by search — so a run where the model quietly declines to search can't
produce recommendations at all, only an "I was unable to verify…" disclaimer.

The trap is that this is invisible to `_web_search_failed`: zero attempts is
deliberately NOT treated as an outage, so the disclaimer caches for the full 8h
window and ships in the daily digest looking exactly like a real upstream
outage. The two have opposite fixes, which is why the trigger is explicit.

The structural test below is the important one — it fails when someone adds a
seventh web-search widget and forgets the nudge, which is the realistic way this
regresses.
"""
import inspect

import api.main
from api.main import _SEARCH_FIRST_INSTRUCTION, _with_search_first


def test_appends_trigger_without_disturbing_the_prompt():
    out = _with_search_first("PROMPT BODY")
    assert out.startswith("PROMPT BODY")
    assert out.endswith(_SEARCH_FIRST_INSTRUCTION)


def test_trigger_is_imperative_about_searching_first():
    """Prescriptive 'when to call' beats a passive mention — a tool description
    that only says what search *is* doesn't move Sonnet 5's should-call rate."""
    text = _SEARCH_FIRST_INSTRUCTION.lower()
    assert "search" in text
    assert "before you answer" in text or "search first" in text


def _web_search_call_sites() -> list[int]:
    """Line indices of the dashboard widget calls that attach `_WEB_SEARCH`.
    Deliberately does not match `_TRADE_WEB_SEARCH`: the trade surfaces run
    Opus 5 with thinking ON, so they don't have the tool-reluctance problem."""
    src = inspect.getsource(api.main).splitlines()
    return [i for i, line in enumerate(src) if "tools=_WEB_SEARCH," in line]


def test_all_six_widgets_are_covered():
    """MLB + NFL x news / start_sit / waiver."""
    assert len(_web_search_call_sites()) == 6


def test_every_web_search_widget_gets_the_nudge():
    src = inspect.getsource(api.main).splitlines()
    for i in _web_search_call_sites():
        # The prompt rides in the `messages=` line right below `tools=`.
        window = "\n".join(src[i:i + 4])
        assert "_with_search_first(" in window, (
            f"web-search widget call site near line {i + 1} builds its prompt "
            "without _with_search_first — with thinking disabled the model will "
            "under-search, and the resulting disclaimer caches silently"
        )
