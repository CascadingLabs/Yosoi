# CAS-298 source representation reference scenarios

Status: normative design scenarios; deterministic fixture implementation is deferred to CAS-303, CAS-305, and CAS-306

Linear: [CAS-298](https://linear.app/cascadinglabs/issue/CAS-298/define-supported-source-representations-and-decoding-semantics)

## Purpose

These scenarios make the decisions in [the source representation contract](cas-298-source-representation-contract.md) reviewable and testable. Each future fixture must assert the retained byte sequence, its exact size and SHA-256 digest, declaration facts, classification result and basis, character-decoding outcome, and capture completeness.

Unless a row states otherwise:

- the HTTP status is `200`;
- the response stream completes within all limits;
- no `Content-Encoding` is present;
- retained bytes exactly equal the response body bytes;
- the source extent is complete;
- the artifact digest is SHA-256 of those exact retained bytes;
- source syntax is not parsed or validated;
- URL filename extensions are ignored.

Literal examples below are descriptive. CAS-306 owns fixture bytes and golden digests.

## Correct declarations

| ID | Response declaration and body | Declaration outcome | Classification | Character decoding | Required assertions |
| --- | --- | --- | --- | --- | --- |
| `html-utf8` | `text/html; charset=utf-8`, UTF-8 HTML | Parsed `text/html`, UTF-8 | HTML, declared basis | UTF-8 complete | Digest covers original UTF-8 bytes, not the Rust string. |
| `html-app-shell` | `text/html; charset=utf-8`, an HTML shell whose content is populated by JavaScript | Parsed `text/html`, UTF-8 | HTML, declared basis | UTF-8 complete | Source may be complete; no rendered-DOM artifact or claim is implied. |
| `xml-application` | `application/xml`, UTF-8 XML declaration or UTF-8 default | Parsed `application/xml`, charset missing | XML generic, declared basis | Encoding declaration or XML UTF-8 default | Syntax validity is not asserted. |
| `xml-text` | `text/xml; charset=utf-8`, XML bytes | Parsed `text/xml`, UTF-8 | XML generic, declared basis | UTF-8 complete | `text/xml` is not plain text in the typed model. |
| `xhtml` | `application/xhtml+xml; charset=utf-8`, XHTML source | Parsed `application/xhtml+xml`, UTF-8 | XML with XHTML profile | XML UTF-8 rules | Must not be classified or decoded using HTML rules. |
| `json-object` | `application/json`, UTF-8 object | Parsed `application/json`, charset missing | JSON, declared basis | Strict UTF-8 complete | No JSON value is constructed. |
| `json-scalar` | `application/json`, UTF-8 `42` | Parsed `application/json`, charset missing | JSON, declared basis | Strict UTF-8 complete | Scalar JSON is supported when declared even though scalar prefixes are not sniffed. |
| `plain-utf8` | `text/plain; charset=utf-8`, UTF-8 text | Parsed `text/plain`, UTF-8 | Plain text, declared basis | Strict UTF-8 complete | Plain text is selected because it was declared. |
| `plain-labelled-legacy` | `text/plain; charset=windows-1252`, valid Windows-1252 bytes | Parsed `text/plain`, Windows-1252 | Plain text, declared basis | Windows-1252 complete | Selected encoding and label-resolution basis are recorded. |

## Structured media suffixes and XHTML

| ID | Response declaration and body | Declaration outcome | Classification | Character decoding | Required assertions |
| --- | --- | --- | --- | --- | --- |
| `problem-json` | `application/problem+json`, valid UTF-8 with malformed JSON syntax | Parsed exact essence | JSON, structured-suffix basis | Strict UTF-8 complete | Malformed syntax does not invalidate capture or classification. Artifact media type remains `application/problem+json`. |
| `vendor-json` | `application/vnd.example.record+json`, UTF-8 JSON | Parsed exact essence | JSON, structured-suffix basis | Strict UTF-8 complete | No registry-specific semantic contract is inferred. |
| `atom-xml` | `application/atom+xml`, UTF-8 XML | Parsed exact essence | XML generic, structured-suffix basis | XML rules | Artifact media type remains `application/atom+xml`. |
| `vendor-xml` | `application/vnd.example.data+xml`, XML with declared legacy encoding | Parsed exact essence | XML generic, structured-suffix basis | XML precedence rules | The structured suffix classifies format; the XML declaration selects encoding only when higher-priority facts are absent. |
| `xhtml-html-looking` | `application/xhtml+xml`, bytes beginning with an HTML-like document | Parsed exact essence | XML with XHTML profile | XML rules | HTML-looking markup does not change XHTML to HTML. |

## Missing, generic, malformed, and unsupported declarations

Classification sniffing examines no more than the first 4096 retained bytes.

| ID | Response declaration and body | Declaration outcome | Classification | Character decoding | Required assertions |
| --- | --- | --- | --- | --- | --- |
| `missing-html` | No `Content-Type`; strong HTML signature | Missing | HTML, sniffed basis | HTML encoding rules | Artifact media type is `text/html`; missing declaration remains separately visible. |
| `generic-xml` | `application/octet-stream`; recognized Unicode signature followed by an XML declaration | Parsed generic essence | XML generic, sniffed basis | XML rules | Generic declaration is retained; selected artifact media type is `application/octet-stream` under the valid-declaration rule. |
| `missing-json-object` | No declaration; whitespace then `{` | Missing | JSON, sniffed basis | Strict UTF-8 | A bounded object/array prefix is sufficient for candidate classification, not syntax validity. |
| `missing-json-scalar` | No declaration; body `42` | Missing | Unknown | Not applicable | JSON scalar prefixes are intentionally not sniffed. |
| `missing-readable-text` | No declaration; valid UTF-8 prose | Missing | Unknown | Not applicable | Valid UTF-8 is not enough to silently classify plain text. |
| `generic-readable-text` | `application/octet-stream`; valid UTF-8 prose | Parsed generic essence | Unknown | Not applicable | Generic bytes do not silently become plain text. |
| `malformed-type-html` | Malformed `Content-Type`; strong HTML signature | Malformed with bounded reason code | HTML, sniffed basis | HTML rules | Raw malformed header text is absent from ordinary errors. |
| `conflicting-content-type` | Conflicting `Content-Type` field values; JSON object bytes | Malformed/conflicting | JSON, sniffed basis | Strict UTF-8 | Conflicting singleton fields are not resolved by field order. |
| `duplicate-content-type` | Two identical `Content-Type: application/json` field lines; JSON object bytes | Malformed duplicate singleton | JSON, sniffed basis | Strict UTF-8 | Even identical repeated singleton fields are rejected rather than silently combined. |
| `unsupported-image` | `image/png`; PNG bytes | Parsed supported syntax, unsupported essence | Unsupported `image/png` | Not applicable | Payload may still be retained as source bytes; artifact media type is `image/png`. |
| `unsupported-html-body` | `image/png`; strong HTML signature | Parsed unsupported essence | Unsupported `image/png`, disagreement recorded | Not applicable | Sniffing does not override a specific unsupported declaration. |
| `other-text-type` | `text/csv; charset=utf-8`; CSV bytes | Parsed unsupported essence | Unsupported `text/csv` | Not applicable | Arbitrary `text/*` does not become plain text. |
| `text-json` | `text/json`; JSON object bytes | Parsed unsupported essence | Unsupported `text/json`, detectable disagreement allowed | Not applicable | `text/json` is outside the initial mapping despite browser MIME grouping precedent. |
| `ambiguous-prefix` | Missing declaration; bounded prefix deliberately matches more than one implemented strong signature | Missing | Ambiguous with candidates | Not applicable | Implementation must not choose by detector order. |
| `signature-after-bound` | Missing declaration; 4096 bytes without a strong signature followed by HTML | Missing | Unknown | Not applicable | No scan past the fixed classification bound. |

## Declared and detected disagreement

A valid supported declaration remains authoritative. Detection is only bounded evidence and does not parse the complete source.

| ID | Declaration and body | Selected classification | Disagreement | Character decoding |
| --- | --- | --- | --- | --- |
| `html-declared-json-body` | `text/html; charset=utf-8`, body begins with `{` | HTML, declared basis | Detected JSON candidate conflicts | HTML UTF-8 rules |
| `json-declared-html-body` | `application/json`, strong HTML signature | JSON, declared basis | Detected HTML candidate conflicts | Strict UTF-8; syntax is not checked |
| `plain-declared-json-body` | `text/plain; charset=utf-8`, JSON object bytes | Plain text, declared basis | Detected JSON candidate conflicts | Strict UTF-8 |
| `xml-no-signature-in-bound` | `application/xml`, long permitted prefix without recognized signature | XML, declared basis | Inconclusive, not conflict | XML encoding selection may still fail explicitly |

## Character-encoding precedence

| ID | Format and encoding evidence | Selected encoding/outcome | Required assertions |
| --- | --- | --- | --- |
| `html-utf8-bom-conflict` | `text/html; charset=windows-1252`, UTF-8 BOM | UTF-8 from BOM | BOM wins, is retained and hashed, is consumed from text, and conflict is recorded. |
| `html-transport-over-meta` | `text/html; charset=windows-1252`, `<meta charset="utf-8">` in first 1024 bytes | Windows-1252 from HTTP charset | Meta disagreement is recorded and does not override transport metadata. |
| `html-meta` | `text/html`, no BOM/charset, valid meta declaration in first 1024 bytes | Encoding from HTML prescan | Prescan consumes no more than 1024 bytes. |
| `html-meta-too-late` | `text/html`, meta declaration begins after byte 1024 | Windows-1252 fallback | Late declaration does not affect offline decoding. |
| `html-no-encoding` | `text/html`, no BOM, charset, or prescanned meta | Windows-1252 fallback | The fallback basis is explicit. |
| `html-invalid-sequence` | `text/html; charset=utf-8`, invalid UTF-8 | UTF-8 view with standard replacement | Original invalid bytes remain authoritative and unchanged. The derived view records its own identity and digest, decoder producer/version and policy, replacement occurrence or count, and lineage to the exact source artifact. |
| `xml-bom-conflict` | `application/xml; charset=iso-8859-1`, UTF-8 BOM, XML declaration names another encoding | UTF-8 from BOM | BOM is authoritative; both disagreements are recorded. |
| `xml-charset-over-declaration` | `application/xml; charset=windows-1252`, no BOM, XML declaration says UTF-8 | Windows-1252 from MIME charset | MIME charset wins in the absence of BOM; conflict is recorded. |
| `xml-declaration` | `application/xml`, no BOM/charset, XML declaration names supported encoding | Declared XML encoding | XML declaration basis is recorded. |
| `xml-default-utf8` | `application/xml`, no BOM/charset/declaration, UTF-8-compatible XML prefix | UTF-8 XML default | Default basis is recorded. |
| `xml-utf32-signature` | `application/xml`, UTF-32 signature | Unsupported UTF-32 | Signature is recognized for an actionable outcome rather than reported as malformed UTF-8. |
| `xml-invalid-sequence` | `application/xml; charset=utf-8`, invalid UTF-8 before any truncation boundary | Undecodable | No replacement Unicode view is claimed. |
| `json-charset-ignored` | `application/json; charset=windows-1252`, valid UTF-8 JSON | UTF-8 | Charset is recorded as inapplicable/conflicting; JSON remains UTF-8. |
| `json-utf8-bom` | `application/json`, UTF-8 BOM followed by valid JSON | UTF-8 complete | BOM is retained and hashed, consumed from text, and recorded as non-conforming but accepted. |
| `json-utf16-bom` | `application/json`, UTF-16 BOM and body | Unsupported encoding | JSON is not silently transcoded as legacy network JSON. |
| `json-invalid-utf8` | `application/json`, invalid UTF-8 | Undecodable | Source bytes remain a complete classified JSON artifact. |
| `plain-bom-conflict` | `text/plain; charset=windows-1252`, UTF-8 BOM | UTF-8 from BOM | Conflict is recorded. |
| `plain-no-charset-valid-utf8` | `text/plain`, valid UTF-8 | UTF-8 validation fallback | No universal HTTP `text/*` default is claimed. |
| `plain-no-charset-invalid-utf8` | `text/plain`, no BOM/charset, invalid UTF-8 | Undecodable | Bytes are not silently decoded as ISO-8859-1 or Windows-1252. |
| `unsupported-label` | Declared XML or plain text with a syntactically valid but unsupported charset label | Unsupported encoding | The bounded normalized label may be reported; no source excerpt is reported. HTML instead records and skips an unsupported label according to its algorithm. |
| `quoted-charset` | `text/plain; charset="utf-8"`, valid UTF-8 | UTF-8 from parsed parameter | Quoted syntax is parsed before label resolution. |
| `empty-charset` | `text/plain; charset=""`, valid UTF-8 | Invalid charset declaration; no decoded view | Empty is not treated as a missing parameter or permitted to use the missing-charset UTF-8 fallback. |
| `escaped-quoted-charset` | Quoted charset value containing an invalid escaped label | Invalid or unsupported bounded label outcome | Quoted-string unescaping cannot inject raw header text into errors. |
| `malformed-content-type-parameter` | Unterminated quoted charset parameter; strong supported-format signature | Malformed declaration | Classification follows missing/malformed sniff rules rather than partially accepting the parameter. |
| `conflicting-charsets` | Supported format with duplicate conflicting charset parameters | Conflicting charset outcome | Format-specific lower-priority evidence is used only where its rules permit; conflict remains visible. |
| `xml-utf16le-bom` | `application/xml`, UTF-16LE BOM and valid UTF-16LE XML | UTF-16LE from BOM | BOM is retained and hashed, consumed from the view, and XML decoding completes. |
| `xml-utf16-signature-conflict` | `application/xml; charset=utf-8`, no BOM but UTF-16LE bytes whose ASCII markup bytes form valid UTF-8 with interleaved NULs | UTF-8 complete from MIME charset, with encoding-signature conflict | The MIME charset remains authoritative without a BOM; the contradictory signature is recorded even though strict UTF-8 decoding itself succeeds. |
| `html-utf16le-bom` | `text/html; charset=utf-8`, UTF-16LE BOM | UTF-16LE from BOM | BOM wins and the charset conflict is recorded. |
| `html-utf32-signature` | `text/html`, UTF-32 signature | Unsupported UTF-32 | It is not sent through the Windows-1252 fallback. |

## Content-coding and byte accounting

| ID | Transfer setup | Retained source outcome | Required assertions |
| --- | --- | --- | --- |
| `gzip-html` | Content-coded bytes, `Content-Encoding: gzip`, complete HTML | Complete decoded representation | Encoded count is compressed bytes; retained count/digest cover decompressed HTML only. |
| `br-json` | Content-coded bytes, `Content-Encoding: br`, complete JSON | Complete decoded representation | Classification and character decoding run after Brotli decode. |
| `deflate-xml` | Zlib-wrapped deflate under `Content-Encoding: deflate` | Complete decoded representation | Raw-deflate guessing is not performed silently. |
| `stacked-codings` | `Content-Encoding: gzip, br` | Complete only after Brotli then gzip decode | Coding order and reverse decoding are asserted. |
| `repeated-content-encoding-fields` | Separate `Content-Encoding: gzip` and `Content-Encoding: br` field lines | Complete only after the combined ordered chain is reversed | A list-valued field preserves arrival order rather than being treated like singleton `Content-Type`. |
| `identity-in-chain` | `Content-Encoding: gzip, identity` | Complete after identity no-op then gzip decode | Identity is represented explicitly and cannot reorder or hide another coding. |
| `already-decoded-provider` | Provider declares `Representation`; response metadata mentions gzip | Complete supplied representation | No second decode; encoded-input count is unavailable. |
| `unsupported-coding` | Content-coded bytes with unknown coding | Source representation unavailable | Content-coded bytes are not relabeled or hashed as source. |
| `malformed-gzip-before-output` | Decoder rejects malformed gzip before emitting bytes | Unavailable | No zero-byte retained source is fabricated. |
| `malformed-gzip-after-output` | Decoder emits bytes and then fails integrity/trailer validation | Truncated emitted sequence | Never complete; retained digest covers only atomically published decoder output and the failure remains explicit. |
| `encoded-limit-exact` | Content-coded input and decoder completion are established at exactly the encoded limit | Complete | Merely reaching the maximum does not imply truncation. |
| `encoded-limit-plus-one` | Another content-coded byte is observed after exactly the encoded limit was admitted | Truncated decoded sequence when available | The additional byte is observed but not admitted; complete decoded size is unavailable. |
| `decoded-limit-exact` | Final decoder emits exactly the decoded limit and settles normally | Complete | Exact-boundary output is not truncated. |
| `decoded-limit-plus-one` | Final decoder attempts to emit one byte beyond the decoded limit | Exactly bounded truncated representation sequence | No output beyond the limit is retained or hashed; expansion cannot allocate unbounded memory. |
| `high-expansion-ratio` | Compressed fixture with extreme expansion | Limit-ended incomplete result | Both encoded and decoded accounting use checked arithmetic. |
| `chunked-multibyte` | Content and character sequences split across every relevant chunk boundary | Same result as contiguous input | Transport chunking does not change retained bytes, digest, classification, or decoded text. |
| `disconnect` | Stream disconnects after decoder emits bytes | Truncated source prefix | Terminal reason is disconnect; no complete-size inference. |
| `deadline` | Slow stream exceeds overall deadline | Truncated prefix or unavailable | Deadline state is explicit and no background read continues publishing. |
| `cancellation` | Cancellation occurs between chunks | Truncated prefix or unavailable | Cancellation evidence and atomic publication behavior are deterministic. |
| `sink-failure` | Payload sink fails after accepting some bytes | Unavailable; no payload published | Metadata cannot claim retained bytes from an unpublished temporary sink. |

## Empty, non-success, malformed, and truncated source

| ID | Response | Classification/decoding | Required assertions |
| --- | --- | --- | --- |
| `empty-html` | `text/html`, normal zero-byte body | HTML by declaration; empty HTML view using fallback selection | Complete extent has zero retained bytes and SHA-256 of empty bytes. Later HTML parsing validity is irrelevant. |
| `empty-json` | `application/json`, normal zero-byte body | JSON by declaration; empty UTF-8 text | Capture/classification can be complete even though later JSON parsing fails. |
| `empty-undeclared` | No `Content-Type`, normal zero-byte body | Unknown with `empty` reason; no decoded view | Empty is not inferred as plain text. |
| `not-found-html` | `404`, `text/html; charset=utf-8`, HTML error body | HTML by declaration; UTF-8 complete | Status remains 404; body is retained normally and is not converted into a transport failure. |
| `server-error-json` | `500`, `application/json`, malformed JSON error body | JSON by declaration; UTF-8 complete | Malformed syntax and non-2xx status do not erase evidence. |
| `truncated-utf8-boundary` | Source limit ends between bytes of a UTF-8 scalar | Prefix-based classification; partial decoded view ends before incomplete scalar | Terminal sequence is attributed to truncation, not silently replaced for strict formats. |
| `invalid-before-truncation` | Invalid UTF-8 occurs before a later source limit | Classified source; undecodable | Earlier malformed input is not hidden by the later truncation boundary. |
| `decoded-text-limit` | Complete source decodes beyond Unicode output limit | Output-truncated Unicode view | Source artifact remains complete; text truncation ends at a scalar boundary and is separately recorded. |
| `malformed-html` | Declared HTML with malformed markup | HTML; character decoding follows HTML rules | No syntax-validity claim is made. |
| `malformed-xml` | Declared XML with well-decoded but malformed markup | XML; character decoding can be complete | No XML tree or well-formedness claim is made. |
| `malformed-json` | Declared JSON with well-decoded invalid syntax | JSON; character decoding can be complete | No JSON value or validity claim is made. |

## Integrity assertions shared by every retained-payload fixture

Every complete or truncated retained source fixture must verify:

1. Retrieved payload bytes equal the expected exact byte sequence.
2. Payload length equals `ArtifactByteExtent.retained_bytes`.
3. SHA-256 of retrieved bytes equals `ArtifactRecord.content_digest`.
4. The payload reference belongs to the containing capture activity.
5. A truncated digest covers the prefix only and does not equal metadata for a complete body unless the byte sequences genuinely coincide.
6. A discarded or unavailable result cannot retrieve payload bytes.
7. Classification and Unicode views refer to the same typed `SourceArtifactRef`.
8. Re-running classification and character decoding offline from retained bytes and recorded facts yields the same outcome.
9. No error text contains response-body excerpts or unrestricted response-header values.
10. A persisted Unicode view has its own artifact identity and digest, decoder producer/version and policy, encoding basis, replacement facts, and `derived_from` lineage; it never replaces or mutates the source artifact.

## Fixture implementation shape

CAS-306 should implement these as deterministic local routes and byte fixtures, grouped so individual cases remain reviewable:

```text
tests/fixtures/acquisition/
  html/
  xml/
  json/
  text/
  media-declarations/
  character-encodings/
  content-codings/
  limits-and-failures/
```

Golden files should store expected semantic outcomes and hashes, while binary fixture bytes remain separate files. Fixture generation must be deterministic and must not use the public network.

## Review checklist

For every row, a reviewer must be able to answer:

1. Which provider byte layer entered the processor?
2. Which bytes were admitted under the encoded and decoded limits?
3. Which exact bytes were retained and hashed?
4. What declaration facts were parsed without preserving unsafe raw values?
5. Which source format, if any, was selected and on what basis?
6. Was disagreement, ambiguity, or unsupported input preserved?
7. Which character encoding was selected and why?
8. Did invalid input fail or use replacement according to the selected format?
9. Is source truncation distinct from Unicode-view truncation?
10. Can the outcome be reproduced offline without HTTP client state?
