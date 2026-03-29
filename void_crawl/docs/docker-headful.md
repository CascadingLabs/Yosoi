# Docker Headful Mode

Run Chrome with a real GUI inside Docker — GPU-accelerated, isolated from your desktop, viewable via VNC.

## What's happening under the hood

```
┌─────────────────── Docker container ───────────────────┐
│                                                        │
│  Sway (Wayland compositor)                             │
│    Creates a virtual screen in GPU memory.             │
│    Chrome draws its windows here — no physical         │
│    monitor needed. Runs with WLR_BACKENDS=headless     │
│    so it doesn't try to find a real display.           │
│                                                        │
│  Chrome (headful, GPU-accelerated)                     │
│    Renders pages into Sway's virtual screen using      │
│    --ozone-platform=wayland. Uses your GPU via         │
│    /dev/dri passthrough for hardware rendering.        │
│    Exposes CDP on ports 19222 and 19223.               │
│                                                        │
│  wayvnc (VNC server)                                   │
│    Reads pixels from Sway's virtual screen and         │
│    streams them to any VNC client on port 5900.        │
│    Uses --gpu for hardware H.264 encoding.             │
│                                                        │
└────────────────────────────────────────────────────────┘
         │                              │
         │ /dev/dri (GPU passthrough)   │ port 5900 (VNC)
         │ port 19222, 19223 (CDP)      │
         ▼                              ▼
┌──── Your host ──────────────────────────────────────────┐
│  void_crawl connects to localhost:19222 via CDP       │
│  VNC client connects to localhost:5900 to watch         │
└─────────────────────────────────────────────────────────┘
```

## Why not just run Chrome headful natively?

- Chrome headful on your desktop steals focus, pops up windows, and interferes with your work
- Docker isolates everything — Chrome runs in its own display server
- You can watch what Chrome sees via VNC, or ignore it entirely
- Same container works in CI/CD, on remote servers, anywhere Docker runs

## Quick start

```bash
# Auto-detects your GPU (AMD/Intel/NVIDIA) and starts everything
./docker/run-headful.sh

# Or specify GPU manually
./docker/run-headful.sh --gpu amd
./docker/run-headful.sh --gpu nvidia
./docker/run-headful.sh --gpu intel
./docker/run-headful.sh --gpu cpu        # no GPU, software rendering
```

Once running, you have three things available:

| Port | What | How to use |
|------|------|------------|
| `localhost:6080` | **noVNC (browser)** | Open **http://localhost:6080** in any browser to **watch Chrome** |
| `localhost:5900` | VNC (native) | Or use a VNC client (Remmina, TigerVNC) for lower latency |
| `localhost:19222` | CDP | void_crawl connects here to control Chrome browser 1 |
| `localhost:19223` | CDP | void_crawl connects here to control Chrome browser 2 |

## Connecting void_crawl to Docker Chrome

```python
import asyncio
import os
from void_crawl import BrowserPool

# Tell the pool to connect to Docker's Chrome instances
os.environ["CHROME_WS_URLS"] = "http://localhost:19222,http://localhost:19223"

async def main():
    async with await BrowserPool.from_env() as pool:
        async with await pool.acquire() as tab:
            # This navigation happens inside Docker's Chrome.
            # If you have a VNC client open on localhost:5900,
            # you'll see the page load in real time.
            await tab.goto("https://en.wikipedia.org/wiki/Web_scraping")
            print(f"Title: {await tab.title()}")
            print(f"HTML length: {len(await tab.content())} chars")

asyncio.run(main())
```

## Viewing Chrome

### In your browser (easiest)
noVNC is built into the container. Just open:

```
http://localhost:6080
```

Click **Connect** — you'll see Chrome's windows live inside Sway. No software to install.

### Native VNC client (lower latency)

#### Remmina (Linux)
1. Open Remmina
2. New connection → Protocol: VNC
3. Server: `localhost:5900`
4. Connect

#### TigerVNC viewer (any OS)
```bash
vncviewer localhost:5900
```

> **Note**: VNC uses a binary protocol (RFB), not HTTP. You cannot open `localhost:5900` directly in a browser — that's what noVNC on port 6080 is for.

## Custom resolution

```bash
# 2K resolution
VNC_WIDTH=2560 VNC_HEIGHT=1440 ./docker/run-headful.sh

# 720p for lower memory usage
VNC_WIDTH=1280 VNC_HEIGHT=720 ./docker/run-headful.sh
```

## GPU support matrix

| GPU | Driver | Container setup | Notes |
|-----|--------|----------------|-------|
| AMD iGPU | amdgpu | `/dev/dri` passthrough | Works out of the box. Uses Mesa RADV. |
| AMD discrete | amdgpu | `/dev/dri` passthrough | Same as iGPU |
| Intel iGPU | i915/xe | `/dev/dri` passthrough | Works out of the box. Uses Mesa ANV. |
| NVIDIA | nvidia | `/dev/dri` + `--gpus all` | Needs `nvidia-container-toolkit` on host + `nvidia-drm.modeset=1` kernel param. Sway runs with `--unsupported-gpu`. |
| None | — | No device passthrough | Falls back to `pixman` (CPU software rendering). Slower but works everywhere. |

## Stopping

```bash
# If started in foreground (no -d), just Ctrl+C

# If started detached
docker compose -f docker/docker-compose.headful.yml --profile amd down
```

## Platform support

| Platform | Headful GPU | Headless Docker | Notes |
|----------|------------|----------------|-------|
| **Linux** | Yes | Yes | Full GPU passthrough via `/dev/dri`. This is the primary target. |
| **macOS** | No | Yes | Docker Desktop runs a Linux VM — no GPU passthrough. Use the headless `docker/Dockerfile` instead. |
| **Windows** | No | Yes | Same as macOS — Docker Desktop's VM has no GPU access. `network_mode: host` also behaves differently. Use the headless `docker/Dockerfile` instead. |
| **WSL2** | Partial | Yes | WSL2 has `/dev/dri` for Intel/AMD iGPUs via Mesa, but Docker-in-WSL GPU passthrough is unreliable. Not officially supported. |

The headful GPU container is a **Linux-only** feature. It relies on:
- `/dev/dri` device passthrough (Linux DRM subsystem)
- Sway/wlroots (Linux Wayland compositor)
- `network_mode: host` (Linux Docker only)

For Windows/macOS, use the standard headless Docker setup (`docker/docker-compose.yml`).

## Troubleshooting

**VNC shows black screen**: Sway might not have started yet. Wait a few seconds — wayvnc auto-reconnects.

**Chrome not responding on CDP**: Check `docker logs <container>` for errors. Common cause: port conflict if you have native Chrome also running on 19222.

**High memory usage**: Each headful Chrome instance uses ~300-500 MB more than headless because it maintains a real render tree + GPU buffers. This is expected.
