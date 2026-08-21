# Reverse Sync: Shopify → Etsy / eBay

Shop Sync 0.0.31 adds a reverse-sync workflow with Shopify as the catalogue master.

## How it works

1. Connect and import Shopify, Etsy and/or eBay.
2. Open **Reverse Sync — Shopify → Etsy / eBay**.
3. Save the destination marketplace defaults once.
4. Select **Etsy** or **eBay** beside a Shopify product.
5. Shop Sync builds a destination-specific plan instead of blindly copying Shopify data.
6. Before writing anything, Shop Sync checks imported destination listings for an existing match.
7. If a likely match exists, choose whether to update the existing listing or create a new listing.

## Existing-listing detection

Shop Sync uses multiple signals, with confirmed mappings and SKUs carrying the most weight:

- a previously confirmed Shop Sync Shopify → marketplace mapping;
- matching product/variant SKUs;
- exact normalised title;
- matching image URL or image filename as supporting evidence.

A match never causes an automatic overwrite. The user must choose **Update existing** or **Create new**.

Once an export/update is confirmed, Shop Sync stores the Shopify → destination mapping so later updates can identify the same listing more reliably.

## Quantities

Shopify quantities are carried per variant. For eBay, each SKU/variation receives its Shopify quantity. For Etsy, quantities are preserved for each generated Etsy product/variation. When Etsy splitting is required, each split listing receives only the variants and quantities that belong to that split.

## Variations

### eBay

Shop Sync keeps the Shopify variation structure and maps Shopify option names/values to eBay variation specifics/aspects.

### Etsy

Etsy supports at most two variation properties. If a Shopify product has more than two option groups, Shop Sync keeps the first two as Etsy variations and automatically splits the remaining option combinations into separate Etsy drafts.

Example Shopify product:

- Size
- Colour
- Application

can become:

- Etsy draft: Application = Window Internal Fit, with Size × Colour variations
- Etsy draft: Application = Body External Fit, with Size × Colour variations

This prevents quantities, SKUs or combinations from being silently discarded.

## Marketplace defaults

Shopify does not contain all marketplace-specific information. Reverse Sync therefore stores destination defaults separately.

Etsy requires values such as taxonomy/category, shipping profile and readiness/processing state. eBay requires values such as category, merchant location and seller payment/returns/fulfilment policies.

These defaults do not modify the Shopify product. Destination-specific listing data is generated only for the Etsy/eBay version.

## Safety

- Shopify remains unchanged by reverse-sync destination edits.
- Existing marketplace listings are not overwritten without confirmation.
- Etsy listings with unsupported option counts are split rather than flattened.
- New eBay exports are created as unpublished Inventory API offers; publishing remains a separate action.
- Etsy exports are created/updated as drafts through the connected Etsy account.

## OAuth broker requirement for Etsy writes

Shopify → Etsy reverse sync requires the current Cloudflare Worker with `/api/etsy/api/request`. This keeps the publisher Etsy API secret on the broker while allowing the user's OAuth token to create/update their Etsy drafts.
