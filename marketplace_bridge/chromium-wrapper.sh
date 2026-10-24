#!/bin/sh
# Keep Chromium's sandbox enabled. Unsupported hosts fail instead of disabling it.
exec su-exec shopsync-browser /usr/bin/chromium-browser "$@"
