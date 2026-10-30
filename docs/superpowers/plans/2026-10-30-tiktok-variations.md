# TikTok variation transfer implementation plan

> **For agentic workers:** Use superpowers:executing-plans task by task. User already requested autonomous continuation without design questions.

**Goal:** Transfer complete variation listings through the existing signed-in TikTok browser without re-entering details.
**Architecture:** Extend the validated immutable transfer plan with ordered axes and SKU rows. Build options using observed Seller Center controls, map generated rows by their displayed option combinations, then verify every price, stock and SKU. Existing single-SKU behavior and unsaved-only result remain intact.
**Tech Stack:** Python/FastAPI/Selenium, existing SQLite state and HTML editor.
**Spec:** docs/superpowers/specs/2026-10-27-master-listings.md

## Global constraints
- Browser only for TikTok; no private endpoints or API fallback.
- Preserve source text, photos, SKU, prices, stock and variations. No guessed product facts or dimensions.
- Automatic order imports must remain ON at the user's request. Do not interrupt active scans.
- No marketplace Save draft or Submit in live tests. Approval to publish actual products is separate from implementation.
- Existing unfinished forms remain protected. Preserve the verified Teacher-board test tab.

## Review focus
- Sparse combinations must not create unrequested SKUs: reject before browser changes.
- Duplicate option labels after trimming/case folding must fail before writes.
- Generated row order can differ from master order: match combinations, never row index alone.
- React rerenders cannot result in mixed SKU values: reacquire controls, verify combination before each row.
- Browser cancellation must retain the shared order lock until the worker stops.

### Task 1: Bounded variation planning
Files: app/tiktok_listing_form.py, app/tests/test_tiktok_listing_form.py.
Produces prepare_plan with axes [{name,values}] and rows [{values,sku,stock,price}], retaining single-SKU fields for old path.
- [ ] Add failing tests for complete 2x2 and one-axis single-row plans, sparse/duplicate/overlong options, >3 axes, >100 SKU rows, invalid per-row money/stock/SKU, immutable source.
- [ ] Run focused tests and observe failure.
- [ ] Implement normalized axes, validate all rows, reject incomplete Cartesian product and ambiguous labels; cap this adapter at100 rows explicitly.
- [ ] Run focused suite and commit.

### Task 2: Observed browser variation controls
Files: app/tiktok_listing_form.py (or focused app/tiktok_listing_variations.py if mapping is substantial), tests/test_tiktok_listing_form.py, tests/fixtures.
Consumes Task1 plan; produces form.variations(plan), form.verify_variations(plan).
- [ ] Finish visible UI/DOM observation of names, values, add controls and generated row keys. Record selectors in docs/TIKTOK_LISTING_BROWSER.md.
- [ ] Add failing tests that unordered generated rows match by exact option tuple; missing/extra/duplicate rows or changed labels block, no save/submit exists.
- [ ] Implement only observed controls, bounded DOM reads and native input events. Preserve single-SKU flow and occupied guard.
- [ ] Verify tests, rendered fixture and an unsaved two-variant test. Commit.

### Task 3: UI, review and installation
Files: app/listing editor HTML, docs/MASTER_LISTINGS.md, docs/TIKTOK_LISTING_BROWSER.md, version files.
- [ ] Update copy to describe supported variations and retain unsaved review requirements; correct stale live acceptance status.
- [ ] Full Python suite, JS syntax and diff checks. One whole-branch review and fix material findings.
- [ ] PR/CI/merge/install under existing authorization; preserve any newer main changes.
- [ ] Live unsaved variation transfer and exact verification, no final actions; keep order imports enabled. Save proof and ledger result.

## Subsequent subsystem
Implement TikTok submission only after observing required compliance and product result controls. Missing packed weight/manufacturer facts cannot be invented. Etsy hosted image transport and Shopify/eBay permission acceptance remain separate work; do not report full four-market readiness.
