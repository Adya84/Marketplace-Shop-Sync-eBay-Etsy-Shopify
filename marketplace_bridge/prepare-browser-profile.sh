#!/bin/sh
set -eu
if [ -L /config/tiktok-browser ]; then
    echo 'Shop Sync: refusing a symlinked browser profile' >&2
    exit 1
fi
mkdir -p /config/tiktok-browser
# Earlier releases created root-owned Default/Preferences via ChromeDriver.
# Keep all saved data; repair ownership without following profile symlinks.
# Disposable Chromium caches can contain host-filesystem entries that reject
# chown. They must not prevent the web app starting. Do not traverse those
# trees; still fail on an ownership error in any persistent profile data.
find /config/tiktok-browser \( \
    -path /config/tiktok-browser/Default/Cache -o \
    -path /config/tiktok-browser/Default/Code\ Cache -o \
    -path /config/tiktok-browser/Default/GPUCache -o \
    -path /config/tiktok-browser/ShaderCache -o \
    -path /config/tiktok-browser/GrShaderCache \
    \) -prune -o -exec chown -h shopsync-browser:shopsync-browser {} +
chmod 700 /config/tiktok-browser
