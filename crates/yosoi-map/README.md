# `yosoi-map`

This crate helps discover and organize website addresses from links, sitemaps, robots files, and public sources. It checks which addresses fit the requested scope and records how they were found.

`yosoi-map` contains pure URL/host admission, bounded discovery-source
parsers, and deterministic graph-to-tree helpers. It does not own HTTP
execution. The public `yosoi::map` facade composes these values with existing
Requests, Direct HTTP, Documents, and Locators APIs.

Use the public consumer contract in [Yosoi Map](../../docs/map.md). This crate
is useful for policy-independent helpers and offline fixtures; applications
should call `yosoi::map::new(seed)` for the bounded operation.

## Components

- `admission` normalizes HTTP(S) URLs, preserves meaningful path/query
  differences, applies host/path scope and explicit exclusion filters, and
  returns typed rejection reasons.
- `sources` parses `YosoiMap` robots rules, XML/gzip sitemap documents, and
  `crt.sh` certificate-name JSON with explicit byte and entry bounds.
- `tree` derives a deterministic spanning tree from the retained page graph.
  It does not erase links or redirects in the graph.

The vendored Public Suffix List includes ICANN and PRIVATE rules. Its upstream
VERSION, commit, source URL, license, and digest are recorded at
[`data/public_suffix_list.dat`](data/public_suffix_list.dat). Refresh that
snapshot deliberately; a file name alone is not a version pin.

## Source and scope limits

The passive adapter uses the public `https://crt.sh/` JSON query and does not
provide active enumeration, DNS liveness probes, a provider plugin framework,
Go/Subfinder execution, or a claim of exhaustive hostname coverage. It does
not copy or adapt Subfinder source. The inspected upstream revision is recorded
in the consumer guide. The
repository has not pinned crt.sh usage terms, rate limits, or an SLA, so
provider behavior remains best-effort and must be rechecked before
high-volume operation.

The parsers and admission kernel have deterministic fixture tests. They do not
prove network cancellation, live provider coverage, or the public Yosoi
operation. See `crates/yosoi-engine/tests/map_end_to_end.rs` and the
[verification record](../../docs/archive/map-verification.md) for those evidence levels.
