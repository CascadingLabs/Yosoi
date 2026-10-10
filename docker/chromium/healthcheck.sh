#!/usr/bin/env bash
set -euo pipefail
if [ "${BROWSER_MODE:-headful}" = headful ]; then /usr/local/bin/check-outputs.sh; fi
python3 - <<'HEALTH'
import os, pathlib, urllib.request
count, base = int(os.environ.get('BROWSER_COUNT', '2')), int(os.environ.get('CDP_PORT_BASE', '9222'))
if not 1 <= count <= 8 or not 1024 <= base <= 65536-count:
    raise ValueError('Invalid CDP farm bounds')
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for port in range(base, base+count):
    with opener.open(f'http://127.0.0.1:{port}/json/version', timeout=2) as response:
        if response.status != 200: raise ValueError('CDP is unavailable')
renderers = 0
for process in pathlib.Path('/proc').iterdir():
    if process.name.isdigit():
        try:
            if b'--type=renderer' in (process/'cmdline').read_bytes().replace(b'\0', b' ').split():
                renderers += 1
        except FileNotFoundError:
            pass
if renderers < count: raise ValueError('Browser renderers are not ready')
HEALTH
