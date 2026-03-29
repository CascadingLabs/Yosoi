#!/usr/bin/env bash
# One-click headful Chrome in Docker with GPU acceleration.
#
# Auto-detects your GPU vendor and launches the right profile.
#
# Usage:
#   ./docker/run-headful.sh              # auto-detect GPU
#   ./docker/run-headful.sh --gpu amd    # force AMD
#   ./docker/run-headful.sh --gpu nvidia # force NVIDIA
#   ./docker/run-headful.sh --gpu intel  # force Intel
#   ./docker/run-headful.sh --gpu cpu    # no GPU, software rendering
#   ./docker/run-headful.sh --res 2560x1440  # custom resolution
#
# Connect VNC client to localhost:5900
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.headful.yml"

GPU_PROFILE=""
VNC_WIDTH="1920"
VNC_HEIGHT="1080"
EXTRA_ARGS=""

# ── Parse args ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case $1 in
        --gpu)
            GPU_PROFILE="$2"; shift 2 ;;
        --res)
            IFS='x' read -r VNC_WIDTH VNC_HEIGHT <<< "$2"; shift 2 ;;
        --build)
            EXTRA_ARGS="--build"; shift ;;
        -d|--detach)
            EXTRA_ARGS="$EXTRA_ARGS -d"; shift ;;
        *)
            echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# ── Auto-detect GPU if not specified ─────────────────────────────────────
if [ -z "$GPU_PROFILE" ]; then
    if [ -e /dev/dri/renderD128 ]; then
        DRIVER=$(basename "$(readlink -f /sys/class/drm/renderD128/device/driver)" 2>/dev/null || echo "unknown")
        case "$DRIVER" in
            amdgpu)  GPU_PROFILE="amd" ;;
            i915|xe) GPU_PROFILE="intel" ;;
            nvidia)  GPU_PROFILE="nvidia" ;;
            *)       GPU_PROFILE="cpu" ;;
        esac
    elif [ -e /dev/nvidia0 ]; then
        GPU_PROFILE="nvidia"
    else
        GPU_PROFILE="cpu"
    fi
    echo "Auto-detected GPU: $GPU_PROFILE"
fi

echo "Starting headful Chrome container..."
echo "  GPU profile: $GPU_PROFILE"
echo "  Resolution:  ${VNC_WIDTH}x${VNC_HEIGHT}"
echo "  VNC:         localhost:5900"
echo "  CDP:         localhost:9222, localhost:9223"
echo ""

export VNC_WIDTH VNC_HEIGHT

docker compose -f "$COMPOSE_FILE" --profile "$GPU_PROFILE" up --build $EXTRA_ARGS
