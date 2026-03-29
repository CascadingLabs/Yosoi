# ── Stage 1: Build the Rust extension ────────────────────────────────────
FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential pkg-config libssl-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Rust
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
ENV PATH="/root/.cargo/bin:${PATH}"

# Install maturin
RUN pip install --no-cache-dir maturin

WORKDIR /build

# Copy workspace files
COPY yosoi_driver/Cargo.toml yosoi_driver/Cargo.toml
COPY yosoi_driver/crates/ yosoi_driver/crates/
COPY yosoi_driver/pyproject.toml yosoi_driver/pyproject.toml
COPY yosoi_driver/LICENSE.md yosoi_driver/LICENSE.md
COPY yosoi_driver/yosoi_driver.pyi yosoi_driver/yosoi_driver.pyi

# Build the wheel
RUN cd yosoi_driver && \
    maturin build --release --manifest-path crates/pyo3_bindings/Cargo.toml -o /wheels

# ── Stage 2: Runtime image ──────────────────────────────────────────────
FROM python:3.11-slim

# Install Chromium + supervisord
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-sandbox \
    supervisor \
    curl \
    fonts-liberation \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpangocairo-1.0-0 \
    libgtk-3-0 \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Install the pre-built Rust extension
COPY --from=builder /wheels/*.whl /tmp/wheels/
RUN uv pip install /tmp/wheels/*.whl && rm -rf /tmp/wheels

# Copy application code
COPY yosoi/ yosoi/
COPY examples/ examples/

# Supervisord config
COPY docker/config/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Chrome warmup script
COPY docker/warmup-chrome.sh /usr/local/bin/warmup-chrome.sh

# Warm up Chrome profiles during build for instant startup
RUN /usr/local/bin/warmup-chrome.sh || true

# Shared memory for Chrome
RUN mkdir -p /dev/shm && chmod 1777 /dev/shm

ENV CHROME_WS_URLS="http://localhost:9222,http://localhost:9223" \
    BROWSER_COUNT=2 \
    TABS_PER_BROWSER=4 \
    TAB_MAX_USES=50 \
    TAB_MAX_IDLE_SECS=60 \
    CHROME_NO_SANDBOX=1

EXPOSE 9222 9223

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:9222/json/version && curl -sf http://localhost:9223/json/version

CMD ["supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
