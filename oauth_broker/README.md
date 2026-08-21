# Shop Sync eBay OAuth broker

This small FastAPI service keeps the Shop Sync eBay **Cert ID/client secret** off end-user Home Assistant installations.

Normal Shop Sync users never need an eBay Developer account. The Home Assistant app asks this broker for an eBay authorization URL, the user signs into eBay and grants consent, and the broker performs the confidential authorization-code and refresh-token exchanges with eBay.

## Required environment variables

```text
EBAY_CLIENT_ID=<production App ID / Client ID>
EBAY_CLIENT_SECRET=<production Cert ID / Client secret>
EBAY_RUNAME=<production OAuth-enabled RuName>
BROKER_SIGNING_SECRET=<long random value, separate from the eBay secret>
```

Never commit any of these secret values to this repository. `EBAY_CLIENT_ID` and the RuName are not equivalent to the client secret, but keeping deployment configuration together in the hosting platform is recommended.

## Run locally

```bash
cd oauth_broker
python -m pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8080
```

Check:

```text
GET /health
```

The response should report `configured: true` before Shop Sync users are sent to the service.

## Required public endpoints

- `POST /api/ebay/oauth/start` — builds the official eBay consent URL using the publisher's app.
- `GET /api/ebay/oauth/callback` — eBay's accepted/declined redirect target. It produces a signed, short-lived authorization result for the user to copy.
- `POST /api/ebay/oauth/exchange` — validates the signed callback result and exchanges the eBay authorization code for seller tokens.
- `POST /api/ebay/oauth/refresh` — renews an expired seller access token. It requires both the refresh token and a broker-issued refresh proof.

## eBay Developer configuration

For the production RuName, set both **Auth accepted URL** and **Auth declined URL** to the deployed callback URL, for example:

```text
https://shop-sync-ebay-compliance.zesty-flame-5295.chatgpt.site/api/ebay/oauth/callback
```

Keep OAuth enabled and grant the scopes currently required by Shop Sync:

```text
https://api.ebay.com/oauth/api_scope
https://api.ebay.com/oauth/api_scope/sell.inventory
```

## Security notes

The client secret must exist only on the hosted broker. Do not put it in Home Assistant add-on defaults, JavaScript, a public GitHub secret file, screenshots or support logs.

Callback results are signed and expire after 15 minutes. The Home Assistant app also validates its original OAuth `state`. Refresh calls require a proof derived by the broker so a raw refresh token alone cannot be submitted to the public refresh endpoint.

Use HTTPS only in production and protect the hosting account with MFA. Rotate the broker signing secret and eBay Cert ID if either is suspected to have leaked.
