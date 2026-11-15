#!/bin/sh
set -eu
for profile in /config/tiktok-browser /config/tiktok-tracking-browser; do
    if [ -L "$profile" ]; then
        echo 'Shop Sync: refusing a symlinked browser profile' >&2
        exit 1
    fi
    mkdir -p "$profile"
    # Earlier releases created root-owned Default/Preferences via ChromeDriver.
    # Keep all saved data; repair ownership without following profile symlinks.
    # Disposable Chromium caches can contain host-filesystem entries that reject
    # chown. They must not prevent the web app starting. Do not traverse those
    # trees; still fail on an ownership error in any persistent profile data.
    find "$profile" \( \
        -path "$profile/Default/Cache" -o \
        -path "$profile/Default/Code Cache" -o \
        -path "$profile/Default/GPUCache" -o \
        -path "$profile/ShaderCache" -o \
        -path "$profile/GrShaderCache" \
        \) -prune -o -exec chown -h shopsync-browser:shopsync-browser {} +
    chmod 700 "$profile"
done
