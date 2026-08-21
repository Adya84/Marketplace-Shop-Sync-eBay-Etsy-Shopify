# Shop Sync Changelog

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
