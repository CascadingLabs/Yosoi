---
title: 'Docker setup'
description: 'Start the headless or headful Chromium browser service in Docker.'
order: 2
---

# Docker setup

The Chromium/CDP images run a browser inside a Linux container. The headless image runs without a display. The headful image includes a virtual display, so its browser windows stay inside the container.

These images contain the browser service, not the Yosoi SDK or your application. Yosoi's current Session API launches a local browser and does not attach to these CDP endpoints. Installing the browser container does not change where an existing Yosoi program runs.

This page assumes Docker is installed and its daemon is running.

## Requirements

The commands below use Docker Engine on Linux and host networking. Docker Desktop has different host-network requirements; see [Docker's host networking guide](https://docs.docker.com/engine/network/drivers/host/). This walkthrough has been checked on Linux, not Docker Desktop.

| Requirement                    | Headless                                 | Headful                       |
| ------------------------------ | ---------------------------------------- | ----------------------------- |
| Published image architectures  | AMD64, ARM64                             | AMD64                         |
| Display                        | None                                     | Sway/Wayland inside the image |
| Host desktop or display socket | Not needed                               | Not needed                    |
| Browser sandbox                | Enabled                                  | Enabled                       |
| Example resource limits        | 1 CPU, 2 GiB memory, 1 GiB shared memory | Same                          |
| CDP port for one browser       | 9222                                     | 19222                         |
| Optional viewer port           | None                                     | 6080                          |

Use the headful image on a native AMD64 machine for this walkthrough. ARM64 headful emulation is not covered here. The resource limits make these examples bounded; they are not a sizing recommendation for a large job.

The host kernel must permit the user namespaces needed by Chromium's sandbox. Use the supplied seccomp profile, run as the image's non-root user, and preserve site/process isolation. Do not fix a sandbox startup error with privileged mode or `--no-sandbox`.

Host networking shares the host's network namespace. The image binds CDP and its optional viewer to loopback. Keep the listed ports free, and do not publish browser control to the public network.

## Download the sandbox profile

Docker loads this profile from your host before starting the container. It permits the namespace operations Chromium needs to run its sandbox. A file inside the image cannot configure that startup policy; see [Docker's seccomp documentation](https://docs.docker.com/engine/security/seccomp/).

Download the profile from the same release as the browser images and keep it in the directory where you run the commands below.

```sh
curl --fail --location --output seccomp-chrome.json \
  https://raw.githubusercontent.com/CascadingLabs/Yosoi/v0.2.1/docker/browser/seccomp-chrome.json
```

## Example: start one browser

Choose one variant. Both use the container name `yosoi-browser`; stop the first before trying the other. The `--rm` option removes the container when it stops.

### Headless

```sh
docker run --rm -d --init --name yosoi-browser \
  --network host \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --security-opt seccomp=seccomp-chrome.json \
  --cpus 1 --memory 2g --pids-limit 512 --shm-size 1g \
  -e BROWSER_COUNT=1 \
  ghcr.io/cascadinglabs/chromium-cdp:headless-0.2.1
```

There is no display or viewer. The browser's CDP listener is at `127.0.0.1:9222` on this Linux host. Browser JavaScript still runs in headless mode.

### Headful

```sh
docker run --rm -d --init --name yosoi-browser \
  --network host \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --security-opt seccomp=seccomp-chrome.json \
  --cpus 1 --memory 2g --pids-limit 512 --shm-size 1g \
  -e BROWSER_COUNT=1 -e VIEWER_MODE=local \
  ghcr.io/cascadinglabs/chromium-cdp:headful-0.2.1
```

The browser has a window on the container's virtual display. It does not open a window on your desktop. The CDP listener is at `127.0.0.1:19222`. `VIEWER_MODE=local` permits an optional viewer; it does not open one automatically.

## Check startup

```sh
docker inspect --format '{{.State.Health.Status}}' yosoi-browser
docker logs yosoi-browser
```

The health status begins as `starting`. Continue when it reports `healthy`. `unhealthy` or an exited container means startup failed; the logs identify which service needs attention.

## View a headful browser

Once the headful container is healthy, request a short-lived viewer:

```sh
docker exec yosoi-browser viewerctl open --browser 1 --ttl 15m
```

Open the printed local URL in your own browser. It includes a temporary token. The viewer lets you see and control the container's display without adding its windows to your desktop. The lease expires after fifteen minutes. Close it sooner with:

```sh
docker exec yosoi-browser viewerctl close
```

This viewer is only available in the headful image. Keep its token-bearing URL private.

## Stop the browser

```sh
docker stop yosoi-browser
```

The example stores browser profiles and logs in the container's temporary filesystem. Removing it discards that state. Saving application evidence is a separate decision.

## Next

[Keeping browser windows in Docker](../concepts/browser-windows-in-docker.md) opens the familiar lamp page on the container's display and explains what changes about headful execution.
