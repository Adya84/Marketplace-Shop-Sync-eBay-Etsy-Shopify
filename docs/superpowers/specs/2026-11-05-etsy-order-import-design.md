# Etsy order imports into Shopify

## Intent
Bring Etsy sales into Shopify for postage labels through the existing Shop Sync installation, avoiding another connector subscription.

## Approach
Use Etsy Open API receipts through the existing OAuth broker. Reuse Shopify order validation and encrypted storage, with marketplace-qualified identities. A browser scraper would introduce a second browser session and fragile selectors; a separate app adds subscription costs and does not reuse existing connections.

## Behaviour
- Add an Etsy section to Order imports with separate enable switch, Preview, Import now, saved confirmation, scan outcome counts and five-minute countdown.
- Read all paid, unshipped, physical orders in the connected shop, with paginated results. Recheck receipt state before creation. Hold cancellations, refunds, digital-only orders, ambiguous totals, masked or missing addresses and unknown weights for review.
- Include exact recipient/address, purchased options, buyer personalisation and quantity. Map weights explicitly to Etsy product/variation identity; do not assume TikTok IDs apply to Etsy.
- Create paid, unfulfilled Shopify orders. Suppress new payment collection and unsolicited confirmation emails. No automatic label purchases.
- Preserve exact Etsy receipt identity in Shopify tags and local encrypted records. Deduplicate by marketplace plus shop plus receipt, including uncertain responses and retries. Existing TikTok records must keep their current identities.
- Keep Etsy scheduling and errors separate from TikTok. Neither importer may stop the other's checks.
- Tracking entry remains manual in this first release.

## Connection and acceptance
Add transactions_r to Etsy OAuth requests and permit only the required receipt/transaction GET routes in the broker. Existing sellers reconnect to approve the new permission. Persist rotated credentials through the existing credential store.

Before enabling writes, prove the connected app can retrieve receipt and full shipping address data. Etsy applies regional/app-category restrictions to addresses; missing access must be a visible blocked state, never an empty-address order. If the hosted broker cannot be deployed from available credentials, deliver its prepared change and identify deployment as outstanding.

## Validation
Use API fixtures for pagination, exact money reconciliation, discounts, personalisation, missing weights, cancellation, redacted address, credential refresh and source isolation. Test duplicate prevention on retry and uncertain Shopify responses. Verify one live preview and a real authorized import with the recipient, amount and physical shipping details returned from Shopify before claiming live operation.
