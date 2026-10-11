# syntax=docker/dockerfile:1
# Build context requires a sanitized complete workspace in YosoiOxide/.
FROM rust:1.99.0@sha256:9d5e02aa6c7e9c112ed7a4c438900b41f519a792959cd5445c25de42bfb8388b AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
      cmake clang libclang-dev ninja-build pkg-config \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build/YosoiOxide
COPY YosoiOxide/ /build/YosoiOxide/
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/build/YosoiOxide/target \
    find crates/yosoi/src benchmarks -type f -name '*.rs' -exec touch {} + \
    && CARGO_BUILD_JOBS=1 cargo build --release --locked -p yosoi-benchmarks \
      --bin profile_browser --bin profile_oopif \
    && mkdir -p /out \
    && cp target/release/profile_browser /out/profile_browser \
    && cp target/release/profile_oopif /out/profile_oopif

# Local hardened runtime image; its Chrome sandbox remains enabled.
FROM voidcrawl-headful:local
ARG CHROME_VERSION=153.0.8010.36
ARG CHROME_DEB_SHA256=9bb44e33031c2f2857cf36b4343051a12f93058e4b781e3c76313df87f6c8d32
USER root
# Google's Linux Stable wrapper appends one trailing space to --version. The
# verifier accepts whitespace only after the exact pinned version.
RUN chrome_deb="/tmp/google-chrome-stable_${CHROME_VERSION}-1_amd64.deb" \
    && curl -fsSLo "$chrome_deb" \
       "https://dl.google.com/linux/chrome/deb/pool/main/g/google-chrome-stable/google-chrome-stable_${CHROME_VERSION}-1_amd64.deb" \
    && printf '%s  %s\n' "$CHROME_DEB_SHA256" "$chrome_deb" | sha256sum --check - \
    && apt-get update \
    && apt-get install -y --no-install-recommends "$chrome_deb" \
    && google-chrome-stable --version | grep -Ex "Google Chrome ${CHROME_VERSION}[[:space:]]*" \
    && rm -f "$chrome_deb" \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /out/profile_browser /usr/local/bin/cas333-profile-browser
COPY --from=builder /out/profile_oopif /usr/local/bin/cas383-profile-oopif
COPY docker/browser/entrypoint.sh /usr/local/bin/cas333-entrypoint
COPY docker/browser/seccomp-chrome.LICENSE /usr/share/licenses/cas333/seccomp-chrome.LICENSE
RUN mkdir -p /usr/share/cas333 \
    && google-chrome-stable --version > /usr/share/cas333/chromium-version.txt \
    && printf '%s\n' "$CHROME_DEB_SHA256" > /usr/share/cas333/chromium-package-sha256.txt \
    && sha256sum /opt/google/chrome/chrome \
       | awk '{print $1}' > /usr/share/cas333/chromium-executable-sha256.txt \
    && chmod 0755 /usr/local/bin/cas333-profile-browser /usr/local/bin/cas383-profile-oopif \
       /usr/local/bin/cas333-entrypoint \
    && chmod 0444 /usr/share/cas333/chromium-version.txt \
       /usr/share/cas333/chromium-package-sha256.txt \
       /usr/share/cas333/chromium-executable-sha256.txt
USER 10001:10001
ENTRYPOINT ["/usr/local/bin/cas333-entrypoint"]
