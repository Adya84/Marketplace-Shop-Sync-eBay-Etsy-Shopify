# TikTok order-only bridge — development beta

This branch extends the existing Home Assistant Shop Sync app. It is not an installed, verified unattended service. Automatic imports are disabled by default. Automatic tracking submission is deliberately unavailable; the review screen reads tracking, but tracking must be entered in TikTok manually in this beta.

The native TikTok sales channel is preferable when its product mappings work: it imports orders and returns supported carrier tracking. Do not enable this bridge alongside native order creation until one owner of each source order has been established. Exact TikTokOrderID tags are checked before creation, but the native app does not share this bridge's SQLite claim and could race with it. Do not retry native imports for orders already created by this bridge without reconciling duplicates first.

## Host and permissions

- Home Assistant OS/Supervised app with authenticated Ingress. The order page and remote browser reject direct-port access. No public VNC or browser-debugging port is published.
- amd64 or aarch64 Linux with Chromium sandbox support. Existing armv7 catalogue use is retained; the browser feature is unavailable there. The Chromium sandbox is not disabled automatically.
- An offline Shopify connection with the scopes Shopify requires for this workflow: `read_orders`, `read_customers`, `write_customers`, `write_draft_orders`, `read_draft_orders`, `write_quick_sale`, `read_quick_sale`, and `read_marketplace_orders`. The current publisher OAuth broker does not request these scopes yet; its app registration and broker must be updated, then the store must reconnect and approve them. Until then, the import controls will report incomplete permissions and will not create orders. Browser sign-in and the ChatGPT Shopify connector are not credentials that this Home Assistant app can reuse.
- Chromium profile, orders database and existing credential key are in the private `/config` directory. Treat app backups as private. The existing SecretBox protects stored payloads against casual disclosure, but its key sits beside the database; this does not protect against a compromised host or exposed backup.

## Install and verify before unattended use

1. Back up the existing Shop Sync app. Build this development branch in a separate local app installation; do not replace the production app until host checks pass.
2. Open the app through Home Assistant Ingress, then select **TikTok order imports · beta**.
3. Connect Shopify using the app's own offline connection after the publisher has added all required scopes above. Approve the updated access in Shopify when requested.
4. Start the TikTok browser and sign in inside that browser panel. Complete any login challenge yourself. The session is separate from your desktop browser and persists across restarts.
5. Enter the verified shop name/ID and connected Shopify domain. Enter the actual weight for each sold TikTok SKU. Save, then **Scan and preview**. Review the displayed orders and recipient details; **Import TikTok orders now** imports only orders that passed the preview checks. The automatic five-minute switch stays disabled until a successful preview and complete Shopify scopes.
6. Check every recipient, street, supplied district, postcode, item option, quantity and price. The parser preserves the entire TikTok street block rather than guessing where a comma separates a post town. Shopify's city field uses the explicitly supplied district. If the label requires a distinct post town, review/edit the address before purchase.
7. Verify one real import on the host, including **Create shipping label**, before unattended use. Restart the app and scan again to verify no second order appears. Check native imports are not racing the bridge.
8. Only then enable the five-minute import switch. Session expiry, missing weights, partial/masked addresses, unmatched totals, cancellations and multiple parcels require review. Buying a label remains a merchant action.

The shipping queue is traversed across all pages and compared with its To ship count. Already-dispatched historical orders are skipped. A source order with existing tracking cannot create another shipment automatically. Previously linked orders are re-read for cancellation/tracking review. Browser page changes stop scans rather than inventing missing data. Uncertain Shopify writes stay blocked until a matching order can be reconciled.

## Verification status

- Python tests cover validation, address preservation, existing tracking, concurrent durable claims, exact native tag detection, ambiguous creation, tracking uncertainty, Ingress/CSRF and websocket denial.
- Shopify customer and draft-order operations validated against Admin GraphQL 2026-07. The current production publisher broker scope set is still insufficient, and the expanded-scope reconnect has not been completed.
- Real read-only Seller Centre pages were used to ground selectors and parser layout. Synthetic fixtures contain no customer addresses.
- No local Docker engine or Home Assistant host was available for the container/browser/Ingress smoke test. Container startup, sandbox compatibility, complete live Selenium scans and unattended import remain unverified.
- On 24 October, ten requested current orders were separately imported through the connected Shopify app as #1026–#1035. This manual run does not verify Home Assistant deployment. A subsequent native TikTok order arrived as #1036 for the previously mapped 30 × 20 cm grooved variant.

## Tracking return

Native carrier mapping already includes Royal Mail. The bridge's carrier map is review-only while automatic tracking submission remains unimplemented. Do not interpret a matching tracking number on both platforms as proof of automatic sync unless manual entry has been ruled out.
