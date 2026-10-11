# CAS-326 browser fixture corpus

`fixtures/browser-acquisition-v1.json` is the versioned, loopback-only contract for
future CAS-329/327 adapter tests. The harness intentionally starts no browser and
has no VoidCrawl dependency. It exposes only synthetic HTTP stimuli and durable
counted barriers; adapters decide cancellation/deadline timing and provider-close
execution.

The primary journey is `/redirect` → `/shell` → JavaScript `fetch('/secondary')`.
The shell's response source contains a distinct DOM-mutation stimulus with
accessible text and fixed CSS geometry. It also emits console records and throws a
deliberate JavaScript exception. Request order is asserted by receipt barriers, not
wall-clock sleeps. Until a browser adapter is wired, DOM, AX, screenshot, CDP, and
provider-close assertions are explicitly deferred; this harness verifies only their
source stimuli and manifest descriptors.

Other routes cover held delayed responses, endless activity, frame/document scope,
cache and service-worker stimuli, event/byte floods, and a declared-length partial
disconnect. Provider/page/browser close and renderer-crash entries are descriptors:
they must be exercised by a browser-capable consumer, not this HTTP-only harness.

Fixture-file digests and every deterministic response body/stimulus have exact byte sizes
and SHA-256 values in the manifest and are self-checked (including generated floods,
partial/endless prefixes, and empty redirect/404 bodies). Scenario IDs are versioned;
change an ID/version rather than silently changing a stimulus.
Headless is the metadata default, headful is compatible, and visual assertions must
check structure/geometry only—never cross-browser pixel equality.
