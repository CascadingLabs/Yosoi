#!/usr/bin/env bash
set -euo pipefail

mode=${1:-}
shift || true
case "$mode" in
  container-headless) profile_mode=headless ;;
  container-headful) profile_mode=headful ;;
  *) printf 'usage: %s container-headless|container-headful [profile arguments]\n' "$0" >&2; exit 64 ;;
esac

if [ "${CHROME_NO_SANDBOX:-0}" != 0 ]; then
  printf '%s\n' 'CHROME_NO_SANDBOX must be 0; the Chrome sandbox is required' >&2
  exit 64
fi
export CHROME_NO_SANDBOX=0 HOME=/tmp/home XDG_RUNTIME_DIR=/tmp/xdg-runtime
mkdir -p "$HOME" "$XDG_RUNTIME_DIR"
chmod 0700 "$HOME" "$XDG_RUNTIME_DIR"

export CHROME=/opt/google/chrome/chrome
expected_version=$(cat /usr/share/cas333/chromium-version.txt)
expected_digest=$(cat /usr/share/cas333/chromium-executable-sha256.txt)
actual_version=$("$CHROME" --version)
actual_digest=$(sha256sum -- "$CHROME" | awk '{print $1}')
if [ "$actual_version" != "$expected_version" ] || [ "$actual_digest" != "$expected_digest" ]; then
  printf '%s\n' 'container Chrome identity does not match the certified image' >&2
  exit 1
fi
if [[ "$actual_version" == *"Chrome for Testing"* ]]; then
  printf '%s\n' 'testing-only Chrome distributions are prohibited' >&2
  exit 1
fi

sway_pid=
cleanup_sway() {
  if [ -n "$sway_pid" ]; then
    kill "$sway_pid" 2>/dev/null || true
    wait "$sway_pid" 2>/dev/null || true
  fi
}
trap cleanup_sway EXIT INT TERM

if [ "$profile_mode" = headful ]; then
  export WLR_BACKENDS=headless WLR_LIBINPUT_NO_DEVICES=1 WLR_NO_HARDWARE_CURSORS=1
  export WLR_RENDERER=pixman WLR_RENDERER_ALLOW_SOFTWARE=1 LIBSEAT_BACKEND=noop
  export XDG_SESSION_TYPE=wayland WAYLAND_DISPLAY=wayland-1
  sway -d > /tmp/sway.log 2>&1 &
  sway_pid=$!
  if ! timeout 15s python3 - "$XDG_RUNTIME_DIR" "$WAYLAND_DISPLAY" <<'PY'
import ctypes
import os
import select
import stat
import struct
import sys

runtime_dir, display = sys.argv[1:]
socket_path = os.path.join(runtime_dir, display)
libc = ctypes.CDLL(None, use_errno=True)
fd = libc.inotify_init1(os.O_CLOEXEC)
if fd < 0:
    raise OSError(ctypes.get_errno(), "inotify_init1")
watch = libc.inotify_add_watch(fd, os.fsencode(runtime_dir), 0x00000100 | 0x00000080)
if watch < 0:
    raise OSError(ctypes.get_errno(), "inotify_add_watch")
try:
    if os.path.exists(socket_path) and stat.S_ISSOCK(os.stat(socket_path).st_mode):
        sys.exit(0)
    while True:
        select.select([fd], [], [])
        data = os.read(fd, 4096)
        offset = 0
        while offset + 16 <= len(data):
            _, _, _, name_length = struct.unpack_from("iIII", data, offset)
            name = data[offset + 16:offset + 16 + name_length].split(b"\0", 1)[0]
            offset += 16 + name_length
            if name == os.fsencode(display) and os.path.exists(socket_path):
                if stat.S_ISSOCK(os.stat(socket_path).st_mode):
                    sys.exit(0)
finally:
    os.close(fd)
PY
  then
    printf '%s\n' 'Sway did not create its Wayland socket within 15 seconds' >&2
    exit 1
  fi
fi

/usr/local/bin/cas374-profile-browser-stealth --mode "$profile_mode" "$@"
