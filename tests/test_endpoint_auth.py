"""Every API route must be deliberately authenticated.

This is a regression guard, not a unit test: adding an endpoint without an auth
dependency is a one-line mistake that nothing else catches, and we shipped three
of them (`/roster/analyze`, `/fantrax/leagues`, `/sleeper/leagues`) before
noticing. If you add a genuinely public route, add it to PUBLIC_PATHS below —
the point is that it becomes a deliberate edit someone has to justify, rather
than a silent default.
"""
import inspect

import pytest

from api.main import app

# Routes that are public on purpose.
PUBLIC_PATHS = {
    "/health",  # uptime probe
    # FastAPI's built-in docs. Public schema is reconnaissance, not a hole —
    # every documented route below is itself authenticated.
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
    "/openapi.json",
}

# Guarded by the CRON_SECRET shared header rather than a user JWT, checked
# inside the handler (see cron_refresh_widgets / cron_daily_digest).
CRON_PATHS = {"/cron/refresh-widgets", "/cron/daily-digest"}


def api_routes():
    for route in app.routes:
        if not hasattr(route, "endpoint") or not getattr(route, "methods", None):
            continue
        yield route


def auth_kind(route) -> str:
    params = inspect.signature(route.endpoint).parameters
    defaults = " ".join(str(p.default) for p in params.values())
    if "require_admin" in defaults:
        return "admin"
    if "get_current_user" in defaults:
        return "user"
    if "x_cron_secret" in params:
        return "cron"
    return "open"


@pytest.mark.parametrize(
    "route", list(api_routes()), ids=lambda r: f"{sorted(r.methods)} {r.path}"
)
def test_route_is_authenticated(route):
    kind = auth_kind(route)
    if route.path in PUBLIC_PATHS:
        return
    if route.path in CRON_PATHS:
        assert kind == "cron", f"{route.path} lost its CRON_SECRET header guard"
        return
    assert kind in {"user", "admin"}, (
        f"{route.path} has no auth dependency. Add "
        f"`Depends(get_current_user)` (or `require_admin`), or add it to "
        f"PUBLIC_PATHS if it's meant to be public."
    )


def test_the_three_locked_down_stay_locked_down():
    """These were unauthenticated in production and are easy to regress —
    /roster/analyze in particular wrote temp files it never cleaned up."""
    by_path = {r.path: r for r in api_routes()}
    for path in ("/roster/analyze", "/fantrax/leagues", "/sleeper/leagues"):
        assert auth_kind(by_path[path]) == "user", f"{path} is unauthenticated again"


def test_league_scoped_routes_check_ownership():
    """Auth alone isn't enough — a signed-in stranger must not be able to act on
    someone else's league by passing its id. Every route that takes a league_id
    must call require_league_owner."""
    offenders = []
    for route in api_routes():
        params = inspect.signature(route.endpoint).parameters
        takes_league = "league_id" in params or any(
            "league_id" in getattr(p.annotation, "model_fields", {}) for p in params.values()
        )
        if not takes_league:
            continue
        src = inspect.getsource(route.endpoint)
        if "require_league_owner" not in src:
            offenders.append(route.path)
    assert not offenders, f"league-scoped routes missing require_league_owner: {offenders}"
