from __future__ import annotations

import html
import re
import unicodedata
from collections import defaultdict
from typing import Any
from urllib.parse import quote

import httpx


EBAY_INVENTORY_BASE = "https://api.ebay.com/sell/inventory/v1"


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(re.sub(r"[^\w]+", " ", value).split())


def option_names(product: dict) -> list[str]:
    names: list[str] = []
    for variant in product.get("variants") or []:
        for option in variant.get("options") or []:
            name = str(option.get("name") or "").strip()
            if name and name not in names and name != "Title":
                names.append(name)
    return names


def variant_option_map(variant: dict) -> dict[str, str]:
    return {
        str(option.get("name") or "").strip(): str(option.get("value") or "").strip()
        for option in variant.get("options") or []
        if str(option.get("name") or "").strip() and str(option.get("name") or "").strip() != "Title"
    }


def product_skus(product: dict) -> set[str]:
    return {
        str(variant.get("sku") or "").strip().casefold()
        for variant in product.get("variants") or []
        if str(variant.get("sku") or "").strip()
    }


def find_existing_candidates(source_product: dict, imported_products: list[dict], destination: str) -> list[dict]:
    """Rank imported destination listings by SKU first, then exact normalised title."""
    source_skus = product_skus(source_product)
    source_title = _norm(source_product.get("title", ""))
    candidates: list[dict] = []
    for row in imported_products:
        if row.get("source") != destination:
            continue
        product = row.get("product") or row
        candidate_skus = product_skus(product)
        overlap = sorted(source_skus & candidate_skus)
        title_match = source_title and _norm(product.get("title", row.get("title", ""))) == source_title
        if not overlap and not title_match:
            continue
        score = 100 if overlap else 60
        if title_match:
            score += 20
        candidates.append({
            "source_id": str(product.get("source_id") or row.get("source_id") or ""),
            "title": str(product.get("title") or row.get("title") or ""),
            "score": score,
            "reason": "SKU match" if overlap else "exact title match",
            "matching_skus": overlap,
        })
    return sorted(candidates, key=lambda item: item["score"], reverse=True)


def _split_etsy(product: dict) -> list[dict]:
    """Etsy allows two variation properties; split on any remaining Shopify options."""
    names = option_names(product)
    if len(names) <= 2:
        return [{"suffix": "", "kept_options": names, "variants": product.get("variants") or []}]

    kept = names[:2]
    split_names = names[2:]
    groups: dict[tuple[str, ...], list[dict]] = defaultdict(list)
    for variant in product.get("variants") or []:
        values = variant_option_map(variant)
        key = tuple(values.get(name, "") for name in split_names)
        groups[key].append(variant)

    result = []
    for key, variants in groups.items():
        parts = [f"{name}: {value}" for name, value in zip(split_names, key) if value]
        result.append({
            "suffix": " - " + " / ".join(parts) if parts else "",
            "kept_options": kept,
            "split_options": dict(zip(split_names, key)),
            "variants": variants,
        })
    return result


def build_reverse_plan(product: dict, destination: str, defaults: dict, imported_products: list[dict]) -> dict:
    if product.get("source") != "shopify":
        raise ValueError("Reverse sync currently starts from an imported Shopify product")
    if destination not in {"etsy", "ebay"}:
        raise ValueError("Reverse sync destination must be Etsy or eBay")

    chunks = _split_etsy(product) if destination == "etsy" else [
        {"suffix": "", "kept_options": option_names(product), "variants": product.get("variants") or []}
    ]
    listings = []
    for chunk in chunks:
        title = (str(product.get("title") or "") + chunk.get("suffix", "")).strip()
        listing = {
            "title": title,
            "description_html": product.get("description_html") or "",
            "category_id": str(defaults.get("category_id") or product.get("category_id") or ""),
            "taxonomy_id": str(defaults.get("taxonomy_id") or ""),
            "tags": list(product.get("tags") or []),
            "images": list(product.get("images") or []),
            "variants": chunk["variants"],
            "kept_options": chunk.get("kept_options", []),
            "split_options": chunk.get("split_options", {}),
        }
        shadow = dict(product)
        shadow["title"] = title
        shadow["variants"] = chunk["variants"]
        listing["existing_candidates"] = find_existing_candidates(shadow, imported_products, destination)
        listings.append(listing)

    missing = []
    if destination == "etsy":
        for key in ("taxonomy_id", "shipping_profile_id", "readiness_state_id"):
            if not str(defaults.get(key) or "").strip():
                missing.append(key)
    else:
        for key in ("category_id", "merchant_location_key", "payment_policy_id", "return_policy_id", "fulfillment_policy_id"):
            if not str(defaults.get(key) or "").strip():
                missing.append(key)

    return {
        "destination": destination,
        "source_id": str(product.get("source_id") or ""),
        "source_title": str(product.get("title") or ""),
        "listing_count": len(listings),
        "split_for_etsy": destination == "etsy" and len(listings) > 1,
        "missing_defaults": missing,
        "listings": listings,
    }


