# syntax=docker/dockerfile:1
# Adapted from CascadingLabs/VoidCrawl f7ca3ee0e9ad427e7695e1b241639cd7084f2975.
FROM debian:trixie-slim@sha256:a29215f6a35e51e22adffa17f89e9d2ef06214e64a2bad10d765c46aea49f11f AS browser
ARG CHROMIUM_VERSION=154.0.8037.92-1~deb13u1
RUN apt-get update && apt-get install -y --no-install-recommends \
      chromium="$CHROMIUM_VERSION" chromium-common="$CHROMIUM_VERSION" chromium-sandbox="$CHROMIUM_VERSION" \
      supervisor curl ca-certificates python3 dbus procps fonts-liberation \
      fonts-dejavu-core fonts-noto-core fonts-noto-color-emoji \
      mesa-vulkan-drivers libgl1-mesa-dri libvulkan1 \
    && mkdir -p /usr/share/chromium-cdp \
    && chromium --version > /usr/share/chromium-cdp/browser-version \
    && sha256sum /usr/lib/chromium/chromium > /usr/share/chromium-cdp/browser-sha256 \
    && dpkg-query -W chromium chromium-common chromium-sandbox > /usr/share/chromium-cdp/packages \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd --gid 10001 browser && useradd --uid 10001 --gid 10001 --create-home --home-dir /home/browser --shell /usr/sbin/nologin browser
COPY docker/chromium/entrypoint.sh docker/chromium/healthcheck.sh /usr/local/bin/
RUN chmod 0755 /usr/local/bin/entrypoint.sh /usr/local/bin/healthcheck.sh
ENV HOME=/home/browser RUNTIME_DIR=/tmp/yosoi XDG_RUNTIME_DIR=/tmp/yosoi/xdg \
    CHROME_BIN=/usr/bin/chromium CHROME_NO_SANDBOX=0 BROWSER_COUNT=2 CDP_PORT_BASE=9222 \
    VNC_PORT_BASE=5900 VNC_WIDTH=1920 VNC_HEIGHT=1080 VIEWER_MODE=disabled
USER 10001:10001
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 CMD /usr/local/bin/healthcheck.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

FROM browser AS headless
ENV BROWSER_MODE=headless

FROM browser AS headful
USER root
RUN apt-get update && apt-get install -y --no-install-recommends sway swaybg wayvnc novnc python3-websockify \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/share/novnc/vnc.html /usr/share/novnc/index.html
COPY docker/chromium/viewerctl.sh /usr/local/bin/viewerctl
COPY docker/chromium/check-outputs.sh /usr/local/bin/check-outputs.sh
RUN chmod 0755 /usr/local/bin/viewerctl /usr/local/bin/check-outputs.sh
ENV BROWSER_MODE=headful CDP_PORT_BASE=19222 WLR_BACKENDS=headless \
    WLR_LIBINPUT_NO_DEVICES=1 WLR_NO_HARDWARE_CURSORS=1 LIBSEAT_BACKEND=noop XDG_SESSION_TYPE=wayland \
    VIEWER_NOVNC_PORT=6080 VIEWER_TTL=15m VIEWER_MAX_FPS=30
USER 10001:10001
