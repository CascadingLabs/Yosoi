#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")/../.."
exec uv run --no-project --python 3.12 \
  --with aiortc==1.14.0 --with aiohttp==3.13.3 \
  python spikes/live-recording/server.py "$@"
