# CAS-394 document and locator certification

## Decision

The CAS-449/CAS-450/CAS-400 candidate is correct and bounded for the 15
promised document/locator pairs. Ordinary callers use representation-named
`Document` constructors, `Plan::new`/`output`, and `parse`/`locate`; resource
caps remain useful Policy defaults but are absent from ordinary ceremony and
Plan serialization. Measurements are descriptive local baselines, never
performance budgets. Live browser acquisition and request execution are
outside this certification.

## Certified boundary

- Public entry point: `yosoi::prelude`; the ordinary surface is `Document`
  constructors, `Plan::new`/`output`, and `parse`/`locate`.
- Documents: decoded text, JSON, source HTML, XML, canonical rendered DOM v1,
  and canonical accessibility tree v1.
- Correctness authority: 15 golden cases and 15 advanced cases in
  `benchmarks/fixtures/document-locators/v1/matrix.json`.
- Advanced archive: 8,422,863 bytes, SHA-256
  `4a292b3d6242f2d85109ab37675002604a60f04d02b0bf9430f2dc1e67992ffc`.
- Generated rendered DOM v2: 3,598,116 bytes, SHA-256
  `318a9d66f3f5a12d27b309e754c8d94f11aad633ceee80351f941aea18277d14`.

The offline verifier hashes the retained archive and every member, checks schema
versions, and recomputes exact ordered values, coordinates, match counts,
identities, and completeness. Advanced HTML is independently replayed through
network-disabled lxml, including SVG adjusted-name paths; DOM/AX/JSON/XML/text
use their independent normalized or parser-native oracle paths.

## Correctness and policy gates

| Gate | Result |
| --- | --- |
| Public facade golden matrix | 15/15 cases, region lineage, and unsupported-pair rejection passed |
| `yosoi-documents --all-targets` | 83 passed; 3 explicit advanced opt-in tests ignored |
| Policy and facade tests | 17 `yosoi-policy` tests and 11 `yosoi` tests passed |
| Repository benchmark contract | 14/14 tests passed |
| Advanced offline verifier | passed all 15 advanced cases and self-tests |
| Warnings-denied Clippy | passed for `yosoi-policy`, `yosoi`, `yosoi-documents`, and the lightweight benchmark crate |
| Formatting and diff checks | passed |
| Production source-size ratchet | passed; no new exception |
| Architecture | `yosoi` directly depends on `yosoi-documents` and `yosoi-policy`; the document engine remains policy/request/capture independent |

## Current CAS-450 Criterion baseline

Criterion 0.7 quick sampling ran serially from exact-current optimized binaries
with one Cargo job. Current harnesses measure parse-only, locate-only, and
end-to-end work. The removed public compile and materialization phases appear
only in the historical CAS-400 table below.

| Document / phase | Fixture | Time |
| --- | --- | --- |
| Decoded text parse | golden orders | 12.266–12.275 ns |
| Decoded text locate | golden orders | 37.181–38.254 µs |
| Decoded text end-to-end | golden orders | 38.847–39.678 µs |
| Decoded text parse | advanced WHATWG text | 94.889–95.646 µs |
| Decoded text locate | advanced WHATWG text | 103.65–104.36 µs |
| Decoded text end-to-end | advanced WHATWG text | 205.24–210.16 µs |
| JSON parse | golden product | 671.02–697.32 ns |
| JSON locate | golden product | 729.81–755.63 ns |
| JSON end-to-end | golden product | 1.7266–1.8003 µs |
| XML parse | golden catalog | 1.1602–1.1801 µs |
| XML locate | golden catalog | 2.0411–2.1349 µs |
| XML end-to-end | golden catalog | 3.3734–3.5418 µs |
| AX parse | golden accessibility tree | 1.1494–1.1602 µs |
| AX locate | role/name/text/state | 464.38–742.34 ns |
| AX end-to-end | role/name/text/state | 1.7987–2.0236 µs |
| Source HTML parse | golden products | 7.3370–7.6654 µs |
| Source HTML locate | golden products | 861.21–869.71 ns |
| Source HTML end-to-end | golden products | 8.2020–8.6357 µs |
| Rendered DOM parse | golden products | 3.1242–3.2418 µs |
| Rendered DOM locate | golden products | 384.68–385.08 ns |
| Rendered DOM end-to-end | golden products | 3.5800–3.6689 µs |
| Rendered DOM parse | advanced WCAG DOM | 16.052–16.191 ms |

## Current CAS-450 allocation baseline

Divan 0.1.21 used `--sample-count 10 --min-time 0.01`. “Max live” is
the maximum simultaneously live allocation count and bytes; “total” is the
allocation count and allocated bytes for one end-to-end golden location.

| Document | Max live | Total allocations |
| --- | --- | --- |
| Decoded text | 158 / 332.4 KB | 529 / 372.0 KB |
| JSON | 37 / 3.890 KB | 54 / 4.422 KB |
| Source HTML | 65 / 8.019 KB | 108 / 10.52 KB |
| XML | 30 / 4.438 KB | 45 / 6.283 KB |
| Rendered DOM | 32 / 2.960 KB | 75 / 6.902 KB |
| Accessibility tree | 21 / 2.050 KB | 34 / 3.167 KB |

## Current CAS-450 fresh-process RSS

Exact-current optimized binaries ran separately under GNU `/usr/bin/time -v`.
Criterion binaries used their one-run test mode; Divan used `--test`. Every
process exited zero, reported zero swaps, and ran with no browser/capture work.

