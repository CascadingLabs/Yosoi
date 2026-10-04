# Yosoi SDK, browser, and benchmark documentation

Current engineering guides live here. Publishable website sources are in
[`public/`](public/); past ticket plans and verification records are in
[`archive/`](archive/README.md). Historical results describe their recorded
revisions, not the current checkout.

## Yosoi Map

The public bounded discovery API, scopes, sources, limits, and persisted Policy
compatibility boundary are documented in [Yosoi Map](map.md). The pure shared
admission/parser helpers are described in [`yosoi-map`](../crates/yosoi-map/README.md).

## Yosoi Search

The provider-backed SDK shape and its Policy boundary are in
[Yosoi Search](search.md). Command behavior and JSON schema are in
[Search CLI](cli-search.md). The bounded local HTTP evidence and open
certification gates are in [Search HTTP evidence](archive/search-local-http-evidence-2026-10-03.md). The current-Stable
DuckDuckGo capability probe is recorded in [DDG container evidence](archive/search-ddg-container-evidence-2026-10-03.md).

## CLI Policy profiles

The version-keyed JSON store and read-only Policy commands are
documented in [CLI Policy profiles](cli-policy-profiles.md).

## Requests CLI

The profile-aware Request command, outcome modes, and raw Document selection
are documented in [Requests CLI](cli-requests.md).

## Map CLI

Page and passive subdomain mapping, JSON redirects, and Map-to-Locate pipes
are documented in [Map CLI](cli-map.md).

## Locate CLI

The file/stdin locator commands and typed Request-to-Locate Document pipe are
documented in [Locate CLI and Document pipes](cli-locate.md).

## CLI foundation handoff

Local installation, completion scripts, integrated examples, and validation
scope are in [CLI foundation handoff](cli-foundation.md).

The exact current-Stable package identity and focused live HTTP/headless/headful
CLI results are in [CLI live URL validation](cli-live-qa.md).

## Policy tuning

The default-only tuning surface, operation call order, existing private HTML
streaming route, and future mode boundary are in [Policy tuning](policy-tuning.md).

## CLI

The [CLI foundation handoff](cli-foundation.md) covers local installation,
completion scripts, Policy profiles, Requests, and Locate. The
[live URL validation](cli-live-qa.md) records the focused HTTP and browser
checks and their limits.

## Archive

The approved first local persistence boundary is documented in
[CAS-309 minimal local Archive contract](archive/cas-309-local-archive-contract.md).
Its executable Policy-first and later offline-replay examples are fixed in the
[CAS-309 golden Archive journey](archive/cas-309-archive-golden-journey.md).

## Contracts and Extractor

The derive-backed Contract, model-shaped candidate extraction, and explicit
runtime validation SDK is documented in
[Contracts and Extractor](contracts-extractor.md). The correctness and
architecture evidence for the first integrated slice is recorded in
[CAS-409 certification](archive/cas-409-contracts-extractor-certification.md).

## CAS-374 browser stealth policy

The supported automation-disclosure policy, threat model, launch-switch audit,
hermetic matrix, and optional passive live checks are in
[CAS-374 browser stealth policy and certification](archive/cas-374-browser-stealth.md).
Current measured outcomes and validation limits are in
[CAS-374 browser stealth results](archive/cas-374-browser-stealth-results.md).

## CAS-373 Chromium/CDP surface

The authoritative repository-internal command, event, domain, M153 status,
ownership, and evidence inventory is in
[Yosoi CDP surface at Chromium M153](chromium-cdp-surface.md).

## CAS-352 advanced browser execution

The ownership, isolation, admission, lease, cleanup, and operating-envelope contract
for warm browser processes is in [CAS-352 bounded browser execution leases](archive/cas-352-browser-execution-leases.md).

## CAS-333 browser environments

`cargo xtask benchmark browser` is the all-four-environment CAS-333 orchestrator:

| Label | Execution boundary | Display mode |
| --- | --- | --- |
| `native-headless` | prepared host | headless browser |
| `native-headful` | prepared host | dedicated `1920x1080x24` X11/Xvfb display |
| `container-headless` | hardened Docker container | headless browser |
| `container-headful` | hardened Docker container | headless Sway/Wayland compositor |

`cargo xtask benchmark check` is compile-only: it compiles browser harnesses and profile binaries without collecting a benchmark. Browser measurements remain excluded from `cargo xtask benchmark all`.

Native and container outputs are distinct evidence classes. Native headful runs
use an isolated Xvfb display rather than an operator's interactive compositor;
container runs add Docker, cgroup-v2 limits, seccomp, software compositor, and
image-identity variance. Compare results only within equivalent labelled
environments and matching recorded inputs and runtime metadata. Do not treat
container timing as directly interchangeable with native timing.

Container benchmark details, isolation limits, cgroup evidence, image reuse, and cleanup rules are in [CAS-333 container benchmarks](archive/cas-333-container-benchmarks.md). Browser fixture, workload, and metric rules are in [CAS-333 browser benchmarks](archive/cas-333-browser-benchmarks.md). Both use loopback-only fixtures; no public URL is a benchmark target.