class EbayInventoryWriter:
    """Create unpublished Inventory API offers. Publishing is deliberately a separate future action."""

    def __init__(self, access_token: str, marketplace_id: str = "EBAY_GB"):
        self.access_token = access_token
        self.marketplace_id = marketplace_id
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Content-Language": "en-GB",
        }

    async def _request(self, method: str, path: str, *, json_data=None, params=None) -> dict:
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.request(method, f"{EBAY_INVENTORY_BASE}{path}", headers=self.headers, json=json_data, params=params)
            if response.status_code >= 400:
                raise RuntimeError(f"eBay Inventory API {response.status_code}: {response.text[:500]}")
            if not response.content:
                return {}
            return response.json()

    @staticmethod
    def _aspect_map(variant: dict, common: dict | None = None) -> dict[str, list[str]]:
        aspects = {str(k): [str(v)] for k, v in (common or {}).items() if str(v).strip()}
        for name, value in variant_option_map(variant).items():
            if value:
                aspects[name] = [value]
        return aspects

    async def create_draft(self, listing: dict, defaults: dict) -> dict:
        variants = listing.get("variants") or []
        if not variants:
            raise ValueError("Shopify product has no variants to send to eBay")
        images = [str(image.get("url") or "") for image in listing.get("images") or [] if image.get("url")]
        if not images:
            raise ValueError("eBay requires at least one product image")
        common_aspects = defaults.get("aspects") or {}
        condition = str(defaults.get("condition") or "NEW")
        offer_ids = []
        skus = []

        for index, variant in enumerate(variants, 1):
            sku = str(variant.get("sku") or f"SHOPSYNC-{listing.get('source_id','')}-{index}").strip()
            skus.append(sku)
            item = {
                "availability": {"shipToLocationAvailability": {"quantity": max(0, int(variant.get("quantity") or 0))}},
                "condition": condition,
                "product": {
                    "title": listing["title"][:80],
                    "description": listing.get("description_html") or listing["title"],
                    "aspects": self._aspect_map(variant, common_aspects),
                    "imageUrls": images,
                },
            }
            await self._request("PUT", f"/inventory_item/{quote(sku, safe='')}", json_data=item)

        group_key = None
        if len(variants) > 1:
            group_key = "shopsync-" + re.sub(r"[^a-z0-9-]+", "-", str(listing.get("source_id") or listing["title"]).lower()).strip("-")[:40]
            names = listing.get("kept_options") or option_names({"variants": variants})
            specs = []
            for name in names:
                values = []
                for variant in variants:
                    value = variant_option_map(variant).get(name)
                    if value and value not in values:
                        values.append(value)
                if values:
                    specs.append({"name": name, "values": values})
            group = {
                "title": listing["title"][:80],
                "description": listing.get("description_html") or listing["title"],
                "imageUrls": images,
                "variantSKUs": skus,
                "aspects": {str(k): [str(v)] for k, v in common_aspects.items() if str(v).strip()},
                "variesBy": {"specifications": specs},
            }
            if names:
                group["variesBy"]["aspectsImageVariesBy"] = names[0]
            await self._request("PUT", f"/inventory_item_group/{quote(group_key, safe='')}", json_data=group)

        for sku, variant in zip(skus, variants):
            offer = {
                "sku": sku,
                "marketplaceId": str(defaults.get("marketplace_id") or self.marketplace_id),
                "format": "FIXED_PRICE",
                "availableQuantity": max(0, int(variant.get("quantity") or 0)),
                "categoryId": str(defaults["category_id"]),
                "merchantLocationKey": str(defaults["merchant_location_key"]),
                "listingDuration": str(defaults.get("listing_duration") or "GTC"),
                "listingPolicies": {
                    "paymentPolicyId": str(defaults["payment_policy_id"]),
                    "returnPolicyId": str(defaults["return_policy_id"]),
                    "fulfillmentPolicyId": str(defaults["fulfillment_policy_id"]),
                },
                "pricingSummary": {"price": {"value": str(variant.get("price") or "0.00"), "currency": str(defaults.get("currency") or "GBP")}},
            }
            if len(variants) == 1:
                offer["listingDescription"] = listing.get("description_html") or listing["title"]
            created = await self._request("POST", "/offer", json_data=offer)
            if created.get("offerId"):
                offer_ids.append(str(created["offerId"]))
        return {"offer_ids": offer_ids, "group_key": group_key, "skus": skus, "published": False}


