# Known Bugs & Proposed Fixes

Working list of diagnosed-but-not-yet-fixed bugs. Each entry: symptoms, diagnosis,
proposed fix, and how to verify. Remove entries when the fix ships (the PR is the
record). Roadmap features live in CLAUDE.md — this file is only for defects.

---

## Daily digest is killed by a Railway redeploy during its run window

**Symptoms:** Some mornings no digest email arrives even though the GitHub Actions
`Daily Digest` run shows `success`. (Observed 2026-07-22.)

**Diagnosis:** The `/cron/daily-digest` endpoint responds immediately and runs the
real pipeline (warm widgets → per-league billed lead AI call → email) as a
FastAPI background task that takes minutes. Railway tears down the running
container on every deploy, which kills any in-flight background task. On
2026-07-22 the cron fired at 17:00:48 UTC (GitHub cron slipped ~77 min from the
15:43 schedule) and a merge to main at 17:01:10 UTC triggered a redeploy ~22s
into the job — before any email was sent. The workflow still reports success
because the curl got its instant 200; the failure is invisible to GitHub. The
digest's own `app_events` (kind `digest`) row is also never written, since the
container died before the final `_log_event`.

**Proposed fix (pick one):**
- *Cheap/operational:* don't merge to main during the digest window (~8:45–10:15am
  PDT, wide because GitHub cron slips badly). No code change.
- *Real hardening:* make the job survive a restart — persist per-owner send state
  (e.g. a `digest_sends` row keyed by date+owner) and have the job skip owners
  already sent, so a re-fire after the redeploy completes the run idempotently.
  Then a post-deploy re-trigger (manual or a short retry) finishes what was
  dropped without double-emailing or double-billing.

**Verify:** trigger `gh workflow run daily-digest.yml` outside a deploy window and
confirm the email arrives + an `app_events` kind=`digest` row with
`results: {..: "sent"}` is written.
