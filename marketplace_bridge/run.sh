#!/usr/bin/with-contenv bashio
set -e

export BRIDGE_DATA_DIR=/config
export BRIDGE_LOG_LEVEL="$(bashio::config 'log_level')"
export EBAY_MARKETPLACE="$(bashio::config 'ebay_marketplace')"
export EBAY_ENVIRONMENT="$(bashio::config 'ebay_environment')"
export SHOPIFY_API_VERSION="$(bashio::config 'shopify_api_version')"

export DISPLAY=:99
if command -v chromium-browser >/dev/null 2>&1; then
    mkdir -p /config/tiktok-browser
    chown shopsync-browser:shopsync-browser /config/tiktok-browser
    chmod 700 /config/tiktok-browser
    Xvfb :99 -screen 0 1280x900x24 -nolisten tcp -ac >/dev/null 2>&1 &
    x11vnc -display :99 -localhost -forever -shared -nopw -rfbport 5900 -quiet >/dev/null 2>&1 &
    websockify --web=/usr/share/novnc 127.0.0.1:6080 127.0.0.1:5900 >/dev/null 2>&1 &
fi
# Preserve the real socket peer for the Ingress-only browser/order routes.
exec python3 -m uvicorn app.main_v8:app --host 0.0.0.0 --port 8099 --no-proxy-headers --no-access-log
