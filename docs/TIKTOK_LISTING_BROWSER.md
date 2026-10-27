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

No product details or photos were submitted, and neither final action was used.
The blank inspection form remains unsaved. Automatic filling, image completion,
variant row mapping, submission result capture and existing-product updates
still require implementation and live acceptance before TikTok is enabled in
Publish to all. Unknown or ambiguous controls must block rather than guess.
