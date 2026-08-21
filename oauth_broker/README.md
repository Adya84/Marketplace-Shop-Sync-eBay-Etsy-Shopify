# Shop Sync eBay OAuth broker

This service keeps the Shop Sync eBay **Cert ID/client secret** off end-user Home Assistant installations.

Normal Shop Sync users never need an eBay Developer account. The Home Assistant app asks the broker for an eBay authorization URL, the user signs into eBay and grants consent, and the broker performs the confidential authorization-code and refresh-token exchanges with eBay.

## Production deployment

The production Shop Sync broker is deployed as a Cloudflare Worker at:

```text
https://shop-sync-ebay-oauth.graffidoodle.workers.dev
```

Health check:

```text
GET https://shop-sync-ebay-oauth.graffidoodle.workers.dev/health
```

The response must report `configured: true` before Shop Sync is released or tested.

## Required environment variables

```text
EBAY_CLIENT_ID=<production App ID / Client ID>
EBAY_CLIENT_SECRET=<production Cert ID / Client secret>
EBAY_RUNAME=<production OAuth-enabled RuName>
BROKER_SIGNING_SECRET=<long random value, separate from the eBay secret>
```

Keep the Client ID and RuName in deployment configuration and keep the Cert ID and broker signing secret as encrypted Cloudflare secrets. Never commit secret values to this repository.

## Required public endpoints

- `POST /api/ebay/oauth/start` — builds the official eBay consent URL using the publisher's app.
- `GET /api/ebay/oauth/callback` — eBay's accepted/declined redirect target. It produces a signed, short-lived authorization result for the user to copy.
- `POST /api/ebay/oauth/exchange` — validates the signed callback result and exchanges the eBay authorization code for seller tokens.
- `POST /api/ebay/oauth/refresh` — renews an expired seller access token. It requires both the refresh token and a broker-issued refresh proof.

## eBay Developer configuration

For the production RuName, set both **Auth accepted URL** and **Auth declined URL** to:

```text
https://shop-sync-ebay-oauth.graffidoodle.workers.dev/api/ebay/oauth/callback
```

Keep OAuth enabled and grant the scopes currently required by Shop Sync:

```text
https://api.ebay.com/oauth/api_scope
https://api.ebay.com/oauth/api_scope/sell.inventory
```

## Security notes

The client secret must exist only on the hosted broker. Do not put it in Home Assistant app defaults, JavaScript shipped to users, a public GitHub secret file, screenshots or support logs.

Callback results are signed and expire after 15 minutes. The Home Assistant app also validates its original OAuth `state`. Refresh calls require a proof derived by the broker so a raw refresh token alone cannot be submitted to the public refresh endpoint.

Use HTTPS only in production and protect the Cloudflare account with MFA. Rotate the broker signing secret and eBay Cert ID if either is suspected to have leaked.

The Python implementation in this folder documents the broker protocol and can be used for local testing or alternate hosting. The live production deployment may use an equivalent Cloudflare Worker implementation as long as these endpoints and security properties are preserved.
