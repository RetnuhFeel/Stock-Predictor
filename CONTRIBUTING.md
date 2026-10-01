# Contributing

Thanks for your interest! This is a small educational project; issues and pull requests are welcome.

> ⚠️ The app is educational and **not financial advice**. Contributions must keep the disclaimers, the plain-language backtest and the honest baseline comparison intact, and must not present forecasts as recommendations.

## Setup

```bash
# backend (Python 3.12+)
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
ruff check . && pytest -q          # tests use synthetic data; no network needed
uvicorn app.main:app --reload --port 8000

# web (Node 20.9+)
cd web && cp .env.example .env.local && npm ci
npm run dev
npm run lint && npm run typecheck && npm run build
```

## Browser checks

`web/e2e/smoke.mjs` runs offline against a mocked API (this is what CI runs; it includes axe-core accessibility checks):

```bash
cd web && NEXT_PUBLIC_API_BASE_URL=http://api.test npm run build && npx next start -p 3000 &
cd web/e2e && npm ci && node smoke.mjs      # needs Chrome/Chromium; set CHROME=/path/to/chrome if needed
```

`web/e2e/run.mjs` is a fuller check against a real backend and live data; `web/e2e/screenshots.mjs` regenerates `docs/img`.

## Guidelines

- One focused change per PR; describe what and why. Add or update tests (pytest for the backend, the smoke script for UI).
- Backend: ruff clean (line length 120). Keep the error shape `{"error": {code, message, retryable, retry_after}}` and the freshness fields stable; add new codes rather than renaming.
- Web: no new tracking, cookies or third-party calls without discussion; keep UI accessible (keyboard, labels, contrast, not colour alone).
- Don't touch the legacy iOS app in web/backend PRs.
- Never commit secrets or real API keys.

## Reporting issues

Use the issue templates. For security problems see [SECURITY.md](SECURITY.md).
