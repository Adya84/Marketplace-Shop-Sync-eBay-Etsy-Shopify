# TikTok Seller Center form observations

Observed in the signed-in UK Seller Center on 2026-10-27. These observations
describe browser controls, not a completed publishing integration.

Adrian identified wood chopping boards as the usual product category. Searching
`chopping` in the category picker returned exactly:

**Kitchenware > Kitchen Knives > Chopping Boards**

Selecting that result exposes sales and shipping fields. Material is a separate
attribute, not a fourth category level. Do not infer a specific wood species,
brand, package weight, compliance declaration or product identifier.

## Observed controls

- New product URL: `https://seller-uk.tiktok.com/product/create?channel=manage&shop_region=GB`
- Product name: `input[data-id="product.publish.product_name"]` (255 characters).
- Main photos: `#preview-product-image input[type=file]`, JPEG/PNG, multiple.
  The separate image input in the description editor is not the main uploader.
- Category wrapper: `[data-id="product.publish.category"]`; selected text is
  `Kitchenware - Kitchen Knives - Chopping Boards`.
- Brand: `#preview-product-brand`, input placeholder `Select a brand`.
- Material attribute: `[data-better-log-outer-key="product_property_normal.100701"]`.
- Description: `#preview-product-description .ProseMirror[contenteditable=true]`.
- Sales section: `#preview-sale-information`. Fixed price is initially selected.
- Add variations is a switch inside the sales section. It supports up to three
  variations. Variation name placeholder: `Select or enter a variation`.
  Value placeholder: `Enter an option` (50 characters). Dynamic numeric suffixes
  in `data-id` and `id` must not be hardcoded.
- Variation controls include `Add option`, `Add variation`, and `SKU options`.
- Stock/retail price/Seller SKU are separate row columns. Bulk Quantity and
  Retail price inputs appear above the row: do not confuse them with row values.
- Weight wrapper: `[data-id="product.publish.package_weight"]`, numeric input
  placeholder `Enter the parcel weight`. Unit is currently `Grams (g)`; the
  category populated 1,225 automatically. This is not a verified product weight.
- Parcel dimension inputs have placeholders `Height`, `Width`, `Length`, in cm.
- Compliance controls include manufacturer, responsible person and safety warning.
- Final actions are `Save as draft` and `Submit for review`.

The Listing tool now has a separate **Fill TikTok form from this listing**
action. It uses saved TikTok overrides/defaults and fills a single-SKU form,
including photos, stock, price and explicit parcel measurements. Preparation
returns `needs_review`, never a remote product ID or a publishing success. It
does not use the save or submit buttons. The regular Publish to all path still
blocks TikTok automatic publishing.

Transfer preflight rejects variations, non-GBP prices, fractional pennies,
out-of-range stock/weight/dimensions, missing photos and existing remote product
mappings. The browser adapter checks for unfinished product, sales, category,
brand or parcel data before changing the form. Matching preselected category
and parcel settings are allowed; different values must be reviewed or cleared.
An unknown packed weight may be omitted for this unsaved transfer. In that case
the adapter explicitly clears TikTok's suggested weight and verifies it stayed
blank. A product's bare weight must not be substituted for a packed measurement.
This clearing applies to suggestions introduced when the transfer selects a
category in a fresh blank form. An already-open form with a nonempty weight
requires manual checking/clearing first: its existing weight cannot reliably be
distinguished from a value entered by the seller and will not be overwritten.
The browser and order scan share a lock, held until Selenium's worker thread
finishes even when cancellation occurs. Interrupted preparation requires browser
review after restart and is never marked as published.

Automated tests cover transfer planning, occupied-form guards, snapshot/override
use, route protection and review outcomes. Live transfer acceptance has not yet
been performed: no product details or photos were submitted during development,
and neither final action was used. Image completion selectors, variant row
mapping, submission result capture and existing-product updates still need live
acceptance or implementation before TikTok is enabled in Publish to all.
Unknown or ambiguous controls must block rather than guess.
