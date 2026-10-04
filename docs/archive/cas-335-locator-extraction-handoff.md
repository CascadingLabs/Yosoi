# CAS-335 locator and deterministic extraction handoff

## Decision and boundary

This handoff defines a bounded downstream project consuming the browser evidence certified through CAS-335. It defines offline document selection and deterministic extraction from an admitted `CaptureBundle`; it does **not** drive Chromium, connect to CDP, replay navigation, or require a live browser for any supported result. A caller supplies all evidence and payload bytes needed for a result. Missing evidence remains missing rather than being reacquired or inferred.

The initial project has two separable layers:

1. **Source-document construction** turns certified source, rendered DOM, AX, layout/viewport, visual, network, and runtime evidence into typed, epoch-bound offline documents.
2. **Typed locator evaluation and extraction** selects nodes, ranges, AX objects, resources, geometry, or pixels from those documents and emits canonical, provenance-complete results.

Live JavaScript execution, DOM mutation, browser actions, and action/JS locators are explicitly a later project. They must have a separate request/permission model, live-session ownership, timeout/cancellation semantics, side-effect audit trail, and fresh evidence epoch; they must not be smuggled into the offline locator grammar.

## Certified input contract

The input is a finalized `CaptureBundle` plus its finalized `WebCapture` metadata, never provider DTOs, CDP object IDs, browser handles, URLs to refetch, or filesystem/provider locators. `CaptureBundle::payload(WebArtifactRef)` is the sole required payload retrieval primitive; it verifies that metadata and retained bytes were bound at bundle construction. CAS-335 reads by typed artifact reference and validates the recorded retained length and SHA-256 before parsing. It does not assume payload storage is local or introduce an archive API.

Each supplied artifact is addressed by its typed `WebArtifactRef`, artifact kind, schema identifier/version, media type, exact retained extent, SHA-256 digest, producer/version, capture offset, document scope, and lineage. A parser accepts only an explicitly supported schema/version and media type. Unknown schema versions are `UnsupportedSchema`, not best-effort JSON/HTML.

The certified evidence families have these offline meanings:

| Family | Offline document / use | Required binding |
| --- | --- | --- |
| Source | Exact retained decoded main-response representation; source parsing and source byte/text ranges. | Source artifact/digest, source-representation facts, source scope where available. |
| Rendered DOM | UTF-8 live-document serialization captured at its own offset; DOM tree and DOM text/attribute locators. | DOM artifact/digest, frame and document epoch. |
| AX | Provider-neutral wrapper around the declared AX payload schema; accessibility-node locators. | AX artifact/digest, document scope/epoch and node schema. |
| Network | Ordered resource graph/transcript facts; resource and response-metadata locators. | Capture-local resource IDs, receipt offsets, loss accounting. |
| Layout/viewport | Structured rectangles, viewport/content geometry, DPR, and scroll observations. | Document epoch, micro-CSS-pixel coordinate space, factual offset. |
| Visual | Validated PNG snapshot; pixel/crop extraction only. | PNG artifact/digest, pixel dimensions, CSS viewport, scroll, DPR, document scope and visual offset. |
| Runtime | Structured, protected diagnostic facts; diagnostic locators only. | Receipt sequence/offset, extent/loss accounting and protected-value digest. |

No family substitutes for another: source is not DOM, DOM is not AX, layout is not a screenshot, and runtime text is not a DOM mutation log. Network evidence is not a replay protocol. A family can be absent while siblings remain usable.

## Epochs, time, and coordinate spaces

All document epochs are capture-local. A downstream `DocumentScope` is `(capture_id, frame_id, document_epoch)`; frame IDs and epochs are opaque equality-only values and are never reusable browser identities. Every document-derived locator has a declared scope. A cross-family join is permitted only when scopes match exactly, except an explicit `SameDocumentEpochOnly` layout/visual relationship supplied by certified evidence.

Offsets are monotonic capture-observation offsets, not wall-clock timestamps and not an ordering claim beyond the recorded family/receipt sequence. An extraction records the input artifact offsets and does not claim that DOM, AX, layout, and visual observations were atomic. A request requiring one epoch fails `EpochMismatch` when its selected evidence differs; it may return independently scoped results only when the request explicitly permits `PerArtifact` correlation.

Geometry is typed and never silently converted:

