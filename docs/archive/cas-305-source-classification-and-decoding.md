# CAS-305: bounded source classification and decoding

Status: production classification/decoding boundary implemented; syntax parsing, capture finalization, and archive publication are excluded.

## Inputs and binding

`ValidatedSourceBinding::new` accepts a `SourceArtifact` only when its retained size, SHA-256 digest, and complete/truncated extent exactly match the `RetainedBody`. `classify_and_decode` cannot accept a loose artifact reference. `DecodedOutputIdentity::new` requires a decoded-source artifact in the same activity, a distinct artifact ID, typed `Producer` and `Schema`, and `derived_from` containing exactly the source reference.

Response observations retain at most 1024 bytes per allowlisted header. `Content-Type` is observed as a singleton and multiple real field lines become `Duplicate`; callers can create text observations only through the bounded constructor. Raw values remain redacted from `Debug`.

## Classification

The strict local MIME parser validates the complete type, subtype, parameters, tokens, quoted strings, quoted-pairs, controls, and 1024-byte bound. It retains a canonical 127-byte essence and at most a 63-byte normalized unsupported charset label. Encoding aliases compare by canonical `encoding_rs` identity, so equal aliases and conflicts are distinct.

Supported declarations are exactly HTML, XHTML, JSON, generic XML, plain text, and non-empty `application/*+json` / `application/*+xml` suffixes. The decision consumes a sorted, deduplicated candidate set, so multiple candidates yield `Ambiguous` independently of detector order. The exact v1 signatures are intentionally disjoint and do not currently overlap through public detection. Only the documented generic binary declarations permit sniffing. The 4096-byte sniffer applies the MIME HTML pattern masks and terminators, anchored XML BOM and UTF-16/32 declaration signatures, ASCII XML declaration signature, and JSON object/array rule. Every result retains extent and every non-singleton result retains all candidates.

## Decoding

HTML applies BOM, supported HTTP charset, the bounded 1024-byte tag/attribute meta state machine, then Windows-1252. The prescan ignores comments and script/style raw text, requires a complete meta tag inside the bound, applies first-occurrence attribute and content-type pragma rules, and performs HTML's UTF-16 and x-user-defined adjustments. XML applies BOM, terminal HTTP charset, UTF-16/32 signature detection, a bounded declaration state machine, then UTF-8. XML declarations are case-sensitive at the encoded start and require VersionInfo before optional EncodingDecl/SDDecl, required separating whitespace, matched quotes, and exact `?>`; absent, malformed, unsupported, and duplicate/conflicting encoding evidence remain distinct. JSON is strict UTF-8 (recording its accepted UTF-8 BOM and ignored charset); UTF-16/32 JSON is rejected. Plain text applies BOM/charset and otherwise strict UTF-8. UTF-7, replacement, unknown labels, and UTF-32 are explicit unsupported outcomes.

Decoding uses `encoding_rs` streaming decoders with a small output buffer. It never decodes the complete source before truncating. The limit counts serialized UTF-8, permits no partial scalar, and probes at most one scalar beyond the limit. Replacement counting comes from malformed decoder events, not occurrences of genuine U+FFFD. Source truncation and output truncation are independent. Terminal incompleteness is determined from decoder state before applying strict or HTML replacement policy, and is recorded only when the retained source ended early; definitive invalid bytes remain invalid or replacement events.

`SelectedEncoding` contains the exact canonical `encoding_rs` name and has no catch-all identity. A decoded view includes bytes, exact size and digest, validated source and output references, typed producer/schema/lineage, selection evidence, conflicts, replacements, and truncation facts.

## Durability and exclusions

Artifact metadata, source/decoded/source-representation family references, producer, schema, digest, and lineage use validated durable types. CAS-324 projects runtime classification/declaration/decoding facts into a compact, versioned, fail-closed `SourceRepresentationEvidence` JSON payload. It preserves interpretation facts and typed references without serializing decoded text or allowing contradictory artifact lineage.

No HTML/XML/JSON syntax parser, selector engine, browser behavior, final capture construction, archive schema, or payload publication is included.

## Dependency rationale

`encoding_rs 0.8.35` provides the WHATWG label registry and incremental browser-compatible decoders absent from the standard library. Defaults are disabled and only `alloc` is enabled. It supports an older Rust version than the workspace MSRV and its `(Apache-2.0 OR MIT) AND BSD-3-Clause` licensing is permitted by `deny.toml`. A narrow local MIME parser avoids a general MIME dependency. Repository advisory, source, and license policy is enforced by `cargo deny`.
