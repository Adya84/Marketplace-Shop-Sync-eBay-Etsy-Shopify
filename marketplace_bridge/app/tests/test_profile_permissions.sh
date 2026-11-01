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

# Cache entries can be unchownable on the persistent host filesystem.
# Simulate that error without changing or deleting any saved login data.
mkdir -p /config/tiktok-browser/Default/Cache/Cache_Data /tmp/profile-test-bin
printf cache > /config/tiktok-browser/Default/Cache/Cache_Data/unchownable
cat > /tmp/profile-test-bin/chown <<'SH'
#!/bin/sh
for argument in "$@"; do
    case "$argument" in
        -R|*/Cache/Cache_Data/*) echo 'simulated cache ownership failure' >&2; exit 1 ;;
    esac
done
exec /bin/chown "$@"
SH
chmod +x /tmp/profile-test-bin/chown
PATH="/tmp/profile-test-bin:$PATH" /usr/local/bin/shop-sync-prepare-profile
test "$(cat /config/tiktok-browser/Default/Cache/Cache_Data/unchownable)" = cache
su-exec shopsync-browser test -w /config/tiktok-browser/Default/Cookies
