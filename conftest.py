"""Repo-root conftest: its presence puts the repo root on sys.path so tests can
`import engine.*` without packaging. Keep even if empty.

Also stubs the two env vars `engine.auth` / `engine.supabase_client` read at
*import* time, so a test may `import api.main` without a live Supabase config
(CI's pytest step sets no env). `setdefault`, so a real local .env still wins.
Nothing here authenticates — the values are never used unless a test actually
calls out, which none do.
"""
import os

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "dummy-service-key")
