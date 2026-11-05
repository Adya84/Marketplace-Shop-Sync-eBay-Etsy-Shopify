# Etsy Order Imports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Import Etsy paid unshipped physical orders into Shopify through Shop Sync.
**Architecture:** Separate Etsy order database and scheduler; reuse validated Shopify creation and reconciliation with explicit marketplace tags.
**Tech Stack:** Existing FastAPI, SQLite, Etsy Open API and Shopify GraphQL.
**Spec:** ../specs/2026-11-05-etsy-order-import-design.md

## Global Constraints
- Preserve TikTok identities and operation.
- No payment collection, buyer notifications or automatic postage purchases.
- Fail closed on missing addresses, weights, unsupported money or refunds.

## Review Focus
- Source identities cannot collide across marketplaces.
- Rotated Etsy credentials must persist after failed calls too.
- Preview must not create Shopify orders.
- Pagination and stale payment/shipping state must be checked.
- Unknown response after creation must reconcile before retry.

### Task 1: Source adapter and Shopify identity
- [ ] Write failing parser, pagination and marketplace tag tests.
- [ ] Implement Etsy receipt conversion and paginated paid/unshipped reads.
- [ ] Generalize source identity and Shopify tags, preserving TikTok defaults.
- [ ] Run focused tests.

### Task 2: Separate Etsy workspace
- [ ] Add independent settings, preview/import routes, encrypted records and scheduler.
- [ ] Add visible save status, completion counts, countdown and review rows.
- [ ] Verify route protection, preview gating and retained deduplication.

### Task 3: Connection and release
- [ ] Add transactions_r to OAuth requests and document reconnect/address acceptance.
- [ ] Run full suite and container checks; independent review before merge.
- [ ] Publish version, then verify live connection/preview/import when permissions are approved.
