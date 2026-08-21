# Shop Sync: eBay, Etsy, TikTok Shop and Shopify

[![Licence](https://img.shields.io/badge/licence-Shop%20Sync%20Personal%20%26%20Store%20Use-red.svg)](LICENSE)

<p align="center">
  <img src="marketplace_bridge/logo.png" alt="Shop Sync marketplace synchronisation logo" width="420">
</p>

Shop Sync is a Home Assistant OS app for importing marketplace listings and creating Shopify drafts. Version `0.0.24` changes eBay onboarding so ordinary Shop Sync users **do not need an eBay Developer account, App ID, Cert ID or RuName**. They authorise their own seller account through the publisher-managed Shop Sync eBay OAuth application.

> [!IMPORTANT]
> Shop Sync is still a development preview. Test with a small number of listings and review Shopify drafts before publishing them. Continuous order/stock synchronisation is not implemented yet.

## What 0.0.24 does

- Imports active eBay UK listings using OAuth user consent.
- Uses the publisher-managed Shop Sync eBay OAuth application for end-user sign-in.
- End users click **Connect eBay**, sign in to eBay, approve Shop Sync, copy the one-time authorization result, paste it back into Shop Sync and finish the connection.
- End users do **not** enter developer credentials.
- Stores each seller's eBay access/refresh credentials locally in the Shop Sync Home Assistant app data and renews short-lived access tokens automatically through the OAuth broker.
- Imports eBay titles, HTML descriptions, category data, item specifics, photos, variations, SKUs, prices and available quantities.
- Imports active Etsy listings through Open API v3 and renews Etsy OAuth tokens automatically.
- Imports active TikTok Shop products.
- Imports the Shopify catalogue for duplicate review and comparison.
- Creates Shopify products as drafts, including variants, inventory and media where supported.
- Provides duplicate-title review before draft creation.
- Supports individual and bulk Shopify draft creation.
- Shows connection state and background-job activity in Home Assistant Ingress.

## Install in Home Assistant OS

1. Open **Settings > Apps > App Store**.
2. Open the three-dot menu and choose **Repositories**.
3. Add:

   ```text
   https://github.com/Adya84/Marketplace-Shop-Sync-eBay-Etsy-Shopify
   ```

4. Install **Shop Sync**.
5. Start it and enable **Start on boot**, **Watchdog**, **Auto update** and **Show in sidebar** as desired.
6. Open **Shop Sync** from the Home Assistant sidebar.

Shop Sync is a custom Home Assistant app, not a HACS integration.

## Connect eBay — normal users

Users installing Shop Sync do **not** need to register with the eBay Developer Program.

1. Open Shop Sync.
2. Select **Connect eBay**.
3. Sign in to the eBay seller account you want Shop Sync to access.
4. Review the official eBay consent screen and select **Agree and Continue**.
5. The Shop Sync callback page will display **Copy authorization result**.
6. Select it, return to Shop Sync, paste the value into **Authorization result**, and select **Finish eBay connection**.
7. eBay should turn green **Connected**.

The authorization result is short-lived and single-use. If it expires or fails, select **Connect eBay** again and complete a fresh authorization.

Shop Sync uses eBay's basic API scope and Sell Inventory scope. eBay requires user consent for seller-owned data, after which a refresh token can be used so the seller does not need to sign in every two hours.

## eBay publisher / OAuth broker setup

This section is for the Shop Sync publisher/operator only, not normal users.

The public Home Assistant repository must **never contain the eBay Cert ID/client secret**. eBay requires the client secret when an authorization code is exchanged for a user access token, so Shop Sync 0.0.24 uses a hosted OAuth broker. The production broker is a Cloudflare Worker at:

```text
https://shop-sync-ebay-oauth.graffidoodle.workers.dev
```

Its health endpoint is:

```text
https://shop-sync-ebay-oauth.graffidoodle.workers.dev/health
```

and should report `{"status":"ok","configured":true}` before releasing or testing Shop Sync.

The broker holds these server-side Cloudflare variables/secrets:

```text
EBAY_CLIENT_ID=<Shop Sync production App ID>
EBAY_CLIENT_SECRET=<Shop Sync production Cert ID>
EBAY_RUNAME=<Shop Sync production RuName>
BROKER_SIGNING_SECRET=<long random secret>
```

The eBay **Auth accepted URL** and **Auth declined URL** should both point to:

```text
https://shop-sync-ebay-oauth.graffidoodle.workers.dev/api/ebay/oauth/callback
```

The eBay Client ID, Cert ID and broker signing secret must never be committed to GitHub or shipped inside the Home Assistant app. The Home Assistant app only contains the public broker URL.

The broker exposes the OAuth start, callback, code exchange and refresh endpoints. It signs one-time callback results and issues a refresh proof so possession of a raw refresh token alone is not enough to use the public refresh endpoint.

See [`oauth_broker/README.md`](oauth_broker/README.md) for the broker architecture and security notes.

## Shopify connection

Create and install a Shopify app for the destination store with these scopes:

```text
write_products,write_inventory,read_locations
```

Then enter the permanent `.myshopify.com` store domain, Client ID and Client secret into Shop Sync and select **Test and save**. Shop Sync obtains short-lived Shopify Admin API tokens and renews them automatically.

## Etsy connection

Create an Etsy Open API v3 seller app and configure this redirect URI:

```text
https://adya84.github.io/Marketplace-Shop-Sync-eBay-Etsy-Shopify/etsy-callback.html
```

In Shop Sync enter the Etsy keystring and shared secret, select **Connect Etsy**, approve the consent screen, copy the authorization result, paste it into Shop Sync and finish the connection. Shop Sync discovers the Shop ID and renews Etsy access tokens automatically.

## TikTok Shop connection

TikTok Shop currently uses the app key, app secret, seller access token and shop cipher from TikTok Shop Partner Center. A development app can only authorise development shops until TikTok approves the app for live use.

## Import and transfer

1. Connect Shopify and at least one source marketplace.
2. Select the matching button under **Import catalogues**.
3. Watch **Activity** until the import completes.
4. Review any entries under **Review duplicate titles**.
5. Start with one product and select **Create Shopify draft**.
6. Check the resulting Shopify draft carefully before publishing it.
7. After testing, select multiple products to queue additional drafts.

## Security and privacy

- Never commit eBay Cert IDs/client secrets, marketplace access tokens or refresh tokens to GitHub.
- The eBay client secret belongs only on the hosted OAuth broker.
- Seller OAuth tokens are stored in the Home Assistant app's private persistent data through Shop Sync's installation-specific authenticated credential wrapper.
- Tokens are not returned by the status API or intentionally written to logs.
- Saved secret fields intentionally appear blank after a page reload.
- See [PRIVACY.md](PRIVACY.md) for the Shop Sync privacy policy.

## Troubleshooting

- **Connect eBay cannot open:** check `https://shop-sync-ebay-oauth.graffidoodle.workers.dev/health` and confirm it reports `configured:true`.
- **Authorization result rejected:** select **Connect eBay** again; callback results expire and are single-use.
- **eBay state mismatch:** discard the result and start a fresh connection.
- **eBay import later fails authentication:** reconnect if the seller revoked access or the long-lived refresh token expired.
- **Shopify says `write_products` is required:** verify the active Shopify app version includes `write_products`, reinstall it, and restart Shop Sync.
- **Etsy authorization fails:** start a fresh Etsy connection; its authorization code is single-use.

## Development

The Home Assistant service uses Python, FastAPI and SQLite.

```bash
cd marketplace_bridge
python -m pip install -r requirements.txt pytest
BRIDGE_DATA_DIR=./data python -m uvicorn app.main_v2:app --reload --port 8099
pytest app/tests
```

The installable Home Assistant app is in `marketplace_bridge/`. The eBay OAuth broker is deployed separately so the eBay client secret is never shipped to Home Assistant users.

## Not implemented yet

- Automatic Shopify-to-eBay stock reconciliation
- eBay order ingestion and automatic stock deductions
- Shopify-to-eBay listing creation
- Shopify-to-Etsy listing creation
- Scheduled reconciliation, webhooks and automatic retries
- A HACS companion integration

## Support

Use [GitHub Issues](https://github.com/Adya84/Marketplace-Shop-Sync-eBay-Etsy-Shopify/issues) for reproducible bugs and feature requests. Remove tokens, personal data, order details and customer information before posting logs or screenshots.

## Licence

Copyright (C) 2026 Adrian Apel. All rights reserved.

Shop Sync is provided under the [Shop Sync Home Assistant App Licence](LICENSE). It can be used free of charge on your own Home Assistant installation to manage marketplace accounts and stores you own or are authorised to operate. Redistribution, rebranding, resale, publication of modified versions, paid hosting and inclusion in paid products or services require prior written permission.
