#!/usr/bin/env bash
# Pre-seed Chrome user profiles so first launch is instant.
set -euo pipefail

echo "Warming up Chrome profiles..."

for port in 9222 9223; do
    idx=$((port - 9221))
    profile="/tmp/chrome-profile-${idx}"
    mkdir -p "$profile"

    # Launch Chrome briefly to initialize the profile
    chromium \
        --headless=new \
        --no-sandbox \
        --disable-gpu \
        --disable-dev-shm-usage \
        --remote-debugging-port="$port" \
        --user-data-dir="$profile" &
    pid=$!

    # Wait for the debug endpoint to become available
    for i in $(seq 1 30); do
        if curl -sf "http://localhost:${port}/json/version" > /dev/null 2>&1; then
            echo "  Chrome profile ${idx} on port ${port} ready"
            break
        fi
        sleep 0.2
    done

    # Shut it down — supervisord will start the real instances
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
done

echo "Chrome profiles warmed up."
