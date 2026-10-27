#!/bin/sh
set -eu
mkdir -p /config/tiktok-browser/Default
printf retained > /config/tiktok-browser/Default/retained
chown root:root /config/tiktok-browser/Default
chmod 755 /config/tiktok-browser/Default
if su-exec shopsync-browser test -w /config/tiktok-browser/Default; then
    echo 'Invalid regression fixture: old root-owned profile is writable' >&2
    exit 1
fi
/usr/local/bin/shop-sync-prepare-profile
su-exec shopsync-browser /bin/sh -eu -c '
    test "$(cat /config/tiktok-browser/Default/retained)" = retained
    test -w /config/tiktok-browser/Default
    printf cookie-fixture > /config/tiktok-browser/Default/Cookies
'
# Repeated startup must preserve the same files and ownership.
/usr/local/bin/shop-sync-prepare-profile
su-exec shopsync-browser /bin/sh -eu -c '
    test "$(cat /config/tiktok-browser/Default/Cookies)" = cookie-fixture
'
/usr/local/bin/shop-sync-chromedriver --version
