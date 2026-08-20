from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Image:
    url: str
    position: int
    alt: str = ""
    variant_skus: list[str] = field(default_factory=list)


@dataclass
class OptionValue:
    name: str
    value: str


@dataclass
class Variant:
    source_id: str
    sku: str
    price: str
    quantity: int
    options: list[OptionValue] = field(default_factory=list)
    barcode: str | None = None
    image_url: str | None = None
    weight_grams: int | None = None


@dataclass
class Product:
    source: str
    source_id: str
    title: str
    description_html: str
    status: str
    currency: str
    vendor: str = ""
    product_type: str = ""
    category_id: str = ""
    category_name: str = ""
    tags: list[str] = field(default_factory=list)
    images: list[Image] = field(default_factory=list)
    variants: list[Variant] = field(default_factory=list)
    attributes: dict[str, str] = field(default_factory=dict)
    source_url: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


