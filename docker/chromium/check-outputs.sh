#!/usr/bin/env bash
# Healthcheck for headful output routing and CDP readiness.
set -uo pipefail

BROWSER_COUNT="${BROWSER_COUNT:-2}"
CDP_PORT_BASE="${CDP_PORT_BASE:-19222}"
[[ "$BROWSER_COUNT" =~ ^[1-9][0-9]*$ ]] || { echo "[guard] invalid BROWSER_COUNT"; exit 1; }
[[ "$CDP_PORT_BASE" =~ ^[1-9][0-9]*$ ]] || { echo "[guard] invalid CDP_PORT_BASE"; exit 1; }

export SWAYSOCK="${SWAYSOCK:-$(find "${XDG_RUNTIME_DIR:-/tmp/yosoi/xdg}" -maxdepth 1 -name 'sway-ipc.*.sock' -type s -print -quit 2>/dev/null)}"
[ -S "${SWAYSOCK:-}" ] || { echo "[guard] no sway IPC socket yet"; exit 1; }

tree=$(swaymsg -t get_tree 2>/dev/null) || { echo "[guard] swaymsg failed"; exit 1; }

SWAY_TREE="$tree" python3 - "$BROWSER_COUNT" "$CDP_PORT_BASE" <<'PY'
import json
import os
import sys
import urllib.request

count, port_base = map(int, sys.argv[1:])
locations = {}

def walk(node, output=None):
    if node.get("type") == "output":
        output = node.get("name")
    app_id = node.get("app_id", "")
    if app_id.startswith("chrome-"):
        locations[app_id] = output
    for child in node.get("nodes", []) + node.get("floating_nodes", []):
        walk(child, output)

walk(json.loads(os.environ["SWAY_TREE"]))
expected = [f"chrome-{index}" for index in range(1, count + 1)]
missing = [name for name in expected if not locations.get(name)]
outputs = [locations[name] for name in expected if locations.get(name)]
if missing:
    raise SystemExit(f"[guard] not ready: missing windows {', '.join(missing)}")
if len(set(outputs)) != count:
    raise SystemExit(f"[guard] FAIL: browsers share outputs: {locations}")
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for index in range(count):
    try:
        with opener.open(f"http://127.0.0.1:{port_base + index}/json/version", timeout=2) as response:
            if response.status != 200:
                raise OSError(f"HTTP {response.status}")
    except OSError as exc:
        raise SystemExit(f"[guard] CDP chrome-{index + 1} unavailable: {exc}") from exc
print("[guard] OK: " + ", ".join(f"{name}={locations[name]}" for name in expected))
PY
