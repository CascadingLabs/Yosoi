# CAS-324 durable source representation evidence

## Outcome

A retained Direct HTTP source now produces a typed `SourceRepresentation` derived-evidence artifact. Canonical Web Capture v1 metadata names the artifact; `CaptureBundle` carries and validates its compact canonical JSON payload. A downstream process can reconstruct the bundle and inspect declaration, classification, and character-decoding facts without a live `wreq` response or `DirectHttpCapture` object.

## Boundary

```text
retained Source artifact
  ├─> optional DecodedSource artifact (UTF-8 text payload)
  └─> SourceRepresentation artifact (facts-only JSON payload)
```

The facts payload never contains source or decoded text. It contains:

- evidence schema version;
- exact typed source reference;
- parsed/missing/malformed media declaration and charset facts;
- classified/unknown/unsupported/ambiguous outcome;
- classification basis, candidates, disagreement, and complete/prefix extent;
- complete/output-truncated/unsupported/undecodable/not-applicable decoding status;
- selected encoding, decoding basis, conflicts, replacement count, source/output truncation, and incomplete terminal-sequence facts;
- optional typed decoded-source reference only when that decoded payload was retained.

## Integrity and lineage

The artifact:

- belongs to the same capture activity as its source;
- has a distinct artifact ID;
- derives directly and only from the final source artifact, never the provisional classification artifact;
- uses the dedicated required schema supplied by `DirectHttpOutputSchemas`;
- uses `application/vnd.yosoi.source-representation-facts+json`;
- is retained with exact byte extent and SHA-256 digest;
- is admitted and exhaustively required by ordinary `CaptureBundle` validation.

`SourceRepresentationArtifact::parse_payload` rechecks size, digest, evidence version, exact source reference, and any decoded-reference activity/identity before returning typed evidence. Unknown fields fail closed. Source-unavailable outcomes report the derived family unavailable and publish no fabricated facts payload.

## Compatibility

This is an intentional pre-release Web Capture v1 shape change. Code, fixtures, and documentation advance together. No legacy reader or v2 migration path is added.

## Runtime convenience

`DirectHttpCapture::source_facts` remains available for immediate inspection, and `replay_source_facts` can recompute facts from retained source and response observations. Neither is required for durable handoff: canonical capture metadata plus validated payload pairs are sufficient to locate and parse `SourceRepresentationEvidence` offline.

## CAS-325 ownership and migration

Source declaration bounds, classification, decoding, durable evidence, wire behavior, and arbitrary-evidence properties are owned by the provider-neutral `yosoi-web-capture` foundation. Direct HTTP converts its bounded header observation into the invariant-safe foundation `SourceMediaType`; transport callers import producer APIs from `yosoi_web_capture_direct_http`. This is a pre-release breaking path with no reverse compatibility reexport.
