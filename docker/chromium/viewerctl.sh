#!/usr/bin/env bash
# Manage the one local noVNC viewer lease. Runs inside the headful container.
set -euo pipefail

RUNTIME_DIR="${RUNTIME_DIR:-/tmp/yosoi}"
XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-$RUNTIME_DIR/xdg}"
WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-1}"
export XDG_RUNTIME_DIR WAYLAND_DISPLAY
VIEWER_DIR="$RUNTIME_DIR/viewer"
STATE_FILE="$VIEWER_DIR/lease.env"
TOKEN_FILE="$VIEWER_DIR/tokens"
LOG_DIR="$RUNTIME_DIR/logs"

usage() {
    cat <<'EOF'
Usage:
  viewerctl open --browser <n> [--ttl <duration>]
  viewerctl close
  viewerctl status

Durations are positive integers with an optional s, m, h, or d suffix.
EOF
}

require_uint() {
    [[ "${2:-}" =~ ^[1-9][0-9]*$ ]] || {
        echo "$1 must be a positive integer (got '${2:-}')" >&2
        exit 64
    }
}

duration_seconds() {
    local value="$1" number unit
    if [[ "$value" =~ ^([1-9][0-9]*)([smhd]?)$ ]]; then
        number="${BASH_REMATCH[1]}"
        [ "${#number}" -le 5 ] && [ "$number" -le 86400 ] || { echo "duration is too large" >&2; return 64; }
        unit="${BASH_REMATCH[2]}"
        case "$unit" in
            '') echo "$number" ;;
            s) echo "$number" ;;
            m) echo $((number * 60)) ;;
            h) echo $((number * 3600)) ;;
            d) echo $((number * 86400)) ;;
        esac
    else
        echo "invalid duration '$value' (use e.g. 30s, 15m, 1h)" >&2
        return 64
    fi
}

load_state() {
    [ -f "$STATE_FILE" ] || return 1
    # The file is only written by this script with a restrictive umask; values
    # are validated numeric or hex before being persisted.
    # shellcheck disable=SC1090
    source "$STATE_FILE"
}

pid_is_running() {
    [[ "${1:-}" =~ ^[1-9][0-9]*$ ]] && kill -0 "$1" 2>/dev/null
}

wait_for_listeners() {
    python3 - "$1" "$2" "$WAYVNC_PID" "$WEBSOCKIFY_PID" "$LOG_DIR" <<'WAIT'
import ctypes
import os
from pathlib import Path
import selectors
import sys
import time

ports = {int(value) for value in sys.argv[1:3]}
pids = [int(value) for value in sys.argv[3:5]]
libc = ctypes.CDLL(None, use_errno=True)
fd = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
if fd < 0 or libc.inotify_add_watch(fd, os.fsencode(sys.argv[5]), 0x102) < 0:
    raise OSError(ctypes.get_errno(), 'Cannot observe viewer startup')
try:
    with selectors.DefaultSelector() as events:
        events.register(fd, selectors.EVENT_READ)
        deadline = time.monotonic() + 10
        while True:
            listening = set()
            for path in ('/proc/net/tcp', '/proc/net/tcp6'):
                for line in Path(path).read_text().splitlines()[1:]:
                    fields = line.split()
                    if fields[3] == '0A':
                        listening.add(int(fields[1].rsplit(':', 1)[1], 16))
            if ports <= listening:
                break
            for pid in pids:
                os.kill(pid, 0)
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not events.select(remaining):
                raise TimeoutError('Viewer listeners did not become ready')
            os.read(fd, 65536)
finally:
    os.close(fd)
WAIT
}

clear_state() {
    rm -f "$STATE_FILE" "$TOKEN_FILE"
}

close_lease() {
    local expected_token="${1:-}" pid
    load_state || return 0
    if [ -n "$expected_token" ] && [ "$expected_token" != "$LEASE_TOKEN" ]; then
        return 0
    fi
    for pid in "${WEBSOCKIFY_PID:-}" "${WAYVNC_PID:-}"; do
        if pid_is_running "$pid"; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    for pid in "${WEBSOCKIFY_PID:-}" "${WAYVNC_PID:-}"; do
        if pid_is_running "$pid"; then
            wait "$pid" 2>/dev/null || true
        fi
    done
    clear_state
    echo "[viewer] lease closed"
}

status() {
    if ! load_state; then
        echo "viewer: inactive"
        return 0
    fi
    if [ "${LEASE_EXPIRES_AT:-0}" -le "$(date +%s)" ]; then
        close_lease "$LEASE_TOKEN"
        echo "viewer: inactive (expired)"
        return 0
    fi
    if ! pid_is_running "${WAYVNC_PID:-}" || ! pid_is_running "${WEBSOCKIFY_PID:-}"; then
        close_lease "$LEASE_TOKEN"
        echo "viewer: inactive (backend exited)"
        return 0
    fi
    printf 'viewer: active browser=%s expires_at=%s url=%s\n' \
        "$LEASE_BROWSER" "$LEASE_EXPIRES_AT" "$LEASE_URL"
}

