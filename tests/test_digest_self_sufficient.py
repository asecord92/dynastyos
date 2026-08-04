"""The digest generates its own grounding instead of warming widgets.

Before: `/cron/daily-digest` called `_warm_stale_widgets` for every opted-in
league, regenerating `start_sit` and `waiver` — two full, search-grounded,
interactive-quality widgets — and then kept only a few condensed lines of each.
That was ~$1.27 per league per day, and it ran regardless of whether the owner
had opened the app in weeks, because the digest is deliberately exempt from the
cron warmer's 36h activity gate.

Now `_digest_brief` produces "Today's Calls" in one cheap no-search Sonnet call
from data already in the database. Dropping search is deliberate: it is what
makes this ~40x cheaper, and it removes the failure mode that prompted the work
— with search attached, an upstream outage made the model refuse to assert
anything and the email shipped a compliance disclaimer instead of picks.
"""
import inspect

import api.main
from api.main import _digest_brief, _digest_brief_context


class FakeTable:
    """Minimal Supabase query-builder stub — every filter returns self."""

    def __init__(self, data):
        self._data = data

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return type("R", (), {"data": self._data})()


class FakeSB:
    def __init__(self, rosters=None, id_map=None):
        self._rosters = rosters if rosters is not None else []
        self._id_map = id_map or []

    def table(self, name):
        if name == "rosters":
            return FakeTable(self._rosters)
        if name == "player_id_map":
            return FakeTable(self._id_map)
        return FakeTable([])


LEAGUE = {"id": "lg1", "fantrax_team_id": "t1"}


def test_digest_no_longer_warms_widgets():
    """The load-bearing assertion: the digest job must not call the warmer.
    Re-adding that call is what would silently restore ~$1.27/league/day."""
    src = inspect.getsource(api.main._daily_digest_job)
    assert "_warm_stale_widgets" not in src


def test_cron_warmer_still_warms():
    """The standalone cron keeps warming — it's activity-gated, so it only
    pays for leagues someone actually opened. Only the digest path changed."""
    src = inspect.getsource(api.main.cron_refresh_widgets)
    assert "_warm_stale_widgets" in src


def test_brief_context_includes_status_flags():
    """IL / minors flags are the facts that make a start-sit call change day to
    day, and they cost nothing to read — they must reach the prompt."""
    sb = FakeSB(
        rosters=[{"roster_items": [{"id": "p1", "position": "SP", "status": "ACTIVE"}],
                  "team_name": "Bashers"}],
        id_map=[{"fantrax_id": "p1", "full_name": "Some Pitcher",
                 "mlb_team": "LAD", "roster_status": "IL", "il_type": "60-day IL"}],
    )
    context = _digest_brief_context(sb, LEAGUE, "MLB")
    assert "Some Pitcher" in context
    assert "60-day IL" in context
    assert "Bashers" in context


def test_brief_context_none_without_a_synced_roster():
    """No roster means nothing truthful to say — the digest reports no_content
    rather than inventing a section."""
    assert _digest_brief_context(FakeSB(rosters=[]), LEAGUE, "MLB") is None


def test_brief_context_none_without_a_team_id():
    assert _digest_brief_context(FakeSB(), {"id": "lg1"}, "MLB") is None


def test_brief_returns_empty_when_context_is_missing():
    """Must not reach the AI client (or raise) when there's nothing to say."""
    assert _digest_brief(FakeSB(rosters=[]), LEAGUE, "MLB") == {}


def test_brief_prompt_forbids_inventing_unverifiable_facts():
    """With no web access the model must not assert injury timelines or
    transactions — the grounding rules are what keep the email honest."""
    src = inspect.getsource(_digest_brief)
    assert "no web access" in src
    assert "Use ONLY the data above" in src


def test_brief_makes_a_no_search_no_thinking_call():
    """The cost shape: no `tools=` (search is what made this expensive and what
    produced the disclaimer bug) and thinking disabled."""
    src = inspect.getsource(_digest_brief)
    assert "tools=" not in src
    assert "thinking=_NO_THINKING" in src
    assert 'tool="digest"' in src
