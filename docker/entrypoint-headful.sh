#!/usr/bin/env bash
# Entrypoint for headful Sway+wayvnc+Chrome container.
#
# Handles:
#   1. GPU detection and renderer selection
#   2. NVIDIA --unsupported-gpu flag
#   3. Render group GID matching for /dev/dri access
#   4. VNC resolution configuration
#   5. Starts supervisord
set -euo pipefail

# ── 1. Match host render group GID for /dev/dri access ──────────────────
if [ -e /dev/dri/renderD128 ]; then
    HOST_RENDER_GID=$(stat -c '%g' /dev/dri/renderD128)
    echo "[gpu] /dev/dri/renderD128 detected (GID=$HOST_RENDER_GID)"

    # Create or update a group with the host's render GID
    if getent group "$HOST_RENDER_GID" > /dev/null 2>&1; then
        RENDER_GROUP=$(getent group "$HOST_RENDER_GID" | cut -d: -f1)
    else
        groupadd -g "$HOST_RENDER_GID" docker-render
        RENDER_GROUP="docker-render"
    fi
    # Ensure root (or whoever runs Chrome) is in the render group
    usermod -aG "$RENDER_GROUP" root 2>/dev/null || true
    echo "[gpu] Added root to group $RENDER_GROUP (GID=$HOST_RENDER_GID)"
else
    echo "[gpu] No /dev/dri/renderD128 — falling back to software rendering"
fi

# ── 2. Detect GPU vendor and set renderer ────────────────────────────────
export SWAY_EXTRA_ARGS=""

detect_gpu() {
    if [ -e /dev/dri/renderD128 ]; then
        local driver
        driver=$(basename "$(readlink -f /sys/class/drm/renderD128/device/driver)" 2>/dev/null || echo "unknown")
        echo "$driver"
    elif [ -e /dev/nvidia0 ]; then
        echo "nvidia"
    else
        echo "none"
    fi
}

GPU_DRIVER=$(detect_gpu)
echo "[gpu] Detected driver: $GPU_DRIVER"

case "$GPU_DRIVER" in
    amdgpu)
        # AMD iGPU / discrete — Mesa RADV works great with gles2
        export WLR_RENDERER="${WLR_RENDERER:-gles2}"
        echo "[gpu] AMD GPU — using WLR_RENDERER=$WLR_RENDERER"
        ;;
    i915|xe)
        # Intel iGPU (i915 = legacy, xe = new Xe driver)
        export WLR_RENDERER="${WLR_RENDERER:-gles2}"
        echo "[gpu] Intel GPU — using WLR_RENDERER=$WLR_RENDERER"
        ;;
    nvidia)
        # NVIDIA — needs --unsupported-gpu for Sway
        export WLR_RENDERER="${WLR_RENDERER:-gles2}"
        export SWAY_EXTRA_ARGS="--unsupported-gpu"
        echo "[gpu] NVIDIA GPU — using WLR_RENDERER=$WLR_RENDERER (--unsupported-gpu)"
        ;;
    *)
        # No GPU or unknown — CPU software rendering
        export WLR_RENDERER="pixman"
        export WLR_RENDERER_ALLOW_SOFTWARE=1
        echo "[gpu] No GPU detected — using software renderer (pixman)"
        ;;
esac

# ── 3. Configure VNC resolution ──────────────────────────────────────────
VNC_WIDTH="${VNC_WIDTH:-1920}"
VNC_HEIGHT="${VNC_HEIGHT:-1080}"
echo "[vnc] Resolution: ${VNC_WIDTH}x${VNC_HEIGHT} on port ${VNC_PORT:-5900}"

# Update Sway output resolution
sed -i "s/resolution [0-9]*x[0-9]*/resolution ${VNC_WIDTH}x${VNC_HEIGHT}/" /etc/sway/config

# ── 4. Ensure runtime dirs exist ─────────────────────────────────────────
mkdir -p /tmp/xdg-runtime
chmod 0700 /tmp/xdg-runtime
mkdir -p /tmp/chrome-profile-1 /tmp/chrome-profile-2

# ── 5. Start supervisord ─────────────────────────────────────────────────
echo "[start] Launching sway → wayvnc → chrome"
exec supervisord -c /etc/supervisor/conf.d/supervisord.conf
