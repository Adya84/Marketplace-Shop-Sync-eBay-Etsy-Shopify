# Etsy orders into Shopify

Etsy imports are a separate page and scheduler. TikTok's saved settings and `orders.db` stay in place; Etsy uses `etsy-orders.db`. Shopify lookup tags use `EtsyOrderID:` and cannot match TikTok tags.

## Publisher setup

The live OAuth sign-in service must include `transactions_r` in its Etsy scope list. `oauth_broker/app.py` includes the reference change, but the production Cloudflare Worker is deployed separately. Existing tokens are not expanded by refresh; the seller must reconnect Etsy and approve order reading. Existing listing permissions must remain in the requested scope list.

Etsy may restrict full receipt shipping addresses according to app category and region. Verify actual address fields before enabling imports. No address means review; never invent one.

## Seller setup

1. Update Shop Sync and reconnect Etsy on the Dashboard after the publisher updates OAuth permissions.
2. Open Etsy imports. Keep automatic import off, verify Shopify destination and Save settings.
3. Scan and preview. Missing item weights are displayed with editable gram fields for each purchased variant.
4. Enter actual weights, save, and preview again. Source IDs are scoped to Etsy listing plus product variant.
5. Import Etsy orders now. Verify one real Shopify order's recipient, delivery address, paid total, quantities, personalisation and weights.
6. Enable five-minute importing and Save settings. The countdown uses the completion time of the last Etsy scan.

Only physical UK GBP orders with verified matching totals are imported. Etsy's reported coupon amount is applied as an order discount, and reported tax/VAT is imported as an aggregate manual tax line with unknown remittance liability. The paid total must still reconcile exactly with items, discount, shipping and tax. Unresolved amounts, gift wrapping charges, refunds, cancellations, existing shipments and incomplete addresses require review. Tracking remains manual. No labels are bought, payments collected, inventory changes requested or confirmation emails sent by the importer.
