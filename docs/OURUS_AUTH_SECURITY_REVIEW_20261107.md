# ListenAlong authentication security review — 2026-11-07

Status: **not production-security approved**. Reviewed repository `auth.py` and its new offline tests.

## Findings
1. **High — fallback signing secret.** `secret()` uses a static `listenalong-dev-secret` when `APP_SECRET` is absent. On an internet-exposed deployment this makes authentication cookies forgeable by anyone aware of the source. Require a strong unique `APP_SECRET` for hosted deployments; test missing/weak secrets and fail closed before release.
2. **High — hosted password configuration.** `required()` forces authentication when `RENDER` is set, but a missing `APP_PASSWORD` prevents legitimate sign-in. Validate required secrets at startup, without logging their values.
3. **Medium — long-lived session.** Signed cookie is valid for up to 90 days and has no embedded issue time or server-side revocation state. Review shorter expiry, rotation and invalidation semantics.
4. **Medium — process-local login throttling.** `_login_hits` is a process-local dictionary. Multiple workers/instances may bypass shared limits and stale keys may accumulate. Use an appropriately bounded, shared rate-limit strategy if exposed publicly.
5. **Medium — proxy HTTPS detection.** Cookie `secure` is based on `RENDER`, not a general verified production HTTPS configuration. Document supported deployments and ensure secure cookies.
6. **Needs review — unauthenticated endpoints.** `/api/me`, `/healthz`, static assets and OPTIONS bypass the gate by design; confirm no sensitive data is returned.

## Safe remediation order
First add tests for missing signing secret and password on hosted deployments; then implement fail-closed configuration, test cookie issuance and restart behaviour, and only after that consider session and rate-limit redesign. **Do not merge a configuration-breaking change into production without staging verification and founder approval.**

This audit is based on source inspection and offline tests only; no live penetration test or deployment was performed.
