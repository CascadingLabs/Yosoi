# Browser Acquisition conformance corpus

`browser-acquisition-v1.json` is the versioned provider-native scenario index
for VoidCrawl's local Chromium contract. It intentionally contains no Yosoi
capture IDs or artifact models. A future Yosoi adapter may serve these files on
loopback and map VoidCrawl results into its own types.

## Provenance

All checked-in payloads are hand-authored synthetic fixtures. Required tests
use `127.0.0.1` or `data:` URLs only. No public-site response, credential,
cookie, or recording is a corpus input. Dynamic entries prefixed `server:` are
implemented by the named Rust integration fixture; `provider:` entries are CDP
lifecycle actions rather than HTTP payloads.

## Golden rules

The JSON records categorical expectations, not unstable timestamps, target
IDs, ports, browser-generated node IDs, or raw screenshots. Reviewers update a
golden only when the provider-native contract intentionally changes:

1. Add a new versioned manifest for a breaking field/meaning change; do not
   silently rewrite an already released version.
2. Keep scenario IDs stable. Add a new ID when stimulus semantics change.
3. Every scenario must name deterministic test coverage and at least one
   terminal/completeness/bounds expectation.
4. Pixel bytes are asserted structurally (PNG signature, dimensions, capture
   region, document epoch), never as cross-Chromium exact hashes.
5. Public-site canaries belong outside required CI and must not be referenced
   as conformance coverage.
6. Synthetic sensitive strings may test protection boundaries, but goldens
   must never contain retained console text, URLs with credentials/query
   values, cookies, headers, or live CDP handles.

## Fixture inventory

- `static.html`: stable DOM/AX and shared-vs-isolated origin state.
- `delayed-dom.html`: same-document mutation after a bounded delay.
- `runtime-error.html`: console error and exception in the first script.
- `frame-parent.html` / `frame-child.html`: explicit child-frame scope.
- `oopif-parent.html` / `oopif-child.html`: deterministic cross-site iframe
  target and session routing using loopback host mappings for `a.test`,
  `b.test`, and `c.test`.
- `visual-layout.html`: deterministic geometry change without navigation.
- `service-worker.html` / `conformance-sw.js`: service-worker registration
  stimulus. Runtime readiness is not itself a required timing assertion;
  navigation provenance may report service-worker state or explicit
  unavailability.
