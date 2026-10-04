# CAS-333 container browser benchmarks

Container browser measurements are a separate, local benchmark environment. They are not a replacement for native results and do not publish a performance target.

## Contract

`cargo xtask benchmark browser` is the only repository orchestrator. It runs and retains four labelled environments:

- `native-headless` and `native-headful` run on the prepared host;
- `container-headless` and `container-headful` run the same bounded profile matrix in Docker.

The container matrix covers success, post-ownership cancellation, deadline, and failure at concurrency 1, 2, and 4. Each row reports nearest-rank attempt elapsed and cancellation-return p50, p95, and p99. Matrix directories are written to a sibling staging directory and atomically renamed. Artifact references in records are relative filenames, not host paths.

Success, cancellation, and failure attempts use a 15,000 ms bound; the
deliberate deadline workload remains fixed at 5,000 ms. These are hard bounds,
not settlement delays.

A container image may be reused only when its labels exactly match the current Yosoi source, VoidCrawl provider source, fixture, and combined build SHA-256 values. The image ID, base image ID, platform, Docker server/storage/cgroup/OCI runtime versions, in-image Chromium version, hashes, security profile hash, and labelled run/change identity are retained; full Docker inspect output, environment dumps, and process argv are not retained.

## Image and runtime isolation

The Dockerfile pins the Linux/amd64 `rust:1.98` builder manifest at
`sha256:af753e6e729c839de28010e323abc550eceaa9572bdaa765429d4f585e2e43dc`
and uses the local `voidcrawl-headful:local` hardened runtime. The runner
refuses to build unless that runtime tag resolves to the reviewed image ID
`sha256:9f89ca6fcbe3ed40f9c3847edaecf9de98b997e57dd65395a990916cd68dd82a`;
it labels the result with that identity and verifies the runtime layers are an
exact prefix of the built image. The runtime binary and entrypoint run as
`10001:10001`; mutable state is confined to `/tmp`.

The generated build context copies complete Yosoi and VoidCrawl workspaces but excludes VCS metadata, agent state, outputs, dotenv files, credentials, keys, certificates, and common generated directories. It is generated outside the checkout rather than relying on an ambient Docker build context.

Every benchmark container uses:

- `--network none`, a read-only root filesystem, and `/tmp` as a `rw,nosuid,nodev,noexec,size=1g` tmpfs;
- `--shm-size=1g`, `--memory=4g`, `--memory-swap=4g`, `--cpus=2`, and `--pids-limit=2048`;
- `--cap-drop ALL`, `no-new-privileges`, and the reviewed pinned seccomp profile.

The PID cgroup counts Chrome threads as well as processes. A 1024 limit was
proven insufficient at four simultaneous headful captures even though peak
memory remained below 2 GB, so 2048 is the smallest reviewed bounded tier with
headroom for that matrix cell. Nonzero `pids.events:max` remains a review alert.

The Chrome sandbox is required: `CHROME_NO_SANDBOX=0` is enforced by the entrypoint. Privileged containers, host networking, an unconfined seccomp profile, and no-sandbox operation are invalid for this benchmark.

Headful containers start a headless Sway compositor. Wayland readiness waits for the compositor socket creation using an inotify event; a timeout only bounds failure and is not a readiness delay.

## Cgroup evidence and cleanup

The runner samples the unified cgroup v2 for CPU usage and throttling, memory current/peak/events, PID current/peak/events, IO counters, and cgroup events. The cgroup must disappear after the container exits; a remaining cgroup is a failed matrix record. Process and cgroup output does not persist command lines or environments.

Cleanup queries and removes only containers carrying `com.cascadinglabs.yosoi.cas333=true`. It never uses Docker prune operations or broad cleanup.

## Comparison limits

Container results are comparable only with the same image identity, exact source/provider/fixture hashes, seccomp hash, resource limits, browser/runtime metadata, fixture artifact set, workload, concurrency, and host cgroup behavior. Docker storage and CPU scheduling, Sway software rendering, kernel/cgroup implementation, browser version, and host GPU/display differences can dominate results. Do not compare container and native timings as interchangeable performance numbers.

All benchmark targets are loopback fixtures. No public URL is a valid target.
