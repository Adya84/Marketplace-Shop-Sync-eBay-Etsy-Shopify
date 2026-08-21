# Shop Sync eBay OAuth broker

This service keeps the Shop Sync eBay **Cert ID/client secret** off end-user Home Assistant installations.

Normal Shop Sync users never need an eBay Developer account. The Home Assistant app asks this broker for the official eBay authorization URL, the user signs into eBay and grants consent, and the broker performs the confidential authorization-code and refresh-token exchanges with eBay.

## Normal users do not configure this

The broker is operated centrally for Shop Sync. End users should **not** create their own broker, eBay developer application, Client ID, Cert ID or RuName.

A normal user's eBay flow is simply:

1. Install/update Shop Sync.
2. Select **Connect eBay**.
3. Sign in to their own eBay seller account.
4. Approve Shop Sync.
5. Copy the short-lived authorization result from the callback page.
6. Paste it into Shop Sync and finish the connection.

## Production deployment

The production Shop Sync broker is deployed as a Cloudflare Worker at:

```text
https://shop-sync-ebay-oauth.graffidoodle.workers.dev
```

Health check:

```text
GET https://shop-sync-ebay-oauth.graffidoodle.workers.dev/health
```

The expected response is:

```json
{"status":"ok","configured":true}
```

If `configured` is `false`, verify the current active Cloudflare deployment includes all required variables/secrets. Cloudflare may create a new Worker version after variables are added; promote the newest version to 100% traffic if necessary.

## Required Cloudflare variables and secrets

The production Worker requires:

```text
EBAY_CLIENT_ID=<production App ID / Client ID>
EBAY_CLIENT_SECRET=<production Cert ID / Client secret>
EBAY_RUNAME=<production OAuth-enabled RuName>
BROKER_SIGNING_SECRET=<long random value, separate from the eBay secret>
```

Recommended Cloudflare types:

- `EBAY_CLIENT_ID` — Secret.
- `EBAY_CLIENT_SECRET` — Secret.
- `EBAY_RUNAME` — Text is sufficient.
- `BROKER_SIGNING_SECRET` — Secret.

The current Worker code does not require `OAUTH_REDIRECT_URI`; if an old deployment still contains it, it is harmless but can be removed.

Never commit any of the actual values to GitHub. Never place the eBay Cert ID/client secret in the Home Assistant app, JavaScript shipped to end users, screenshots, issues or support logs.

## eBay Developer configuration

The publisher's production RuName should have OAuth enabled and should request:

```text
https://api.ebay.com/oauth/api_scope
https://api.ebay.com/oauth/api_scope/sell.inventory
```

Set both **Auth accepted URL** and **Auth declined URL** to:

```text
https://shop-sync-ebay-oauth.graffidoodle.workers.dev/api/ebay/oauth/callback
```

The RuName itself remains the eBay-generated redirect URL name and is supplied to eBay as the OAuth `redirect_uri`. It is not the same thing as the callback web address above.

## Required public endpoints

The production broker contract is:

- `POST /api/ebay/oauth/start` — accepts Shop Sync state/environment and returns the official eBay consent URL.
- `GET /api/ebay/oauth/callback` — eBay's accepted/declined redirect target and callback page.
- `POST /api/ebay/oauth/exchange` — validates the signed callback result and exchanges the eBay authorization code for seller tokens.
- `POST /api/ebay/oauth/refresh` — renews an expired seller access token using the seller refresh token plus the broker-issued refresh proof.
- `GET /health` — reports service/configuration health without exposing secrets.

## Security model

- The eBay Client Secret exists only on the hosted broker.
- The seller authorizes Shop Sync using eBay's official consent page; Shop Sync never asks for the user's eBay password.
- Callback results are signed and expire after about 15 minutes.
- The Home Assistant app validates the original OAuth `state` before accepting the result.
- Seller access/refresh credentials are stored in that user's local Shop Sync installation, not committed to the repository.
- Refresh requests require both the seller refresh token and a broker-issued proof.
- HTTPS is required in production.
- Protect the Cloudflare account with MFA.
- Rotate the broker signing secret and eBay Cert ID if either is suspected to have leaked.

## Cloudflare deployment checklist

1. Create/deploy the Worker.
2. Add the four required variables/secrets above.
3. Promote the newest Worker version so it receives 100% traffic.
4. Open `/health` and confirm `configured:true`.
5. In eBay Developer settings, set accepted and declined URLs to the Worker callback.
6. Save the eBay redirect configuration.
7. Ensure Home Assistant Shop Sync `0.0.24` or later points at the production broker URL.
8. Test with one eBay seller account before announcing the release.

## Alternate/local implementation

The Python implementation in this folder documents the broker protocol and can be used for local testing or alternate hosting:

```bash
cd oauth_broker
python -m pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8080
```

An alternate deployment is acceptable as long as it preserves the same endpoint contract and security properties and keeps the eBay Client Secret server-side only.
