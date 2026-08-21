from __future__ import annotations

import uuid

from .shopify import ShopifyClient


LOCATION_QUERY = "{ locations(first: 1) { nodes { id name } } }"

INVENTORY_ACTIVATE_WITH_STOCK = """
mutation Activate($inventoryItemId: ID!, $locationId: ID!, $available: Int!, $idempotencyKey: String!) {
  inventoryActivate(inventoryItemId: $inventoryItemId, locationId: $locationId, available: $available)
    @idempotent(key: $idempotencyKey) {
    inventoryLevel { id quantities(names: [\"available\"]) { name quantity } }
    userErrors { field message }
  }
}
"""

CURRENT_INVENTORY = """
query CurrentInventory($inventoryItemId: ID!, $locationId: ID!) {
  inventoryItem(id: $inventoryItemId) {
    inventoryLevel(locationId: $locationId) {
      quantities(names: [\"available\"]) { name quantity }
    }
  }
}
"""

INVENTORY_SET = """
mutation SetInventory($input: InventorySetQuantitiesInput!, $idempotencyKey: String!) {
  inventorySetQuantities(input: $input) @idempotent(key: $idempotencyKey) {
    inventoryAdjustmentGroup { createdAt }
    userErrors { field message code }
  }
}
"""


async def _set_inventory_verified(self: ShopifyClient, created_variants: list[dict], source_variants: list[dict]):
    """Set imported stock and verify Shopify actually stored the quantity.

    New variants are activated with their desired available quantity immediately.
    If a level already exists, inventorySetQuantities is used to correct it. A
    final read-back prevents a successful draft job from hiding a zero-stock
    write.
    """
    location_data = await self.graphql(LOCATION_QUERY)
    locations = location_data["locations"]["nodes"]
    if not locations:
        raise RuntimeError("Shopify store has no inventory location")
    location_id = locations[0]["id"]

    quantities_by_sku = {
        str(v.get("sku") or ""): max(0, int(v.get("quantity") or 0))
        for v in source_variants
    }

    for variant in created_variants:
        sku = str(variant.get("sku") or "")
        desired = quantities_by_sku.get(sku, 0)
        inventory_item = variant.get("inventoryItem") or {}
        inventory_item_id = inventory_item.get("id")
        if not inventory_item_id:
            raise RuntimeError(f"Shopify did not return an inventory item for SKU {sku or '(blank)'}")

        activation = await self.graphql(
            INVENTORY_ACTIVATE_WITH_STOCK,
            {
                "inventoryItemId": inventory_item_id,
                "locationId": location_id,
                "available": desired,
                "idempotencyKey": str(uuid.uuid4()),
            },
        )
        activation_errors = activation["inventoryActivate"]["userErrors"]

        current_data = await self.graphql(
            CURRENT_INVENTORY,
            {"inventoryItemId": inventory_item_id, "locationId": location_id},
        )
        level = current_data["inventoryItem"]["inventoryLevel"]
        current = 0
        if level:
            current = next(
                (q["quantity"] for q in level["quantities"] if q["name"] == "available"),
                0,
            )

        # Activation can legitimately report that the item is already stocked at
        # this location on a retry. In that case, or if Shopify did not retain the
        # requested quantity, explicitly correct the level.
        if activation_errors or current != desired:
            if not level:
                messages = "; ".join(e.get("message", "") for e in activation_errors)
                raise RuntimeError(f"Shopify inventory activation failed for {sku}: {messages}")

            corrected = await self.graphql(
                INVENTORY_SET,
                {
                    "idempotencyKey": str(uuid.uuid4()),
                    "input": {
                        "name": "available",
                        "reason": "correction",
                        "quantities": [
                            {
                                "inventoryItemId": inventory_item_id,
                                "locationId": location_id,
                                "quantity": desired,
                                "changeFromQuantity": current,
                            }
                        ],
                    },
                },
            )
            errors = corrected["inventorySetQuantities"]["userErrors"]
            if errors:
                raise RuntimeError("; ".join(e["message"] for e in errors))

        verify_data = await self.graphql(
            CURRENT_INVENTORY,
            {"inventoryItemId": inventory_item_id, "locationId": location_id},
        )
        verify_level = verify_data["inventoryItem"]["inventoryLevel"]
        actual = 0
        if verify_level:
            actual = next(
                (q["quantity"] for q in verify_level["quantities"] if q["name"] == "available"),
                0,
            )
        if actual != desired:
            raise RuntimeError(
                f"Shopify stock verification failed for {sku or inventory_item_id}: expected {desired}, got {actual}"
            )


ShopifyClient._set_inventory = _set_inventory_verified
