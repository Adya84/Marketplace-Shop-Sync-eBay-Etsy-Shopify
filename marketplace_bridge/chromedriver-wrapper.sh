#!/bin/sh
# Driver and Chromium must share an owner: ChromeDriver creates Default/Preferences.
exec su-exec shopsync-browser /usr/bin/chromedriver "$@"