- `MicroCssPx` is signed integer micro-CSS pixels, used by layout rectangles, layout viewport, visual viewport, content bounds, and scroll offsets.
- `ImagePx` is unsigned PNG pixel coordinates with origin at the PNG top-left.
- `DocumentCssPx` is content-relative CSS geometry; `ViewportCssPx` is viewport-relative geometry.
- Conversion from document to viewport subtracts the recorded scroll offset; conversion to image pixels uses the recorded DPR and must be exact under the declared rounding policy. Initial offline extraction permits only exact representable conversion; otherwise it returns `UnrepresentableGeometry`.
- A visual crop must be inside PNG dimensions using checked arithmetic. No scaling, OCR, computer vision, paint-order, or element-to-pixel hit testing is implied.

## Typed locator surface

The locator language is a closed, versioned AST, serialized canonically. Inputs are values, never executable strings:

```rust
pub struct ExtractionRequest {
    pub version: ExtractionApiVersion,
    pub correlation: CorrelationPolicy, // OneDocumentEpoch | PerArtifact
    pub locator: Locator,
    pub projection: Projection,
    pub limits: ExtractionLimits,
}

pub enum Locator {
    Source(SourceLocator),
    Dom(DomLocator),
    Accessibility(AxLocator),
    Network(NetworkLocator),
    Layout(LayoutLocator),
    Visual(VisualLocator),
    Runtime(RuntimeLocator),
}
```

Initial locator variants are deliberately finite: source byte range and parsed-source tree path; DOM tree path, element ID, exact attribute equality, and bounded descendant text match; AX node ID/role/name equality; network capture-local resource ID, URL-equivalence policy, and resource outcome; layout rectangle by certified document scope; visual image rectangle; and runtime receipt sequence/kind/level. Tree paths use child indices only after parsing the exact retained payload with the declared parser profile. CSS selectors, XPath, regular expressions, arbitrary JSONPath, accessibility name fuzzy matching, JavaScript expressions, and natural-language locators are out of scope until each has explicit deterministic grammar, complexity bound, and canonicalization rules.

`Projection` is also typed: `NodeSummary`, `Text`, `Attribute`, `ByteRange`, `AxSummary`, `ResourceSummary`, `Geometry`, `PngCrop`, or `RuntimeSummary`. It cannot request protected runtime values, arbitrary response headers/bodies, cookies, storage, raw console objects, or provider diagnostics. A projection must be compatible with its locator; incompatible pairs fail validation before payload retrieval.

## Deterministic evaluation and outputs

```rust
pub struct ExtractionResult {
    pub status: ExtractionStatus,
    pub matches: Vec<ExtractionMatch>,
    pub omissions: Vec<ExtractionOmission>,
    pub result_digest: Sha256Digest,
}

pub struct ExtractionMatch {
    pub match_id: MatchId,
    pub value: ExtractedValue,
    pub provenance: ExtractionProvenance,
}
```

Evaluation is deterministic for identical request bytes, supported parser/profile versions, input metadata, and payload bytes. Match order is locator-defined document order; network/runtime use certified receipt order; ties are prohibited by stable capture-local IDs/path order. Results use canonical serialization and `result_digest = SHA-256(canonical result bytes excluding the digest field)`. A digest identifies the result encoding and inputs; it is not a claim of semantic equivalence across schema, parser, or API versions.

Each match carries: canonical request digest; locator/projection/API versions; artifact refs and verified payload digests; schema and parser-profile versions; document scope; relevant capture offsets; exact byte/text/node/image range; coordinate space where relevant; completeness status; and lineage. Derived output lineage is `derived_from` every consumed artifact, plus any certified source-representation artifact used to interpret source bytes. A crop additionally records the visual digest, image rectangle, and the layout/visual relationship used, if any. No output replaces or changes capture artifact identity.

Payload-bearing output is returned inline only within `max_output_bytes`; otherwise the result contains an `ExtractionPayloadRef` with its digest, media type, exact length, and lineage. Retrieval is explicit: `ExtractionResultStore::payload(ExtractionPayloadRef) -> Result<&[u8], RetrievalError>`. The store must recheck length/digest and must not use an ambient URL, path, or provider locator. Implementations may initially return inline output only and reject oversized projections; they must not claim a durable output ref without a verified retrievable payload.

## Completeness, failure, and partial behavior

An extraction never upgrades evidence completeness. `Complete` means all inputs required by that match are certified complete. `Partial` names the limiting input(s), retained prefix/range, known or unknown loss, and reason. `UnknownCompleteness` is used only when certified evidence reports unknown loss. Source/DOM byte truncation allows only parsers and locators whose requested region is wholly within the retained bytes and whose parse profile can prove a result without reading omitted bytes; otherwise return `IndeterminateDueToTruncation`. AX/node, network/event, and runtime loss similarly makes absence claims indeterminate.

