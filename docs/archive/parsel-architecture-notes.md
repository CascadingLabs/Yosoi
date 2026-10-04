# Parsel architecture notes

Classification: read-only competitor architecture study. No Parsel source is
copied into Yosoi.

## Source identity

- Repository: `https://github.com/scrapy/parsel`
- Inspected revision: `9f353b99d81778b1dc97e99c1e5f0afab48340a4`
- Reported package version at that revision: `1.12.0`
- Inspection date: 2026-09-27

## What actually makes Parsel fast

Parsel's measured HTML path is not predominantly Python parsing or selector
execution. It is a thin Python API over lxml, whose parser and XPath engine are
implemented by native libxml2/libxslt code.

The relevant pipeline is:

1. Normalize the input boundary in Python.
2. Parse with lxml's HTML parser using recovery and huge-tree mode.
3. Translate CSS into XPath with `cssselect`.
4. Compile and cache the XPath expression.
5. Execute XPath in the native lxml engine.
6. Wrap the returned nodes or scalar values in lightweight Selector objects.

Parsel maintains a per-translator CSS-to-XPath cache of 256 entries and a
process-wide compiled XPath cache of 2,048 entries. XPath smart strings are
disabled. The Benchmark Lab arm reuses the parsed document for locate-only
measurements, while end-to-end constructs a fresh Selector and runs CSS.

## Work Parsel does not perform in the headline

The frozen Benchmark Lab output oracle proves the extracted values. It does not
make Parsel construct Yosoi's complete result contract. Parsel does not emit:

- a versioned HTML5 parser profile;
- Yosoi SourceTree coordinates;
- document and output identities on every finding;
- region lineage;
- explicit completeness;
- selector-visit, match, node, depth, or output-byte accounting;
- typed Yosoi failure outcomes;
- retained provenance-bearing Findings.

Its HTML input behavior also differs. The current implementation uses lxml
recovery, enables libxml2 huge-tree mode by default, strips surrounding input,
removes NUL bytes, and can retry decoded text with replacement characters for
some invalid byte sequences. Those are useful ergonomic choices, but they are
not Yosoi's strict UTF-8 and bounded HTML5 contract.

## Lessons for Yosoi

The reusable lessons are architectural, not language-specific:

- Compile queries once and keep the executable form close to the authored plan.
- Make CSS and XPath share one optimized execution substrate where semantics
  genuinely align.
- Keep hot evaluation in compact native data structures with minimal wrapper
  allocation.
- Separate parse, compiled-query construction, locate, and materialization so
  the expensive phase is visible.
- Do not rebuild general query machinery during every locate.

Yosoi candidate 2 already applies the first and last lessons: its caveman
locate-and-materialize median fell from 103.451 microseconds to 33.259
microseconds. Parsing and final result semantics now dominate the remaining
gap.

The wrong lesson would be to reproduce Parsel's value-only boundary, relax
Yosoi limits, adopt recovery differences, or hide provenance work. The target
is to beat the native libxml2-backed path while continuing to return the full
Yosoi result contract.
