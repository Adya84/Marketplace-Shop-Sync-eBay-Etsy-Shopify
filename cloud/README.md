# Shop Sync Cloud

Hosted multi-user edition of Shop Sync. The existing Home Assistant app remains in `marketplace_bridge/` and is not replaced by this service.

## Phase 1 foundation

This first cloud milestone provides:

- public FastAPI service;
- PostgreSQL persistence;
- email/password signup and login;
- Argon2 password hashing;
- signed HTTP-only session cookies;
- CSRF protection for browser forms;
- workspace membership and tenant isolation;
- workspace-scoped marketplace connection records;
- AES-GCM helper for encrypting seller OAuth credentials at rest;
- workspace-scoped sync-job records;
- premium hosted dashboard shell;
- Docker deployment files and health endpoint.

Marketplace OAuth buttons are intentionally disabled in this first foundation commit. The next milestone will connect the existing publisher OAuth broker to the logged-in workspace so Shopify, Etsy and eBay tokens are stored against the correct tenant automatically.

## Local development

```bash
cd cloud
cp .env.example .env
```

Generate a production-style credential encryption key:

```bash
python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Set that value as `SHOPSYNC_TOKEN_ENCRYPTION_KEY` in `.env`, then run:

```bash
docker compose up --build
```

Open `http://localhost:8080`.

Health check:

```text
GET /health
```

## Production target

Initial public beta target:

```text
https://shopsync.graffidoodle.co.uk
```

For production set:

```text
SHOPSYNC_ENV=production
SHOPSYNC_BASE_URL=https://shopsync.graffidoodle.co.uk
SHOPSYNC_SECURE_COOKIES=true
SHOPSYNC_SESSION_SECRET=<long random value>
SHOPSYNC_TOKEN_ENCRYPTION_KEY=<urlsafe-base64 32-byte key>
SHOPSYNC_DATABASE_URL=<managed PostgreSQL URL>
```

Do not commit production secrets.

## Tenant model

A user belongs to a workspace through `memberships`. Marketplace credentials and sync jobs are keyed by `workspace_id`. Every cloud marketplace query must be scoped to the current authenticated workspace; never retrieve connections/products/jobs globally and filter them only in the browser.

## Next milestones

1. Wire Shopify hosted OAuth directly into the signed-in cloud workspace.
2. Wire Etsy and eBay OAuth the same way.
3. Move/shared-import the marketplace product adapters into a reusable core package.
4. Add cloud product catalogue and Shopify → Etsy/eBay reverse export workflow.
5. Add resumable background workers and scheduled stock reconciliation.
6. Add account deletion/data export/privacy endpoints required for marketplace review.
7. Add PWA manifest/service worker and Android packaging.
