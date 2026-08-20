#!/usr/bin/with-contenv bashio
set -e

export BRIDGE_DATA_DIR=/config
export BRIDGE_LOG_LEVEL="$(bashio::config 'log_level')"
export EBAY_MARKETPLACE="$(bashio::config 'ebay_marketplace')"
export EBAY_ENVIRONMENT="$(bashio::config 'ebay_environment')"
export SHOPIFY_API_VERSION="$(bashio::config 'shopify_api_version')"

exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8099 --proxy-headers


