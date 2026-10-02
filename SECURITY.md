# Security policy

## Reporting a vulnerability

Please **don't open a public issue** for security problems. Use GitHub's private reporting:
**Security → Report a vulnerability** on this repository
(https://github.com/RetnuhFeel/Stock-Predictor/security/advisories/new).

Include what you found, how to reproduce it, and the impact. This is a hobby project maintained on a best-effort basis, so there is no guaranteed response time, but reports are taken seriously and I'll credit you if you wish.

## Scope

In scope: the FastAPI backend (`backend/`), the Next.js app and service worker (`web/`), and the deployment configuration in this repo.
Out of scope: the legacy iOS app, third-party data providers (Yahoo Finance, Twelve Data), and Render's platform.

## Design notes relevant to security

- No accounts, cookies or stored personal data; watchlist and price alerts live in the browser's `localStorage`.
- Secrets (`ADMIN_TOKEN`, `LOG_TASK_TOKEN`, `DATABASE_URL`, `TWELVEDATA_API_KEY`, `SENTRY_DSN`) are environment variables only. Never commit them. `ADMIN_TOKEN` and `LOG_TASK_TOKEN` must be at least 16 characters; shorter values are ignored (the endpoint stays disabled) and a warning is logged at startup.
- The rate limiter trusts `X-Forwarded-For` only when `TRUST_PROXY=true`, counting `TRUSTED_PROXY_HOPS` entries from the right (Render: `true` and `1`). A wrong value either shares one bucket or lets clients bypass the limit; see docs/REFERENCE.md.
- The underscore routes are hidden from `/openapi.json`, but that is not a security control; they are protected by their token or flag.
- `/api/_stats` is disabled unless `ADMIN_TOKEN` is set; `/api/_client-error` is disabled unless `CLIENT_ERROR_LOGGING=true`.
- Public endpoints are rate limited; logs omit IP addresses, user agents and query strings.

## Supported versions

Only the latest `master` is supported.
