# Shop Sync: eBay, Etsy, TikTok Shop and Shopify

[![Licence](https://img.shields.io/badge/licence-Shop%20Sync%20Personal%20%26%20Store%20Use-red.svg)](LICENSE)

<p align="center">
  <img src="marketplace_bridge/logo.png" alt="Shop Sync marketplace synchronisation logo" width="420">
</p>

Shop Sync is an early-stage Home Assistant OS app for transferring marketplace listings. Version `0.0.23` implements **eBay UK, Etsy or TikTok Shop to Shopify**, imports the Shopify master catalogue, adds destination-specific duplicate-title review, and introduces guided eBay OAuth with automatic access-token renewal.

> [!IMPORTANT]
> This is a development preview. Test with a small number of listings and review every Shopify draft before publishing it. Continuous stock/order synchronisation and multi-user onboarding are not implemented yet.

## What version 0.0.23 does

- Reads active listings from the connected eBay UK seller account.
- Guides eBay OAuth sign-in using the eBay App ID, Cert ID and RuName.
- Requests the eBay basic API and Sell Inventory OAuth scopes.
- Validates the OAuth state before accepting the eBay callback result.
- Exchanges the eBay authorization code for access and refresh tokens and renews short-lived access tokens automatically.
- Imports listing titles, HTML descriptions, eBay category details and item specifics.
- Imports listing photos in source order and maps variation photos where eBay supplies the association.
- Imports variations, option values, SKUs, prices and available quantities.
- Creates products as **drafts** in Shopify.
- Enables tracked inventory and writes quantities to the first Shopify inventory location.
- Stores eBay-to-Shopify product and variant mappings for later reconciliation.
- Shows connections, imported products, transfer actions and job activity on a Home Assistant Ingress page called **Shop Sync**.
- Uses Shopify client credentials to obtain and renew short-lived Admin API tokens automatically.
- Preserves partially entered connection forms instead of refreshing and clearing them.
- Submits connections and actions through the correct Home Assistant Ingress path.
- Imports active Etsy listings through Open API v3, including descriptions, images, variations, SKUs, prices and quantities.
- Imports active TikTok Shop listings, including descriptions, images, variations, SKUs, prices and quantities.
- Supplies a complete Shopify product-option matrix for simple and multi-option variants, including Shopify's required default option for products without named variations.
- Renews Etsy OAuth access tokens automatically when a refresh token is available.
- Guides Etsy sign-in with PKCE, validates single-use state and discovers the authorised Shop ID automatically.
- Provides an optional **Buy me a beer** button linked directly to the Graffidoodle PayPal page.
- Displays an Adrian Apel copyright notice and links to the Shop Sync licence.
- Allows multiple imported products to be selected and queued as Shopify drafts together.
- Moves successfully created Shopify drafts from **Ready to send** into a separate **Completed** section.
- Clears the visible **Completed** list without deleting Shopify products or the saved transfer mappings.
- Imports the Shopify product catalogue so it can be used as the master comparison source and prepared for Shopify-to-marketplace transfers.
- Detects duplicate titles across imported Etsy, eBay and Shopify catalogues after ignoring case, punctuation and repeated spacing.
- Holds duplicate candidates in **Review duplicate titles** and excludes them from individual and bulk draft creation until approved for that destination.
- Refreshes Activity automatically every 60 seconds without reloading connection forms.

## Not implemented yet

- Automatic Shopify-to-eBay stock updates
- eBay order ingestion or automatic stock deductions
- Bulk Shopify export/approval
- Etsy export and Shopify-to-Etsy transfer
- Shopify-to-eBay transfer
- Scheduled reconciliation, webhooks and automatic retries
- A HACS companion integration

The available draft creation routes in `0.0.23` are eBay UK, Etsy and TikTok Shop to Shopify. Shopify catalogue import and shared duplicate review are included; Shopify-to-marketplace draft creation remains planned work.

## Complete setup guide

Follow these sections in order. Shopify is the destination and intended catalogue master in the current preview.

### 1. Install Shop Sync in Home Assistant OS

1. In Home Assistant, open **Settings > Apps > App Store**.
2. Open the three-dot menu and select **Repositories**.
3. Add this repository URL:

   ```text
   https://github.com/Adya84/Marketplace-Shop-Sync-eBay-Etsy-Shopify
   ```

4. Close the repository dialog and refresh the App Store if necessary.
5. Select **Shop Sync**, choose **Install**, and wait for the image to build.
6. Start the app and enable **Start on boot**, **Watchdog**, **Auto update** and **Show in sidebar** as required.
7. Open **Shop Sync** from the Home Assistant sidebar.

Home Assistant previously called this type of package an add-on. Current Home Assistant versions display it under **Apps**. Shop Sync is a custom Home Assistant app, not a HACS integration. It needs its own container for background jobs, API connections and persistent storage.

### 2. Create and install the Shopify app

1. Open the [Shopify Dev Dashboard](https://dev.shopify.com/dashboard) and select **Create app**.
2. Name the app **ShopSync**.
3. Open **Versions** and select **Create version**.
4. In **API access > Scopes**, enter exactly:

   ```text
   write_inventory,read_locations,write_products
   ```

5. Leave **Optional scopes** empty and do not enable the legacy install flow.
6. Release the version and confirm that it is marked **Active**.
7. Install the app into the destination Shopify store and approve its permissions.
8. Copy the app's **Client ID** and **Client secret** and keep both private.
9. Find the permanent `.myshopify.com` store domain.
10. Enter the store domain, Client ID and Client secret in Shop Sync and select **Test and save**.

Shopify should show green **Connected**. Saved secret fields intentionally appear blank after refresh. Shop Sync exchanges the client credentials for short-lived Admin API tokens and renews them automatically.

### 3. Create and connect the eBay application

1. Create or open the production application in the eBay Developer Program.
2. Open **User Tokens / Get a Token from eBay via Your Application** and configure an eBay Redirect URL (RuName).
3. Set the display title to **Shop Sync** and enable application branding if desired.
4. Configure a public HTTPS privacy-policy URL. This repository includes [PRIVACY.md](PRIVACY.md).
5. Configure the accepted and declined authorization URLs for the Shop Sync callback endpoint used by your deployment.
6. Select **OAuth (new security)**.
7. Select the basic API scope and **Sell Inventory** scope.
8. Save the redirect configuration and retain the generated **RuName**.
9. In Shop Sync enter the eBay **App ID (Client ID)**, **Cert ID (Client secret)** and **RuName**, then select **Connect eBay**.
10. Complete the official eBay consent screen.
11. After eBay redirects to the configured callback, copy the **full callback URL** from the browser address bar.
12. Return to Shop Sync, paste it into **eBay callback URL**, and select **Finish eBay connection**.

Shop Sync validates the single-use OAuth state, exchanges the authorization code with eBay and stores the resulting credentials in its protected local credential store. It then renews the short-lived eBay access token automatically using the refresh token.

**Keep the Cert ID, access token and refresh token private. Never put them in screenshots, chat messages, GitHub issues or commits.** The RuName identifies the configured redirect and is required by the OAuth flow.

### 4. Create and connect the Etsy seller app

1. Sign in to the [Etsy Developer Portal](https://www.etsy.com/developers/) with the Etsy account that owns the shop.
2. Create a seller app.
3. Add this exact callback URL:

   ```text
   https://adya84.github.io/Marketplace-Shop-Sync-eBay-Etsy-Shopify/etsy-callback.html
   ```

4. Save the callback URL and keep the keystring and shared secret private.
5. Enter both values in Shop Sync and select **Connect Etsy**.
6. Approve the official Etsy consent screen. Shop Sync requests `listings_r`, `listings_w`, and `shops_r`.
7. On the **Etsy approved** callback page, select **Copy authorization result**.
8. Paste it into **Authorization result** in Shop Sync and select **Finish Etsy connection**.

Shop Sync discovers the Etsy Shop ID automatically and renews its access token when required.

### 5. TikTok Shop connection

1. Create a TikTok Shop app in TikTok Shop Partner Center and request `seller.authorization.info` and `seller.product.basic`.
2. Complete TikTok's app review. A development app can only authorise development shops; a live seller shop cannot connect until TikTok approves and publishes the app.
3. Authorise the seller shop and obtain its seller access token.
4. Run **Get Authorized Shops** in TikTok's API testing tool and copy the selected shop's `cipher` value.
5. In Shop Sync, enter the app key, app secret, seller access token and shop cipher, then select **Test and save**.
6. Select **Import TikTok Shop listings**.

TikTok credentials are stored in Shop Sync's local credential store. Never paste an app secret or access token into chat, screenshots, issues or logs.

### 6. Import listings and create Shopify drafts

1. Connect Shopify and at least one source marketplace.
2. Select the applicable import button under **Import catalogues**.
3. Monitor the **Activity** table until the import completes.
4. Review imported products and any entries under **Review duplicate titles**.
5. Start with one product and select **Create Shopify draft**.
6. Verify the resulting draft in Shopify Admin, including title, description, photos, variants, SKUs, prices and inventory.
7. When satisfied, select multiple products in Shop Sync to queue additional Shopify drafts.

Shop Sync deliberately creates drafts rather than immediately publishing products.

### 7. Update Shop Sync

1. Open **Home Assistant > Settings > Apps > Shop Sync**.
2. When **Update available** appears, select **Update**.
3. Restart Shop Sync after the update.
4. Reopen its sidebar page and retry the operation.

If Home Assistant still shows the installed and latest versions as identical, refresh the custom app repository and check again.

## Connection reference

### eBay

Shop Sync `0.0.23` uses eBay's OAuth authorization-code flow rather than requiring you to manually generate and repeatedly replace a short-lived production user token.

Provide the following through the Shop Sync interface:

- **App ID (Client ID)**
- **Cert ID (Client secret)**
- **RuName (eBay Redirect URL name)**

Shop Sync opens the official eBay authorization page with the basic API and Sell Inventory scopes. After approval, paste the full returned callback URL into Shop Sync. The app checks the OAuth state, exchanges the code, validates the seller connection and stores the refresh token so future eBay imports can renew the access token automatically.

### Shopify

Required Shopify scopes:

```text
write_products,write_inventory,read_locations
```

Provide the `.myshopify.com` store domain, Client ID and Client secret. Shop Sync obtains and renews short-lived Admin API tokens automatically.

### Etsy

Use this redirect URI:

```text
https://adya84.github.io/Marketplace-Shop-Sync-eBay-Etsy-Shopify/etsy-callback.html
```

Enter the keystring and shared secret, select **Connect Etsy**, approve Etsy, copy the authorization result and finish the connection in Shop Sync. Shop Sync validates the state and PKCE verifier, discovers the Shop ID and renews the access token automatically.

## Duplicate-title review

Shop Sync imports the Shopify master catalogue alongside source marketplaces. Duplicate-title matching ignores capitalisation, punctuation and repeated spaces. Potential duplicates are held for review and cannot be submitted through the affected Shopify draft route until approved for that destination.

## Troubleshooting

- **eBay connection expired while authorising:** select **Connect eBay** again and complete the flow within 15 minutes.
- **eBay callback reports a state mismatch:** discard that callback and start a fresh eBay connection. Do not reuse an old callback URL.
- **eBay callback has no authorization code:** make sure you copied the full URL after approving access, including its query string.
- **eBay import later reports authentication failure:** reconnect eBay if the refresh token has expired or access has been revoked in the eBay account.
- **Shopify says `write_products` is required:** verify the active Shopify app version contains `write_products`, reinstall the Shopify app to approve that version, restart Shop Sync, and retry.
- **Etsy authorization gives an error:** begin a fresh Etsy connection because authorization codes are single-use.
- **Connection fields are blank after refresh:** this is intentional for secrets. Check the green/red connection status rather than expecting saved secrets to be displayed.
- **A Shopify job failed after creating a draft:** check Shopify for the draft before retrying.

## Data and security

- The SQLite database and installation key are stored in the Home Assistant app's private persistent configuration directory.
- Marketplace credentials are stored through Shop Sync's installation-specific authenticated credential wrapper.
- OAuth access and refresh tokens are not returned by the status API or intentionally written to application logs.
- eBay Cert IDs, access tokens and refresh tokens must never be committed to this repository or posted publicly.
- Saved secret fields intentionally remain blank when the dashboard is reloaded.
- Uninstalling the app may not remove persistent app data automatically; inspect Home Assistant app data and backups when retiring an installation.

See [PRIVACY.md](PRIVACY.md) for Shop Sync's privacy policy.

## Development

The service uses Python, FastAPI, SQLite and marketplace APIs.

```bash
cd marketplace_bridge
python -m pip install -r requirements.txt pytest
BRIDGE_DATA_DIR=./data python -m uvicorn app.main:app --reload --port 8099
pytest app/tests
```

The repository root is a Home Assistant custom app repository. The installable app is in `marketplace_bridge/`.

## Roadmap

1. Hosted eBay callback handling to remove the manual callback-copy step
2. Preview and validation before Shopify export
3. Bulk export improvements, rate limiting and retries
4. Shopify-master stock reconciliation and eBay order ingestion
5. Etsy export and additional transfer directions
6. Multi-merchant OAuth, tenant isolation and onboarding
7. Optional HACS companion exposing Home Assistant entities and actions

## Support

Use [GitHub Issues](https://github.com/Adya84/Marketplace-Shop-Sync-eBay-Etsy-Shopify/issues) for reproducible bugs and feature requests. Remove tokens, personal data, order details and customer information from logs before attaching them.

## Licence

Copyright (C) 2026 Adrian Apel. All rights reserved.

Shop Sync is provided under the [Shop Sync Home Assistant App Licence](LICENSE). It can be used free of charge on your own Home Assistant installation to manage marketplace accounts and stores you own or are authorised to operate. Redistribution, rebranding, resale, publication of modified versions, paid hosting and inclusion in paid products or services require prior written permission.
