# Parser and locator optimization results

Classification: locally landed implementation with a current-artifact smoke.
The final cross-library performance claim awaits the Benchmark Lab run on the
lab PC. This document is not a public speed claim.

## Plain English

Yosoi now avoids building a retained HTML tree when a private, fail-closed
certificate can prove the same result. The reviewed parser code is in the clean
default workspace. A short local run from its exact artifact returned the
frozen Caveman value and all 64 hard-catalog values in order; it measured
0.093 ms and 7.871 ms end to end, respectively. Those are Yosoi-only smoke
measurements. The final competitor and resource comparisons will run on the
lab PC.

## Current local landing evidence

- Yosoi source revision: `b72e01e83743b4497886bac66ddb23846f6fcf51`.
- Clean default child: `64149142`; the browser/docs work is preserved at
  `ee3c9828` for the next phase.
- Built pure-Rust artifact SHA-256:
  `36d050549731535914e8d559b5b413f78efb007c0166c1f383cd20b66778c981`
  (`5,315,576` bytes).
- The frozen Caveman and hard-catalog fixture SHA-256 digests below still match
  the generated local fixtures.
- One local Yosoi-only campaign: 10 Caveman samples at ten operations per
  sample, three hard-catalog samples at one operation per sample. Exact output
  preflight and every measured phase passed. End-to-end medians were 0.093 ms
  and 7.871 ms; cold Caveman process time was 2.739 ms.
- This short campaign establishes a current-artifact regression smoke, not a
  current Parsel speedup, valid campaign p95, RSS claim, or release certification.

The separate Benchmark Lab can regenerate the fixture and artifact using
`tools/generateFixtures.py` and `tools/buildYosoiArtifact.py`, then run the
Yosoi arm of `tools/runMatrix.py`. Its final five-campaign V1/V2 comparison is
reserved for the lab PC.

## Historical comparison identities

The earlier V1 comparison used a different pure-Rust artifact. Its results do
not certify the current source revision:

- Production revision: `55510ba0a75c5cb84073e56945394423053ee512`
- Artifact SHA-256:
  `c35e7c33ee2c1098dcdb4c54563ea24db14c89a1e2d1526d293483296dec2fe3`
- Artifact bytes: `5,309,952`
- Caveman fixture: `87,928` bytes, SHA-256
  `3a189573c0ab36b7e77b67a1a5b2a849133969c472067e16fae3f5c10ffcd4ef`
- Hard catalog: `17,186,672` bytes, SHA-256
  `139ee57c396ae07c3910295e705fcacb79b08b6a8faf74813e443e494bb6a163`
- Protocol: five counterbalanced campaigns; 100 Caveman samples with ten
  operations per sample; 30 hard-catalog samples with one operation per sample.

The earlier V2 matrix also used an immutable source archive and a different
artifact. Its family-specific results remain diagnostic history:

- Source revision: `53d4a655196c687a31cad14f5cba63693aa324aa`
- Artifact SHA-256:
  `e0b03c1fc7173d9fc49e27cc1f3ffcc0a34d86e5703c2ca6541f1b642e1f13ec`
- Source archive SHA-256:
  `21f5a07ce61c1f3afcbc0dd492ceff9ce4b48c2141e87e549f27d29581ca28b6`
- Matrix: 36 cells, 3,105 records, five campaigns.

## Historical V1 comparison

These are medians of five campaign medians from the earlier `55510ba0a` run.
Both arms passed its exact ordered-output gate; the comparison must be rerun
for `b72e01e8` on the lab PC.

| Workload | Yosoi | Parsel | Yosoi speedup | Yosoi campaign range |
| --- | ---: | ---: | ---: | ---: |
| 87.9 KB Caveman end to end | 0.0724 ms | 0.6007 ms | 8.30x | 0.0611-0.0953 ms |
| 17.2 MB hard catalog end to end | 8.216 ms | 143.039 ms | 17.41x | 7.735-8.518 ms |

The hard-catalog p95 was 11.61 ms for Yosoi and 154.91 ms for Parsel. Cold
Caveman process time was 2.32 ms versus 64.57 ms. The hard resource pass
measured 39.6 MiB peak and 28.2 MiB mean RSS for Yosoi, versus 344.5 MiB peak
and 232.8 MiB mean RSS for Parsel: 8.70x lower peak and 8.27x lower mean RSS.

The benchmark adapters hold the fixture bytes in memory, so this is not a
network-streaming claim. “Streaming” here means the parser/locator evaluates
the immutable source without first materializing the retained HTML5 tree.

The critical hard-catalog fix was not a looser safety rule. The old path counted
every `span` as a possible `span.price` match and treated attribute byte length
as attribute count. That conservative proof exceeded the selector-work budget
after scanning the whole document, discarded the scan, and reparsed the entire
tree. Large-document record certification now parses selector-relevant
attributes exactly, so the same budget proof succeeds without the second parse.

## Historical V2 diagnostics

The earlier `53d4a655` artifact passed 8/8 negative fixtures and 30/30
conformance cases.
On the 1.36 MB large HTML fixture, exact CSS and XPath end-to-end cells compared
with Rust `scraper` were:

| Cell | Yosoi | Speedup |
| --- | ---: | ---: |
| CSS attribute | 1.447 ms | 9.70x |
| CSS node | 1.160 ms | 12.10x |
| CSS text | 1.248 ms | 11.95x |
| XPath attribute | 1.021 ms | 13.84x |
| XPath node | 1.400 ms | 10.46x |
| XPath text | 1.185 ms | 12.72x |

