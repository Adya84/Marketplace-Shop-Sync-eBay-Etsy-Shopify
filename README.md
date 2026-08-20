# Shop Sync: eBay, Etsy and Shopify

Shop Sync is an early-stage Home Assistant OS add-on for transferring marketplace listings. Version `0.0.4` implements the first route: **eBay UK to Shopify**, with Shopify intended to become the catalogue master.

> [!IMPORTANT]
> This is a development preview. Test with a small number of listings and review every Shopify draft before publishing it. Continuous stock/order synchronisation, Etsy support and multi-user onboarding are not implemented yet.

## What version 0.0.4 does

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

## Not implemented yet

- Automatic Shopify-to-eBay stock updates
- eBay order ingestion or automatic stock deductions
- Bulk Shopify export/approval
- Etsy import or export
- Shopify-to-eBay transfer
- Scheduled reconciliation, webhooks and automatic retries
- Guided eBay OAuth onboarding for other sellers
- A HACS companion integration

The interface may refer to broader marketplace transfers because those routes are planned, but only eBay UK to Shopify is available in `0.0.4`.

## Install in Home Assistant OS

1. In Home Assistant, open **Settings > Add-ons > Add-on Store**.
2. Open the three-dot menu and select **Repositories**.
3. Add this repository URL:

   ```text
   https://github.com/Adya84/Marketplace-Shop-Sync-eBay-Etsy-Shopify
   ```

4. Close the repository dialog and refresh the Add-on Store if necessary.
5. Select **Shop Sync**, choose **Install**, and wait for the image to build.
6. Start the add-on and enable **Show in sidebar**.
7. Open **Shop Sync** from the Home Assistant sidebar.

Shop Sync is distributed as a Home Assistant custom add-on, not through HACS. It needs its own container for background jobs, API connections and persistent storage.

## Connect eBay

Version `0.0.4` requires an eBay production OAuth user access token from an eBay Developer application. The token must be authorised for the seller account and permit access to its listings.

Enter the token on the Shop Sync page and select **Test and save**. The add-on validates it by requesting the account's active listings before storing it.

Do not paste an eBay client secret into the user-token field. Guided eBay OAuth and automatic token refresh are planned for a later release.

## Connect Shopify

Create, release and install a Shopify Dev Dashboard app for the destination store with these required scopes:

```text
write_products,write_inventory,read_locations
```

Then provide:

- The store domain in the form `your-store.myshopify.com`
- The app's Client ID
- The app's Client secret

Shop Sync exchanges these credentials directly with the store's official token endpoint. It caches the returned access token in memory and requests a replacement before expiry. The generated access token is not stored in the database. Shop Sync tests the connection by reading the store identity before saving the credentials.

## Transfer a listing

1. Connect eBay and Shopify.
2. Select **Import eBay listings** and monitor the Activity table.
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

1. Guided eBay OAuth with token refresh
2. Preview and validation before Shopify export
3. Bulk draft creation, rate limiting and retries
4. Shopify-master stock reconciliation and eBay order ingestion
5. Etsy connector and additional transfer directions
6. Multi-merchant OAuth, tenant isolation and onboarding
7. Optional HACS companion exposing Home Assistant entities and actions

## Support

Use [GitHub Issues](https://github.com/Adya84/Marketplace-Shop-Sync-eBay-Etsy-Shopify/issues) for reproducible bugs and feature requests. Remove tokens, personal data, order details and customer information from logs before attaching them.