class EtsyDraftWriter:
    def __init__(self, broker_client: Any):
        self.client = broker_client

    async def _property_map(self, taxonomy_id: str, option_names_list: list[str]) -> dict[str, int]:
        if not option_names_list:
            return {}
        payload = await self.client.request("GET", f"/v3/application/seller-taxonomy/nodes/{taxonomy_id}/properties")
        rows = payload.get("results", payload if isinstance(payload, list) else [])
        result = {}
        for wanted in option_names_list:
            wanted_norm = _norm(wanted)
            match = next((row for row in rows if _norm(row.get("display_name") or row.get("name")) == wanted_norm), None)
            if match and match.get("property_id"):
                result[wanted] = int(match["property_id"])
        return result

    async def create_or_update_draft(self, listing: dict, defaults: dict, existing_listing_id: str | None = None) -> dict:
        variants = listing.get("variants") or []
        if not variants:
            raise ValueError("Shopify product has no variants to send to Etsy")
        first = variants[0]
        quantity = sum(max(0, int(v.get("quantity") or 0)) for v in variants)
        base_form = {
            "quantity": max(1, quantity),
            "title": listing["title"][:140],
            "description": re.sub(r"<[^>]+>", " ", listing.get("description_html") or "").strip(),
            "price": str(first.get("price") or "0.01"),
            "who_made": str(defaults.get("who_made") or "i_did"),
            "when_made": str(defaults.get("when_made") or "made_to_order"),
            "taxonomy_id": int(defaults["taxonomy_id"]),
            "is_supply": bool(defaults.get("is_supply", False)),
            "shipping_profile_id": int(defaults["shipping_profile_id"]),
            "readiness_state_id": int(defaults["readiness_state_id"]),
            "should_auto_renew": bool(defaults.get("should_auto_renew", True)),
            "type": "physical",
        }
        if defaults.get("return_policy_id"):
            base_form["return_policy_id"] = int(defaults["return_policy_id"])
        tags = [str(tag)[:20] for tag in listing.get("tags") or [] if str(tag).strip()][:13]
        if tags:
            base_form["tags"] = tags

        if existing_listing_id:
            result = await self.client.request("PUT", f"/v3/application/shops/{self.client.shop_id}/listings/{existing_listing_id}", form=base_form)
            listing_id = str(existing_listing_id)
        else:
            result = await self.client.request("POST", f"/v3/application/shops/{self.client.shop_id}/listings", params={"legacy": "false"}, form=base_form)
            listing_id = str(result.get("listing_id") or "")
            if not listing_id:
                raise RuntimeError("Etsy did not return a listing ID")

        kept = listing.get("kept_options") or []
        if kept:
            property_map = await self._property_map(str(defaults["taxonomy_id"]), kept)
            missing = [name for name in kept if name not in property_map]
            if missing:
                raise ValueError("Etsy taxonomy does not expose variation properties for: " + ", ".join(missing))
            products = []
            for variant in variants:
                option_map = variant_option_map(variant)
                property_values = []
                for name in kept:
                    value = option_map.get(name)
                    if value:
                        property_values.append({"property_id": property_map[name], "property_name": name, "values": [value]})
                products.append({
                    "sku": str(variant.get("sku") or ""),
                    "property_values": property_values,
                    "offerings": [{
                        "price": str(variant.get("price") or first.get("price") or "0.01"),
                        "quantity": max(0, int(variant.get("quantity") or 0)),
                        "is_enabled": True,
                    }],
                })
            await self.client.request("PUT", f"/v3/application/listings/{listing_id}/inventory", json_data={"products": products, "price_on_property": [], "quantity_on_property": [], "sku_on_property": []})
        return {"listing_id": listing_id, "state": result.get("state", "draft")}
