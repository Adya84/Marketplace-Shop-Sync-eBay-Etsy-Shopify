# TikTok Shop to Shopify order importer

## Agreed purpose
Run online using the merchant’s signed-in TikTok Shop browser session, without TikTok API access. Import orders into Shopify for postage labels and copy Shopify tracking back to the corresponding TikTok order.

## Approach
Use a persistent private browser on the hosted server for TikTok Seller Centre and an authorised Shopify API connection for Shopify. The existing native TikTok connector is the alternative already tested; product mapping blocked some orders. Manual exports are an alternative but do not meet the request for ongoing automatic imports.

## Order handling
Read all available order pages on the initial scan and subsequent scans. Create paid orders once they are ready to ship and the full delivery address is available. Use custom physical line items carrying the TikTok item name, variant, quantity, price and available weight; no Shopify catalogue mapping is required. Do not invent missing addresses or weights. Hold incomplete orders for review.

Skip unpaid and cancelled orders. Do not re-import previously shipped or completed historical orders as unfulfilled shipments. Record those historical IDs to prevent later imports. If historical sales records are wanted too, import them separately with their actual fulfilment status.

Check Shopify for existing TikTok order references before importing, including order #1020 already imported by the native channel. Store a unique shop/order identifier in a durable database and on the Shopify order. Reconcile uncertain creation results before retrying. Suppress duplicate receipts and avoid charging the buyer again. Preserve source prices and tax information without adding tax twice.

## Tracking handling
Read Shopify fulfilment events, with a periodic reconciliation scan for missed events. Match using the saved TikTok order identifier. Enter the actual tracking number and correctly matched carrier into TikTok Seller Centre, submit, then verify the saved value and order status. Do not mark an order dispatched before Shopify provides a real fulfilment and tracking number. Handle partial shipments per item; if the browser flow cannot safely represent a split, request review. Never overwrite conflicting existing tracking silently.

## Reliability
Run one scheduled worker at a time, with durable progress, bounded retries and a review queue. Stop affected work when login expires, a CAPTCHA appears, addresses are masked, or the page layout is unrecognised. Notify the merchant when action is needed. Automatic operation depends on the account remaining accessible and TikTok’s browser pages continuing to support the required actions; uninterrupted access cannot be guaranteed.

## Changes outside scope
Do not buy labels, change TikTok product listings or catalogue prices, refund buyers, or cancel orders automatically. Flag cancellations received after import so the merchant can avoid shipping them.

## Hosting and access needed
A server that supports a persistent browser process and encrypted persistent storage; an HTTPS address for Shopify callbacks; an authorised Shopify app connection with the required order, fulfilment and customer-address permissions; and the merchant signing into the hosted TikTok browser. Do not copy browser cookies from the merchant’s normal browser or put credentials into source files. Hosting availability and costs must be confirmed before deployment.

## Validation before unattended operation
Use synthetic records to test pagination, duplicate prevention, retries and tracking reconciliation. Verify one real import retains the correct items, totals and shipping address and offers Shopify labels. Verify one real Shopify fulfilment writes the same carrier/tracking back to TikTok. Keep automatic writes disabled until these checks pass. Test order #1020 is recognised as existing.

## Outstanding decision
Choose a hosting account and service capable of running a persistent browser. Confirm whether “all orders” means all orders needing dispatch, as assumed here, or also historical completed sales records.

## Approved Home Assistant deployment choice
Extend the existing Shop Sync app in Adya84/Marketplace-Shop-Sync-eBay-Etsy-Shopify (main at 9a0a832), rather than cloud hosting. User selected GitHub/Home Assistant and approved continuing. Preserve the existing catalogue workflows and OAuth broker. Run a headed Chromium browser with Selenium in the add-on and expose its screen through noVNC inside protected Home Assistant Ingress. Browser automation uses visible Seller Centre pages, not private TikTok API endpoints. Persistent profile and encrypted order payloads stay in the add-on config volume. Browser support targets amd64 and aarch64; preserve the existing app for unsupported hosts with browser features explicitly unavailable.

Poll every 5 minutes with one worker, off by default. Import only seller-fulfilled, paid, ready-to-ship orders. Inspect all To ship pages, including orders awaiting collection, but do not create duplicates of orders already in Shopify. Import ready-to-ship orders that have not yet been dispatched; existing tracking conflicts require review. Track each source shop/order and Shopify ID. On uncertain Shopify creation, do not create again until reconciled; Shopify query failures never mean no match. Match existing native imports by exact TikTokOrderID tag. All automatic writes remain off until the merchant explicitly enables them after dry-run review.

Use Shopify 2026-07, preserving the configured app version. Add required order/fulfilment scopes to the publisher OAuth broker without deploying changes until reviewed; explain reauthorization is required. Prefer polling Shopify for tracking so no public callback or separate hosting is needed. Only submit one-parcel, whole-order tracking automatically; split shipments and unmapped carriers require review. Do not purchase postage or charge customers. Cancellation after import creates a review item and blocks tracking for that order.

### Implementation choices delegated to builder
Module boundaries, browser selectors grounded in observed UK Seller Centre pages, conservative validation of money/address fields, ingress-relative frontend links, exact dependency versions verified with vendor docs, and review queue presentation. A browser/page interpretation error must fail closed. Storefront product changes and native connector configuration are out of scope.

### Acceptance boundary
Automated tests plus a real read-only Seller Centre scan and a dry-run preview must pass before a release can be called ready. Real order creation and TikTok tracking submission need individual verification before unattended writes are enabled. If Home Assistant host/container execution is unavailable, deliver code and explicitly state container/live verification remains outstanding; do not label it production-ready.
