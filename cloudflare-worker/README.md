# CT Atlas Report Worker — usage analytics upgrade

This folder contains the upgraded Cloudflare Worker used by CT Atlas.

## What this version adds

- All CT Atlas accounts are recognised by the Worker.
- Report Generator activity is linked to the authenticated username rather than a browser UUID.
- Non-admin accounts are limited to one accepted Report Generator request every 20 minutes.
- `admin` is exempt from the 20-minute per-user interval.
- The existing global concurrency safeguard (maximum four active reports) is preserved.
- The existing global daily safety ceiling (100 accepted report requests/day) is preserved.
- Usage counters are stored in the existing `REPORT_GATE` Durable Object:
  - logins
  - searches
  - map searches
  - event-list searches
  - report requests
  - actual AI reports generated
  - cached reports served
  - blocked report requests
  - last activity
- Admin statistics support Today / 7 days / 30 days / All time.
- Search terms themselves are not stored.
- Admin statistics require an authenticated admin session.

## Files

- `index.js` — Worker HTTP entry point
- `shared.js` — report generation, authentication and common helpers
- `report-gate.js` — Durable Object, sessions, cooldown and usage accounting

## Deploy to the existing Worker

Deploy these three files to the existing `ct-report-generator` Worker, with `index.js` as the entry module.

Preserve the existing Worker bindings and variables, especially:

- Durable Object binding: `REPORT_GATE`
- `EVENTS_URL`
- `GEMINI_API_KEY`
- `GEMINI_MODEL` if configured
- `ALLOWED_ORIGIN` if configured
- `ADMIN_LOG_KEY` if still used for the legacy `/login-stats` endpoint

Do not create a new Durable Object namespace if the existing Worker already has the `REPORT_GATE` binding; keeping the existing binding preserves its stored data and cache.

## Important

GitHub Pages deployment does not deploy Cloudflare Workers. The Worker files in this folder must therefore be deployed separately to the existing Cloudflare Worker before server-side 20-minute enforcement and the Admin Usage dashboard become authoritative.
