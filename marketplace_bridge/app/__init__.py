"""Marketplace Bridge Home Assistant add-on."""

# Shopify can return uploaded media IDs before those files are ready to attach
# to variants. Install the narrow retry shim when the package is imported.
from . import shopify_media_retry as _shopify_media_retry  # noqa: F401
