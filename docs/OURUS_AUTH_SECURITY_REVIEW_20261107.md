# ListenAlong authentication security review — 2026-11-07

Status: **not production-security approved**. Reviewed repository `auth.py` and its new offline tests.

## Findings
1. **High — fallback signing secret.** `secret()` uses a static `listenalong-dev-secret` when `APP_SECRET` is absent. On an internet-exposed deployment this makes authentication cookies forgeable by anyone aware of the source. Require a strong unique `APP_SECRET` for hosted deployments; test missing/weak secrets and fail closed before release.
2. **High — hosted password configuration.** `required()` forces authentication when `RENDER` is set, but a missing `APP_PASSWORD` prevents legitimate sign-in. Validate required secrets at startup, without logging their values.
3. **Medium — long-lived session (partially remediated).** Signed cookie remains valid for up to 90 days, but now embeds a signed issue timestamp and enforces that lifetime server-side. Existing static `ok` cookies are intentionally invalidated, requiring users to sign in again. Server-side revocation, per-device sessions and shorter default lifetimes remain open.
4. **Medium — process-local login throttling (partially remediated).** `_login_hits` is now bounded to 4,096 IP entries and evicts expired or least-recently-used entries. Multiple workers/instances still bypass shared limits, so deploy a shared reverse-proxy or datastore-backed rate limiter before public exposure.
5. **Medium — proxy HTTPS detection.** Cookie `secure` is based on `RENDER`, not a general verified production HTTPS configuration. Document supported deployments and ensure secure cookies.
6. **Needs review — unauthenticated endpoints.** `/api/me`, `/healthz`, static assets and OPTIONS bypass the gate by design; confirm no sensitive data is returned.

## Safe remediation order
First add tests for missing signing secret and password on hosted deployments; then implement fail-closed configuration, test cookie issuance and restart behaviour, and only after that consider session and rate-limit redesign. **Do not merge a configuration-breaking change into production without staging verification and founder approval.**

This audit is based on source inspection and offline tests only; no live penetration test or deployment was performed.

## Development-branch remediation (2026-11-07)
- `auth.sign("ok")` now signs `v1:<issued_unix_seconds>`; `valid_token` rejects legacy static cookies, expired tokens, future-dated tokens outside 60 seconds, and malformed timestamps.
- Tests cover expiry boundary, future skew, malformed values, signature tampering and legacy token rejection.
- **Compatibility:** all sessions issued by previous versions require a fresh login after deployment. No deployment has been performed.
- **Release blocker:** validate proxy/cookie configuration and external session revocation requirements before production approval.

- The process-local login throttle now caps tracked IPs at 4,096; regression tests cover the 12-attempt threshold, eviction and expiry. Distributed rate limiting remains a release gate.
