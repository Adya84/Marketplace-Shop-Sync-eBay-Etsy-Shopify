# TikTok orders implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend Shop Sync with persistent TikTok browser login, custom Shopify order imports and tracking return.
**Architecture:** One browser worker and SQLite order ledger; use existing Shopify credentials. Home Assistant Ingress protects the browser and order UI. Automatic writes start disabled.
**Tech stack:** Python/FastAPI, SQLite, Selenium/Chromium, noVNC, Shopify GraphQL 2026-07.
**Spec:** ../specs/2026-10-23-tiktok-orders.md

## Global constraints
- No TikTok API credentials; operate visible UK Seller Centre pages.
- Do not buy labels, change catalogue products or charge customers.
- Never retry uncertain order creation without reconciliation.
- Browser/profile access only through authenticated Home Assistant Ingress.
- Preserve existing catalogue functionality; new feature is experimental until HA/live checks pass.

## Review focus
- Address masking and incomplete/missing postcodes stop the affected import.
- Native connector imports and concurrent scans cannot create a second order.
- Network failure after creation cannot cause a retry to duplicate it.
- Existing conflicting tracking, cancellations and split shipments need review.
- Login/CAPTCHA/page changes pause browser actions and surface the problem.

### Task 1: Order validation and durable ledger
Files: app/order_models.py, app/order_store.py, tests/test_orders.py.
Interfaces: SourceOrder validates an order; OrderStore.claim(shop,id), save/get/list and settings persist progress.
- [ ] Add tests for invalid/masked addresses, money totals, non-shippable statuses and durable unique claims.
- [ ] Run pytest; observe missing modules fail.
- [ ] Implement validation, encrypted payloads and atomic unique claims.
- [ ] Run tests and record results.

### Task 2: Shopify import and reconciliation
Files: app/order_shopify.py, app/order_sync.py, tests/test_order_sync.py.
Interfaces: OrderShopify.find(order_id), create(SourceOrder), tracking(shopify_id); OrderSync.import_order and sync_tracking.
- [ ] Test native-order tag detection, duplicates, ambiguous writes, errors and tracking conflicts.
- [ ] Implement custom physical line-item orders using source totals, suppressed receipts and no inventory claim.
- [ ] Test cancellation, multi-parcel and carrier review paths.
- [ ] Validate every new GraphQL operation against Shopify 2026-07 and run tests.

### Task 3: Browser adapter
Files: app/tiktok_browser.py, tests/test_tiktok_browser.py.
Interfaces: scan() returns SourceOrder values; submit_tracking(source_id,carrier,number) verifies saved tracking.
- [ ] Test synthetic DOM snapshots for UK detail parsing, ambiguous/masked data and page changes.
- [ ] Add persistent headed Chromium with one lock; no hidden TikTok endpoints.
- [ ] Traverse all order pages, validate shop identity and use exact order detail URLs.
- [ ] Read current tracking before submitting; review uncertain writes rather than resubmitting.

### Task 4: Home Assistant UI and packaging
Files: app/main_v8.py, app/order_routes.py, run.sh, Dockerfile, config.yaml, requirements.txt.
- [ ] Test ingress authentication, path traversal rejection and disabled-write defaults.
- [ ] Add noVNC HTTP/WebSocket proxy and a protected Orders page with dry-run, start/pause, review queue and browser login.
- [ ] Add lifecycle polling every five minutes, shutdown cleanup and persistent private profile.
- [ ] Keep unsupported browser hosts explicitly unavailable, with existing catalogue service usable.

### Task 5: Review and delivery
- [ ] Run existing/new Python tests, compile modules and check dependency/package metadata.
- [ ] Run independent whole-branch review and fix material issues.
- [ ] Package a reviewable update and instructions; do not claim HA installation or live verification without evidence.
- [ ] Request required new Shopify order/fulfilment permissions at connection time, not in an unreviewed deployment.
