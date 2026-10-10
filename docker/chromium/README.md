# Chromium/CDP runtime images

These are generic browser services adapted from the existing
[CascadingLabs/VoidCrawl images](https://github.com/CascadingLabs/VoidCrawl/tree/f7ca3ee0e9ad427e7695e1b241639cd7084f2975/docker),
not a new Yosoi application image. The existing `docker/browser` and
`docker/browser-stealth` images remain historical benchmark wrappers.

| Release image | Platforms | Default CDP ports |
| --- | --- | --- |
| `ghcr.io/cascadinglabs/chromium-cdp:headless-VERSION` | Linux AMD64, ARM64 | 9222, 9223 |
| `ghcr.io/cascadinglabs/chromium-cdp:headful-VERSION` | Linux AMD64 | 19222, 19223 |

Replace VERSION with a published version such as `0.1.0-rc.3`. RC tags never
move a `latest` alias. Publication requires every SDK release gate and all
three native container smoke jobs. CI builds each image once, transfers the
smoke-tested Docker archives, and pushes those bytes after verification.
Versioned image and index tags reject different existing bytes. Anonymous
manifest access is required before GitHub release publication; a new GHCR
package may need its visibility set to public in GitHub's package settings.

## Running

```sh
docker run --rm --init --cap-drop ALL --security-opt no-new-privileges:true \
  --security-opt seccomp=docker/browser/seccomp-chrome.json \
  --cpus 1 --memory 2g --pids-limit 512 --shm-size 1g \
  --network host \
  ghcr.io/cascadinglabs/chromium-cdp:headless-0.1.0-rc.3
```

On Linux, host networking makes Chromium's loopback CDP listeners reachable
at `127.0.0.1:9222` and `127.0.0.1:9223`. Bridge-mode `-p` mappings cannot
forward to a listener bound only to container loopback. Use a private tunnel
or a shared network namespace when host networking is unavailable.

Use the headful tag and ports 19222/19223 for the Sway/Wayland service. Both
variants run as UID/GID 10001, preserve Chromium's sandbox and site isolation,
and keep profiles/configuration/logs under `/tmp/yosoi`. The existing `docker/browser/seccomp-chrome.json`
seccomp profile allows the namespaces required by Chromium's user sandbox.
Do not add `--no-sandbox`, privileged mode, or a public CDP port binding.
CDP grants control of the browser: use loopback or an authenticated private
network. CI uses `--network none`; normal browsing requires network access.

`BROWSER_COUNT` (1–8), `CDP_PORT_BASE`, `VNC_WIDTH`, `VNC_HEIGHT`, and
`CHROME_PROFILES_DIR` configure the farm. Defaults retain two independent
browsers/profiles; headful browsers each own a distinct Sway output. Ports
are consecutive from the base, replacing the Alpha image's individual
`CDP_PORT_1`/`CDP_PORT_2` overrides. The runtime has no Yosoi Python dependency
or automatic worker-pool sizing; clients select `BROWSER_COUNT` explicitly.

Headful viewer support is opt-in: set `VIEWER_MODE=local`, then run
`docker exec CONTAINER viewerctl open --browser 1 --ttl 15m`.
`viewerctl close` revokes it; `viewerctl status` reports the lease. The noVNC
listener binds container loopback, so operator access needs a private tunnel
or shared network namespace. Viewer startup observes log events and is
bounded by a timeout; lease expiry is a timer. Host GPU access is optional:
pass `/dev/dri` and the host render group if appropriate; otherwise Sway uses
software rendering. Hardware GPU behavior is not covered by hosted smoke tests.

## Browser identity and evidence

The Debian 13 base is pinned by digest. Regular Debian Stable/security
Chromium, chromium-common, and chromium-sandbox are pinned to
`154.0.8037.92-1~deb13u1` for both architectures, as listed by
[Debian](https://packages.debian.org/trixie/chromium). This is a normal browsing
distribution, not Chrome for Testing. The repository's 2026-10-10 eligibility
snapshot includes this M154 version; admitting Debian 13's distribution suffix
preserves the exact version/age checks. It does not promote the historical
M153 controller/CDP certification tuple.

Builds record package versions, browser version, and executable SHA-256 in
`/usr/share/chromium-cdp`. Smoke evidence records these identities separately
from the OCI source/revision labels and image ID. CI checks both CDP endpoints,
headful output routing, non-root operation, renderer sandbox filters, and the
inactive viewer. Full Yosoi browser compatibility/benchmark certification is
separate; these smoke checks do not certify stealth or hardware GPUs. The
current SDK's remote attachment policy also requires a verifiable local
executable and loopback endpoint; an arbitrary remote container URL alone is
not a supported SDK attachment configuration.

Update pins deliberately when Debian security updates become available;
expired or unsupported versions must not be represented as certified.
