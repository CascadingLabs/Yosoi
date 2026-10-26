# Headless Moli service

The image contains pinned Moli 1.1.19 and its upstream licenses. Yosoi's optional
`browser-bidi` controller connects at `ws://127.0.0.1:9222/session`.

```sh
docker compose -f docker/moli/compose.yaml up --build -d
docker compose -f docker/moli/compose.yaml down
```

The single runtime Compose file publishes only on loopback. It runs UID/GID
10001 with a read-only root, private 128 MiB tmpfs, dropped capabilities,
no-new-privileges, 1 CPU, 768 MiB memory and 128 PIDs. Carry those restrictions
into other orchestrators. A remote client needs a trusted network or authenticated
tunnel: BiDi grants browser control.

## Profiles

| Variable | Default | Values |
| --- | --- | --- |
| `MOLI_PROFILE` | `dom` | `dom` or `layout`; always headless |
| `MOLI_RESOURCES` | `0` | `1` loads optional image/font/media resources |
| `MOLI_ALLOW_PRIVATE_NETWORKS` | `0` | `1` deliberately permits private networks |

```sh
MOLI_PROFILE=layout docker compose -f docker/moli/compose.yaml up -d --force-recreate
```

The entrypoint rejects unknown values/extra arguments, clears proxy variables,
and bounds HTTP to 8 concurrent requests, 4 per host, 16 MiB per response and
15 seconds. The native private-address filter is not a universal egress firewall.

Match the service profile in `Policy.browser`; see the paired Rust/Python
[engine-selection examples](../../docs/public/concepts/choosing-a-browser.md).
Select rendered DOM explicitly for Requests. Session PNG/input require layout;
input also requires Screenshot permission. Remote engine versions and enforcement
claims remain unavailable when they cannot be observed. Closing a client releases
its logical contexts, not the shared server process.

## Health and tests

Health uses the existing curl binary against Moli's native `/status` endpoint.
It creates no session. Installed-SDK tests verify BiDi itself.
There is no C health program or compiler stage. Firefox tests use the installed
regular release unchanged; the common HTTP pages are browser test inputs.

The test-only Compose project lives in `python/tests/bidi/compose.yaml`, separate
from runtime configuration. It runs allowed/blocked peers against one counted
fixture, including a deterministic redirect hop. CI executes its pytest policy
and fault cases, installed consumers, isolation and bounded stress.

## Export without publishing

The base digest, signed package snapshot and amd64/arm64 archive checksums are
pinned in the Dockerfile. Only tested architectures are qualified. The image
retains package and executable digests under `/usr/share`.

```sh
docker save --output yosoi-moli-1.1.19.tar yosoi-moli:1.1.19-local
sha256sum yosoi-moli-1.1.19.tar
# On the receiving machine:
docker load --input yosoi-moli-1.1.19.tar
```

Verify the export digest and use the same Compose restrictions after loading.
Registry publication, deployment and anti-bot compatibility are separate steps.
