## What and why

## Checklist
- [ ] `cd backend && ruff check . && pytest -q`
- [ ] `cd web && npm run lint && npm run typecheck && npm run build`
- [ ] UI changes: checked keyboard use and light/dark; ran `web/e2e` smoke if relevant
- [ ] No secrets, personal data or tracking added; privacy page updated if data handling changed
- [ ] Disclaimers, error codes/freshness fields and the plain-language backtest are intact
- [ ] Docs updated (README / docs/) if behaviour or env vars changed

> This project is educational and not financial advice. Please don't add features that present forecasts as recommendations.
