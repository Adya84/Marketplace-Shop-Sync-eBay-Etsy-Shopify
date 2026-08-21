from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(os.getenv("BRIDGE_DATA_DIR", "./data"))
    ebay_marketplace: str = os.getenv("EBAY_MARKETPLACE", "EBAY_GB")
    ebay_environment: str = os.getenv("EBAY_ENVIRONMENT", "production")
    ebay_oauth_broker_url: str = os.getenv(
        "EBAY_OAUTH_BROKER_URL",
        "https://shop-sync-ebay-compliance.zesty-flame-5295.chatgpt.site",
    )
    shopify_api_version: str = os.getenv("SHOPIFY_API_VERSION", "2026-07")
    etsy_redirect_uri: str = os.getenv(
        "ETSY_REDIRECT_URI",
        "https://adya84.github.io/Marketplace-Shop-Sync-eBay-Etsy-Shopify/etsy-callback.html",
    )

    @property
    def database_path(self) -> Path:
        return self.data_dir / "marketplace_bridge.db"


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
