# Shop Sync eBay + Etsy + Shopify OAuth broker

This service keeps the Shop Sync publisher **eBay client secret**, **Etsy shared secret** and **Shopify client secret** off end-user Home Assistant installations.

Normal Shop Sync users do not need an eBay Developer account, Etsy developer application, or Shopify app credentials. The Home Assistant add-on asks the hosted broker for the official marketplace/store authorization URL, the seller signs in and grants consent, and the broker performs sensitive OAuth/token work using publisher credentials stored only on Cloudflare.

## Normal users do not configure this

The broker is operated centrally for Shop Sync. End users should not create their own broker or enter publisher API credentials into Home Assistant.

A normal connection flow is:

1. Install/update Shop Sync.
2. Select **Connect eBay**, **Connect Etsy** or **Connect Shopify**.
3. Sign in to the seller/store account.
4. Approve Shop Sync.
5. Copy the short-lived authorization result from the hosted callback page.
6. Paste it into Shop Sync and finish the connection.

For Shopify, the user first enters the permanent `.myshopify.com` store domain so the broker can open the correct store authorization page.

## Production deployment

Production broker:

```text
https://shop-sync-ebay-oauth.graffidoodle.workers.dev
```

Health check:

```text
GET https://shop-sync-ebay-oauth.graffidoodle.workers.dev/health
```

Expected response when all providers are configured:

```json
{"status":"ok","configured":true,"ebay_configured":true,"etsy_configured":true,"shopify_configured":true}
```

If a provider is false, verify the active Cloudflare Worker version contains the matching variables/secrets and is receiving 100% production traffic.

## Required Cloudflare variables and secrets

```text
BROKER_SIGNING_SECRET=<long random secret>
EBAY_CLIENT_ID=<production App ID / Client ID>
EBAY_CLIENT_SECRET=<production Cert ID / Client secret>
EBAY_RUNAME=<production OAuth-enabled RuName>
ETSY_KEYSTRING=<production Etsy keystring>
ETSY_SHARED_SECRET=<production Etsy shared secret>
SHOPIFY_CLIENT_ID=<production Shopify app Client ID>
SHOPIFY_CLIENT_SECRET=<production Shopify app client secret>
```

Recommended Cloudflare types:

- `BROKER_SIGNING_SECRET` — Secret.
- `EBAY_CLIENT_ID` — Secret.
- `EBAY_CLIENT_SECRET` — Secret.
- `EBAY_RUNAME` — Text.
- `ETSY_KEYSTRING` — Secret.
- `ETSY_SHARED_SECRET` — Secret.
- `SHOPIFY_CLIENT_ID` — Secret.
- `SHOPIFY_CLIENT_SECRET` — Secret.

Never commit the real values to GitHub, screenshots, issues, logs or code distributed to Home Assistant users.

## eBay Developer configuration

The publisher's production RuName should request:

```text
https://api.ebay.com/oauth/api_scope
https://api.ebay.com/oauth/api_scope/sell.inventory
```

Set both **Auth accepted URL** and **Auth declined URL** to:

```text
https://shop-sync-ebay-oauth.graffidoodle.workers.dev/api/ebay/oauth/callback
```

## Etsy Developer configuration

Register the production callback URL:

```text
https://shop-sync-ebay-oauth.graffidoodle.workers.dev/api/etsy/oauth/callback
```

Shop Sync requests:

```text
listings_r listings_w shops_r
```

Etsy OAuth uses PKCE with `S256`. The publisher keystring/shared secret stay on the broker. Etsy Open API reads are proxied through the broker so the required publisher `x-api-key` value is never shipped to end-user Home Assistant installations.

## Shopify Developer configuration

The active Shop Sync Shopify app version should use:

```text
App URL:
https://shop-sync-ebay-oauth.graffidoodle.workers.dev

Allowed redirection URL:
https://shop-sync-ebay-oauth.graffidoodle.workers.dev/api/shopify/oauth/callback

Required scopes:
write_inventory,read_locations,write_products
```

