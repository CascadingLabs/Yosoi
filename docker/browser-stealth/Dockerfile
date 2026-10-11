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
    find crates/yosoi/src benchmarks/src vendor/chromiumoxide/src vendor/chromiumoxide_cdp/src \
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
