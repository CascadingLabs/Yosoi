# CAS-328 source, rendered DOM, and network evidence

## Scope boundary

CAS-328 converts owned VoidCrawl observations into validated Yosoi staging inputs. CAS-332 remains responsible for constructing and publishing the final `WebCapture` and `CaptureBundle` last.

Source, rendered DOM, and network evidence are independent observations:

- Source is the main-document body returned by Chromium's `Network.getResponseBody`.
- Those source bytes are a decoded HTTP representation. They are not transfer-framed, content-coded, or raw wire bytes.
- Rendered DOM is a later live-document serialization with its own document scope and acquisition offset.
- Network evidence is an ordered, bounded provider-receipt transcript plus its correlated resource graph. It is not a replay log and does not imply raw protocol ordering unavailable from the client.

## Provider facts consumed

The adapter consumes one owned `NavigationCaptureReport` after its collector has stopped:

- requested and final URL
- redirect edges
- final main-document response status, protected headers, MIME declaration, cache and service-worker facts
- main-document decoded-representation bytes and byte report
- bounded resources
- bounded provider-receipt network events with capture-local sequence, monotonic offset, kind, and optional known resource correlation
- admitted, retained, dropped, and additional-unknown-loss accounting
- explicit ExtraInfo unavailability
- typed termination and cleanup facts

Provider values remain protected until the Yosoi admission boundary. No provider DTO or browser handle enters durable Yosoi output.

## Source staging

When source is requested, the adapter passes the resolved `CdpDecodedBody` bound to VoidCrawl instead of the prior one-byte placeholder.

The source slot maps provider extent exactly:

- available with no loss -> complete
- retained prefix with known or unknown loss -> truncated
- provider-reported discard -> discarded
- no body -> unavailable with the provider reason
- provider failure -> failed with a namespaced reason

The source mapping uses `BrowserByteLayer::DecodedResponseBody`. Encoded transfer length remains only a network resource metric.

## Source-representation evidence

Retained source bytes are wrapped as `RetainedSource` with complete or truncated extent. The adapter records the observed media declaration from the main response without inventing missing, duplicate, invalid, or overlong values.

Classification and character decoding reuse the provider-neutral source pipeline. CAS-328 stages canonical source-representation evidence bound to the SHA-256 digest of the exact retained source bytes. The source and representation schemas must come from the resolved browser specification and remain distinct.

Artifact identity, final metadata records, and bundle publication remain CAS-332 responsibilities. CAS-328 must stage enough typed identity and lineage input that CAS-332 does not reinterpret source bytes or rerun provider observation. The decoded UTF-8 view is not retained by this ticket, so canonical source-representation evidence deliberately omits a decoded-artifact reference while preserving classification, selected encoding, replacement, conflict, and truncation facts. A later retained decoded payload must use the separately reserved decoded-source identity.

## Rendered DOM staging

Rendered DOM remains a separate UTF-8 payload with:

- `RenderedDomUtf8` byte domain
- complete or truncated extent from the provider byte report
- exact retained length and SHA-256 digest
- document frame/epoch scope
- factual completion offset
- resolved schema and producer inputs

A JavaScript-shell fixture must prove retained source bytes differ from rendered DOM bytes. The DOM snapshot carries its own factual acquisition offset. Network quiet settlement does not claim that arbitrary later timer-only DOM mutations are impossible or that the document is frozen after serialization.

## Network staging

The network artifact preserves:

- requested and final URL as distinct facts
- redirect graph edges
- resource creation order and capture-local identities
- request/response/completion/failure event kinds in provider receipt order
- status, cache, service-worker, and encoded-length observations
- main-document correlation where known
- ExtraInfo as unavailable in the current client
- exact-or-unknown resource and event loss

Unknown frame, loader, body, header fidelity, or loss is not reconstructed from URLs, DOM, or display strings.

## Secret handling

No hidden redaction default is introduced. The resolved specification must carry an explicit caller-selected URL/header/body admission policy before protected raw provider values can become durable payload bytes. Until such policy is represented and validated, sensitive headers and arbitrary selected bodies remain unavailable rather than silently retained.

CAS-328 does not add broad selected-response-body capture. The main-document source body is the only required body payload. Additional selected bodies require a future explicit selection and aggregate-budget contract.

## Verification matrix

Deterministic tests must cover:

- static, redirected, and JavaScript-mutated documents
- source differing from rendered DOM
- UTF-8 and non-UTF-8 declarations and decoding
- exact-bound and over-bound source/DOM payloads
- canonical source-representation digest binding and lineage
- redirect, final URL, cache, service-worker, and ExtraInfo-unavailable facts
- event/resource loss and terminal cancellation
- no wire-byte claims
- protected values absent from debug/serialized output before explicit admission
- stable canonical payload bytes and digests
