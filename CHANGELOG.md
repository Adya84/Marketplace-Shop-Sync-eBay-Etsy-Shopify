# Shop Sync Changelog

## 0.0.30

- Added publisher-managed Shopify OAuth so normal users no longer need to create a Shopify app or enter Client ID/client-secret values into Shop Sync.
- Added Shopify authorization through the hosted Shop Sync OAuth broker using the permanent `.myshopify.com` store domain supplied by the user.
- Added Shopify callback HMAC verification on the hosted broker before issuing the signed Shop Sync authorization result.
- Added hosted Shopify authorization-code exchange using the publisher Shopify app credentials stored only on Cloudflare.
- Shop Sync now stores the authorised Shopify store access token locally and uses it for Shopify catalogue imports and draft creation.
- Preserved compatibility with Shopify credentials created by earlier Shop Sync versions.
- Removed Shopify Client ID/client-secret fields from the normal Shop Sync UI and replaced them with **Connect Shopify** plus the authorization-result flow used by eBay/Etsy.
- Switched the add-on runtime to `main_v5` and bumped the Home Assistant app version to `0.0.30`.
- Updated the root README, installation guides, troubleshooting and OAuth broker documentation for the shared eBay + Etsy + Shopify hosted OAuth architecture.

## 0.0.29

- Added publisher-managed Etsy OAuth so normal users no longer need an Etsy developer app, keystring or shared secret.
- Added Etsy PKCE (`S256`) authorization through the hosted Shop Sync OAuth broker.
- Added hosted Etsy callback, authorization-code exchange and automatic refresh-token handling.
- Added a broker-issued Etsy API credential so Etsy Open API reads can be proxied without exposing the publisher shared secret to Home Assistant users.
- Added automatic discovery of the authorised Etsy Shop ID after connection.
- Preserved compatibility with Etsy credentials created by earlier Shop Sync versions.
- Removed Etsy keystring/shared-secret fields from the normal Shop Sync UI.
- Switched the add-on runtime to `main_v4` and bumped the Home Assistant app version to `0.0.29`.
- Updated the root README and OAuth broker README for the shared eBay + Etsy hosted OAuth architecture.

## 0.0.28

- Added a LIVE Activity panel with current job/product message, progress, percentage, running/queued counts and last update time.
- LIVE Activity now refreshes every 2 seconds.
- Activity history now exposes up to 5,000 recent jobs and displays 25 jobs per page with pagination.
- Bulk Shopify transfers now have a parent progress job showing current item number, completed count, failed count and remaining count.
- Individual failed products stay visible in Activity and no longer make a large bulk transfer look frozen.
- Updated the Home Assistant app entry point, version number, README and troubleshooting/development instructions.

## 0.0.27

- Added retry handling for Shopify's temporary `Non-ready media cannot be attached to variants` response while newly uploaded images finish processing.
- Other Shopify media errors remain fatal and visible in Activity.

## 0.0.26

- Added 50-item catalogue pagination, search and marketplace filtering.
- Added SKU, variant count and stock display to the Ready to send catalogue.
- Improved eBay available-stock extraction.
- Fixed eBay-to-Shopify inventory writing and added Shopify read-back verification.

## 0.0.25

- Added publisher-managed eBay OAuth so normal users do not need an eBay Developer account or application credentials.
- Added automatic skipping of removed/unavailable eBay listings during catalogue import.