Family-local outcomes map as follows:

- unrequested, unavailable, disabled, unsupported, discarded, or failed required evidence yields a typed no-result/error for that locator only;
- malformed retained source/DOM/AX payload yields `ParseFailed` with a bounded error code and no payload excerpt;
- missing payload for metadata claiming retained/truncated bytes yields `IntegrityUnavailable`;
- length/digest/schema/media/scope mismatch yields `IntegrityViolation` and aborts that request;
- no match in complete relevant evidence yields `NoMatch`; no match in partial/lossy evidence yields `Indeterminate`, never `NoMatch`;
- one requested locator may return successful matches plus omissions only under `PerArtifact`; `OneDocumentEpoch` is atomic with respect to epoch mismatch.

No retry, browser launch, refetch, inference from a sibling family, or hidden fallback is permitted.

## Smallest conformance fixture

The minimum fixture is one offline finalized bundle, with no network service or browser process:

1. complete source payload `<p id="s">source</p>` and its source-representation facts/digest;
2. complete rendered DOM payload `<html><body><p id="d">rendered</p></body></html>` at document epoch `E1` and a different digest;
3. one AX payload in the supported declared schema containing role `paragraph`, name `rendered`, scoped to `E1`;
4. one layout record and one valid 2×2 PNG visual artifact, both `E1`, with declared DPR/scroll and distinct offsets;
5. one network resource and one runtime diagnostic with receipt offsets and complete accounting.

Tests must prove byte/digest verification, source-versus-DOM distinction, stable match order/result digest, scope-preserving DOM/AX join, exact geometry conversion/crop, explicit payload retrieval, and an epoch-mismatch or truncated-DOM indeterminate outcome. The fixture contains no secrets, live endpoints, CDP IDs, or timing dependency.

## Limits and security

Requests declare nonzero checked bounds for parsed input bytes, parser depth/nodes, locator steps, candidate matches, output bytes, output payload bytes, PNG crop pixels, and canonical result bytes. Evaluation uses checked arithmetic, bounded allocation, bounded recursion or iterative traversal, and cancellation/deadline supplied by the caller. A deadline bounds work; it is not a readiness or settlement signal. Unsupported compression, oversized payload, decompression expansion, malformed image/tree, or bound exhaustion fails closed without publishing partial unverified output.

Treat all payloads and metadata as hostile. Parsers disable external entity/network resolution, filesystem inclusion, script execution, and embedded-resource loading. Never log body excerpts, protected runtime values, unrestricted headers, cookies, storage, authorization, URLs outside the admitted policy, archive/provider locators, or raw provider errors. Canonical error codes and bounded structural context are permitted. Digest comparison is over exact bytes; no Unicode normalization, HTML repair, whitespace normalization, or image transcoding occurs before integrity verification.

## Dependencies and ownership

The downstream project depends on finalized CAS-300 bundle integrity/payload retrieval; CAS-328 source/DOM/network facts; CAS-330 scope/schema/bound contract; CAS-332 final admission; CAS-334 AX/layout/visual/runtime evidence; and CAS-335 certification. It consumes CAS-333 evidence but does not rerun browser certification. It may add a narrowly reviewed offline HTML/source, AX-schema, PNG, and canonical-serialization parser only after version, memory, and security review. It must not add a browser/CDP dependency to deterministic consumers.

## Acceptance evidence

Acceptance requires persisted deterministic tests using the smallest fixture and negative variants, plus canonical golden request/result bytes and SHA-256 values. Evidence must demonstrate: offline operation with browser/CDP unavailable; rejection of altered payload bytes and unknown schemas; stable result ordering/digest across repeated runs; explicit source/DOM and epoch distinction; coordinate-space correctness; exact payload-reference retrieval; complete versus partial/indeterminate behavior; bounded failure on malformed/oversized inputs; and absence of protected values from serialized results/errors. Dependency review and warnings-denied test/build evidence are required before claiming implementation certification.

## Non-goals

This handoff does not define capture, admission, archive storage, remote payload retrieval, browser automation, CDP attachment, navigation, refetching, replay, DOM mutation, JavaScript evaluation, clicks/forms/downloads, cookies/storage, CSS/XPath/regex/general JSONPath, OCR/CV, screenshot-to-element mapping, visual diffing, generalized source parsing, cross-capture identity, or a public query language. Those capabilities require separate contracts and cannot weaken these offline evidence, provenance, and determinism rules.
