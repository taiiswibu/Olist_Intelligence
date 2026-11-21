# Project workflow

- This is the Olist Intelligence local application for Vo Van Tai. Communicate in Vietnamese.
- Frontend is buildless HTML/CSS/JavaScript under frontend/. Backend is FastAPI under olist/.
- Default runtime: Python 3.12, http://127.0.0.1:8000/. Users do not need Node to run the app.
- Keep data, credentials, models, caches and .env out of Git. Never print API keys or APP_TOKEN.
- Never replace missing Olist source data with synthetic application data. Synthetic fixtures belong only in tests.
- Preserve KPI grain and calendar-day late-delivery semantics. BI numbers must come from parameterized tools.
- ERP writes require the explicit proposal/approval flow. Do not call Odoo confirmation/invoice operations.
- The delivery model is experimental; retain honest holdout limitations. Do not tune on the exposed holdout.
- Before committing: inspect the diff and run checks appropriate to changed behavior. After a validated milestone, create a descriptive commit and push to the connected repository when available. Do not force-push or discard user work.
- User authorized ongoing commits for requested project work. This does not authorize background work while no task is active.
- Check current remote HEAD before modifying GitHub. Report remote commit/CI success only from verified results.
- If GitHub is not connected, retain local history and a durable delivery; do not claim that the repository exists.
- Useful checks: python -m pytest -q; node --check frontend/assets/app.js; python scripts/verify_release.py after data setup; git diff --check.
- Browser QA in the managed environment uses the provided sites-preview CLI and the supported browser tools. No need to publish a hosted Site for this local application.