The app is not embedded in Shopify Admin for the Home Assistant flow.

The broker validates the supplied shop domain as a permanent `.myshopify.com` domain. Shopify redirects back to the broker with `code`, `state`, `shop` and `hmac`. The broker verifies Shopify's HMAC with `SHOPIFY_CLIENT_SECRET` before creating the signed Shop Sync authorization result. The authorization code is then exchanged server-side for the store access token.

The Shopify store access token is returned only to the requesting Shop Sync installation and stored in that user's encrypted add-on data. Shopify Admin API calls are then made from Shop Sync using that token; the publisher client secret is not required for normal API requests.

## Public broker endpoints

### eBay

- `POST /api/ebay/oauth/start` — returns the official eBay authorization URL.
- `GET /api/ebay/oauth/callback` — eBay accepted/declined callback page.
- `POST /api/ebay/oauth/exchange` — verifies the signed result and exchanges the code for seller tokens.
- `POST /api/ebay/oauth/refresh` — renews a short-lived seller access token using the refresh token plus broker-issued proof.

### Etsy

- `POST /api/etsy/oauth/start` — returns the official Etsy PKCE authorization URL.
- `GET /api/etsy/oauth/callback` — Etsy callback page and signed authorization result.
- `POST /api/etsy/oauth/exchange` — verifies the signed result and exchanges the code using the derived PKCE verifier.
- `POST /api/etsy/oauth/refresh` — renews Etsy access credentials using broker-issued refresh proof.
- `POST /api/etsy/api/get` — performs authorised Etsy Open API GET requests while keeping the publisher shared secret server-side.

### Shopify

- `POST /api/shopify/oauth/start` — accepts `shop` and Shop Sync `state`, validates the `.myshopify.com` domain and returns the Shopify authorization URL.
- `GET /api/shopify/oauth/callback` — validates the Shopify callback HMAC and returns a signed short-lived authorization result.
- `POST /api/shopify/oauth/exchange` — validates the signed result and exchanges the Shopify authorization code for the store access token.

### Service

- `GET /health` — reports provider configuration without exposing secret values.

## Security model

- eBay Client Secret, Etsy Shared Secret and Shopify Client Secret exist only on the hosted broker.
- Sellers authenticate only on official marketplace/store sign-in and consent pages.
- Shop Sync never asks for seller/store passwords.
- Callback results are signed with `BROKER_SIGNING_SECRET` and expire after about 15 minutes.
- The Home Assistant add-on validates the original OAuth `state` before accepting a result.
- Shopify also validates that the returned store matches the store that started the connection.
- Shopify callback HMAC is verified on the broker before a result is issued.
- Seller/store access credentials are stored in that user's local encrypted Shop Sync installation.
- eBay and Etsy refresh requests use broker-issued proofs.
- Etsy API proxy requests use a broker key bound to the current access token.
- HTTPS is required in production.
- Protect the Cloudflare account with MFA.
- Rotate the broker signing secret and affected publisher credentials if a secret may have leaked.

## Cloudflare deployment checklist

1. Deploy the current Worker code containing eBay, Etsy and Shopify routes.
2. Add all required variables/secrets.
3. Promote the newest Worker version to 100% production traffic.
4. Open `/health` and confirm `ebay_configured:true`, `etsy_configured:true` and `shopify_configured:true`.
5. Verify the eBay accepted/declined URLs.
6. Verify the Etsy callback URL.
7. Verify the active Shopify app version App URL, redirect URL and required scopes.
8. Update Shop Sync to `0.0.30` or later.
9. Test one eBay, Etsy and Shopify connection before announcing the release.
10. Run a small import and one Shopify draft creation before a larger catalogue transfer.

## Alternate/local Python implementation

The Python implementation in this folder documents part of the broker protocol and can be used for local testing or alternate hosting:

```bash
cd oauth_broker
python -m pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8080
```

The production Cloudflare Worker may be implemented separately as long as it preserves the endpoint contract and security properties and keeps publisher secrets server-side only.
