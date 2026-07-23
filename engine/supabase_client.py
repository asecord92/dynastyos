import os
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

_client: Client | None = None


def get_supabase() -> Client:
    global _client
    if _client is None:
        if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        _client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    return _client


def reset_supabase() -> None:
    """Drop the cached client so the next get_supabase() builds a fresh one.

    The client holds a single pooled HTTP/2 connection; under concurrent load
    Supabase can send a GOAWAY (surfaced as ConnectionTerminated), which poisons
    that connection — every subsequent call on the same client fails until it's
    rebuilt. Callers reset after a connection-level error so a retry gets a new
    connection instead of hammering the dead one."""
    global _client
    _client = None
