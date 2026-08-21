from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Any
from urllib.parse import quote

import httpx

EBAY_INVENTORY_BASE = "https://api.ebay.com/sell/inventory/v1"


def norm(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(re.sub(r"[^\w]+", " ", value).split())


def option_names(product: dict) -> list[str]:
    names: list[str] = []
    for variant in product.get("variants") or []:
        for option in variant.get("options") or []:
            name = str(option.get("name") or "").strip()
            if name and name != "Title" and name not in names:
                names.append(name)
    return names


def option_map(variant: dict) -> dict[str, str]:
    return {str(o.get("name") or "").strip(): str(o.get("value") or "").strip() for o in variant.get("options") or [] if str(o.get("name") or "").strip() and str(o.get("name") or "").strip() != "Title"}


def product_skus(product: dict) -> set[str]:
    return {str(v.get("sku") or "").strip().casefold() for v in product.get("variants") or [] if str(v.get("sku") or "").strip()}


def image_keys(product: dict) -> set[str]:
    keys: set[str] = set()
    for image in product.get("images") or []:
        raw = str(image.get("url") or "").strip()
        if raw:
            keys.add(raw.casefold())
            name = raw.split("?", 1)[0].rsplit("/", 1)[-1].casefold()
            if name:
                keys.add(name)
    return keys


def existing_candidates(source_product: dict, imported_products: list[dict], destination: str) -> list[dict]:
    source_skus = product_skus(source_product)
    source_title = norm(source_product.get("title", ""))
    source_images = image_keys(source_product)
    candidates = []
    for product in imported_products:
        if product.get("source") != destination:
            continue
        overlap = sorted(source_skus & product_skus(product))
        title_match = bool(source_title and norm(product.get("title", "")) == source_title)
        photo_overlap = source_images & image_keys(product)
        if not overlap and not title_match and not photo_overlap:
            continue
        score = (100 if overlap else 0) + (20 if title_match else 0) + min(30, 10 * len(photo_overlap))
        reasons = []
        if overlap: reasons.append("SKU match")
        if title_match: reasons.append("exact title match")
        if photo_overlap: reasons.append("matching photo")
        candidates.append({"source_id": str(product.get("source_id") or ""), "title": str(product.get("title") or ""), "score": score, "reason": " + ".join(reasons), "matching_skus": overlap})
    return sorted(candidates, key=lambda row: int(row["score"]), reverse=True)


def split_etsy(product: dict) -> list[dict]:
    names = option_names(product)
    if len(names) <= 2:
        return [{"suffix": "", "kept_options": names, "variants": product.get("variants") or []}]
    kept = names[:2]
    split_names = names[2:]
    groups: dict[tuple[str, ...], list[dict]] = defaultdict(list)
    for variant in product.get("variants") or []:
        values = option_map(variant)
        groups[tuple(values.get(name, "") for name in split_names)].append(variant)
    result = []
    for key, variants in groups.items():
        parts = [f"{name}: {value}" for name, value in zip(split_names, key) if value]
        result.append({"suffix": " - " + " / ".join(parts) if parts else "", "kept_options": kept, "split_options": dict(zip(split_names, key)), "variants": variants})
    return result


def build_plan(product: dict, destination: str, defaults: dict, imported_products: list[dict], mapped_id: str = "") -> dict:
    if product.get("source") != "shopify":
        raise ValueError("Reverse sync starts from an imported Shopify product")
    if destination not in {"etsy", "ebay"}:
        raise ValueError("Destination must be Etsy or eBay")
    chunks = split_etsy(product) if destination == "etsy" else [{"suffix": "", "kept_options": option_names(product), "variants": product.get("variants") or []}]
    listings = []
    for chunk in chunks:
        title = (str(product.get("title") or "") + chunk.get("suffix", "")).strip()
        shadow = dict(product)
        shadow["title"] = title
        shadow["variants"] = chunk["variants"]
        candidates = existing_candidates(shadow, imported_products, destination)
        if mapped_id:
            candidates.insert(0, {"source_id": mapped_id, "title": "Previously mapped listing", "score": 1000, "reason": "confirmed Shop Sync mapping", "matching_skus": []})
        listings.append({"source_id": str(product.get("source_id") or ""), "title": title, "description_html": product.get("description_html") or "", "category_id": str(defaults.get("category_id") or product.get("category_id") or ""), "taxonomy_id": str(defaults.get("taxonomy_id") or ""), "tags": list(product.get("tags") or []), "images": list(product.get("images") or []), "variants": chunk["variants"], "kept_options": chunk.get("kept_options", []), "split_options": chunk.get("split_options", {}), "existing_candidates": candidates})
    required = ("taxonomy_id", "shipping_profile_id", "readiness_state_id") if destination == "etsy" else ("category_id", "merchant_location_key", "payment_policy_id", "return_policy_id", "fulfillment_policy_id")
    missing = [key for key in required if not str(defaults.get(key) or "").strip()]
    return {"destination": destination, "source_id": str(product.get("source_id") or ""), "source_title": str(product.get("title") or ""), "listing_count": len(listings), "split_for_etsy": destination == "etsy" and len(listings) > 1, "missing_defaults": missing, "listings": listings}


class EbayDraftWriter:
    def __init__(self, access_token: str, marketplace_id: str = "EBAY_GB"):
        self.headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json", "Accept": "application/json", "Content-Language": "en-GB"}
        self.marketplace_id = marketplace_id

    async def request(self, method: str, path: str, *, json_data=None) -> dict:
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.request(method, f"{EBAY_INVENTORY_BASE}{path}", headers=self.headers, json=json_data)
            if response.status_code >= 400:
                raise RuntimeError(f"eBay Inventory API {response.status_code}: {response.text[:500]}")
            return response.json() if response.content else {}

    async def create_draft(self, listing: dict, defaults: dict) -> dict:
        variants = listing.get("variants") or []
        if not variants:
            raise ValueError("Shopify product has no variants to send to eBay")
        images = [str(i.get("url") or "") for i in listing.get("images") or [] if i.get("url")]
        if not images:
            raise ValueError("eBay requires at least one product image")
        common = defaults.get("aspects") or {}
        skus = []
        for index, variant in enumerate(variants, 1):
            sku = str(variant.get("sku") or f"SHOPSYNC-{listing.get('source_id','')}-{index}").strip()
            skus.append(sku)
            aspects = {str(k): [str(v)] for k, v in common.items() if str(v).strip()}
            for name, value in option_map(variant).items():
                if value: aspects[name] = [value]
            await self.request("PUT", f"/inventory_item/{quote(sku, safe='')}", json_data={"availability": {"shipToLocationAvailability": {"quantity": max(0, int(variant.get("quantity") or 0))}}, "condition": str(defaults.get("condition") or "NEW"), "product": {"title": listing["title"][:80], "description": listing.get("description_html") or listing["title"], "aspects": aspects, "imageUrls": images}})
        group_key = None
        if len(variants) > 1:
            group_key = "shopsync-" + re.sub(r"[^a-z0-9-]+", "-", str(listing.get("source_id") or listing["title"]).lower()).strip("-")[:40]
            names = listing.get("kept_options") or option_names({"variants": variants})
            specs = []
            for name in names:
                values = list(dict.fromkeys(option_map(v).get(name) for v in variants if option_map(v).get(name)))
                if values: specs.append({"name": name, "values": values})
            group = {"title": listing["title"][:80], "description": listing.get("description_html") or listing["title"], "imageUrls": images, "variantSKUs": skus, "aspects": {str(k): [str(v)] for k, v in common.items() if str(v).strip()}, "variesBy": {"specifications": specs}}
            if names: group["variesBy"]["aspectsImageVariesBy"] = names[0]
            await self.request("PUT", f"/inventory_item_group/{quote(group_key, safe='')}", json_data=group)
        offer_ids = []
        for sku, variant in zip(skus, variants):
            offer = {"sku": sku, "marketplaceId": str(defaults.get("marketplace_id") or self.marketplace_id), "format": "FIXED_PRICE", "availableQuantity": max(0, int(variant.get("quantity") or 0)), "categoryId": str(defaults["category_id"]), "merchantLocationKey": str(defaults["merchant_location_key"]), "listingDuration": str(defaults.get("listing_duration") or "GTC"), "listingPolicies": {"paymentPolicyId": str(defaults["payment_policy_id"]), "returnPolicyId": str(defaults["return_policy_id"]), "fulfillmentPolicyId": str(defaults["fulfillment_policy_id"])}, "pricingSummary": {"price": {"value": str(variant.get("price") or "0.00"), "currency": str(defaults.get("currency") or "GBP")}}}
            if len(variants) == 1: offer["listingDescription"] = listing.get("description_html") or listing["title"]
            created = await self.request("POST", "/offer", json_data=offer)
            if created.get("offerId"): offer_ids.append(str(created["offerId"]))
        return {"offer_ids": offer_ids, "group_key": group_key, "skus": skus, "published": False}


class EtsyDraftWriter:
    def __init__(self, client: Any):
        self.client = client

    async def property_map(self, taxonomy_id: str, names: list[str]) -> dict[str, int]:
        if not names: return {}
        payload = await self.client.request("GET", f"/v3/application/seller-taxonomy/nodes/{taxonomy_id}/properties")
        rows = payload.get("results", payload if isinstance(payload, list) else [])
        result = {}
        for wanted in names:
            match = next((row for row in rows if norm(row.get("display_name") or row.get("name")) == norm(wanted)), None)
            if match and match.get("property_id"): result[wanted] = int(match["property_id"])
        return result

    async def create_or_update(self, listing: dict, defaults: dict, existing_id: str = "") -> dict:
        variants = listing.get("variants") or []
        if not variants: raise ValueError("Shopify product has no variants to send to Etsy")
        first = variants[0]
        quantity = sum(max(0, int(v.get("quantity") or 0)) for v in variants)
        form = {"quantity": max(1, quantity), "title": listing["title"][:140], "description": re.sub(r"<[^>]+>", " ", listing.get("description_html") or "").strip(), "price": str(first.get("price") or "0.01"), "who_made": str(defaults.get("who_made") or "i_did"), "when_made": str(defaults.get("when_made") or "made_to_order"), "taxonomy_id": int(defaults["taxonomy_id"]), "is_supply": bool(defaults.get("is_supply", False)), "shipping_profile_id": int(defaults["shipping_profile_id"]), "readiness_state_id": int(defaults["readiness_state_id"]), "should_auto_renew": bool(defaults.get("should_auto_renew", True)), "type": "physical"}
        if defaults.get("return_policy_id"): form["return_policy_id"] = int(defaults["return_policy_id"])
        tags = [str(tag)[:20] for tag in listing.get("tags") or [] if str(tag).strip()][:13]
        if tags: form["tags"] = tags
        if existing_id:
            result = await self.client.request("PUT", f"/v3/application/shops/{self.client.shop_id}/listings/{existing_id}", form=form)
            listing_id = existing_id
        else:
            result = await self.client.request("POST", f"/v3/application/shops/{self.client.shop_id}/listings", params={"legacy": "false"}, form=form)
            listing_id = str(result.get("listing_id") or "")
            if not listing_id: raise RuntimeError("Etsy did not return a listing ID")
        kept = listing.get("kept_options") or []
        if kept:
            props = await self.property_map(str(defaults["taxonomy_id"]), kept)
            missing = [name for name in kept if name not in props]
            if missing: raise ValueError("Etsy taxonomy does not expose variation properties for: " + ", ".join(missing))
            products = []
            for variant in variants:
                omap = option_map(variant)
                property_values = [{"property_id": props[name], "property_name": name, "values": [omap[name]]} for name in kept if omap.get(name)]
                products.append({"sku": str(variant.get("sku") or ""), "property_values": property_values, "offerings": [{"price": str(variant.get("price") or first.get("price") or "0.01"), "quantity": max(0, int(variant.get("quantity") or 0)), "is_enabled": True}]})
            await self.client.request("PUT", f"/v3/application/listings/{listing_id}/inventory", json_data={"products": products, "price_on_property": [], "quantity_on_property": [], "sku_on_property": []})
        return {"listing_id": listing_id, "state": result.get("state", "draft")}
