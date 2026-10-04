# Parser and locator optimization baseline

Classification: attributable local optimization baseline. This is internal
evidence, not a public performance claim.

## Identity

- Yosoi source revision: `d9b64106568b02e4960988ac5f18887301c576c4`
- Benchmark Lab fixture: `cavemanCatalog.html`
- Fixture bytes: `87,928`
- Fixture SHA-256: `3a189573c0ab36b7e77b67a1a5b2a849133969c472067e16fae3f5c10ffcd4ef`
- Built artifact SHA-256: `01ac2b904e2b37e071b7bfbe312da52676752b886929962a3a8a849c83e7c8ba`
- Stripped artifact bytes: `5,080,624`
- Build tree bytes: `720,825,488`
- Five independent Criterion campaigns
- Per campaign: 3-second warm-up, 5-second measurement, 100 samples
- Cargo build jobs: one
- Every campaign used the public Rust `Document` and `Plan` path and returned
  exactly `USD 19.73` before timing.

## Current product baseline

Times are the median of the five campaign medians. Ranges are the minimum and
maximum campaign medians, not request-level tail latency.

| Phase | Median (microseconds) | Campaign range (microseconds) |
| --- | ---: | ---: |
| Parse and retained representation | 1,102.096 | 1,086.976-1,104.179 |
| Locate and materialize on a parsed document | 103.451 | 102.603-104.469 |
| End to end | 1,174.322 | 1,159.211-1,179.205 |

The frozen external headline remains Parsel at 608 microseconds for the same
caveman operation. The optimization candidate therefore needs to remove at
least 566 microseconds from this current end-to-end baseline to win, and about
870 microseconds to reach the aggressive 2x target of 304 microseconds.

## Attributed costs

The preceding isolated root-cause campaigns bound the largest costs:

| Diagnostic phase | Median of campaign medians (microseconds) |
| --- | ---: |
| Raw html5ever RcDom parse | 916.033 |
| Current Yosoi parse and secondary index | 1,098.556 |
| Current Yosoi locate and materialize | 127.598 |
| Rust scraper locate | 25.300 |
| Compact linked-tree end to end | 798.677 |
| Plan-specialized streaming end to end | 200.457 |

The current product first builds an RcDom, then walks and retains a second
element representation with eager normalized text and text segments. Locate
then lowers representation-specific query state, scans broadly, allocates
traversal state, clones attribute values, reconstructs coordinates, accounts
output bytes, and materializes provenance-bearing Findings.

The compact and streaming numbers are diagnostic lower bounds. They do not
count as product results until the production implementation passes the full
semantic corpus through the public API and is rerun by the independent
Benchmark Lab adapter.

## Candidate 1: rejected

Candidate revision `5986be09fd3309cca88b7f95bb631dc2cbb1e1b1`
replaced the RcDom plus secondary element payload with a custom arena, made the
HTML text index lazy, and cached decoded-text regex execution state. Its built
artifact SHA-256 was
`80ddcab774659af49aaa88fe149d23e365426616c6eb954dfa7f1f07ecca32e5`.

| Phase | Parent median (microseconds) | Candidate median (microseconds) | Candidate range (microseconds) |
| --- | ---: | ---: | ---: |
| Parse and retained representation | 1,102.096 | 1,172.259 | 1,130.047-1,192.914 |
| Locate and materialize | 103.451 | 113.659 | 105.470-159.376 |
| End to end | 1,174.322 | 1,374.627 | 1,314.269-1,596.723 |

The candidate was rejected. End-to-end median regressed by approximately 17%,
parse regressed by approximately 6%, and locate regressed by approximately
10%. The stripped artifact became 28,056 bytes smaller, which does not
compensate for the latency regression.

Independent review also found that the first custom TreeSink omitted
html5ever's customizable-select `selectedcontent` clone callback. That is a
real HTML5 semantic gap. The next candidate must implement the missing tree
behavior, add the corresponding regression corpus, remove redundant per-node
child vectors, and beat this frozen parent before promotion.

## Candidate 2: retained for further optimization

Candidate revision `cd1cacc1fc4319bc067829d775d7494c4c1ef727`
implemented the missing selected-content behavior, replaced per-node element
child vectors with one flattened buffer, cached compiled CSS/XPath plans, and
removed the common one-step selector's per-candidate traversal allocations.
Its built artifact SHA-256 was
`743af78578fc8bb16c122e0b75fa6f489eaa59a2276d25c05f4aa1d3c04edcbc`.

| Phase | Parent median (microseconds) | Candidate median (microseconds) | Candidate range (microseconds) |
| --- | ---: | ---: | ---: |
| Parse and retained representation | 1,102.096 | 854.975 | 843.785-865.361 |
| Locate and materialize | 103.451 | 33.259 | 32.770-35.570 |
| End to end | 1,174.322 | 977.748 | 965.695-1,012.555 |

Against the parent, parse improved by approximately 22%, locate by 68%, and
end to end by 17%. The stripped artifact was 5,063,872 bytes. The full
`yosoi-documents` suite and warnings-denied all-target Clippy passed before the
candidate was checkpointed.

The candidate is a useful foundation, not the milestone winner. It still takes
approximately 1.61 times Parsel's frozen 608-microsecond caveman median. A
five-sample hard-catalog smoke run returned the exact 64 values with a median
of 259.657 milliseconds, versus Parsel's frozen 143.600 milliseconds.

The next work therefore targets the remaining parser finalization overhead and
tests whether a private plan-adaptive evaluator can preserve the complete
public Finding contract. Event-only value extraction is not sufficient:
SourceTree coordinates, provenance, limits, ordering, and completion remain
admission requirements.

## Measurement boundaries still required

This first frozen product run establishes parse, locate, end-to-end, artifact
size, and raw distributions. Later family-specific campaigns must add:

- CSS, XPath, tree-text, literal, regex, capture, and XML rows;
- first-N, all-results, no-match, late-match, and repeated-plan stories;
- allocations and allocated bytes;
- retained bytes per document;
- peak and time-weighted average process-tree RSS;
- fixed-operation p95 latency;
- supported instruction, cycle, branch, and cache counters.

Those diagnostics remain separate from the unchanged caveman and hard-catalog
headline gates.

## Benchmark Lab V2 direction

The sealed V2 diagnostic bundle was produced from parent revision `d9b64106`
and confirms that HTML is the dominant optimization problem:

- large source-HTML end-to-end rows took 20.017-31.887 milliseconds across
  CSS, XPath, tree-text, and projection variants;
- exact HTML CSS text took 26.683 milliseconds versus rust-scraper at 17.123
  milliseconds;
- decoded-text literal, regex, and capture lanes were already approximately at
  their direct Rust controls;
- XML CSS/XPath lanes ranged from wins or near parity to narrower projection-
  specific losses, with no single universal XML deficit;
- query-build cost was small compared with HTML parse and evaluation, although
  caching remains important for repeated-plan latency and allocation.

Accordingly, the active headline work stays on source HTML parsing, selector
execution, and an exact private fast path. Decoded text is regression-protected,
and XML optimization remains a separate measured follow-up rather than being
mixed into the caveman result.

## Commands

The artifact was built with Benchmark Lab's `buildYosoiArtifact.py` from a
clean isolated checkout. Campaigns used `runCriterionCampaigns.py` against the
generated caveman fixture. Raw scratch evidence is retained under
`/tmp/cas471-baseline` for this active optimization run.