The tree-text control is `nearestPrimitive`, not equivalent text-contains
semantics, so its 8.69x node and 4.52x text ratios remain internal diagnostics,
not competitor claims. Large decoded-text speedups were 2.27x for literal,
1.19x for regex text, and 2.57x for captures. XML is not universally ahead:
the six large CSS/XPath cells range from 0.81x to 1.77x. Those results remain
open optimization work rather than being averaged into a misleading headline.

## Private routing model

The correct decision unit is the combination of three private inputs:

1. Immutable document facts: class, byte length, and structural hazards.
2. Compiled-plan requirements: selector shape, projection, ancestry, regions,
   and other semantics that require a particular evaluator.
3. Per-call budget: match, node, depth, output, and selector-work limits.

The current implementation has direct streaming plus bounded record
certificates and retained-tree fallback. The record certifier computes metrics;
it is not yet a true retained HTML5 “hybrid island” parser. The intended routes
are:

- **Direct stream:** statically eligible plan and document-wide preconditions;
  return only after a complete exact equivalence and resource proof.
- **Certified stream:** stream the document while proving bounded skipped or
  repair-sensitive records cannot change coordinates, output, order, or limits.
- **Hybrid island (future):** parse a bounded region with the retained HTML5
  algorithm and reconcile it with the surrounding stream.
- **Retained tree:** authoritative fallback whenever any proof is incomplete.

Plan compilation is already privately cached. Document facts are still
recomputed per locate call; a private `OnceLock<HtmlDocumentFacts>` is the next
structural step. It must be derived only from immutable bytes, excluded from
serialization, equality, debug output, requirements, and the public SDK. Route
selection may use cached document facts, but plan/document/budget certification
must remain per call.

The 1 MiB exact-selector-metrics boundary is a performance threshold, not a
semantic boundary. Below it, safe upper bounds may choose retained fallback;
at or above it, deferred records use exact selector accounting. Neither path
may return a streaming result without a complete proof.

## Correctness and adversarial boundary

- The complete `yosoi-documents` suite passed at the landed source revision;
  three advanced external-corpus cases remain explicit opt-in ignores.
- The pinned 15.6 MB WHATWG HTML oracle passed as an opt-in test through both
  the retained tree and public `Document::locate` route.
- Warnings-denied all-target Clippy, formatting, the public Yosoi document
  matrix (3/3), and archive evaluation tests (4/4 executed; 3 ignored) passed.
- Frozen Caveman and hard fixtures both passed direct-versus-retained
  differential checks, including low node, depth, selector-work, match, and
  output budgets.
- Adversarial HTML coverage includes repair boundaries, adoption-agency
  formatting, table foster-parenting, foreign content, raw text, duplicate
  attributes, malformed EOF, comments, entity fallback, multiplicity,
  absence, coordinates, and resource-limit edges.
- A cross-document test applies the same two-step CSS plan to source HTML,
  source XML, and rendered DOM and compares direct with parsed results. The
  same plan is rejected before parsing for source JSON, decoded text, and
  accessibility documents.
- V2 negative suite: 8/8. V2 conformance suite: 30/30. Full V2 matrix: 3,105
  correctness-gated records, all on the earlier V2 artifact.
- `Document`, `Plan`, and `LocateOutcome` calls and their wire/serde shapes are
  unchanged. `ParsedHtmlDocument::node_count()` now counts every allocated
  parser arena slot, including detached repair clones; its Debug label states
  that meaning. This is the narrow observable breaking boundary of the compact
  tree change.
- Every parser/locator production file is below the repository's 400-line
  target. The repository-wide source-size command still reports twelve
  inherited violations outside this parser/locator change; it is not green.

## Deferred experiments and certification

1. Run the unchanged five-campaign V1 and relevant V2 cross-library matrix on
   the lab PC from immutable artifacts, retaining correctness gates, resource
   records, exact identities, and independent raw-bundle review. CAS-489 owns
   that certification and the final Beta performance claim.
2. Complete candidate-bound allocation, retained-byte, supported hardware
   counter, and exact-command attribution for CAS-475. Unsupported counters
   must be reported as unavailable.
3. Consider replacing the coarse 1 MiB performance threshold with a two-stage
   proof:
   attempt cheap aggregate bounds, then recompute exact record metrics only
   when those bounds would reject an otherwise eligible document.
4. Consider caching private immutable `HtmlDocumentFacts`; keep route selection
   distinct from final plan/document/budget certification.
5. Implement a real bounded `HybridIsland` only with forced-retained
   differential oracles for boundaries, coordinates, resource accounting, and
   late fallback. Until then, call the current path certified streaming.
6. Evaluate Caveman variance and the remaining XML, decoded-text, and
   tree-text cells by family. The earlier V2 numbers cannot be carried forward
   as current artifact results or averaged into one score.
7. Add candidate-bound 100 MB and 1 GB scale ladders only after the router is
   profiled for fallback rate and late-reject cost.

## Decision

The reviewed implementation is locally landed in a clean default workspace.
The current release artifact passes exact-output local smokes for both frozen
fixtures, and the hard catalog remains on the certified fast path. CAS-489 and
the public comparison remain open until the lab-PC campaigns and independent
evidence review. The cache, true hybrid island, larger scale ladders, and
family-specific improvements are explicit future work rather than claims of
this landing.
