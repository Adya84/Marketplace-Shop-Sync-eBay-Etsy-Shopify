from __future__ import annotations

import asyncio

from .shopify import ShopifyClient


_original_graphql = ShopifyClient.graphql


def _non_ready_variant_media(result: dict) -> bool:
    try:
        errors = result["productVariantAppendMedia"]["userErrors"]
    except (KeyError, TypeError):
        return False
    if not errors:
        return False
    return all(
        "non-ready media cannot be attached to variants" in str(error.get("message", "")).lower()
        for error in errors
    )


async def graphql_with_media_retry(self: ShopifyClient, query: str, variables=None):
    result = await _original_graphql(self, query, variables)

    if "productVariantAppendMedia" not in query or not _non_ready_variant_media(result):
        return result

    # Shopify processes newly uploaded images asynchronously. The media IDs can
    # be returned before the files are READY, so attaching those IDs to product
    # variants immediately can fail. Retry only this specific transient error;
    # other userErrors are returned to the normal caller unchanged.
    for delay in (1, 2, 3, 4, 5, 5):
        await asyncio.sleep(delay)
        result = await _original_graphql(self, query, variables)
        if not _non_ready_variant_media(result):
            return result

    return result


ShopifyClient.graphql = graphql_with_media_retry
