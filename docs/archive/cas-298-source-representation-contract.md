# CAS-298: Source representation and decoding contract

Status: proposed normative contract; implementation is deferred to CAS-299 through CAS-305

Linear: [CAS-298](https://linear.app/cascadinglabs/issue/CAS-298/define-supported-source-representations-and-decoding-semantics)

## Purpose

This document defines the source representation produced by bounded Web Capture acquisition. It fixes the meaning of each byte layer, the bytes covered by source artifact integrity metadata, the initial source-format classification rules, and the character-decoding rules needed to recreate a Unicode view offline.

The contract is acquisition-provider-neutral. Direct HTTP is its first producer. A later browser producer may reuse it only when that producer can state honestly which byte layer it supplies.

The initial source formats are HTML, XML, JSON, and plain text. They are source representations, not filename extensions and not parsed document models.

## Boundary

The normative pipeline is:

```text
HTTP response body
  -> transfer framing removed by the HTTP stack
  -> content-coded body bytes, when exposed
  -> bounded Content-Encoding decode
  -> retained representation bytes
  -> bounded source-format classification
  -> bounded character decoding
  -> optional Unicode source view
```

The source artifact is the retained representation bytes. A Unicode source view is a reproducible interpretation of that artifact; it does not replace it.

This contract does not define HTML or XML trees, JSON values, selectors, syntax validity, rendered DOM evidence, browser execution, request execution, payload storage, or the canonical `WebCapture` envelope.

## Normative vocabulary

| Term | Meaning | May be unavailable? |
| --- | --- | --- |
| **Wire bytes** | Octets carried by the underlying transport, including protocol framing where applicable. | Yes; Yosoi does not claim these unless a provider explicitly exposes them. |
| **Transfer-decoded bytes** | Message content after HTTP transfer framing or transfer coding has been removed by the HTTP stack. | Yes. This layer is not automatically observable through a high-level client. |
| **Content-coded bytes** | Transfer-decoded content with the declared HTTP content codings still applied. | Yes; some providers expose only a decoded representation. |
| **Representation bytes** | Content after all declared and supported HTTP `Content-Encoding` codings have been removed in reverse application order. | Yes when decoding is unsupported or fails before usable output exists. |
| **Retained representation bytes** | The exact complete representation or exact prefix admitted under the decoded-representation limit. | No for a retained source artifact; the sequence may be empty. |
| **Unicode source view** | Unicode scalar content decoded from retained representation bytes according to the selected source-format rules. | Yes; capture of bytes does not require successful character decoding. |

HTTP representation metadata such as `Content-Type` and `Content-Encoding` is not part of representation data. Transfer framing is not source content. Character decoding is not HTTP content decoding.

## Core invariants

1. The source artifact digest covers exactly the retained representation bytes and no other layer.
2. Byte order marks remain in retained representation bytes and therefore remain covered by the source digest. A character decoder may consume a BOM as an encoding signature rather than emit it as text.
3. Retention does not normalize newlines, whitespace, Unicode, markup, or JSON escapes.
4. A truncated source digest covers exactly the retained prefix. It never represents an inferred complete body.
5. `Content-Length` is an observation, not proof of a complete decoded representation.
6. A provider must identify whether its body stream contains content-coded bytes or representation bytes. Yosoi must not decode a representation twice.
7. Encoded-input accounting is unavailable when the provider supplies only representation bytes. It must not be reconstructed from `Content-Length` or another header.
8. Unknown, unsupported, ambiguous, and undecodable are distinct outcomes.
9. A supported media declaration can classify malformed structured source. Syntax validity belongs to later parsing.
10. URL paths and filename extensions never participate in classification.
11. HTTP status does not determine whether a body is source evidence. A non-2xx body follows the same byte, classification, and decoding rules.
12. Empty retained bytes are a valid complete source payload when the response body completed normally.
13. Classification and decoding of a truncated source must remain marked as based on a retained prefix; neither operation upgrades it to complete.
14. Errors, metadata, and reason codes must not contain body excerpts or unrestricted header values.

## Provider byte-layer declaration

A provider supplies one of these semantic states:

```rust
pub enum AcquiredBodyLayer {
    ContentCoded {
        codings: Vec<HttpContentCoding>,
    },
    Representation,
}
```

This is an illustrative shape rather than a committed public API.

`ContentCoded` means Yosoi can count input bytes and apply the declared coding chain itself. `Representation` means the provider has already removed content codings; encoded-input count and decoder-specific evidence are unavailable unless the provider reports them through a separately reviewed trustworthy interface.

Every provider must make this declaration true. CAS-302 should separately document how its reviewed `wreq` configuration satisfies the requirement. Current `wreq` documentation exposes switches that disable automatic gzip, Brotli, deflate, and Zstandard response decompression; the transport implementation should prefer consuming content-coded bytes when its selected version and feature set proves that behavior. If it cannot expose those bytes reliably, it must use `Representation` and accept unavailable encoded-input accounting rather than fabricate it.

## HTTP content-coding rules

### Parsing and order

`Content-Encoding` field values are parsed as a bounded ordered list of case-insensitive coding tokens. Multiple field lines are combined in field order according to HTTP field combination rules. Empty elements and invalid tokens produce `malformed_content_encoding`.

Codings are listed in the order in which they were applied. Decoding therefore runs in reverse order. For example:

```text
Content-Encoding: gzip, br
```

means gzip was applied first and Brotli second; Yosoi decodes Brotli and then gzip.

The initial recognized codings are:

- `identity` — no transformation;
- `gzip` and `x-gzip` — gzip coding;
- `deflate` — zlib-wrapped deflate as registered for HTTP;
- `br` — Brotli.

An unrecognized coding produces `unsupported_content_encoding`. Yosoi does not guess whether an unrecognized coding was already removed.

### Bounds

The resolved capture specification must provide non-zero limits for:

- content-coded input bytes, when that layer is exposed;
- decoded representation bytes;
- Unicode view output bytes.

The body processor checks limits incrementally with checked arithmetic. It must not collect an unbounded complete input before enforcing them. A limit is the maximum admitted count, not an automatic truncation marker: a body that completes and whose decoder settles at exactly the limit is complete. Truncation requires observing additional input or decoder output beyond the limit, or terminating without being able to establish completion. A bounded one-byte probe may establish that more input exists; a header alone may not.

The decoded-representation limit applies to bytes emitted by the final content decoder. Observing output beyond the limit retains at most the configured number of representation bytes and produces a truncated source extent. Decoder output beyond the retained bound is neither stored nor hashed.

The encoded-input limit applies before input is admitted to the coding chain. Observing another content-coded byte after the admitted count reaches the limit produces an incomplete attempt. Partial decoder output may be retained as a truncated source when it is the exact sequence emitted before termination.

Deadline and cancellation checks belong to the acquisition lifecycle and apply between incremental reads and writes as well as while awaiting more input.

### Completion and failures

| Condition | Source-byte outcome |
| --- | --- |
| Stream and all decoder trailers complete within limits | Complete representation, including known zero bytes. |
| Additional decoded output observed beyond the decoded-output limit | Truncated retained prefix; complete size is unavailable unless independently and honestly known. |
| Additional content-coded input observed beyond the encoded-input limit | Truncated decoded prefix when one was emitted; otherwise unavailable. |
| Premature disconnect | Truncated decoded prefix when one was emitted; otherwise unavailable. |
| Malformed content coding or integrity trailer | Truncated decoded prefix may be retained, with the decoding failure recorded; never complete. |
| Unsupported coding | Representation unavailable because the representation layer was not reached. |
| Sink failure | No payload is published; the attempted artifact is unavailable. |
| Deadline or cancellation | Truncated decoded prefix may be retained atomically; otherwise unavailable. |

A content-coded payload is not relabeled as a source representation when the decoding chain cannot be completed. A future network-exchange artifact may retain such bytes under its own schema.

## Payload integrity and publication

SHA-256 is updated only for representation bytes accepted by the payload sink. The retained count and digest are finalized from the same accepted sequence.

For a complete or truncated `SourceArtifact`:

- `ArtifactRecord.content_digest` is SHA-256 of the exact retained bytes;
- `WebArtifactMetadata.extent.retained_bytes` equals the payload length;
- `ArtifactAvailability` agrees with the extent;
- a zero-length complete body uses the SHA-256 digest of the empty byte string;
- a failed or discarded payload has no retrievable bytes.

CAS-300 owns atomic payload publication and verification. Capture finalization must not succeed with metadata claiming retained bytes that the bundle cannot retrieve and verify.

## HTTP representation declarations

The complete `Content-Type` field is parsed separately from the existing artifact `MediaType`, which represents only a canonical lowercase `type/subtype` essence.

The parser records a bounded semantic projection rather than the unrestricted raw field:

```rust
pub enum MediaDeclarationOutcome {
    Missing,
    Parsed(DeclaredMediaType),
    Malformed { reason: MediaDeclarationErrorCode },
}

pub struct DeclaredMediaType {
    essence: MediaType,
    charset: DeclaredCharsetOutcome,
}

pub enum DeclaredCharsetOutcome {
    Missing,
    Label(CharacterEncodingLabel),
    Unsupported(CharacterEncodingLabel),
    Invalid,
    Conflicting,
}
```

The exact Rust layout remains reviewable in CAS-305. The semantic requirements are fixed:

- type, subtype, parameter names, and charset labels are compared ASCII-case-insensitively;
- the stored essence is canonical lowercase;
- quoted parameter syntax is parsed before interpreting `charset`;
- optional whitespace and quoted parameter syntax are normalized according to HTTP media-type parsing before values are interpreted;
- duplicate equal charset parameters may normalize to one value while recording duplication;
- empty, syntactically invalid, or conflicting charset parameters produce explicit invalid or conflicting outcomes;
- because `Content-Type` is a singleton field, multiple field lines are malformed even when their parsed values are identical; field order does not select a winner;
- arbitrary parameters and raw field text are not copied into ordinary errors;
- parsing is bounded before allocation.

### Artifact media type

`WebArtifactMetadata.media_type` describes the retained source payload but is not the declaration record:

1. When a valid `Content-Type` exists, use its canonical essence, including structured suffixes and unsupported types.
2. Otherwise, when classification selects a format through permitted sniffing, use that format's canonical media type.
3. Otherwise use `application/octet-stream`.

The declaration outcome, classification outcome, and artifact media type remain separate facts even when their strings agree.

## Source-format model

The initial semantic vocabulary is closed:

```rust
pub enum SourceFormat {
    Html,
    Xml(XmlProfile),
    Json,
    PlainText,
}

pub enum XmlProfile {
    Generic,
    Xhtml,
}
```

XHTML uses XML decoding and future XML parsing semantics. It is not classified as HTML merely because browsers can render it.

A classification result is independent of syntax validity:

```rust
pub enum SourceClassificationOutcome {
    Classified(ClassifiedSource),
    Unknown { reason: ClassificationReason },
    Unsupported {
        declared_media_type: MediaType,
        disagreement: DeclarationDisagreement,
    },
    Ambiguous { candidates: Vec<SourceFormat> },
}

pub struct ClassifiedSource {
    format: SourceFormat,
    basis: ClassificationBasis,
    disagreement: DeclarationDisagreement,
    source_extent: ClassificationExtent,
}
```

`ClassificationExtent` distinguishes a complete source from a retained prefix. `DeclarationDisagreement` records whether bounded byte evidence supports, contradicts, or cannot assess the declared format, including for a specific unsupported declaration. It must not contain source excerpts. When an ambiguous result carries multiple candidates, their wire order is HTML, XML generic, XML XHTML, JSON, then plain text; implementations must not expose detector execution order.

## Media-type mapping

A valid supported declaration is authoritative for the selected format even when later syntax parsing would fail.

| Canonical essence | Selected source format |
| --- | --- |
| `text/html` | HTML |
| `application/xhtml+xml` | XML, XHTML profile |
| `application/json` | JSON |
| `application/xml` | XML, generic profile |
| `text/xml` | XML, generic profile |
| `text/plain` | Plain text |
| `application/*+json` | JSON |
| `application/*+xml` | XML, generic profile |

The `*` rows mean a non-empty subtype ending in `+json` or `+xml`; they are not literal wildcard declarations.

Other valid media types are `Unsupported` in the first version. In particular, an arbitrary `text/*` type is not silently plain text, and `text/json` is not added without a separate compatibility decision.

## Classification precedence

Classification follows this deterministic order:

1. Parse the media declaration.
2. If the valid essence maps to an initial format, select that format.
3. If the valid essence is specific but unsupported, return `Unsupported`. Bounded sniff evidence may record disagreement but does not override the selection.
4. If the declaration is missing, malformed, or generic, apply bounded strong-signature sniffing.
5. If exactly one strong signature matches, select it with a sniffed basis.
6. If multiple strong signatures match, return `Ambiguous`.
7. Otherwise return `Unknown`; never default unknown bytes to plain text.

For this contract, generic declarations are `application/octet-stream`, `application/unknown`, `unknown/unknown`, and `*/*` where such a value can be represented by the parser. `text/plain` is not generic; it explicitly selects plain text.

### Bounded sniffing

Format sniffing examines at most the first 4096 retained representation bytes. HTML character-encoding prescan remains separately limited to the first 1024 bytes.

Strong signatures are deliberately narrow:

- HTML: the HTML byte-pattern rows in the MIME Sniffing Standard's algorithm for identifying an unknown MIME type, using that table's byte masks, leading-whitespace treatment, and required tag-terminating byte. A partial pattern at the sniff boundary does not match;
- XML: a recognized Unicode byte-order/encoding signature followed by an XML declaration, or the MIME Sniffing Standard's `<?xml` byte pattern after its permitted leading whitespace. A BOM alone does not classify XML;
- JSON: optional UTF-8 BOM, JSON whitespace, then `{` or `[`;
- plain text: no strong signature. Plain text requires its valid media declaration.

JSON scalar values are not sniffed because common prefixes such as digits, quotes, `true`, `false`, and `null` are too ambiguous without parsing. Sniffing identifies a candidate representation; it does not validate complete syntax.

For a valid supported declaration, the same bounded signatures may be evaluated only to record agreement or disagreement. They never cause a different selected format. Absence of a signature is `not_assessed` or `inconclusive`, not disagreement: valid HTML, XML, and JSON need not provide a recognizable prefix within the sniff bound.

An `Unsupported`, `Ambiguous`, or `Unknown` classification never enters character decoding in this version, even when the retained bytes happen to be valid UTF-8. Its decoding outcome is `NotApplicable`; later policy may explicitly add another source format without reinterpreting this contract.

## Character-decoding contract

Character decoding consumes retained representation bytes and the recorded declaration/classification facts. It never fetches the URL or reads process-global defaults.

The decoder records:

- selected encoding and canonical label;
- selection basis;
- declaration/BOM/in-band conflicts;
- whether invalid input was rejected or replaced;
- source artifact reference and source completeness;
- exact UTF-8 byte size of the produced Rust string;
- complete, output-truncated, unsupported, or undecodable outcome.

The Unicode output limit counts UTF-8 bytes in the resulting string. Truncation occurs only at a Unicode scalar boundary. A truncated Unicode view is explicitly distinct from a truncated source artifact.

A decoded view is a constructed `DecodedSourceArtifact`, with media essence
`application/vnd.yosoi.decoded-source+utf8`. This stable vendor essence makes the
canonical UTF-8 derived representation unambiguous and does not mislabel it as
`text/plain` or as the original HTML, XML, JSON, or plain-text source format. Its
metadata digest and extent cover exactly the bounded UTF-8 bytes. Complete views
are retained without a reason; output-truncated views are truncated with an
explicit reason and unavailable complete size. The artifact is compatible with
later `CaptureBundle` publication, but decoding alone neither inserts its payload
into a bundle nor finalizes a capture. No serialization contract is claimed for
`DecodedSourceView`.

Encoding labels and legacy decoders use the WHATWG Encoding Standard label mapping where that standard applies. The replacement encoding and UTF-7 are never accepted. A recognized signature for an unsupported encoding, including UTF-32 in the initial implementation, produces a specific unsupported outcome rather than a misleading UTF-8 failure.

### HTML

HTML follows the browser-oriented Encoding/HTML rules within the bounded offline context:

1. UTF-8 or UTF-16 BOM;
2. supported HTTP `charset` parameter;
3. HTML encoding declaration found by the standard prescan of at most the first 1024 bytes;
4. `windows-1252` fallback.

Conflicts remain recorded even though the higher-precedence source wins. An invalid, empty, or unsupported HTTP charset label is recorded and then skipped as the HTML algorithm requires; prescan and fallback remain available. A BOM is consumed as a signature. Invalid byte sequences use the selected WHATWG decoder's replacement behavior and the view records that replacement occurred. This behavior is security-relevant and must not be replaced by platform-default decoding.

Replacement is a provenance-visible derivation, not a correction to captured evidence. The retained source artifact remains the authority for the exact original representation bytes. A persisted HTML Unicode view receives its own artifact identity, digest over its serialized UTF-8 text, schema, decoder producer and version, encoding-selection basis, replacement occurrence or count, and `derived_from` reference to the exact `SourceArtifactRef`. It never overwrites the source payload or reuses the source digest. Re-running the recorded decoder policy against that source must reproduce the same view.

No user override, parent-frame encoding, locale heuristic, or provider default participates in Direct HTTP offline decoding.

### XML and XHTML

XML follows RFC 7303 and XML autodetection:

1. BOM or encoding signature;
2. MIME `charset` when no BOM is present;
3. XML declaration or XML byte-pattern autodetection when no MIME charset is present;
4. UTF-8 when XML rules establish the no-declaration default.

A BOM is authoritative. A MIME charset is authoritative only in the absence of a BOM. A present invalid or unsupported MIME charset produces the corresponding decoding outcome rather than falling through to the XML declaration. Conflicts with an XML declaration are recorded. XHTML uses these XML rules.

XML decoding is strict. Invalid byte sequences produce `Undecodable`; they are not replaced silently. UTF-32 signatures are recognized for an actionable `UnsupportedEncoding` outcome in the initial implementation.

### JSON

JSON transported between systems is UTF-8 under RFC 8259. The `application/json` registration defines no `charset` parameter.

- Decode JSON as strict UTF-8.
- Ignore a declared charset for selection but record it as an inapplicable or conflicting declaration.
- Accept and consume an initial UTF-8 BOM for interoperability while recording the non-conforming BOM.
- UTF-16 or UTF-32 signatures produce `UnsupportedEncoding`, not JSON text.
- Invalid UTF-8 produces `Undecodable`.

JSON syntax validity is not checked in this stage. Empty or malformed JSON can decode successfully as text while remaining unparsed source.

### Plain text

For `text/plain`:

1. a recognized Unicode BOM;
2. a supported declared charset;
3. strict UTF-8 only when the charset is missing and the entire retained input is valid UTF-8;
4. otherwise the explicit invalid, conflicting, unsupported, or `Undecodable` outcome because HTTP no longer supplies a universal default charset for `text/*`.

The UTF-8 fallback basis is recorded explicitly. Plain-text decoding is strict; invalid input is not silently replaced.

## Truncated source and character decoding

A decoder may produce a partial Unicode view from a truncated retained source, but the view must carry `source_truncated` and cannot be `Complete`.

For strict formats, an incomplete trailing code unit caused solely by the acquisition boundary is omitted at the last valid scalar boundary and recorded as `incomplete_terminal_sequence`; it is not reported as malformed source. Invalid input occurring before that boundary remains `Undecodable`. HTML continues to use its standard replacement decoder but remains source-truncated.

Classification from a truncated prefix is likewise marked as prefix-based. A supported media declaration remains authoritative regardless of truncation.

## Empty and malformed source

- A normally completed empty body is a complete zero-byte source artifact.
- A supported media declaration still classifies an empty body by declaration.
- Without a supported declaration, an empty body is `Unknown { reason: empty }`.
- Character decoding of a declared supported empty HTML, XML, JSON, or plain-text source produces an empty Unicode view using that format's selection rules when an encoding can be selected.
- Empty JSON/XML/HTML may fail later syntax parsing; that does not alter capture integrity or classification.
- Malformed HTML, XML, or JSON remains faithfully captured and classified when its declaration or strong signature selects that format.

## Required HTTP observations

To interpret retained source bytes offline, the acquisition result must preserve bounded semantic forms of:

- HTTP status;
- `Content-Type` declaration outcome, essence, and charset outcome;
- ordered `Content-Encoding` parsing and decoding outcome;
- provider-supplied body layer;
- available content-coded and decoded byte accounting;
- complete/truncated/unavailable state and terminal reason;
- source artifact reference, retained count, and digest.

`Content-Length`, `Transfer-Encoding`, and unrestricted response headers may be useful network observations but are not required source-decoding inputs. Sensitive or unrestricted header values must not be copied into source-decoding errors.

## Illustrative source facts

A likely independently versioned source payload schema can use a shape like:

```rust
pub struct SourceRepresentationFacts {
    source: SourceArtifactRef,
    declaration: MediaDeclarationOutcome,
    content_decoding: ContentDecodingOutcome,
    classification: SourceClassificationOutcome,
}

pub enum CharacterDecodingOutcome {
    Complete(DecodedSourceView),
    Truncated(DecodedSourceView),
    UnsupportedEncoding { label: CharacterEncodingLabel },
    Undecodable { reason: CharacterDecodingErrorCode },
    NotApplicable { reason: CharacterDecodingErrorCode },
}
```

These types should live with web-capture behavior until another immediate consumer proves they are shared vocabulary. Display text is not a wire protocol; stable error codes and bounded context are required where values cross a process boundary.

## Relationship to later project issues

- CAS-299 supplies explicit limits, accepted formats, and unsupported-format behavior.
- CAS-300 binds retained payloads to `SourceArtifactRef` and verifies digest and size.
- CAS-301 owns deadlines, cancellation, accounting, and terminal lifecycle state.
- CAS-302 proves the byte-layer declaration against `wreq`.
- CAS-303 implements incremental content decoding, bounds, hashing, and retention.
- CAS-305 implements declaration parsing, classification, character decoding, and provenance-complete decoded views.
- CAS-306 proves the complete contract with deterministic local fixtures.

## Rejected alternatives

### One generic `Document` model

Rejected for this slice. HTTP source HTML, parsed HTML, XML, JSON, browser-rendered DOM, accessibility data, and screenshots are different evidence. The reusable seam is bounded source-byte processing, not a universal document tree.

### Hashing content-coded bytes

Rejected because the same representation can use different transfer codings and later offline extraction needs the decoded representation. Content-coded evidence may belong to a separately identified network artifact.

### Hashing Unicode text

Rejected because character-decoding choices and replacement behavior would change source identity and could erase byte-level evidence.

### Treating unknown bytes as plain text

Rejected because it hides unsupported and binary formats and makes accidental decoding look authoritative.

### Parsing to validate classification

Rejected because malformed structured source is still valid capture evidence. Parsing belongs to deterministic extraction.

## Sources and intentional profile choices

Primary sources:

- [RFC 9110: HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110), especially Sections 6 and 8 on message content, representations, representation data, metadata, and content codings.
- [RFC 6839: Additional Media Type Structured Syntax Suffixes](https://www.rfc-editor.org/rfc/rfc6839) for `+json` and `+xml`.
- [RFC 7303: XML Media Types](https://www.rfc-editor.org/rfc/rfc7303) for XML media types and BOM/charset/declaration precedence.
- [RFC 8259: JSON](https://www.rfc-editor.org/rfc/rfc8259), especially Section 8.1 and the `application/json` registration.
- [RFC 6657: Update to MIME regarding Charset Parameter Handling in Textual Media Types](https://www.rfc-editor.org/rfc/rfc6657) for the absence of a universal `text/*` charset default.
- [WHATWG MIME Sniffing Standard](https://mimesniff.spec.whatwg.org/) for MIME groups and bounded signature precedent.
- [WHATWG HTML parsing: determining the character encoding](https://html.spec.whatwg.org/multipage/parsing.html#determining-the-character-encoding) for BOM handling and the 1024-byte HTML prescan.
- [WHATWG Encoding Standard](https://encoding.spec.whatwg.org/) for encoding labels and decoder behavior.

Yosoi intentionally uses a narrower classification profile than a browser: specific unsupported declarations are not overridden, plain text is never inferred without its declaration, and JSON sniffing accepts only object/array prefixes. These restrictions favor explainable capture evidence over browser compatibility. The HTML decoding path intentionally follows browser-compatible replacement behavior; XML, JSON, and plain text use strict decoding.
