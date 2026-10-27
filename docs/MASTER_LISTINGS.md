# Master listing editor — 0.0.35-beta1

Select **Listings** in the Shop Sync navigation to open its own page inside the app. **Dashboard**, **Listings** and **Order imports** have separate pages with links between them. Enter the title, description, photos, tags, price, stock and SKU once. Add size/colour options to generate editable variation rows. Select the destinations; optional adjustments change a shop's title, description, tags or price without changing the master.

Set usual categories, policies, shipping profiles, processing profiles and Shopify channel under **Shop defaults**. These are reused by later listings. Individual listings may override them. Load shop choices instead of typing account IDs when the API provides those choices. eBay currently takes a category ID; **Load required product details** loads the category's aspects. TikTok settings use a browser category path and brand name rather than API category and warehouse identifiers. Its live browser form integration is still pending.

**Save draft** is local only. **Check shops** checks the shared data and required shop settings. **Publish to all** sends the saved listing to selected shops. Once remote IDs are known the button becomes **Update all**. Saving changes never automatically sends them. Each destination has its own durable result and mapping. Unchanged successful destinations are skipped on retry. Returned validation errors can be corrected and retried; an ambiguous network outcome requires checking the shop and linking the existing listing ID. Listing revisions are preserved when editing during an outstanding publish.

## Installation and live acceptance

This is source code for the Home Assistant add-on, not an already installed release. Merge/release and update the add-on through the existing deployment process. Back up persistent `/config` before acceptance testing. Existing catalogue, credentials and order tables are unchanged. New persistent files: `listings.db` and `listing-photos/`.

Etsy image uploads require the publisher OAuth service's `/api/etsy/api/request` handler to accept the bounded `image` payload and advertise `features.etsy_listing_images: true` from `/health`. The reference implementation and tests are included in `oauth_broker/app.py`. The lister checks this capability before creating an Etsy listing. The currently hosted Cloudflare Worker needs the equivalent update before Etsy publishing is enabled for sellers. Do not replace its existing OAuth routes with this reference service. The new payload carries base64 JPEG/PNG plus `content_type`; the broker forwards multipart `image` to Etsy. Account tokens and publisher secrets stay out of the editor, and refreshed seller credentials are persisted for subsequent uploads.

The Shopify connection needs product/inventory scopes already used by Shop Sync, plus file access for photo uploads and publication access for the selected sales channel. Validate the app's granted scopes, update its configured scopes and reconnect if necessary. TikTok must publish through its signed-in Seller Center browser: the API-based listing path is disabled and there is no API fallback. The browser publisher still needs to be implemented and verified against the live product form before release. eBay requires Inventory API write permission, business policies and a merchant location. These permissions have not been expanded automatically.

Before production release, use dedicated test products and seller approval to verify a create, photo upload, two-variant create, title/price/photo update, failed-shop retry and pending-review outcome in each connected shop. Automated tests use fake API responses; they do not prove live seller permissions or approval. No live product was created by this development run.

## Current boundaries

- eBay master listing publication is production-only; sandbox tokens are rejected before writes.
- Etsy supports up to two variation options here. Three-option masters are blocked for Etsy rather than losing variants; automatic multi-listing splitting is not implemented by this editor.
- Removing published eBay variation SKUs is blocked until they are reviewed/ended in eBay. Adding variations is supported and publishes the new offers.
- TikTok submissions are shown as pending review, not live. Review webhooks and automatic final approval tracking are not included.
- Certificate/size-chart uploads, digital downloads, listing video, per-variant photo selection and automatic stock synchronization are outside this version. Categories that require unsupported assets need Seller Center setup before submission.
- Etsy/Shopify shop currencies must match the master; this editor does not convert money.
- An ambiguous create with no returned remote ID needs seller reconciliation; it is never blindly repeated.

## Verification

Run `python -m pytest marketplace_bridge/app/tests -q` with `PYTHONPATH=marketplace_bridge`, and `python -m compileall -q marketplace_bridge/app oauth_broker`. New GraphQL operations were checked against Shopify Admin API `2026-07`. Browser QA covers entry, save/reload, variation generation, shop validation and reusable settings on an isolated localhost preview. Production acceptance and Home Assistant installation remain separate.
