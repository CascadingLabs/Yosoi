# CAS-334 browser-native evidence

## Boundary

CAS-334 translates owned VoidCrawl observations into validated `BrowserAdapterFacts` and staged artifact envelopes. CAS-332 exclusively owns durable admission, final artifact publication, and bundle-last finalization. Capture-local frame IDs and document epochs are not reusable DOM identities.

## Accessibility

Accessibility evidence is a canonical, provider-neutral wrapper around an explicitly bound provider payload schema (`ChromiumCdpAxNodeJson`, version 1). The provider supplies schema/version, full-tree or depth-limited capture mode, requested depth, and ignored-node policy; the adapter does not invent them. The wrapper records scope and offset, observed/retained/exact-or-unknown lost nodes, and configured limit, enforcement layer, budget scope, observed/retained/lost bytes, completeness, and canonical node bytes. Retained nodes—not observed nodes—are checked against the configured node bound, and known node and byte accounting must reconcile. Chromium materializes the AX node vector before provider retention enforcement; this is not a streaming-memory guarantee.

## Visual and layout

Visual evidence is PNG only. VoidCrawl validates the PNG signature, the 13-byte IHDR declaration, and nonzero IHDR dimensions before returning an owned visual snapshot. Yosoi retains the PNG in full only when it fits the independent screenshot bound; an oversized materialized PNG is discarded, never byte-truncated. The outcome explicitly names post-materialization limiting.

Visual facts record pixel dimensions, CSS viewport dimensions, document scroll offsets, device scale, capture time, document scope, and a typed layout relationship. Layout and visual are separate sequential captures with separate factual offsets. Matching scopes permits only `SameDocumentEpochOnly`; it never claims simultaneous or atomic measurement. A changed or unavailable epoch yields `Unavailable`. Atomic staging remains all-or-none admission of each retained artifact and does not strengthen measurement correlation. No pixel-equality gate is used. Layout geometry is integer micro-CSS-pixels and records layout viewport, visual viewport, content bounds, DPR, scope, and time.

## Runtime diagnostics

The observation scope is armed before navigation whenever runtime diagnostics are requested. Console and exception markers retain provider receipt sequence and monotonic offset. Durable structured diagnostic facts contain kind/console level, UTF-8 complete and retained byte counts, truncation, and a digest of the protected retained value. Raw console objects and exception strings are not placed in canonical staged JSON or default debug output. Collector completion/cancellation is consumed before staging; missing or failed finalization remains a typed family failure and does not erase siblings.

Runtime event and byte accounting are provider-owned and independent from network lifecycle counters and the all-observation aggregate. Runtime retained event count must equal diagnostic length; loss is exact or explicitly unknown. Aggregate diagnostic bytes carry configured limit, post-materialization enforcement, capture-aggregate budget scope, observed/retained/exact-or-unknown lost bytes, and completeness. Provider and Yosoi validate all known sums with checked arithmetic, diagnostic order and offsets, per-diagnostic lengths/truncation, per-family bounds, and aggregate limits.

## Outcomes and provenance

Each family remains independently unrequested, complete, partial/truncated, discarded/limited, unavailable, failed, disabled, or unsupported. Every retained envelope binds the exact bytes to SHA-256, schema, producer/version, media type, extent, capture offset, artifact identity, and lineage. Sibling successes survive a family-specific failure or limit. Provider-native values remain capture-local and owned; live handles and unvalidated raw strings do not cross the staging boundary.
