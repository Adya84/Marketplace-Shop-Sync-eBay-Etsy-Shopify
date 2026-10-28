# Shop Sync master listings

Enter product details and upload photos once in Shop Sync, then publish to Etsy, eBay, TikTok Shop and Shopify. Shop Sync owns the master; Shopify is a destination. Changes are local until Update all. The user asked to proceed with the whole feature without further design questions.

## Approach
Use a durable master catalogue plus destination adapters, reusing the current FastAPI app and marketplace connections. A Shopify master was considered and rejected by the user. Independent forms per shop would recreate the repetition this feature removes.

## Behaviour
Shared title, description, photos, currency, tags and SKU variants are entered once. Each selected shop inherits these values. Optional overrides and reusable defaults provide category, shipping, policies, product attributes and shop-specific pricing. Validation identifies missing data for each shop before writes. Do not silently truncate text, discard images, flatten variations or substitute stock quantities.

Save draft never writes to a marketplace. Publish to all creates or updates only explicitly selected destinations; Update all sends a saved revision to linked destinations. Track each result separately. Marketplace review/pending state is distinct from live. No cross-market atomic transaction is possible. A failure must not repeat successful creates. Persist remote IDs immediately, prevent concurrent publishes, and require reconciliation for ambiguous create responses.

Photo binaries stay in the add-on persistent data directory and are uploaded by the server to each marketplace. No publicly exposed local photo server. Access to the editor and write routes follows the existing Home Assistant Ingress boundary and CSRF protection. Existing imports, reverse export and order sync remain intact.

## Scope and constraints
Implement editor, local drafts, photo upload, variants, saved shop defaults, validation, four publishing adapters, persisted mappings and manual Update all. No continuous stock/order synchronization, automatic publishing on save, listing deletion or automatic overwriting of unrelated existing products. Marketplace credentials/permissions and seller eligibility must be present; never report a mock write as successful. Keep production shops untouched during verification. Deliver a reviewable source package; installation and live seller acceptance require the running host and credentials.

## Builder decisions
Use separate SQLite listing tables; immutable revision snapshots for publishing; deterministic internal IDs and explicit destination mappings. Per-destination failures can be retried independently. Keep the existing add-on entry point and add a Listings navigation link. Test durable state, partial failures, API payloads, upload boundaries and route authorization. Any unavailable live integration is reported explicitly.
