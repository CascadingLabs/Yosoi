# Document-locator conformance corpus v1

This directory is the offline authority shared by the first Rust implementation
and future Python bindings. It describes locator behavior without importing a
request client, browser, archive, queue, or evaluator implementation.

## Tiny golden tier

`manifest.json` pins six UTF-8 fixtures by byte count, SHA-256, representation
schema, media type, and provenance. `matrix.json` contains the authoritative
15 golden locator cases, one for each supported document/locator pair:

| Document | Locator pairs |
| --- | --- |
| Source HTML | CSS, bounded XPath, tree text |
| XML | namespace-aware CSS, bounded XPath, tree text |
| JSON | RFC 6901 Pointer, bounded JSONPath |
| Rendered DOM | CSS, bounded XPath, tree text |
| Accessibility tree | exact role, exact text |
| Decoded text | literal text, regex |

Each case fixes its query, projection, output ID, ordered values, match count,
and evidence coordinate. HTML5-repaired markup uses one-based element-child
paths because tree repair can synthesize or move nodes. XML uses exact source
byte ranges and expanded-name paths. JSON uses RFC 6901 coordinates. Rendered
DOM and accessibility-tree coordinates carry the document epoch and node ID.
Decoded text records UTF-8 byte offsets and Unicode-scalar offsets.

The DOM fixture uses the canonical `yosoi.rendered-dom.v1` document-light-DOM
schema. It includes explicit document, element, and text nodes with
namespace-aware attribute pairs. It excludes shadow and composed trees, iframe
subdocuments, pseudo-elements, and layout visibility. The AX fixture uses
`yosoi.accessibility-tree.v1`; accessible name and text remain separate fields,
and the fixture records that capture completeness is unknown.

The separate `region_cases` lock repeated-product outputs and their
parent-region coordinates. They do not change the 15-case locator-pair
registry.

Decoded text accepts strict UTF-8 only: invalid input fails at its first invalid
byte, and no lossy replacement, byte-order-mark removal, normalization, or
implicit case folding occurs. Literal queries are exact and case-sensitive,
return left-to-right non-overlapping matches, and may contain whitespace.
Regex queries use Rust's Unicode-aware non-backtracking engine; matching is
leftmost-first and non-overlapping, inline flags may opt into case-insensitive
matching, and zero-width matches have empty half-open ranges. Look-around and
backreferences are unsupported. Regex results contain the full match; named
captures are returned only when a plan explicitly requests them.

Run the default, tiny, network-free check with:

```bash
python3 scripts/fixtures/verify-document-locator-corpus.py --self-test
```

The self-test rejects unknown schemas, digest and path mismatches, incorrect
coordinate/value projections, and malformed modality-specific oracle records.
The same command is exercised by the `yosoi-benchmarks` contract test.

## Advanced stress tier

The retained source/browser set is 55,572,090 bytes. The expanded corpus is
63,475,181 bytes after including the 4,304,975-byte derived-text fixture and
the 3,598,116-byte normalized rendered-DOM v2 fixture. The normalized AX v1
fixture is included in the retained source archive. The deterministic
8,422,863-byte `advanced/source.tar.gz` is pinned by SHA-256
`4a292b3d6242f2d85109ab37675002604a60f04d02b0bf9430f2dc1e67992ffc`.
`advanced/manifest.json` pins every member by size and SHA-256, plus its
schema, encoding, source URL, capture timestamp, license, attribution, and
derivation or browser-capture provenance.

All 15 advanced expectations are locked against independent reference results:

- CAS-387 fixes both decoded-text values and their byte/scalar ranges.
- CAS-388 fixes the NVD `totalResults` pointer and the 10,790 ordered USGS
  magnitude results, including the ordered-coordinate digest and end samples.
- CAS-389 fixes three WHATWG HTML queries against an offline lxml/libxml2
  parser, with parser identity, ordered-record digests, and samples.
- CAS-390 fixes the RFC-index namespace-aware CSS and text cases and the ECB
  XPath case using an independent Python Expat oracle with exact expanded-name
  paths and source byte ranges.
- CAS-391 fixes the normalized AX role and exact-text cases. Completeness stays
  `unknown` because the retained capture metadata does not pin its collection
  method; absent AX matches therefore cannot claim complete coverage. The
  normalization maps known Chromium role tokens to provider-neutral v1 names
  and removes 160 identical duplicate records.
- CAS-392 fixes the three rendered-DOM cases against a normalized v2 fixture.
  The output is 3,598,116 bytes with SHA-256
  `318a9d66f3f5a12d27b309e754c8d94f11aad633ceee80351f941aea18277d14`.
  Normalizer `yosoi-rendered-dom-cdp-snapshot` version 2 consumes the retained
  raw DOMSnapshot whose SHA-256 is
  `2483f0acb28b007205611df9bfa83ce194b37db2c834e05ff9b246cc959bacb0`.
  Its three oracle result counts and ordered-record digests are 142 /
  `34ead`, 1,551 / `aa7a`, and 91 / `40a7` respectively; the manifest and
  matrix retain the complete digests and first/last samples.

Several upstream URLs are rolling datasets. Repository commands therefore do
not download them. Materialization verifies the retained archive and every
expanded source before publishing the ignored materialized path:

```bash
python3 scripts/fixtures/materialize-document-locator-stress.py
python3 scripts/fixtures/verify-document-locator-corpus.py --require-advanced
```

Materialization is all-or-nothing and local. It does not overwrite an existing
directory; an existing destination must already match every pinned file. An
explicit `--archive` may select a relocated copy, but it must have the
canonical manifest digest. The v2 DOM output is generated from the retained
local snapshot and normalizer. This transformation does not launch a browser,
connect to CDP, or access the network.

See `advanced/ATTRIBUTION.md` for human-readable upstream notices. The same
license and attribution facts are required machine-readable fields on every
advanced manifest entry. The raw DOMSnapshot stays pinned separately from the
normalized DOM and AX representations.

## Benchmark contract

Every case keeps parse, locate, and end-to-end measurements separate. The
`document_locators` Criterion target registers these phases for the golden
HTML and rendered-DOM fixtures: parse the immutable document, locate against a
pre-parsed document, and parse plus locate. Fixture construction and plan
compilation are excluded from all three. The advanced WCAG DOM has an opt-in
parse-only case that reads the official normalized file and performs no browser
or CDP work. Advanced archive hashing, decompression, materialization, and
validation remain opt-in and must run serially under the repository
resource-safety rules. Default checks read only the tiny golden inputs and
metadata and stat the retained archive.
