# Master Listings Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** One Shop Sync listing and photo upload for all four marketplaces, with manual Update all.
**Architecture:** Add a local listing store, publish coordinator, destination adapters and Ingress-protected editor to the current FastAPI app.
**Tech Stack:** Python, FastAPI, SQLite, httpx, vanilla HTML/JS.
**Spec:** ../specs/2026-10-27-master-listings.md

## Global Constraints
Save draft never writes to a marketplace. Keep production shops untouched during verification. Do not silently truncate text, discard images, flatten variations or substitute stock quantities.

## Review Focus
Ambiguous create failures; simultaneous publish clicks; edits during a running publish; photo path traversal and oversized uploads; shop-specific validation and limits.

### Task 1: Durable local master catalogue
- [ ] Add tests for revisioned save, destination overrides, mappings and failed/uncertain jobs.
- [ ] Run the tests and observe missing-module failure.
- [ ] Implement listing_store.py and listings.py; validate input and preserve snapshots.
- [ ] Run persistence/coordinator tests, including no writes on save and retrying only unfinished destinations.

### Task 2: Destination adapters
- [ ] Test exact title/description/variants/media payloads and returned remote IDs with fake HTTP transports.
- [ ] Implement listing_publishers.py using official APIs and existing credentials.
- [ ] Validate Shopify GraphQL against configured 2026-07 schema and run adapter tests.

### Task 3: Listing editor and release package
- [ ] Test Ingress/CSRF enforcement, upload size/type/path checks, save and publish routes.
- [ ] Implement listing_web.py and listing_editor.html, mount in main_v8.py.
- [ ] Run focused tests then existing suite, inspect UI where available, review and fix findings.
- [ ] Package source and include deployment/acceptance instructions and limitations.