| Harness | Peak RSS |
| --- | --- |
| Decoded text + advanced WHATWG | 18,148 KiB |
| JSON | 17,940 KiB |
| XML + AX | 18,576 KiB |
| HTML + rendered DOM + advanced WCAG DOM | 33,944 KiB |
| Allocation harness | 18,116 KiB |

## Criterion baseline (historical)

Criterion 0.7 quick sampling was run serially with one Cargo job. Times are the
reported estimate intervals on this host.

| Document / phase | Fixture | Time |
| --- | --- | --- |
| Decoded text plan compilation (historical phase) | golden orders | 100.69–102.71 ns |
| Decoded text parse | golden orders | 10.011–10.117 ns |
| Decoded text locate | golden orders | 36.435–36.499 µs |
| Decoded text result materialization (historical phase) | golden orders | 144.71–145.11 ns |
| Decoded text end-to-end | golden orders | 36.261–36.486 µs |
| Decoded text parse | advanced WHATWG text | 97.017–98.837 µs |
| Decoded text locate | advanced WHATWG text | 103.11–103.39 µs |
| Decoded text end-to-end | advanced WHATWG text | 201.21–202.07 µs |
| JSON parse | golden product | 613.76–631.20 ns |
| JSON locate | golden product | 553.54–568.50 ns |
| JSON end-to-end | golden product | 1.3761–1.3766 µs |
| XML parse | golden catalog | 1.0195–1.0211 µs |
| XML locate | golden catalog | 1.8183–1.8189 µs |
| XML end-to-end | golden catalog | 3.4244–3.4427 µs |
| AX parse | golden accessibility tree | 1.0880–1.0944 µs |
| AX locate | role/name/text/state | 437.53–597.16 ns |
| AX end-to-end | role/name/text/state | 1.6422–1.8042 µs |
| Source HTML parse | golden products | 6.4778–6.7355 µs |
| Source HTML locate | golden products | 776.84–779.79 ns |
| Source HTML end-to-end | golden products | 7.6292–7.6598 µs |
| Rendered DOM parse | golden products | 2.8956–2.9091 µs |
| Rendered DOM locate | golden products | 347.01–353.96 ns |
| Rendered DOM end-to-end | golden products | 3.3566–3.3875 µs |
| Rendered DOM parse | advanced WCAG DOM | 12.012–12.528 ms |

## Allocation baseline (historical)

Divan 0.1.21 used its system allocator profiler. “Max live” is Divan's maximum
simultaneously live allocation count and bytes; “total” is allocations and
allocated bytes for one end-to-end golden location at the measured revision.

| Document | Max live | Total allocations |
| --- | --- | --- |
| Decoded text | 158 / 332.4 KB | 529 / 372.0 KB |
| JSON | 37 / 3.890 KB | 44 / 3.996 KB |
| Source HTML | 65 / 8.019 KB | 108 / 10.52 KB |
| XML | 30 / 4.438 KB | 45 / 6.283 KB |
| Rendered DOM | 32 / 2.960 KB | 75 / 6.902 KB |
| Accessibility tree | 21 / 2.050 KB | 34 / 3.167 KB |

## Fresh-process RSS (historical)

Each optimized benchmark binary was started separately under GNU `time -v`
with quick fixture verification. Peak RSS includes runtime and fixture setup.

| Harness | Peak RSS |
| --- | --- |
| Decoded text | 17,524 KiB |
| JSON | 17,868 KiB |
| XML + AX | 17,888 KiB |
| HTML + rendered DOM | 18,124 KiB |

## Environment and commands

- Current candidate JJ change: `utpluxnsksss` (`documents-locators-sdk-cleanup`).
- Historical CAS-400 candidate: `wronlsnnyypp`.
- Rust: `rustc 1.98.0 (88d9e12ae 2026-08-18)`, LLVM 22.1.8.
- Host: Linux 7.2.5-3-omarchy, x86-64.
- CPU: AMD Ryzen AI 9 HX 370, 12 cores / 24 threads, 24 MiB L3.
- Memory: 30 GiB physical; all commands used `CARGO_BUILD_JOBS=1` and ran
  serially. Current measurement classes ran with zero swap after a host restart.
- Criterion command shape:
  `cargo bench -p yosoi-document-locator-benchmarks --bench <target> -- --quick --noplot`.
- Advanced inputs were selected only with
  `YOSOI_DOCUMENT_LOCATOR_ADVANCED_DIR=<verified materialized directory>`.
- Allocation command:
  `cargo bench -p yosoi-document-locator-benchmarks --bench allocation_document_locators -- --sample-count 10 --min-time 0.01`.
- RSS command: optimized benchmark binary under `/usr/bin/time -v`.

## Validation boundary and successors

The first monolithic `yosoi-benchmarks` contract build was stopped when swap use
grew during unrelated browser/capture dependency compilation. Document
benchmarks were moved into the lightweight
`yosoi-document-locator-benchmarks` workspace member, then compiled, linted,
and measured independently. After dependency caching, the repository benchmark
contract also completed: 14/14 tests passed. This is a cleaner dependency
boundary, not substitute evidence from another target.

Plan construction remains validated and portable, but CAS-450 intentionally has
no public compile phase. Result creation is part of locate and is no longer a
separate public materialization phase. Historical rows remain above only to
show the prior measured boundary.

Future work may add PyO3 pressure tests, expanded region composition,
streaming/paging, and request/archive/distributed lifecycle wiring. Those are
not part of this static document-locator certification.
