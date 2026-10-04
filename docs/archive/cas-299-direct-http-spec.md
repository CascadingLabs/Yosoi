# CAS-299: Resolved Direct HTTP capture specification

Status: implemented candidate

Linear: [CAS-299](https://linear.app/cascadinglabs/issue/CAS-299/define-the-resolved-direct-http-capture-specification)

## Purpose

`ResolvedDirectHttpCaptureSpec` is the explicit validated runtime input for one Direct HTTP capture occurrence. It contains every decision the acquisition runner requires without reading environment variables, dotenv files, global defaults, credentials, arbitrary headers, or policy documents.

The value preserves the complete `WebCaptureRequest`, including its fresh `CaptureId`, requested target, semantic Direct HTTP strategy, transport profile, and session use. Retry, fallback, crawl, and scheduling orchestration create another spec with another occurrence identity.

## Shape and invariants

The specification composes existing domain types for:

- `WebCaptureRequest`;
- `WebArtifactRequestSet`;
- `ObservationPolicy` and its mandatory `MaximumElapsed` deadline;
- `Producer`, `OperationId`, and `Schema`.

It adds only Direct HTTP runtime decisions that do not yet exist elsewhere:

- independent non-zero bounds for content-coded input bytes, retained representation bytes, and decoded Unicode UTF-8 bytes;
- disabled or positively bounded redirect following;
- a non-empty closed accepted-format set, including generic XML and XHTML as distinct XML profiles;
- explicit behavior for classified formats outside that set;
- representation-only or representation-plus-Unicode-view retention;
- source, required source-representation-evidence, optional minimal-network, and optional Unicode-view schemas.

Construction rejects:

1. a non-Direct-HTTP strategy;
2. an empty accepted-format set or zero body limit;
3. a source artifact that is not required;
4. browser-only artifact families;
5. quiet-period settlement, because one Direct HTTP attempt terminates through response/controller completion rather than browser quiet;
6. missing or unexpected network schema relative to the network artifact request;
7. missing or unexpected Unicode-view schema relative to retention.

The source schema is mandatory because source evidence is mandatory for this initial runtime contract. Network evidence remains optional or required through the existing artifact request vocabulary.

## Wire boundary

These runtime specification types intentionally do not implement Serde. They are resolved in-process inputs, not the durable `WebCapture` wire document or an archive record. Adding a durable queue/process handoff requires a separately versioned fail-closed wire envelope whose deserialization invokes the same constructor validation; direct derived deserialization must not bypass invariants.

## Future policy mapping

| Runtime field | Likely future policy input | Runtime-only fact |
| --- | --- | --- |
| Requested target | Job target resolution | Fresh `CaptureId` |
| Direct HTTP transport profile/session use | Acquisition transport/session policy | Concrete resolved strategy |
| Source/network artifact requests | Evidence requirement policy | Exhaustive request set used for result validation |
| Maximum elapsed, event, and observation-byte limits | Capture observation limits | Resolved `ObservationPolicy` |
| Content-coded byte limit | HTTP response safety limit | Exact bound supplied to body processor |
| Representation byte limit | Retained source safety limit | Exact bound supplied to payload admission |
| Unicode UTF-8 byte limit | Character-decoding safety limit | Exact bound supplied to text decoder |
| Redirect policy and hop cap | Redirect/effect policy | One closed redirect choice |
| Accepted source formats | Source acceptance policy | Non-empty resolved set |
| Unsupported-format behavior | Unsupported source policy | Retain/report versus non-successful attempt decision |
| Retention policy | Evidence retention policy | Whether a Unicode derivation is requested |
| Producer and operation | Runtime/provider selection | Exact producer version and operation used for receipt |
| Output schemas | Runtime release/schema registry | Exact source/source-representation/network/view schema versions |

No field accepts an arbitrary configuration map, header collection, provider handle, cookie, authorization value, filesystem path, or archive locator.

## Relationship to adjacent work

- CAS-298 defines the byte, classification, and character-decoding semantics selected by this spec.
- CAS-300 binds finalized artifact metadata to exact retained payload bytes.
- CAS-301 consumes this value while enforcing timing, cancellation, accounting, and finalization.
- CAS-302 maps the semantic strategy and explicit limits to reviewed `wreq` behavior.

The type does not execute requests, retain payloads, follow redirects, classify bytes, or finalize `WebCapture`; it makes those later operations deterministic and bounded before I/O begins.
