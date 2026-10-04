# syntax=docker/dockerfile:1
# Build context is produced by scripts/browser/prepare-container-context.sh.
FROM rust:1.98@sha256:af753e6e729c839de28010e323abc550eceaa9572bdaa765429d4f585e2e43dc AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
      cmake clang libclang-dev ninja-build pkg-config \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build/YosoiOxide
COPY YosoiOxide/ /build/YosoiOxide/
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/build/YosoiOxide/target \
    find crates/voidcrawl/src crates/yosoi-types/src \
      crates/yosoi-web-capture/src crates/yosoi-web-capture-direct-http/src \
      benchmarks/src vendor/chromiumoxide/src vendor/chromiumoxide_cdp/src \
      -type f -name '*.rs' -exec touch {} + \
    && CARGO_BUILD_JOBS=1 cargo build --release --locked \
      -p yosoi-benchmarks --bin profile_browser_stealth \
    && mkdir -p /out \
    && cp target/release/profile_browser_stealth /out/profile_browser_stealth

# This tag is verified against the immutable CAS-373 image ID before build.
FROM yosoi-cas333:local
USER root
COPY --from=builder /out/profile_browser_stealth /usr/local/bin/cas374-profile-browser-stealth
COPY YosoiOxide/docker/browser-stealth/entrypoint.sh /usr/local/bin/cas374-entrypoint
RUN chmod 0755 /usr/local/bin/cas374-profile-browser-stealth /usr/local/bin/cas374-entrypoint
USER 10001:10001
ENTRYPOINT ["/usr/local/bin/cas374-entrypoint"]
