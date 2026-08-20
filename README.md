# Shop Sync: eBay, Etsy and Shopify

[![Licence](https://img.shields.io/badge/licence-Shop%20Sync%20Personal%20%26%20Store%20Use-red.svg)](LICENSE)

<p align="center">
  <img src="marketplace_bridge/logo.png" alt="Shop Sync marketplace synchronisation logo" width="420">
</p>

Shop Sync is an early-stage Home Assistant OS app for transferring marketplace listings. Version `0.0.19` implements **eBay UK or Etsy to Shopify**, imports the Shopify master catalogue, and adds destination-specific duplicate-title review.

> [!IMPORTANT]
> This is a development preview. Test with a small number of listings and review every Shopify draft before publishing it. Continuous stock/order synchronisation and multi-user onboarding are not implemented yet.

## What version 0.0.19 does

- Reads active listings from the connected eBay UK seller account.
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
- Renews Etsy OAuth access tokens automatically when a refresh token is available.
- Guides Etsy sign-in with PKCE, validates single-use state and discovers the authorised Shop ID automatically.
- Provides an optional **Buy me a beer** button linked directly to the Graffidoodle PayPal page.
- Displays an Adrian Apel copyright notice and links to the Shop Sync licence.
- Allows multiple imported products to be selected and queued as Shopify drafts together.
- Moves successfully created Shopify drafts from **Ready to send** into a separate **Completed** section.
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
- Guided eBay OAuth onboarding for other sellers
- A HACS companion integration

The available draft creation routes in `0.0.19` are eBay UK to Shopify and Etsy to Shopify. Shopify catalogue import and shared duplicate review are now included; Shopify-to-Etsy and Shopify-to-eBay draft creation are the next routes.

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

   `write_products` permits draft creation, `write_inventory` permits stock updates, and `read_locations` lets Shop Sync select the store's inventory location.
5. Leave **Optional scopes** empty and do not enable the legacy install flow.
6. Release the version and confirm that it is marked **Active**.
7. From the app overview, select **Install app**, choose the destination Shopify store and approve the requested permissions.
8. Open the app's **Settings** and copy its **Client ID** and **Client secret**. Keep both private.
9. Find the store's permanent domain under Shopify store settings. It must end in `.myshopify.com`; do not use the public storefront domain.
10. In Home Assistant, open **Shop Sync** and enter the store domain, Client ID and Client secret in the Shopify panel. Select **Test and save**.

Shopify should show a green **Connected** status. Saved secret fields intentionally appear blank after a page refresh; green still means they are stored. Shop Sync exchanges the client credentials for short-lived Admin API tokens and renews them automatically.

If Shopify scopes are changed later, releasing a version is not enough. Uninstall ShopSync from **Shopify > Settings > Apps and sales channels**, install it again from the Dev Dashboard, approve the permissions, and restart the Home Assistant Shop Sync app to clear its cached token. Imported products remain in Home Assistant.

### 3. Create and connect the Etsy seller app

1. Sign in to the [Etsy Developer Portal](https://www.etsy.com/developers/) with the Etsy account that owns the shop.
2. Choose **Create a seller app**. If the form flashes and disappears in Chrome, use Microsoft Edge or another clean browser session.
3. After Etsy creates the app, open its callback URL settings and add this exact HTTPS address:

   ```text
   https://adya84.github.io/Marketplace-Shop-Sync-eBay-Etsy-Shopify/etsy-callback.html
   ```

4. Save the callback URL.
5. Copy the Etsy app's **keystring** and **shared secret**. Keep them private.
6. In Home Assistant, enter both values in the Etsy panel and select **Connect Etsy**.
7. Approve the official Etsy consent screen. Shop Sync requests `listings_r`, `listings_w`, and `shops_r`; write access is needed for the upcoming Shopify-to-Etsy draft route. Existing users must reconnect Etsy once after installing 0.0.19 to grant the added scope.
8. On the **Etsy approved** callback page, select **Copy authorization result**.
9. Return to Home Assistant, paste it into **Authorization result**, and select **Finish Etsy connection**.

Etsy should now show green **Connected**. The authorization result and Etsy code are single-use. If the connection attempt fails before completion, select **Connect Etsy** again and use a new result. Shop Sync discovers the Etsy Shop ID automatically and renews its access token when required.

### 4. Import Etsy listings

1. Confirm that Etsy and Shopify both show green **Connected**.
2. Select **Import Etsy listings**.
3. Watch the **Activity** table. Shop Sync first finds the active listings and then downloads each listing's description, full-size images, inventory, variations, SKUs, prices and quantities.
4. Wait for the job to show **complete**. Imported listings then appear in the **Products** table.
5. Use **Clear activity** to remove completed and failed activity records. It does not remove products or running jobs.

### 5. Create and verify a Shopify draft

1. Start with one simple imported listing and select **Create Shopify draft** beside it.
2. After verifying the first draft, tick any additional products you want, or use **Select all**, then select **Create selected drafts**.
3. Wait for the Shopify export job to complete.
4. In Shopify Admin, open **Products** and inspect the new draft.
5. Check its title, description, full-size images and image order, variations, variation images where Etsy supplied associations, SKUs, prices and stock quantities.
6. Publish it manually only after the draft is correct.

Shop Sync uses a stable source-specific Shopify handle, so retrying the same listing updates the same draft instead of intentionally creating another product.

### 6. Update Shop Sync

1. Open **Home Assistant > Settings > Apps > Shop Sync**.
2. When **Update available** appears, select **Update**.
3. Restart Shop Sync after the update.
4. Reopen its sidebar page and retry the operation.

If Home Assistant still shows the installed and latest versions as identical, refresh the custom app repository and check again. GitHub versions use the form `0.0.11`, not `0.11`.

### 7. Troubleshooting

- **Shopify says `write_products` is required:** verify the active Shopify app version contains `write_products`, reinstall the Shopify app to approve that version, restart Shop Sync, and retry.
- **Shopify says `@idempotent` is required:** update Shop Sync to version `0.0.11` or later.
- **Etsy returns HTTP 400 with `includes=Images,Inventory`:** update Shop Sync to version `0.0.9` or later; current Etsy versions fetch inventory from its dedicated endpoint.
- **Etsy authorization gives Internal Server Error:** update Shop Sync to version `0.0.8` or later and begin a fresh Etsy connection because the previous authorization code cannot be reused.
- **Connection fields are blank after refresh:** this is intentional for secrets. Check the green/red connection status rather than expecting saved secrets to be displayed.
- **A Shopify job failed after creating a draft:** check Shopify for the draft before retrying. Current versions use the same stable product handle, although media from a partially completed older attempt should still be reviewed for duplication.

## Connect eBay

Version `0.0.19` requires an eBay production OAuth user access token from an eBay Developer application. The token must be authorised for the seller account and permit access to its listings.

Enter the token on the Shop Sync page and select **Test and save**. The app validates it by requesting the account's active listings before storing it.

Do not paste an eBay client secret into the user-token field. Guided eBay OAuth and automatic token refresh are planned for a later release.

## Shopify connection reference

Create, release and install a Shopify Dev Dashboard app for the destination store with these required scopes:

```text
write_products,write_inventory,read_locations
```

Then provide:

- The store domain in the form `your-store.myshopify.com`
- The app's Client ID
- The app's Client secret

Shop Sync exchanges these credentials directly with the store's official token endpoint. It caches the returned access token in memory and requests a replacement before expiry. The generated access token is not stored in the database. Shop Sync tests the connection by reading the store identity before saving the credentials.

## Etsy connection reference

Create an Etsy Open API v3 Seller App and add this exact redirect URI to its settings:

```text
https://adya84.github.io/Marketplace-Shop-Sync-eBay-Etsy-Shopify/etsy-callback.html
```

On the Shop Sync page, enter the app's keystring and shared secret, then select **Connect Etsy**. Approve the official Etsy consent screen with `listings_r`, `listings_w`, and `shops_r`, copy the authorization result from the Shop Sync callback page, and paste it into **Authorization result**. Shop Sync validates the state and PKCE verifier, exchanges the one-use code directly with Etsy, discovers the Shop ID, and stores the resulting credentials in its encrypted credential store. Access tokens are renewed automatically.

### Import the Shopify master catalogue and review duplicates

1. Connect Shopify, Etsy and/or eBay as described above.
2. Select each applicable button under **Import catalogues**. Re-importing refreshes existing records rather than creating another stored copy.
3. Check **Review duplicate titles**. A match ignores capitalisation, punctuation and repeated spaces.
4. Confirm that the similarly named records really are separate products before selecting **Approve for Shopify**.
5. Approval applies only to that source listing and destination. Future Etsy and eBay exporters use separate approvals, so an approval cannot leak between marketplaces.

Duplicate checks are also enforced by the API. Unreviewed duplicates cannot be submitted through the single-item or bulk Shopify draft endpoints.

The GitHub repository must have Pages enabled from the `/docs` folder on the `main` branch for the HTTPS callback to load.

## Transfer reference

1. Connect eBay or Etsy and Shopify.
2. Select the matching **Import** button and monitor the Activity table.
3. Review the imported products in Shop Sync.
4. Select **Create Shopify draft** for the required listing.
5. Review the resulting product, photos, variants, price and inventory in Shopify before publishing it.

Shop Sync creates drafts deliberately. A failed photo or inventory operation is recorded as a failed job and should be reviewed before retrying.

## Data and security

- The SQLite database and installation key are stored in the add-on's private persistent configuration directory.
- Tokens are not returned by the status API or intentionally written to application logs.
- Stored eBay and Shopify credentials are authenticated and obfuscated with an installation-specific key. This preview does not claim the protections of a dedicated secrets manager.
- Uninstalling the add-on may not remove persistent add-on data automatically; inspect Home Assistant's add-on data and backups when retiring an installation.

Never post API tokens in GitHub issues, screenshots or chat messages.

## Development

The add-on service uses Python, FastAPI, SQLite and the official eBay and Shopify APIs.

```bash
cd marketplace_bridge
python -m pip install -r requirements.txt pytest
BRIDGE_DATA_DIR=./data python -m uvicorn app.main:app --reload --port 8099
pytest app/tests
```

The repository root is a Home Assistant custom add-on repository. The installable add-on is in `marketplace_bridge/`.

## Roadmap

1. Guided eBay OAuth with hosted callback support
2. Preview and validation before Shopify export
3. Bulk draft creation, rate limiting and retries
4. Shopify-master stock reconciliation and eBay order ingestion
5. Etsy export and additional transfer directions
6. Multi-merchant OAuth, tenant isolation and onboarding
7. Optional HACS companion exposing Home Assistant entities and actions

## Support

Use [GitHub Issues](https://github.com/Adya84/Marketplace-Shop-Sync-eBay-Etsy-Shopify/issues) for reproducible bugs and feature requests. Remove tokens, personal data, order details and customer information from logs before attaching them.

## Licence

Copyright (C) 2026 Adrian Apel. All rights reserved.

Shop Sync is provided under the [Shop Sync Home Assistant App Licence](LICENSE). It can be used free of charge on your own Home Assistant installation to manage marketplace accounts and stores you own or are authorised to operate. Redistribution, rebranding, resale, publication of modified versions, paid hosting and inclusion in paid products or services require prior written permission.
