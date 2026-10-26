# syntax=docker/dockerfile:1@sha256:4edf897a3ffa55b89f906fc8cc78afdb3f1834cc9c7083565e611a8a7d5fe99e
# Native binaries only: no engine source build on the workstation.
FROM debian:bookworm-slim@sha256:7ff6ba31527b9e336162fa061746c366c4b2032f4d2cff2078bea43f78efe3f8
ARG TARGETARCH

# The base, package snapshot and both upstream archives are fixed inputs.
RUN rm -f /etc/apt/sources.list.d/debian.sources \
    && printf '%s\n' \
      'deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/20261024T000000Z bookworm main' \
      'deb [check-valid-until=no] http://snapshot.debian.org/archive/debian-security/20261024T000000Z bookworm-security main' \
      > /etc/apt/sources.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
      ca-certificates curl libstdc++6 libfontconfig1 zlib1g libfreetype6 \
      libexpat1 libbz2-1.0 libpng16-16 libbrotli1 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && dpkg-query -W > /usr/share/moli-runtime-packages.txt

RUN set -eu; \
    case "$TARGETARCH" in \
      amd64) triple=x86_64-unknown-linux-gnu; checksum=5c22362065e64e6de785274f6b3f28a735fca363abf9896c48733e5f58489def ;; \
      arm64) triple=aarch64-unknown-linux-gnu; checksum=f3c71ff43d250fdc16fbf74a34f7c0041b47f8ba25bba1cb476bc88db587bfc8 ;; \
      *) echo 'Moli image supports linux/amd64 and linux/arm64 only' >&2; exit 1 ;; \
    esac; \
    curl --fail --location --proto '=https' --tlsv1.2 \
      "https://github.com/lexmount/moli/releases/download/v1.1.19/moli-$triple.tar.gz" -o /tmp/moli.tar.gz; \
    printf '%s  %s\n' "$checksum" /tmp/moli.tar.gz | sha256sum -c -; \
    mkdir -p /opt/moli; \
    tar -xzf /tmp/moli.tar.gz --strip-components=1 -C /opt/moli; \
    rm /tmp/moli.tar.gz; \
    ln -s /opt/moli/moli /usr/local/bin/moli; \
    /usr/local/bin/moli --version; \
    sha256sum /opt/moli/moli > /usr/share/moli-executable.sha256; \
    printf 'moli:x:10001:10001:Moli:/tmp:/usr/sbin/nologin\n' >> /etc/passwd; \
    printf 'moli:x:10001:\n' >> /etc/group

COPY --chmod=0555 entrypoint.sh /usr/local/bin/yosoi-moli
ENV HOME=/tmp RAYON_NUM_THREADS=1 TOKIO_WORKER_THREADS=1 \
    MOLI_PROFILE=dom MOLI_RESOURCES=0 MOLI_ALLOW_PRIVATE_NETWORKS=0
LABEL org.opencontainers.image.title="Yosoi headless Moli" \
    org.opencontainers.image.version="1.1.19" \
    org.opencontainers.image.licenses="Apache-2.0 OR MIT" \
    org.opencontainers.image.vendor="Cascading Labs" \
    org.opencontainers.image.description="Native BiDi service; pinned Moli, explicit DOM/layout and network profiles"
USER 10001:10001
EXPOSE 9222
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl --fail --silent --noproxy '*' --max-time 2 http://127.0.0.1:9222/status > /dev/null
ENTRYPOINT ["/usr/local/bin/yosoi-moli"]
