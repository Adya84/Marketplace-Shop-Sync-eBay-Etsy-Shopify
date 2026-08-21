# Shop Sync: eBay, Etsy, TikTok Shop and Shopify

[![Licence](https://img.shields.io/badge/licence-Shop%20Sync%20Personal%20%26%20Store%20Use-red.svg)](LICENSE)

<p align="center">
  <img src="marketplace_bridge/logo.png" alt="Shop Sync marketplace synchronisation logo" width="420">
</p>

Shop Sync is a Home Assistant OS app for importing marketplace listings and creating Shopify drafts. Version `0.0.30` gives normal users the same simple hosted OAuth connection experience for **eBay, Etsy and Shopify**.

Normal users do **not** need an eBay Developer account, Etsy developer app, or Shopify app Client ID/secret. They connect the seller/store accounts they are authorised to use through the publisher-managed Shop Sync OAuth service.

> [!IMPORTANT]
> Shop Sync is still a development preview. Test with a small number of listings and review every Shopify draft before publishing it. Continuous order/stock synchronisation and reverse marketplace publishing are still planned work.

## What users need

### Home Assistant

- Home Assistant OS with custom Apps/Add-ons support.
- This repository added to the Home Assistant App Store.
- Shop Sync installed and started.

### eBay

You only need the eBay seller account you want to connect. Normal users do **not** need App ID, Cert ID, RuName or a manually generated token.

### Etsy

You only need the Etsy seller account you want to connect. Normal users do **not** need an Etsy API keystring, shared secret or developer application.

### Shopify

You only need:

- the Shopify store you are authorised to manage; and
- its permanent `.myshopify.com` domain, for example `your-store.myshopify.com`.

Normal users do **not** need to create a Shopify app or enter a Shopify Client ID/client secret into Shop Sync.

### TikTok Shop

TikTok Shop currently still requires the app key, app secret, seller access token and shop cipher from TikTok Shop Partner Center.

## What version 0.0.30 does

- Adds publisher-managed Shopify OAuth for normal users.
- Removes Shopify Client ID/client-secret fields from the normal Shop Sync UI.
- Lets the user enter only the permanent `.myshopify.com` store domain and select **Connect Shopify**.
- Uses the hosted Shop Sync broker to create the Shopify authorization URL and exchange the authorization code using the publisher Shopify app credentials.
- Verifies Shopify's callback HMAC on the hosted broker before accepting the callback.
- Stores the authorised store access token locally in that user's private Shop Sync add-on data.
- Uses the authorised Shopify token for catalogue imports and Shopify draft creation.
- Preserves compatibility with Shopify credentials saved by older Shop Sync versions.
- Keeps the publisher-managed eBay and Etsy OAuth flows introduced earlier.
- Imports active eBay UK listings, active Etsy listings, Shopify catalogue products and TikTok Shop products.
- Imports titles, descriptions, images, variations, SKUs, prices and available quantities where supported.
- Skips removed/unavailable eBay listings instead of aborting a full import.
- Provides catalogue pagination, title/SKU/listing-ID search and marketplace filtering.
- Shows SKU, variant count and stock in the Ready to send catalogue.
- Creates Shopify products as drafts and verifies inventory after writing it.
- Retries temporary Shopify media-readiness errors.
- Provides LIVE Activity with 2-second refresh, parent bulk-transfer progress and paginated job history.

## Install Shop Sync in Home Assistant OS

1. Open **Settings > Apps > App Store**.
2. Open the three-dot menu and choose **Repositories**.
3. Add:

   ```text
   https://github.com/Adya84/Marketplace-Shop-Sync-eBay-Etsy-Shopify
   ```

4. Close the repository dialog and refresh the App Store if necessary.
5. Select **Shop Sync** and choose **Install**.
6. Start Shop Sync.
7. Enable **Start on boot**, **Watchdog**, **Auto update** and **Show in sidebar** as desired.
8. Open **Shop Sync** from the Home Assistant sidebar.

Shop Sync is a custom Home Assistant app, not a HACS integration.

## Updating an existing installation

For users upgrading from `0.0.29` or earlier:

1. Open **Home Assistant > Settings > Apps > Shop Sync**.
2. Refresh the custom app repository if Home Assistant does not immediately show the new version.
3. Update to `0.0.30` or later.
4. Restart Shop Sync.
5. Reopen the Shop Sync sidebar page.

After updating, the Shopify panel no longer asks for Client ID/client secret. Existing Shopify credentials created by older versions remain supported, but reconnecting through the hosted OAuth flow is recommended.

## Connect eBay

1. Open **Shop Sync**.
2. Select **Connect eBay**.
3. Sign in to the eBay seller account you want Shop Sync to access.
4. Approve Shop Sync.
5. On the callback page select **Copy authorization result**.
6. Return to Shop Sync and paste it into **Authorization result**.
7. Select **Finish eBay connection**.
8. The eBay panel should turn green **Connected**.

Shop Sync requests the basic API scope and **Sell Inventory** scope. The seller refresh credential is stored locally and short-lived access tokens are refreshed through the hosted broker.

## Connect Etsy

1. Open **Shop Sync**.
2. Select **Connect Etsy**.
3. Sign in to the Etsy seller account you want Shop Sync to access.
4. Approve the Shop Sync consent screen.
5. Etsy redirects to the hosted Shop Sync callback page.
6. Select **Copy authorization result**.
7. Return to Shop Sync and paste the copied value into **Authorization result**.
8. Select **Finish Etsy connection**.
9. Shop Sync discovers the authorised Etsy Shop ID and the Etsy panel should turn green **Connected**.

Normal users do not need to create an Etsy developer app or enter API credentials. Etsy access tokens are refreshed automatically.

## Connect Shopify

1. Open the Shopify Admin for the store you want to connect and confirm its permanent `.myshopify.com` domain.
2. Open **Shop Sync**.
3. Enter that permanent domain in the Shopify **Store domain** box, for example:

   ```text
   your-store.myshopify.com
   ```

4. Select **Connect Shopify**.
5. Shopify opens its official authorization/install page for that store.
6. Review the requested permissions and approve Shop Sync.
7. Shopify redirects to the hosted Shop Sync callback page.
8. Select **Copy authorization result**.
9. Return to Shop Sync and paste the copied value into **Authorization result**.
10. Select **Finish Shopify connection**.
11. Shop Sync verifies the store by calling Shopify and the Shopify panel should turn green **Connected**.

Normal users do not create a Shopify developer app and do not enter Client ID/client secret values into Shop Sync.

Shop Sync currently requests these Shopify Admin API scopes:

```text
write_products,write_inventory,read_locations
```

The authorised Shopify access token is stored only in that user's encrypted Shop Sync add-on data and is used for Shopify imports and draft creation.

## Connect TikTok Shop

1. Create/configure a TikTok Shop app in TikTok Shop Partner Center.
2. Obtain the app key and app secret.
3. Authorise the seller shop and obtain the seller access token.
4. Obtain the selected shop's `cipher` value.
5. Enter those values into Shop Sync and select **Test and save**.

TikTok is currently the remaining marketplace connection that still requires user-supplied developer/app credentials.

## Import listings and create Shopify drafts

1. Connect Shopify and at least one source marketplace.
2. Select the matching import action under **Import catalogues**.
3. Watch the **LIVE Activity** panel while the import runs.
4. Use **Ready to send** to search, filter and review imported products.
5. Check the Stock column and variants before transfer.
6. Start with one product and select **Create Shopify draft**.
7. Review the resulting Shopify draft carefully, including title, description, images, variants, prices, SKUs and stock.
8. Use bulk selection once satisfied with the result.

Shop Sync deliberately creates Shopify drafts rather than immediately publishing products.

## Publisher OAuth broker setup

> [!NOTE]
> This section is only for the Shop Sync publisher/operator. Normal Shop Sync users should ignore it.

Production broker:

```text
https://shop-sync-ebay-oauth.graffidoodle.workers.dev
```

Health check:

```text
https://shop-sync-ebay-oauth.graffidoodle.workers.dev/health
```

Expected production response:

```json
{"status":"ok","configured":true,"ebay_configured":true,"etsy_configured":true,"shopify_configured":true}
```

The Cloudflare Worker holds these variables/secrets:

```text
BROKER_SIGNING_SECRET=<long random secret>
EBAY_CLIENT_ID=<Shop Sync production App ID>
EBAY_CLIENT_SECRET=<Shop Sync production Cert ID>
EBAY_RUNAME=<Shop Sync production RuName>
ETSY_KEYSTRING=<Shop Sync Etsy production keystring>
ETSY_SHARED_SECRET=<Shop Sync Etsy shared secret>
SHOPIFY_CLIENT_ID=<Shop Sync Shopify app Client ID>
SHOPIFY_CLIENT_SECRET=<Shop Sync Shopify app client secret>
```

### eBay publisher callback

Both the eBay accepted and declined URLs are:

```text
https://shop-sync-ebay-oauth.graffidoodle.workers.dev/api/ebay/oauth/callback
```

### Etsy publisher callback

```text
https://shop-sync-ebay-oauth.graffidoodle.workers.dev/api/etsy/oauth/callback
```

### Shopify publisher app configuration

The active Shopify app version should use:

```text
App URL:
https://shop-sync-ebay-oauth.graffidoodle.workers.dev

Allowed redirection URL:
https://shop-sync-ebay-oauth.graffidoodle.workers.dev/api/shopify/oauth/callback

Scopes:
write_inventory,read_locations,write_products
```

The Shopify app is not embedded in Shopify Admin for the Shop Sync Home Assistant flow.

Never commit publisher secrets to GitHub or ship them in the Home Assistant app.

See [`oauth_broker/README.md`](oauth_broker/README.md) for full broker deployment and security details.

## Security and privacy

- Publisher eBay, Etsy and Shopify client secrets live only on the hosted broker.
- Seller/store OAuth credentials are stored in the user's private encrypted Shop Sync add-on data.
- OAuth callback results are signed, short-lived and checked against the original state.
- The Shopify broker verifies Shopify's callback HMAC before issuing a Shop Sync authorization result.
- OAuth tokens are not intentionally exposed through the status API or application logs.
- Users can revoke Shop Sync access from the relevant marketplace/store where supported.
- See [PRIVACY.md](PRIVACY.md) for the privacy policy.

## Troubleshooting

- **Home Assistant still shows Shopify Client ID/client-secret fields:** update Shop Sync to `0.0.30` or later and restart the add-on.
- **Connect Shopify cannot open:** check the broker `/health` endpoint and confirm `shopify_configured:true`.
- **Shopify says the shop domain is invalid:** use the permanent domain ending in `.myshopify.com`, not a custom customer-facing domain.
- **Shopify authorization result rejected:** select **Connect Shopify** again; the result is short-lived and should be used promptly.
- **Shopify state/store mismatch:** discard the result and start a fresh connection from the intended store.
- **Shopify connection later returns 401/403:** the app may have been uninstalled or access revoked; connect Shopify again.
- **Home Assistant still shows Etsy keystring/shared-secret fields:** update Shop Sync to `0.0.29` or later and restart the add-on.
- **Connect Etsy cannot open:** check the broker `/health` endpoint and confirm `etsy_configured:true`.
- **Etsy authorization result rejected:** select **Connect Etsy** again; the result is short-lived and single-use.
- **Connect eBay cannot open:** check the same health endpoint and confirm `ebay_configured:true`.
- **Not all imported listings appear:** use the catalogue page controls and search/filter tools.
- **Shopify draft stock becomes zero:** re-import and verify the Stock column; inventory write-back verification should fail the job if Shopify does not store the expected value.
- **`Non-ready media cannot be attached to variants`:** Shop Sync retries this temporary Shopify processing state before failing.
- **Activity looks frozen:** LIVE Activity should refresh every 2 seconds; restart the add-on if the frontend was left open across an update.

## Development

The Home Assistant service uses Python, FastAPI and SQLite.

```bash
cd marketplace_bridge
python -m pip install -r requirements.txt pytest
BRIDGE_DATA_DIR=./data python -m uvicorn app.main_v5:app --reload --port 8099
pytest app/tests
```

The installable Home Assistant app is in `marketplace_bridge/`. The shared eBay/Etsy/Shopify OAuth broker is deployed separately so publisher secrets are never shipped to Home Assistant users.

## Not implemented yet

- Automatic Shopify-to-eBay stock reconciliation.
- eBay order ingestion and automatic stock deductions.
- Shopify-to-eBay listing creation.
- Shopify-to-Etsy listing creation.
- Scheduled reconciliation, webhooks and automatic retries.
- A HACS companion integration.

## Support

Use [GitHub Issues](https://github.com/Adya84/Marketplace-Shop-Sync-eBay-Etsy-Shopify/issues) for reproducible bugs and feature requests. Remove tokens, personal data, order details and customer information before posting logs or screenshots.

## Licence

Copyright (C) 2026 Adrian Apel. All rights reserved.

Shop Sync is provided under the [Shop Sync Home Assistant App Licence](LICENSE). It can be used free of charge on your own Home Assistant installation to manage marketplace accounts and stores you own or are authorised to operate. Redistribution, rebranding, resale, publication of modified versions, paid hosting and inclusion in paid products or services require prior written permission.
