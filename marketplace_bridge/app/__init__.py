"""Marketplace Bridge Home Assistant add-on."""

# Apply runtime compatibility fixes before the FastAPI application is imported.
# This keeps the stock-writing behaviour in one place while preserving the
# existing Shopify client API used throughout Shop Sync.
from . import shopify_stock_patch as _shopify_stock_patch  # noqa: F401
