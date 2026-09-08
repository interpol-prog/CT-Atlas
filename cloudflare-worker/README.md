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

- `deep-search.js` — multilingual search planning, retrieval and reports
- `index.js` — Worker HTTP entry point
- `shared.js` — report generation, authentication and common helpers
- `report-gate.js` — Durable Object, sessions, cooldown and usage accounting

## Deploy to the existing Worker

Deploy these four files to the existing `ct-report-generator` Worker, with `index.js` as the entry module.

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

## Deep Search recall fix and release verification

The v5 search planner supplies two initial queries plus a short scope-preserving
rescue query in each of 12 languages. Languages with fewer than three distinct
result URLs, including English, receive the broad rescue (at most 36 news
requests). Provider HTML failures are reported separately from empty RSS feeds.
The cache version changes so old reports are not reused.

Validation: `node --test tests/deep-search-recall.test.cjs` (mocked retrieval).
These tests do not establish live Google News recall or model plan quality.

Deploy the four Worker modules together to the existing `ct-report-generator`
Worker, preserving all existing bindings and secrets. Publishing GitHub Pages
alone does not release this fix. After deployment, GET `/health` must return
`deep_search_version: "deep-search-v5-broad-query-rescue"`. Then repeat the
original Afghanistan question in an authenticated session and inspect language
coverage and actual queries. No live source-count increase has been verified yet.
