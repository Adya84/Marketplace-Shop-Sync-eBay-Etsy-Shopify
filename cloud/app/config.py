from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SHOPSYNC_", case_sensitive=False)

    env: str = "development"
    base_url: str = "http://localhost:8080"
    database_url: str = "postgresql+psycopg://shopsync:shopsync@db:5432/shopsync"
    session_secret: str = "development-only-change-me"
    token_encryption_key: str = ""
    secure_cookies: bool = False
    oauth_broker_url: str = "https://shop-sync-ebay-oauth.graffidoodle.workers.dev"


@lru_cache

def get_settings() -> Settings:
    return Settings()
