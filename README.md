# Shop Sync

Shop Sync is a Home Assistant OS add-on that imports complete eBay UK listings into Shopify. Shopify becomes the catalogue and inventory master after a listing is linked.

## Current MVP

- Reads active eBay listings created through either eBay's website or APIs.
- Imports titles, HTML descriptions, all listing and variation images, item specifics, categories, SKUs, prices, variants, and available quantities.
- Creates Shopify products as drafts using a stable external identifier, avoiding duplicate products on retry.
- Creates tracked Shopify inventory at the store's first location.
- Stores source-to-destination mappings, job progress, and encrypted API credentials in persistent add-on storage.
- Provides a responsive Home Assistant Ingress dashboard.

## Installation during development

1. Publish this directory to a GitHub repository.
2. In Home Assistant, open **Settings â†’ Add-ons â†’ Add-on Store â†’ â‹® â†’ Repositories**.
3. Add the repository URL and install **Shop Sync**.
4. Start the add-on and enable **Show in sidebar**.
5. Enter an eBay production user token and a Shopify Admin API token in the add-on dashboard.

## Required Shopify access

The custom app needs access to read/write products, product listings, files, inventory, locations, and fulfilment/order data when order sync is enabled.

## Development

```bash
cd marketplace_bridge
python -m pip install -r requirements.txt pytest
BRIDGE_DATA_DIR=./data python -m uvicorn app.main:app --reload --port 8099
pytest app/tests
```

## Roadmap

- Guided eBay OAuth authorization instead of manual token entry.
- Shopify OAuth for multi-merchant onboarding.
- Preview and field-validation screen before export.
- Shopify-to-eBay stock reconciliation and eBay order ingestion.
- Bulk draft creation, rate limiting, retries, and webhook processing.
- Etsy connector and any-to-any transfers through the normalized product model.
- Optional HACS companion integration exposing entities and Home Assistant actions.

## Security

Tokens are never written to logs or returned by the API. Stored credentials are authenticated and obfuscated with an installation-specific key in the add-on's private configuration directory. A production multi-user release should use a dedicated secrets manager and per-tenant envelope encryption.

