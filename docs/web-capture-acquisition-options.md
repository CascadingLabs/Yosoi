# Web capture acquisition options

Status: Option A selected as the design direction for [CAS-295](https://linear.app/cascadinglabs/issue/CAS-295/define-capture-target-and-origin-types); exact field and wire details remain reviewable.

This note separates the resource a caller wants from the mechanism used to acquire it and from the evidence ultimately retained. It documents design options for direct HTTP, browser-associated HTTP, requests executed by page script, and browser navigation. No option in this note commits the project to a provider or implementation.

## Decision to make

A web target such as `https://example.com/` can be approached in several materially different ways:

1. a native Rust HTTP client, potentially with browser-like TLS and HTTP/2 behavior;
2. an HTTP client associated with browser session state;
3. `fetch()` or XHR executed inside a page;
4. navigation of a browser document.

All can be useful capture strategies, but they do not have the same security model, state, redirect visibility, execution behavior, or possible artifacts. The model needs to make those differences inspectable without treating one mechanism as the universal definition of a capture.

Decision: callers select one concrete closed semantic acquisition variant per attempt. Adaptive selection and ordered fallback remain capture-agnostic orchestration above this crate, potentially using the shared Activity vocabulary across web and mobile capture.

## Concrete candidate implemented for evaluation

A compiling Option A candidate now lives in:

- `crates/yosoi/src/internal/web_capture/target.rs`
- `crates/yosoi/src/internal/web_capture/acquisition.rs`
- `crates/yosoi/src/internal/web_capture/capture.rs`
- `crates/yosoi/src/internal/web_capture/integration_tests/capture_model.rs`

Its central shape is:

```rust
pub struct WebCaptureRequest {
    capture_id: CaptureId,
    target: RequestedWebTarget,
    strategy: WebAcquisitionStrategy,
}

pub enum WebAcquisitionStrategy {
    DirectHttp(DirectHttpAcquisition),
    ContextBoundHttp(ContextBoundHttpAcquisition),
    PageContextFetch(PageContextFetchAcquisition),
    DocumentNavigation(DocumentNavigationAcquisition),
}

pub struct CaptureResolution {
    final_url: Observation<ResolvedWebUrl>,
    redirects: Observation<Vec<RedirectHop>>,
    resource_origin: Observation<ObservedWebOrigin>,
    initiator_origin: Observation<ObservedWebOrigin>,
}

pub struct BrowserContextRef {
    activity_id: ActivityId,
    local_id: NonZeroU32,
}

pub struct PageContextRef {
    capture_id: CaptureId,
    frame_id: NonZeroU32,
}

pub struct WebAcquisitionRecord {
    request: WebCaptureRequest,
    resolution: CaptureResolution,
    receipt: CaptureReceipt,
}
```

This code implements the selected structural direction. Individual names, fields, and wire representations remain candidates until CAS-295 review is finalized.

## Vocabulary

This note uses the following terms deliberately:

- **Target**: validated caller intent, including the requested URL.
- **Acquisition strategy**: the semantic way an attempt reaches the target.
- **Provider**: the concrete component performing work, such as a particular `wreq` adapter or browser driver.
- **Transport profile**: declared network behavior, such as ordinary native HTTP or a named browser-impersonation profile.
- **Execution context**: state that can affect an attempt, such as an isolated HTTP client, browser context, or initiating page.
- **Observation**: a fact learned during an attempt, such as a final URL, redirect hop, initiator, or resource origin.
- **Representation**: retained evidence such as response bytes, parsed static HTML, rendered DOM, accessibility data, or a screenshot.
- **Receipt**: the terminal activity facts and artifact references defined by CAS-293.

“Static HTML” is a representation, not an acquisition strategy. Direct HTTP and browser-associated requests can both return HTML. Browser navigation can also expose the original response and multiple derived document representations.

Similarly, CDP is an observation/control protocol rather than necessarily an acquisition strategy. A browser can navigate normally while CDP observes its document, XHR, Fetch, script, image, and other resource traffic.

## Findings from existing systems

### Native HTTP impersonation is still native HTTP

[`wreq`](https://github.com/0x676e67/wreq) describes itself as a Rust HTTP client with configurable TLS, JA3/JA4, HTTP/2 signatures, header behavior, and maintained browser-device emulation profiles. It is explicit that these are protocol-matching facilities. They do not supply a DOM, JavaScript runtime, navigation lifecycle, CORS enforcement, or a page's service-worker behavior.

Design consequence: a browser-like transport profile should be recorded, but it must not cause a native HTTP attempt to be labeled as browser execution.

### HTTP and browser crawling are commonly separate, with adaptation above them

[Crawlee's architecture](https://crawlee.dev/python/docs/guides/architecture-overview) separates HTTP crawlers from browser crawlers. HTTP crawlers use an HTTP client and optionally parse the response; browser crawlers manage browsers, pages, and contexts and render JavaScript. Its adaptive crawler sits above both and chooses a mode per request using heuristics or configuration while exposing a deliberately limited common interface.

Design consequence: direct and browser acquisition can share a target and a small common result vocabulary without pretending their full capabilities are identical. Adaptive selection is an orchestration concern above concrete attempts.

### Browser-associated HTTP is not necessarily page `fetch()`

[Playwright's `APIRequestContext` documentation](https://playwright.dev/docs/api/class-apirequestcontext) distinguishes an isolated API request context from one associated with a browser context. The associated form shares cookie storage with browser pages; the isolated form has its own cookie storage. This is useful precedent for separating state binding from the mechanism that sends the HTTP request.

Design consequence: “uses browser cookies” does not prove “was sent by page script” or “used the browser renderer.” A browser-associated API client deserves a distinct semantic description if Yosoi supports it.

### Page-context Fetch has web-platform restrictions

[MDN's Fetch guide](https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API/Using_Fetch) documents that page `fetch()` participates in CORS, has forbidden request headers, applies request modes, has explicit credential behavior, integrates with service workers, and can yield opaque responses whose body and headers are unavailable to script.

Design consequence: page-context acquisition needs an initiating context or origin and must not promise the same observable bytes and headers as a native HTTP client.

### Browser capture spans a resource graph

[Browsertrix Crawler](https://crawler.docs.browsertrix.com/) uses real browser windows, controls them through browser automation, and captures data through CDP. It treats headless/headful operation and browser behaviors as configuration of a browser-based crawl.

The [CDP Network domain](https://chromedevtools.github.io/devtools-protocol/tot/Network/) tracks page network activity across resource types including Document, XHR, Fetch, scripts, images, WebSockets, and others. It exposes request, loader, frame, initiator, cache, service-worker, response-body, and failure concepts.

Design consequence: headless/headful belongs to the browser environment, while document navigation and page-initiated Fetch are different activities within that environment. Per-resource observations should not be collapsed into the top-level requested target.

### URL parsing and origins already have web-platform semantics

The [WHATWG URL Standard](https://url.spec.whatwg.org/) defines parsing, serialization, hosts, credentials, fragments, default ports, and tuple versus opaque origins. The Rust [`url` crate](https://docs.rs/url/latest/url/) implements that standard and exposes parsed URL, host, origin, and opaque-origin types.

Design consequence: Yosoi should wrap a reviewed URL implementation with domain-specific validation rather than invent URL parsing or normalization. Requested URLs, final URLs, and origins still need different domain types even if they share the same parser internally.

### Archive packaging keeps page entry points separate from archived records

The draft [WACZ 1.2 specification](https://specs.webrecorder.net/wacz/1.2.0/) stores page entry points with URL and timestamp, stores HTTP representations in WARC data, and records contextual package metadata such as creation time and software. It does not make the page URL itself the identity or provenance of all archived resources.

Design consequence: target, resource evidence, producer information, and package identity should remain separate concepts.

## Candidate semantic strategy set

The following names describe semantics rather than libraries:

```rust
pub enum WebAcquisitionStrategy {
    DirectHttp(DirectHttpAcquisition),
    ContextBoundHttp(ContextBoundHttpAcquisition),
    PageContextFetch(PageContextFetchAcquisition),
    DocumentNavigation(DocumentNavigationAcquisition),
}
```

This is illustrative, not proposed production code.

### `DirectHttp`

A non-browser HTTP stack owns the request and response.

Relevant declared facts may include:

- ordinary or browser-impersonating transport profile;
- redirect-following policy;
- isolated or reusable non-browser session;
- desired response-body limits.

A concrete provider such as `wreq` belongs in CAS-293 producer identity and version fields, not in the strategy enum. A named emulation profile is a transport fact and does not assert that a real browser performed the request.

### `ContextBoundHttp`

An HTTP API client shares selected state with a browser context but is not page script and does not navigate a document.

Relevant declared facts may include:

- a secret-safe browser-context reference;
- which categories of state are shared;
- whether response cookies update the context;
- whether redirects are exposed by the provider.

The durable form must not serialize cookies, authorization values, profile paths, or other secrets. If there is no immediate implementation requiring this mode, it can remain a reserved design direction rather than an initial variant.

### `PageContextFetch`

Page script initiates Fetch or XHR from an existing document or worker context.

Relevant declared facts may include:

- the initiating page/context reference;
- the initiator's observed origin when available;
- Fetch mode and credential policy;
- service-worker involvement when observed;
- whether the script-visible response was basic, CORS, opaque, or unavailable.

This strategy cannot be reconstructed from the target alone. The same target can succeed, fail, or expose different evidence depending on the initiator and context state.

### `DocumentNavigation`

A browser navigates a top-level document or frame and may execute page behavior.

Relevant declared facts may include:

- top-level versus frame navigation;
- browser environment reference;
- requested navigation target;
- final document URL and origin when observed;
- resulting document and resource artifacts.

Headless/headful is not a separate target or strategy. It is a browser environment fact under CAS-291.

## Shared invariants under every option

1. `RequestedWebTarget` is distinct from `ResolvedWebUrl`.
2. Only supported web schemes are admitted before capture construction.
3. Credential-bearing URL inputs are rejected rather than redacted after construction.
4. Redirects are observations. A redirect never mutates the identity of the original request. Direct HTTP automatically follows only 301/302/303/307/308 and remains GET-only on every hop; 300/305 remain observable final responses. Redirect continuity and final-resource association compare network resources without fragments, while each recorded URL and the final URL retain their independently observed fragment semantics. See `cas-304-direct-http-redirects.md`.
5. An unavailable final URL is not replaced with the requested URL.
6. An unobserved redirect history is not serialized as an observed empty history.
7. Target data is not inferred from artifact provenance.
8. Every actual attempt receives a fresh `CaptureId` and terminal `CaptureReceipt`.
9. A fallback from direct HTTP to browser navigation produces multiple attempts, not one receipt whose strategy changes halfway through.
10. Provider identity and version remain explicit. An orchestrator may own the receipt while individual artifacts identify their immediate producers.
11. Stored context references and environment metadata do not contain cookies, credentials, browser profile paths, or authorization headers.
12. Representations are outputs. Strategy variants do not guarantee an artifact unless the corresponding receipt actually contains it.

## Option A: closed semantic variants (selected)

Callers choose one concrete strategy variant. Each variant carries only fields meaningful to it.

```rust
pub struct WebCaptureRequest {
    capture_id: CaptureId,
    target: RequestedWebTarget,
    strategy: WebAcquisitionStrategy,
}
```

### Optimizes for

- straightforward Rust matching;
- invalid combinations being difficult to construct;
- stable, explainable wire fixtures;
- clear provenance and operational behavior.

### Risks

- adding a genuinely new mechanism changes the enum;
- shared fields can be duplicated across variants;
- callers wanting automatic fallback need a separate orchestration type.

### Likely failure mode

The enum starts naming providers (`Wreq`, `ChromeCdp`) rather than semantics, making stored data obsolete when implementations change.

## Option B: orthogonal facets with validation (deferred)

Represent acquisition as a combination of independently selected axes.

```rust
pub struct WebAcquisitionDescriptor {
    transport: TransportOwner,
    state_binding: StateBinding,
    execution: ExecutionModel,
    requested_representation: RequestedRepresentation,
}
```

A constructor validates combinations, for example rejecting page-script execution without an initiating page context.

### Optimizes for

- expressing new combinations without growing a large enum;
- querying capabilities across mechanisms;
- future provider diversity.

### Risks

- the cross-product contains many meaningless states;
- validation becomes a second, hand-built type system;
- compatibility rules become harder to explain and serialize;
- callers can depend on combinations no provider can actually perform.

### Likely failure mode

The descriptor becomes a bag of booleans such as `uses_browser`, `renders`, `shares_cookies`, and `enforces_cors`, with contradictory combinations accepted or assigned inaccurate meanings.

## Option C: target plus selection policy (rejected for this layer)

The caller states the target and required outcome while an orchestrator selects a concrete strategy. The completed capture records the strategy actually performed.

```rust
pub struct WebCaptureIntent {
    target: RequestedWebTarget,
    requirement: AcquisitionRequirement,
    policy: StrategyPolicy,
}
```

Examples of requirements might be “retain response bytes,” “produce a rendered document,” or “execute within this page context.” Policy could allow direct HTTP only, browser only, or controlled escalation.

### Optimizes for

- adaptive acquisition;
- provider substitution;
- callers that care about evidence rather than implementation;
- future performance/cost policy.

### Risks

- requirements and policy are substantially more design than CAS-295 needs;
- hidden strategy selection can surprise callers;
- a “rendered document” requirement still needs precise completion rules;
- generalized plans/replay semantics were intentionally deferred by CAS-293.

### Likely failure mode

A request records only what was desired, while the result fails to record what actually happened. Reproducibility then depends on mutable orchestrator policy.

## Option D: explicit ordered fallback plan (rejected for this layer)

Represent a non-empty ordered sequence of permitted concrete attempts, for example direct HTTP followed by document navigation.

```rust
pub struct AcquisitionPlan {
    attempts: NonEmpty<WebAcquisitionStrategy>,
    escalation: EscalationPolicy,
}
```

Each executed entry receives its own capture occurrence and receipt. A higher-level orchestration activity can describe why another attempt was launched.

### Optimizes for

- transparent “safe tiering” or escalation;
- bounded cost and side effects;
- explainable adaptive behavior;
- retaining failures as useful evidence.

### Risks

- this is a plan/replay layer rather than only target/origin vocabulary;
- success criteria across heterogeneous attempts require another model;
- context handoff between attempts can leak or mutate state;
- premature introduction conflicts with CAS-295's small scope.

### Likely failure mode

The list is labeled `tier_1`, `tier_2`, and `tier_3`, implying a universal quality ordering that does not exist.

## Comparison

| Option | Static safety | Extensibility | Adaptive behavior | Wire clarity | CAS-295 scope fit |
| --- | --- | --- | --- | --- | --- |
| A. Closed variants | High | Moderate | Separate layer required | High | High |
| B. Orthogonal facets | Constructor-dependent | High | Possible | Moderate to low | Moderate |
| C. Selection policy | Moderate | High | High | Moderate | Low to moderate |
| D. Ordered fallback | High per attempt | Moderate | Explicit | High if bounded | Low |

The selected direction implements Option A for individual attempts. Options C and D may inform future capture-agnostic orchestration, but do not belong in the web capture contract. Option B remains documented only as future decomposition pressure if closed variants accumulate substantial duplication.

## Tiering and safety

There is no single fidelity ladder:

- direct HTTP can be the best source of exact response bytes;
- direct HTTP with browser impersonation can improve protocol compatibility without adding browser semantics;
- context-bound HTTP can reuse state without CORS or DOM execution;
- page Fetch best reproduces page security and service-worker behavior but may hide opaque response bytes;
- document navigation is necessary for rendered evidence but introduces scripts, subresources, timing, and more side effects.

If the product needs “safe tiers,” define a policy over explicit effects rather than assigning permanent quality numbers. Useful policy dimensions include:

- may execute remote script;
- may use existing browser/session state;
- may send credentials from that state;
- may mutate cookies or storage;
- may load subresources;
- may impersonate a named browser network profile;
- may perform cross-origin requests;
- maximum requests, bytes, redirects, and elapsed time.

Strategy types should determine their inherent semantics. A separate policy decides whether those semantics are permitted for a job.

## Target, URL, and origin distinctions

The eventual model should distinguish at least:

- requested target URL;
- observed final document or response URL;
- page-script initiator origin;
- final document security origin;
- origins of observed frames and resources;
- opaque browser origins when they become a concrete requirement.

A generic `origin: String` cannot safely represent all of these. A generic URL type also permits requested and final URLs to be interchanged accidentally.

Suggested initial URL behavior for discussion:

| Input or condition | Candidate behavior |
| --- | --- |
| Relative or schemeless target | Reject before request construction |
| Non-HTTP(S) requested target | Reject for the initial CAS-295 web-target type |
| Username or password present | Reject |
| Fragment present | Preserve in caller intent; do not treat it as HTTP request bytes |
| Host casing and default ports | Use WHATWG parse/serialize behavior |
| Query ordering | Preserve; do not sort |
| Final URL unavailable | Explicitly unobserved |
| Redirect observation unavailable | Explicitly unobserved, distinct from zero redirects |

Opaque origins should either receive a capture-local identity or remain explicitly unsupported in the first version. They should not be converted to synthetic tuple origins or globally comparable strings.

## Relationship to CAS-293

CAS-293 supplies generic activity and evidence vocabulary:

- `ActivityReceipt` describes one terminal attempt;
- `CaptureReceipt` narrows that same occurrence to `CaptureId`;
- artifact provenance names the immediate producer of each artifact;
- the receipt producer may be an orchestrator rather than the producer of every artifact.

CAS-295 composes with those types rather than modifying them. Its acquisition record has the following bounded shape:

```rust
pub struct WebAcquisitionRecord {
    request: WebCaptureRequest,
    resolution: CaptureResolution,
    receipt: CaptureReceipt,
}
```

The record validates that its observations and receipt describe the same capture occurrence. The requested target is never reconstructed from output artifacts. CAS-292 remains responsible for the final immutable `WebCapture` aggregate that adds environment, observation windows, capabilities, and artifact-wide invariants.

## Relationship to CAS-291

CAS-291 is expected to distinguish semantic HTTP and browser environments. Browser mode, viewport, locale, timezone, user agent, and similar representation-affecting settings belong there.

CAS-295 therefore avoids embedding headless/headful, viewport, or concrete renderer identity into the target or strategy. CAS-292 will compose the acquisition record with the applicable CAS-291 environment and validate that strategy and environment agree.

## Settled decisions represented by the candidate

1. Direct HTTP, context-bound HTTP, page-context Fetch, and document navigation are separate closed semantic variants.
2. Browser-associated HTTP cookie sharing is not labeled as page Fetch; Fetch/XHR requires a typed page context.
3. A caller selects one strategy for one capture occurrence. Adaptive selection, escalation, and effect policy remain capture-agnostic orchestration outside this crate.
4. Strategy and resolution values are both public Rust API and validated Serde wire data.
5. Browser and page context references are typed, secret-safe input dependencies; they never contain paths, cookies, credentials, or provider handles.
6. Opaque origins have capture-local identity and cannot be attached to another capture's acquisition record.
7. The name `WebCapture` is reserved for the final CAS-292 aggregate.

## Relationship to CAS-296 and CAS-297

CAS-295 defines deterministic Serde representations and rejects invalid nested values because its acceptance criteria require round-trip fixtures. CAS-296 remains responsible for versioning and the canonical complete Web Capture wire format. The local `thiserror` validation types in this candidate are Rust construction errors, not the stable machine-readable transport errors reserved for CAS-297; CAS-297 can map them to codes and context paths without using display text as protocol.

## Candidate dependency note

The compiling candidate adds `url` 2.5.8 with default features disabled and only `std` enabled. The required capability is WHATWG-compatible parsing, canonical serialization, host handling, and origin derivation. Hand-written parsing and normalization were rejected because URL edge cases are security-sensitive and already standardized. The crate supports Rust 1.63, below this workspace's Rust 1.98 MSRV, and is dual MIT/Apache-2.0 licensed. Its normal graph includes `form_urlencoded`, `percent-encoding`, and IDNA/Unicode support; this is a meaningful compile-time and binary-size cost that should be accepted or rejected with the API candidate.

Serde support is implemented by the Yosoi wrappers rather than enabling `url`'s Serde feature, because deserialization must reapply the HTTP(S) and no-credentials domain validation.

## Research quality and limitations

The sources above are primary project documentation or web standards documentation. They establish useful precedent but do not define Yosoi's contract:

- Crawlee and Browsertrix are crawler products with broader orchestration concerns.
- CDP's `tot` documentation includes experimental facilities and is not a stable storage schema.
- MDN explains browser-visible Fetch behavior rather than archival provenance.
- WACZ 1.2 identifies itself as a draft and intentionally focuses on archive packaging.
- `wreq` documents transport emulation, not equivalence with full browser behavior.

The research supports separating target, strategy, execution context, observations, representations, and receipts. The exact Rust and JSON shapes remain an explicit project decision.
