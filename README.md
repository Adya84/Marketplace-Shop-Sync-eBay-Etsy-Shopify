# Shop Sync: eBay, Etsy, TikTok Shop and Shopify

[![Licence](https://img.shields.io/badge/licence-Shop%20Sync%20Personal%20%26%20Store%20Use-red.svg)](LICENSE)

<p align="center">
  <img src="marketplace_bridge/logo.png" alt="Shop Sync marketplace synchronisation logo" width="420">
</p>

Shop Sync is a Home Assistant OS app for importing marketplace listings and creating Shopify drafts. Version `0.0.29` adds the same simple hosted OAuth experience for Etsy that Shop Sync already uses for eBay.

Normal users do **not** need an eBay Developer account or an Etsy developer app. They connect their own seller accounts through the publisher-managed Shop Sync OAuth service.

> [!IMPORTANT]
> Shop Sync is still a development preview. Test with a small number of listings and review every Shopify draft before publishing it. Continuous order/stock synchronisation and reverse marketplace publishing are still planned work.

## What users need

### Home Assistant

- Home Assistant OS with custom Apps/Add-ons support.
- This repository added to the Home Assistant App Store.
- Shop Sync installed and started.

### eBay

Normal users only need an eBay seller account and permission to approve Shop Sync. They do **not** need App ID, Cert ID, RuName or a manually generated token.

### Etsy

Normal users only need the Etsy seller account they want to connect. They do **not** need an Etsy API keystring, shared secret or developer application.

### Shopify

For the destination Shopify store, create/install a Shopify app with:

```text
write_products,write_inventory,read_locations
```

Then enter the permanent `.myshopify.com` domain, Client ID and Client secret into Shop Sync.

### TikTok Shop

TikTok Shop currently still requires the app key, app secret, seller access token and shop cipher from TikTok Shop Partner Center.

## What version 0.0.29 does

- Adds publisher-managed Etsy OAuth for normal users.
- Removes Etsy API keystring/shared-secret fields from the normal Shop Sync UI.
- Uses Etsy OAuth PKCE through the hosted Shop Sync broker.
- Keeps the Etsy publisher keystring/shared secret only on the hosted broker.
- Stores each seller's Etsy access/refresh credentials locally in their Shop Sync installation.
- Renews Etsy access tokens automatically through the broker.
- Routes Etsy Open API reads through the broker so the publisher shared secret is never shipped to Home Assistant users.
- Preserves compatibility with existing Etsy connections created by older Shop Sync versions.
- Keeps the publisher-managed eBay OAuth flow introduced earlier.
- Imports active eBay UK listings and active Etsy listings.
- Imports titles, descriptions, images, variations, SKUs, prices and available quantities where supported.
- Skips removed/unavailable eBay listings instead of aborting a full import.
- Provides catalogue pagination, title/SKU/listing-ID search and marketplace filtering.
- Shows SKU, variant count and stock in the Ready to send catalogue.
- Creates Shopify products as drafts and verifies inventory after writing it.
- Retries temporary Shopify media-readiness errors.
- Provides LIVE Activity with 2-second refresh, parent bulk-transfer progress and paginated job history.
- Imports TikTok Shop products and the Shopify catalogue for comparison/duplicate review.

## Install Shop Sync in Home Assistant OS

1. Open **Settings > Apps > App Store**.
2. Open the three-dot menu and choose **Repositories**.
3. Add:

   ```text
   https://github.com/Adya84/Marketplace-Shop-Sync-eBay-Etsy-Shopify
   ```

4. Refresh the App Store if necessary.
5. Select **Shop Sync** and choose **Install**.
6. Start Shop Sync.
7. Enable **Start on boot**, **Watchdog**, **Auto update** and **Show in sidebar** as desired.
8. Open **Shop Sync** from the Home Assistant sidebar.

Shop Sync is a custom Home Assistant app, not a HACS integration.

## Updating an existing installation

For users upgrading from `0.0.28` or earlier:

1. Open **Home Assistant > Settings > Apps > Shop Sync**.
2. Refresh the custom app repository if Home Assistant does not immediately show the new version.
3. Update to `0.0.29` or later.
4. Restart Shop Sync.
5. Reopen the Shop Sync sidebar page.

After updating, the Etsy panel no longer asks for API keystring/shared secret. Existing old Etsy credentials remain supported, but reconnecting through the new hosted OAuth flow is recommended.

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

1. Create/install a Shopify app for the destination store.
2. Give it these scopes:

   ```text
   write_products,write_inventory,read_locations
   ```

3. Release/activate the app version and install it on the store.
4. Enter the permanent `.myshopify.com` domain, Client ID and Client secret in Shop Sync.
5. Select **Test and save**.

## Connect TikTok Shop

1. Create/configure a TikTok Shop app in TikTok Shop Partner Center.
2. Obtain the app key and app secret.
3. Authorise the seller shop and obtain the seller access token.
4. Obtain the selected shop's `cipher` value.
5. Enter those values into Shop Sync and select **Test and save**.

## Import listings and create Shopify drafts

1. Connect Shopify and at least one source marketplace.
2. Select the matching import action under **Import catalogues**.
3. Watch the **LIVE Activity** panel while the import runs.
4. Use **Ready to send** to search, filter and review imported products.
5. Check the Stock column and variants before transfer.
6. Start with one product and select **Create Shopify draft**.
7. Review the resulting Shopify draft carefully.
8. Use bulk selection once satisfied with the result.

Shop Sync deliberately creates drafts rather than immediately publishing products.

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
{"status":"ok","configured":true,"ebay_configured":true,"etsy_configured":true}
```

The Cloudflare Worker holds these variables/secrets:

```text
BROKER_SIGNING_SECRET=<long random secret>
EBAY_CLIENT_ID=<Shop Sync production App ID>
EBAY_CLIENT_SECRET=<Shop Sync production Cert ID>
EBAY_RUNAME=<Shop Sync production RuName>
ETSY_KEYSTRING=<Shop Sync Etsy production keystring>
ETSY_SHARED_SECRET=<Shop Sync Etsy shared secret>
```

The eBay accepted and declined callback URL is:

```text
https://shop-sync-ebay-oauth.graffidoodle.workers.dev/api/ebay/oauth/callback
```

The Etsy production callback URL is:

```text
https://shop-sync-ebay-oauth.graffidoodle.workers.dev/api/etsy/oauth/callback
```

Never commit any of the publisher secrets to GitHub or ship them in the Home Assistant app.

See [`oauth_broker/README.md`](oauth_broker/README.md) for the full broker deployment/security details.

## Security and privacy

- Publisher eBay and Etsy secrets live only on the hosted broker.
- Seller OAuth credentials are stored in the user's private Shop Sync add-on data.
- OAuth callback results are signed, short-lived and checked against the original state.
- OAuth tokens are not intentionally exposed through the status API or application logs.
- Users can revoke Shop Sync access from the marketplace account where supported.
- See [PRIVACY.md](PRIVACY.md) for the privacy policy.

## Troubleshooting

- **Home Assistant still shows Etsy keystring/shared-secret fields:** update Shop Sync to `0.0.29` or later and restart the add-on.
- **Connect Etsy cannot open:** check the broker `/health` endpoint and confirm `etsy_configured:true`.
- **Etsy authorization result rejected:** select **Connect Etsy** again; the result is short-lived and single-use.
- **Etsy state mismatch:** discard the result and start a fresh connection.
- **Etsy import later fails authentication:** reconnect if the seller revoked access or the refresh token is no longer valid.
- **Connect eBay cannot open:** check the same health endpoint and confirm `ebay_configured:true`.
- **eBay authorization result rejected:** start a fresh eBay connection.
- **Not all imported listings appear:** use the catalogue page controls and search/filter tools.
- **Shopify draft stock becomes zero:** re-import and verify the Stock column; inventory write-back verification should fail the job if Shopify does not store the expected value.
- **`Non-ready media cannot be attached to variants`:** Shop Sync retries this temporary Shopify processing state before failing.
- **Activity looks frozen:** LIVE Activity should refresh every 2 seconds; restart the add-on if the frontend was left open across an update.

## Development

The Home Assistant service uses Python, FastAPI and SQLite.

```bash
cd marketplace_bridge
python -m pip install -r requirements.txt pytest
BRIDGE_DATA_DIR=./data python -m uvicorn app.main_v4:app --reload --port 8099
pytest app/tests
```

The installable Home Assistant app is in `marketplace_bridge/`. The shared eBay/Etsy OAuth broker is deployed separately so publisher secrets are never shipped to Home Assistant users.

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
