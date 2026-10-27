ARG BUILD_FROM
FROM ${BUILD_FROM}

WORKDIR /app
RUN case "$(uname -m)" in x86_64|aarch64) apk add --no-cache chromium chromium-chromedriver xvfb x11vnc novnc websockify su-exec font-noto ;; esac \
    && addgroup -S shopsync-browser && adduser -S -G shopsync-browser shopsync-browser
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY app /app/app
COPY logo.png /app/logo.png
COPY run.sh /run.sh
COPY chromium-wrapper.sh /usr/local/bin/shop-sync-chromium
COPY chromedriver-wrapper.sh /usr/local/bin/shop-sync-chromedriver
COPY prepare-browser-profile.sh /usr/local/bin/shop-sync-prepare-profile
RUN chmod a+x /run.sh /usr/local/bin/shop-sync-chromium /usr/local/bin/shop-sync-chromedriver /usr/local/bin/shop-sync-prepare-profile

CMD ["/run.sh"]
