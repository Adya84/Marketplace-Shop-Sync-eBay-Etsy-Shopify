# Shop Sync eBay + Etsy OAuth broker

This service keeps the Shop Sync publisher **eBay client secret** and **Etsy shared secret** off end-user Home Assistant installations.

Normal Shop Sync users do not need an eBay Developer account or Etsy developer application. The Home Assistant add-on asks the hosted broker for the official marketplace authorization URL, the seller signs in and grants consent, and the broker performs the sensitive OAuth/token work using the publisher credentials stored only on Cloudflare.

## Normal users do not configure this

The broker is operated centrally for Shop Sync. End users should not create their own broker or enter publisher API credentials into Home Assistant.

A normal connection flow is:

1. Install/update Shop Sync.
2. Select **Connect eBay** or **Connect Etsy**.
3. Sign in to the seller account.
4. Approve Shop Sync.
5. Copy the short-lived authorization result from the hosted callback page.
6. Paste it into Shop Sync and finish the connection.

## Production deployment

Production broker:

```text
https://shop-sync-ebay-oauth.graffidoodle.workers.dev
```

Health check:

```text
GET https://shop-sync-ebay-oauth.graffidoodle.workers.dev/health
```

Expected response when both providers are configured:

```json
{"status":"ok","configured":true,"ebay_configured":true,"etsy_configured":true}
```

If either provider is false, verify the active Cloudflare Worker version contains the matching variables/secrets and is receiving 100% production traffic.

## Required Cloudflare variables and secrets

```text
BROKER_SIGNING_SECRET=<long random secret>
EBAY_CLIENT_ID=<production App ID / Client ID>
EBAY_CLIENT_SECRET=<production Cert ID / Client secret>
EBAY_RUNAME=<production OAuth-enabled RuName>
ETSY_KEYSTRING=<production Etsy keystring>
ETSY_SHARED_SECRET=<production Etsy shared secret>
```

Recommended Cloudflare types:

- `BROKER_SIGNING_SECRET` — Secret.
- `EBAY_CLIENT_ID` — Secret.
- `EBAY_CLIENT_SECRET` — Secret.
- `EBAY_RUNAME` — Text.
- `ETSY_KEYSTRING` — Secret.
- `ETSY_SHARED_SECRET` — Secret.

An old `OAUTH_REDIRECT_URI` variable is not required by the current Worker and may be removed, although leaving it present is harmless.

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

The RuName remains the eBay-generated redirect URL name supplied to eBay during OAuth. It is not the same as the callback web address.

## Etsy Developer configuration

Register the production callback URL:

```text
https://shop-sync-ebay-oauth.graffidoodle.workers.dev/api/etsy/oauth/callback
```

Shop Sync currently requests:

```text
listings_r listings_w shops_r
```

Etsy OAuth uses PKCE with `S256`. The broker derives the code verifier from the broker signing secret and the original OAuth state, so it does not need to persist a verifier between the start and exchange requests.

The Etsy publisher keystring/shared secret stay on the broker. Etsy Open API reads are proxied through the broker so the required publisher `x-api-key` value is never shipped to end-user Home Assistant installations.

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

### Service

- `GET /health` — reports provider configuration without exposing any secret values.

## Security model

- eBay Client Secret and Etsy Shared Secret exist only on the hosted broker.
- Sellers authenticate only on the marketplace's official sign-in/consent pages.
- Shop Sync never asks for seller passwords.
- Callback results are signed with `BROKER_SIGNING_SECRET` and expire after about 15 minutes.
- The Home Assistant add-on validates the original OAuth `state` before accepting a result.
- Seller access/refresh credentials are stored in that user's local Shop Sync installation.
- eBay refresh requests require a broker-issued refresh proof.
- Etsy refresh requests require an Etsy-specific broker-issued refresh proof.
- Etsy API proxy requests require a broker key bound to the current access token.
- The Etsy proxy only allows `/v3/application/` paths and blocks path traversal/absolute URL injection.
- HTTPS is required in production.
- Protect the Cloudflare account with MFA.
- Rotate the broker signing secret and affected publisher credentials if a secret may have leaked.

## Cloudflare deployment checklist

1. Deploy the current Worker code.
2. Add all required variables/secrets.
3. Promote the newest Worker version to 100% production traffic.
4. Open `/health` and confirm both `ebay_configured:true` and `etsy_configured:true`.
5. Verify the eBay accepted/declined URLs.
6. Verify the Etsy callback URL.
7. Update Shop Sync to `0.0.29` or later.
8. Test one eBay connection and one Etsy connection before announcing the release.
9. Run one small marketplace import and confirm token refresh/import behaviour before a larger catalogue transfer.

## Alternate/local Python implementation

The Python implementation in this folder documents the broker protocol and can be used for local testing or alternate hosting:

```bash
cd oauth_broker
python -m pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8080
```

The production Cloudflare Worker may be implemented separately as long as it preserves the same endpoint contract and security properties and keeps publisher secrets server-side only.
