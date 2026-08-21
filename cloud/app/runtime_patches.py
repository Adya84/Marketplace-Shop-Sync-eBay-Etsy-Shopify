from __future__ import annotations

from . import sync_routes as sync
from .catalog_service import EbayCloudClient, EtsyCloudClient, ShopifyCloudClient, save_product

_REMOVED = (
    "this listing was removed",
    "listing was removed",
    "intellectual property rights owner",
    "item has been removed",
    "item is no longer available",
    "listing is no longer available",
    "invalid item",
    "item not found",
)


def removed_ebay_listing(message: str) -> bool:
    value = str(message or "").strip().lower()
    return any(fragment in value for fragment in _REMOVED)


async def run_import(job_id: str, wid: str, provider: str) -> None:
    try:
        sync.update_job(job_id, status="running", progress="0/0", message=f"Reading {sync.LABELS[provider]} catalogue")
        cred = sync.credentials(wid, provider)
        if provider in {"etsy", "ebay"}:
            cred = await sync.broker.ensure_fresh(provider, cred)
            sync.save_credentials(wid, provider, cred)

        skipped = 0
        if provider == "shopify":
            client = ShopifyCloudClient(cred["shop_domain"], cred["access_token"])
            products = await client.list_products()
            total = len(products)
            sync.update_job(job_id, progress=f"0/{total}", message=f"Found {total} Shopify products")
            for index, product in enumerate(products, 1):
                save_product(wid, product)
                sync.update_job(job_id, progress=f"{index}/{total}", message=f"Imported {product['title']}")
        elif provider == "etsy":
            client = EtsyCloudClient(sync.broker, cred)
            ids = await client.list_active_ids()
            total = len(ids)
            sync.update_job(job_id, progress=f"0/{total}", message=f"Found {total} Etsy listings")
            for index, listing_id in enumerate(ids, 1):
                product = await client.get_product(listing_id)
                save_product(wid, product)
                sync.update_job(job_id, progress=f"{index}/{total}", message=f"Imported {product['title']}")
        elif provider == "ebay":
            client = EbayCloudClient(cred["access_token"])
            ids = await client.list_active_ids()
            total = len(ids)
            sync.update_job(job_id, progress=f"0/{total}", message=f"Found {total} eBay listings")
            for index, item_id in enumerate(ids, 1):
                try:
                    product = await client.get_product(item_id)
                except Exception as exc:
                    if removed_ebay_listing(str(exc)):
                        skipped += 1
                        sync.update_job(job_id, progress=f"{index}/{total}", message=f"Skipped unavailable eBay listing {item_id} ({skipped} skipped)")
                        continue
                    raise
                save_product(wid, product)
                sync.update_job(job_id, progress=f"{index}/{total}", message=f"Imported {product['title']}")
        else:
            raise RuntimeError("Unsupported marketplace")

        suffix = f" · skipped {skipped} unavailable listing{'s' if skipped != 1 else ''}" if skipped else ""
        sync.update_job(job_id, status="complete", message=f"{sync.LABELS[provider]} import complete{suffix}")
    except Exception as exc:
        sync.update_job(job_id, status="failed", message=str(exc))


# Existing route functions resolve this module-global at call time.
sync.run_import = run_import
