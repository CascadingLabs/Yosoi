# Map page concurrency verification (CAS-533)

The SDK now uses `Policy.map.limits.max_concurrency`, default two, for page
acquisition as well as the existing public-provider phase. The CLI only maps
`--max-concurrency` to that Policy field. The phases run separately. Metadata
and redirect follow-up requests remain coordinated; batches overlap initial
page acquisition and commit link discovery in frontier order.

## QScrape live comparison

Three runs per case, alternating execution order, with frozen debug binaries and
identical depth5/request1000/deadline180s bounds. Public providers were disabled.

| Mode | Runs (seconds) | Median | Speedup over original |
| --- | --- | ---: | ---: |
| Original sequential | 22.27, 18.13, 18.26 | 18.26 s | 1.00x |
| New scheduler, concurrency1 | 21.23, 18.74, 18.85 | 18.85 s | 0.97x |
| Concurrency2 | 15.85, 15.45, 15.26 | 15.45 s | 1.18x |
| Concurrency4 | 13.57, 13.10, 12.30 | 13.10 s | 1.39x |

Concurrency two reduced median wall time by 15.4% against the original version
and 18.0% against the same new scheduler at concurrency one. Four reduced it by
28.3% and 30.5%, respectively. The earlier user run took23.101s; the comparison
uses the repeated fresh baseline, not that earlier observation. Live HTTP timing
varies; three samples per case do not establish a universal speedup. Metadata,
redirect follow-ups, parsing, and commits remain serial, and each batch waits for
its slowest member.

Every measured run returned exactly290 URLs,205 inspected pages,941 relationships,
218 requests and6,997,330 charged response bytes, with exhausted termination.
The benchmark compares exact URL/depth/exploration and relationship sets with
the baseline and rejects differences. All concurrent runs had zero unused page
prefetches. Request count and byte totals did not increase.

[Raw measurements and source/binary hashes](../evidence/map-concurrency/qscrape-2026-10-03.json).
Full Map manifests/stderr and frozen binaries remain under `.yosoi/map-concurrency/`
in the isolated workspace.

## Safety and speculative work

One coordinator owns scope, robots, queue, inventory and observations. Each
request reserves request count, response extent and trace inventory before
dispatch. Aggregate reservations cannot exceed remaining response capacity.
Metadata is loaded once per origin before page admission; redirects validate
each next URL before fetching and reuse already acquired terminal targets.
The coordinator accounts every admitted result, including unused prefetches.

The number of concurrent jobs is capped by the smaller of max_concurrency and
max_pending. Queue admission includes buffered, uninspected results. Deadline
and cancellation cancel child tokens and drain all started jobs before return.
The response-byte budget is not a promise of exact process peak RAM.

Concurrency can waste bounded work on early termination. A URL-limit fixture
with concurrency two returned one unused sibling prefetch after the first page
filled the inventory. Cancelling before inspection can leave the entire admitted
batch unused. `unused_page_prefetches` reports that explicitly; it is not a count
of all skipped or metadata-only URLs. Page concurrency peak records admitted
acquisition jobs; event fixtures separately prove actual overlap.

## Verification

Event-controlled cases passed for concurrency1/2/4, cancellation/deadline drain,
request/aggregate-byte reservations, deterministic capped inventory, redirect
reuse for HTML/non-HTML/404/converging targets, and rejected/terminal provider
probes. Existing Map E2E24, limits14, XML6 and audit5 passed. CLI Map14,
completions2 and policy_values5 passed; SDK unit checks passed including provider
budget regressions. Production Clippy passed with warnings denied (the existing
vendored CDP MSRV configuration warning remains). Builds/tests used one Cargo
worker and serial test threads. No full repository/browser suite or hosted CI
was run. Independent review findings on redirect/probe reuse and rejected-task
admission were fixed and re-reviewed.

## Reproduce

```sh
python3 scripts/map/benchmark-map-concurrency.py \
  --baseline .yosoi/map-concurrency/bin/baseline \
  --candidate .yosoi/map-concurrency/bin/candidate \
  --output .yosoi/map-concurrency/repeat --rounds 3
```

The default changes from four (provider-only concurrency) to two for both
phases. Explicit saved Policy values remain explicit and now also control page
acquisition. Setting one gives sequential acquisition. The Map API has no new
scheduler parameter; Summary exposes page peak and unused-prefetch counters.

## Default convergence