expire() {
    local token="$1" seconds="$2"
    sleep "$seconds"
    close_lease "$token"
}

open_lease() {
    local browser="" ttl="${VIEWER_TTL:-15m}" ttl_seconds token vnc_port expires_at
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --browser) browser="${2:-}"; shift 2 ;;
            --ttl) ttl="${2:-}"; shift 2 ;;
            -h|--help) usage; return 0 ;;
            *) echo "unknown option: $1" >&2; usage >&2; return 64 ;;
        esac
    done
    [ "${VIEWER_MODE:-disabled}" = "local" ] || {
        echo "viewer mode is disabled; set VIEWER_MODE=local and restart the container" >&2
        return 77
    }
    require_uint browser "$browser"
    require_uint BROWSER_COUNT "${BROWSER_COUNT:-2}"
    [ "$browser" -le "${BROWSER_COUNT:-2}" ] || {
        echo "browser $browser is outside configured range 1..${BROWSER_COUNT}" >&2
        return 64
    }
    ttl_seconds=$(duration_seconds "$ttl")

    mkdir -p "$VIEWER_DIR" "$LOG_DIR"
    chmod 0700 "$VIEWER_DIR"
    # One viewer at a time. A new lease deterministically revokes the old one.
    close_lease

    token=$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')
    vnc_port=$(( ${VNC_PORT_BASE:-5900} + browser - 1 ))
    expires_at=$(( $(date +%s) + ttl_seconds ))
    umask 077
    printf '%s: 127.0.0.1:%s\n' "$token" "$vnc_port" > "$TOKEN_FILE"

    wayvnc --gpu --max-fps="${VIEWER_MAX_FPS:-30}" --output="HEADLESS-$browser" \
        -S "$VIEWER_DIR/wayvnc.sock" 127.0.0.1 "$vnc_port" \
        >> "$LOG_DIR/wayvnc.log" 2>&1 &
    local wayvnc_pid=$!

    # TokenFile selects the short-lived backend target. There is one shared
    # noVNC listener, never one listener per browser.
    websockify --web=/usr/share/novnc --token-plugin TokenFile --token-source "$TOKEN_FILE" \
        "127.0.0.1:${VIEWER_NOVNC_PORT:-6080}" \
        >> "$LOG_DIR/websockify.log" 2>&1 &
    local websockify_pid=$!

    # Scale the 1920x1080 RFB framebuffer to the operator's available browser
    # viewport. noVNC otherwise defaults to `resize=off`, leaving a clipped or
    # panned canvas when the browser window is narrower than the virtual output.
    # Pin connection settings in the URL so a browser's persisted noVNC
    # preferences cannot switch this loopback, plaintext websockify listener to
    # WSS or a stale host/port.
    local url="http://127.0.0.1:${VIEWER_NOVNC_PORT:-6080}/vnc.html?autoconnect=true&resize=scale&encrypt=false&host=127.0.0.1&port=${VIEWER_NOVNC_PORT:-6080}&path=websockify%3Ftoken%3D${token}"
    WAYVNC_PID="$wayvnc_pid"
    WEBSOCKIFY_PID="$websockify_pid"
    {
        printf 'LEASE_TOKEN=%q\n' "$token"
        printf 'LEASE_BROWSER=%q\n' "$browser"
        printf 'LEASE_EXPIRES_AT=%q\n' "$expires_at"
        printf 'WAYVNC_PID=%q\n' "$wayvnc_pid"
        printf 'WEBSOCKIFY_PID=%q\n' "$websockify_pid"
        printf 'LEASE_URL=%q\n' "$url"
    } > "$STATE_FILE"
    chmod 0600 "$STATE_FILE" "$TOKEN_FILE"

    if ! wait_for_listeners "$vnc_port" "${VIEWER_NOVNC_PORT:-6080}"; then
        echo "[viewer] backend failed to start; see $LOG_DIR/{wayvnc,websockify}.log" >&2
        close_lease "$token"
        return 1
    fi

    # Detach expiry cleanup from docker exec. A stale watcher cannot close a
    # replacement lease because close_lease verifies its original token.
    setsid "$0" _expire "$token" "$ttl_seconds" </dev/null >> "$LOG_DIR/viewer-expiry.log" 2>&1 &

    printf 'viewer URL: %s\nexpires: %s\n' "$url" "$(date -d "@$expires_at" --iso-8601=seconds)"
}

case "${1:-}" in
    open) shift; open_lease "$@" ;;
    close) shift; [ "$#" -eq 0 ] || { usage >&2; exit 64; }; close_lease ;;
    status) shift; [ "$#" -eq 0 ] || { usage >&2; exit 64; }; status ;;
    _expire) shift; expire "$@" ;;
    -h|--help|'') usage ;;
    *) echo "unknown command: $1" >&2; usage >&2; exit 64 ;;
esac
