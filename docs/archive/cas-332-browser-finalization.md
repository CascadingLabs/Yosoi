# CAS-332 browser finalization and offline handoff

## Publication boundary

`finalize_browser_capture` consumes one validated `BrowserAdapterResult` plus wall-clock anchors and explicit origin observations. It derives acquisition resolution, termination, artifact results, receipts, provenance, payload bindings, and completeness. The function returns only a fully validated `CaptureBundle`; no intermediate payload-bearing `WebCapture` is exposed before exhaustive bundle validation.

The implementation is provider-neutral and has no VoidCrawl, Chromium, CDP, `wreq`, or Direct HTTP semantic dependency. Provider-native values end at `BrowserAdapterFacts`.

## Durable artifact mapping

Every browser staging slot maps independently:

- unrequested -> `NotRequested`;
- complete retained evidence -> `Complete` with exact payload;
- logically partial or byte-truncated evidence -> `Partial` with exact retained payload and reason;
- discarded bytes -> `Partial` with a durable discarded artifact record and no payload;
- unavailable -> `Unavailable`;
- provider failure -> `Failed`;
- disabled -> `OmittedByPolicy`;
- unsupported -> `Unsupported`.

Retained envelopes preserve artifact identity, schema, producer/version, media type, sensitivity, byte extent, digest, capture offset, and computational lineage. Monotonic capture offsets are converted to checked wall-clock provenance timestamps from the supplied start anchor. Source-representation evidence remains complete, canonical, and directly source-bound.

Raw source and rendered-DOM payloads carry a durable `BrowserArtifactContext::DocumentSnapshot` with document scope and factual capture offset. PNG visual payloads carry the complete validated `BrowserVisualFact`. AX, network, layout, and runtime payloads are canonical `BrowserStructuredEvidence` and can be decoded offline with `BrowserStructuredEvidence::from_json`. Browser-only context is rejected on HTTP captures and when it contradicts artifact family, provenance time, scope, geometry, or visual/layout correlation.

## Resolution and terminal truth

Final URL and redirect observations are derived only from retained structured network evidence. The requested URL, when admitted, must match the resolved request target. Redirects become observed only when resource accounting has no loss and every redirect endpoint URL is admitted; otherwise redirect resolution remains unobserved. Resource and initiator origins remain explicit finalization inputs because the adapter does not otherwise possess authoritative origin evidence.

Deadline, event-limit, byte-domain limit, caller cancellation, system interruption, provider stop, quiet settlement, and controller completion map to typed capture termination and activity signals. Browser byte-limit termination uses the exact matching per-domain configured bound. Normal termination with incomplete requested families remains partial. A provider-stopped attempt is failed only when it preserves no artifact evidence; retained, truncated, or discarded evidence makes it partial.

Terminal in-flight counts preserve exact provider measurements or namespaced unavailability. Known-count JSON retains the existing compact shape; unmeasured counts serialize explicitly and are never replaced with zero. Quiet settlement requires exact settlement-relevant terminal accounting equal to its proof.

## Offline handoff

A worker serializes `WebCaptureWire::to_canonical_json` and transfers exact `(WebArtifactRef, bytes)` pairs from `CaptureBundle::into_parts` or `payloads`. A receiver parses the capture, inserts every payload through `CaptureBundle::builder`, and finalizes. Missing, foreign, orphaned, substituted, wrong-size, and wrong-digest payloads fail closed. No browser process, page, context, provider DTO, or live connection is required for reconstruction or typed evidence inspection.

Semantic artifact relationships remain empty until an exact artifact-to-artifact correlation exists. Shared document epoch or timestamp proximity alone does not justify a durable relationship.