Andrew authorized convergence after reviewing the live comparison. The merge
preserves the newer public `yosoi-sdk` facade and Search work. Public SDK
authoring verifies default concurrency two and a Budget override of four; its
Map wrapper delegates to the existing engine, with no separate scheduler.
Merged checks passed Map concurrency6, CLI Map14, completions2, canonical
Policy values5 and public SDK2. The current merged default identity is
`v5 a340f9711e02d7c1c8218814a7d810e7dc1a1584fb659a03cc45cc202a99e924`;
benchmark identities belong to the frozen experiment source described above.

The final combined candidate, without a concurrency flag, completed QScrape in
16.095s at page peak2 and zero unused prefetches, with the same290 URLs,941
relationships,218 requests and6,997,330 bytes. All original/comparison/default
runs exit3 because QScrape links to a404 Cloudflare email-protection path; no
source failures or unfinished frontier appeared in the final smoke. This is an
existing failed-page classification, not a concurrency regression.

The merged public SDK needed a boxed HTTP future at the acquisition boundary to
keep caller trait checking within the normal compiler recursion limit. Its
authoring test checks the returned Map future is Send. One inherited Search
subtraction was made saturating under its existing positive guard to satisfy
the production arithmetic lint without changing behavior. Destination Clippy
and archived Policy round trips passed; final Map concurrency6, CLI14 and SDK2
passed after the async-boundary fix.

## Final project completion audit (2026-10-04)

The active goal explicitly authorizes default-workspace completion, main landing
and project closure. Later Map tickets supersede the original serial/default4,
CLI-deferred and feed-deferred scope. The current SDK/CLI use shared Policy
concurrency2, robots Ignore by default, and opt-in public-only passive discovery.

| Issue | Implemented boundary | Acceptance evidence |
| --- | --- | --- |
| CAS-451 | dedicated kernel, Policy, public SDK, snapshots/identity | Map/Policy/SDK consumer checks, compiling examples, Archive Policy round trips |
| CAS-512 | normalized URLs, scoped host/path admission, explicit filters | admission9, limits14, public/private suffix and encoding fixtures, documented decision table |
| CAS-513 | native passive observations, no Go/DNS scans/API keys | providers7, source12, provider budget/provenance/cancellation fixtures; anonymous live reports |
| CAS-514 | bounded frontier, graph/tree, robots/sitemaps, retention | E2E24, limits14, audit5; original-document reuse and seeded subtree controls |
| CAS-515 | integrated Requests/Documents composition and delivery audit | kernel/SDK/CLI checks, offline tuning example, bounded live inventories; remote landing verification recorded in Linear |
| CAS-528 | first-class CLI, JSON files and typed Document pipes, stats | Map CLI14, Request/Locate/profile/completion process checks, recorded PTY/pipe evidence |
| CAS-530 | XML/RSS/Atom, XML Base, optional versus declared sitemaps | XML6, independent QScrape root/news inventories and20 source article IDs |
| CAS-531 | four anonymous indexes, safely concurrent source lane | fixed public catalog, independent provider fixtures and event-controlled admission; live Anthropic223 hosts/no target HTTP |
| CAS-533 | policy-owned page concurrency2 and measured speed | concurrency1/2/4 fixture and repeated live comparison; identical URL/graph/request/byte inventories |

The final audit closed public SDK omissions: Robots, named provider/skip types,
wildcard provenance and request-trace accessors are available in SDK namespaces.
It also fixed multi-hop redirect inventory and duplicate intermediate GETs.
Every accepted hop is inventoried at its observed link depth, redirect facts are
reused before terminal alias state, all aliases receive the resolved exploration
state, and actually observed HTTP hosts are marked accordingly. Chain, authored
root, cached-alias provenance and shorter-path/no-refetch regressions passed.
Private Map checks now22; external Map checks58 (concurrency9/E2E24/limits14/
audit5/XML6). Production Clippy passed with warnings denied. The live stress
example handles the current Sampled and Skipped outcomes and all four Map/Tuning
examples compile; policy_tuning runs offline and locates Hello in Default mode.

Coverage boundaries remain explicit: index samples, upstream errors, scoped
published inventories, depth limits, and bounded speculative work. Browser-only
URLs, durable Crawl/resume, new index providers and llms.txt discovery remain
follow-up scope, not unfinished requirements of these nine issues.

The final landing executable covered all142 published QScrape URLs and all20
source news IDs, with290 inventoried URLs and no unfinished frontier. One
article request had a visible transient incomplete response, so203 pages were
inspected in that run; a focused follow-up mapping of that article succeeded.
The failure is preserved in the original report rather than overwritten.
