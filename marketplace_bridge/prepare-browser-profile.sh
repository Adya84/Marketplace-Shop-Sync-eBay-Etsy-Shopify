#!/bin/sh
set -eu
if [ -L /config/tiktok-browser ]; then
    echo 'Shop Sync: refusing a symlinked browser profile' >&2
    exit 1
fi
mkdir -p /config/tiktok-browser
# Earlier releases created root-owned Default/Preferences via ChromeDriver.
# Keep all saved data; repair ownership without following profile symlinks.
chown -R -h shopsync-browser:shopsync-browser /config/tiktok-browser
chmod 700 /config/tiktok-browser
