# Earlier Map SDK verification

This records the first SDK candidate. Follow-up XML/feed discovery and concurrent
public-provider evidence are in [Map discovery verification](map-discovery-verification.md).

# Map implementation verification

Date: 2026-10-03. Local Linux review candidate; not landed or release-certified.

## Implemented scope

Dedicated `yosoi-map` crate, ordinary `Policy.map` structs and v3 effective
identity, public async Map facade, safe URL/host admission with a pinned ICANN
and PRIVATE suffix list, explicit passive-only crt.sh discovery, bounded page
frontier, robots and XML/gzip sitemaps, link graph and authored-root tree,
partial/failed/not-started outcomes, typed omission counts, cancellation,
aggregate resource limits, and opt-in original Requests response reuse.
Map still reads robots metadata for sitemap declarations when enforcement is
ignored; `Robots::Ignore` is the default and `Robots::Respect` opts in to rules.

Source values remain unverified until page acquisition observes an HTTP response.
There is no active enumeration, target DNS probe, browser fallback, Go process,
content job, implicit Archive write, or durable resume promise.

## Local validation

All expensive checks ran serially with one Cargo worker and serial test threads.

| Gate | Evidence |
| --- | --- |
| Map kernel | 9 admission + 12 source + 4 tree tests passed |
| Public Map | 24 E2E cases passed, including default Ignore and explicit Respect |
| Independent audit | 5 canonical, off-host sitemap, absolute Map deadline, and earlier Request deadline cases passed |
| Map resources | 14 local resource/admission cases passed |
| Private host/probe behavior | 5 no-network host-cap/provenance/wildcard/disabled/cancelled cases passed |
| Facade library | 24 unit cases passed, including the 5 Map cases |
| Policy | 29 acquisition/snapshot/value/Map/robots/bound cases passed |
| Requests/Archive facade | 24 preparation/execution/cancellation/archive cases passed |
| Legacy run identity | Selected Archive v2/v3 reference mismatch test passed |
| HTTP crawler identity | Loopback wire-header + known environment test passed; optional tagged-profile serde test passed |
| Production lint | `cargo clippy --offline -p yosoi-map -p yosoi-policy -p yosoi --lib --no-deps -j 1 -- -D warnings` passed |
| Formatting | Focused rustfmt checks and diff whitespace checks passed |

The checks prove the selected local behavior, not the full repository, hosted CI,
browser coverage, deployment, or exhaustive internet discovery. Existing unused
browser test-helper warnings appeared in the selected web-capture serde test;
no browser was launched or changed.

Kernel, facade, public E2E, limits, independent audit, Policy, and production
lint were rerun after the robots/deadline changes. Requests/Archive and HTTP
bridge checks above are from the preceding candidate; those bridge paths were
unchanged in this follow-up.

Useful commands:

```sh
cargo test --offline -p yosoi --lib --test map_audit --test map_end_to_end --test map_limits -j 1 -- --test-threads=1
cargo test --offline -p yosoi-map -j 1 -- --test-threads=1
cargo test --offline -p yosoi-policy -j 1 -- --test-threads=1
cargo clippy --offline -p yosoi-map -p yosoi-policy -p yosoi --lib --no-deps -j 1 -- -D warnings
```

## Real-provider QA

A bounded public SDK passive run against `https://example.com/` completed with
one crt.sh request, 27,146 charged response bytes, six hostnames, and zero page
requests. Returned hosts were `example.com`, `dev.example.com`, `m.example.com`,
`products.example.com`, `support.example.com`, and `www.example.com`; all were
unverified. This was the initial pre-explicit-User-Agent source sample.

A later combined-mode run with the explicit Map agent returned a typed crt.sh
HTTP 502 and continued to inspect the example.com seed. It exhausted selected
work after five requests, reported one HTTP-observed host and one inspected
page, and kept the provider failure and conventional-sitemap 404 outcomes.
This proves failure isolation, not a positive combined-provider coverage sample.
A second combined-mode example.org sample also reported a provider transport
failure while retaining the inspected seed (five requests, 2,308 charged bytes).
The source is usable in the successful passive samples but live availability is
variable; no exhaustive coverage or service-reliability guarantee is claimed.

A final passive run with the explicit Map agent against `https://example.org/`
completed after one request and 18,947 charged response bytes. It returned three
unverified hosts (`example.org`, `www.example.org`, and
`www.testdomain.example.org`) and zero pages. Provider results vary with freshness
and service availability; a successful query is not a provider SLA or exhaustive
subdomain certification.

## Live stress evidence

The current SDK and harness source revision is
`5be7256f563ff3ff07242ab83095aa1efbc8d7a5`. Exact JSONL policies, digests, limits,
request targets/statuses/charges, source failures, and outcomes are retained in
[live evidence](../evidence/map/live-2026-10-03.jsonl). The
[manifest](../evidence/map/live-2026-10-03-manifest.json) records the development
executable SHA-256, platform, compiler, packages, and validation scope.

All ten cases ran serially. Nine passed their scope/resource and case-specific
gates. Yahoo failed its required inspected-page gate, as recorded below.

| Case | Requests | URLs | HTML link edges | Stop | Elapsed |
| --- | ---: | ---: | ---: | --- | ---: |
| QScrape root | 100 | 218 | 413 | Requests limit, 19 pending | 11.7 s |
| QScrape news subtree | 21 | 19 | 43 | Selected work exhausted | 3.1 s |
| QScrape shop subtree | 23 | 21 | 55 | Selected work exhausted | 2.7 s |
| QScrape larger frontier | 178 | 250 | 636 | Selected work exhausted | 20.4 s |
| QScrape query filter | 100 | 218 | 413 | Requests limit | 9.8 s |
| QScrape news, robots respected | 4 | 8 | 0 | Seed skipped without dispatch | 0.4 s |
| Yahoo root | 7 | 3,995 | 0 | Observations limit before seed inspection | 2.7 s |
| example.org passive | 1 | 0 | 0 | Provider 502 preserved | 0.5 s |
| example.org combined | 5 | 1 | 0 | Provider 502, seed inspected | 0.7 s |
| Rust book subtree | 16 | 15 | 50 | Selected work exhausted | 4.3 s |

The larger owned-site run inspected 157 pages and charged 4,824,630 response
bytes. Its 500-request/5,000-URL limits are caps, not work artificially generated
to consume them. All actual dispatches stayed in scope, traces matched request
counts and charged totals, and retained/document/inventory bounds held. The
filter sample encountered no matching utm_source URL: it proves bounded execution,
while the deterministic fixture proves that exclusion actually filters a match.

Robots enforcement defaults to Ignore; metadata is still read for sitemaps.
The paired Respect sample confirms the disallowed news seed was not fetched.
QScrape's conventional sitemap URLs returned HTML and failed XML parsing; its
robots-declared sitemap completed. A 404 page and valid non-HTML inspection skips
remain visible rather than being erased.

Yahoo first hit a 500-URL cap after four metadata requests; with 5,000 URLs it
hit the independent 4,000-observation cap. Support inventory runs before page
inspection and can consume a global budget. The returned seed remains pending:
this is bounded partial inventory evidence, not successful Yahoo HTML mapping.
No live browser or Yahoo content coverage is claimed.

The current passive and combined cases prove provider-failure isolation and
bounds, not positive provider coverage. Earlier successful passive samples above,
and a positive combined sample on `dd1371f2`, establish the actual provider path:
the combined sample used a 30-second Request / 60-second Map deadline, 20 requests,
10 hosts, registrable-domain scope, and link depth zero. It completed crt.sh and
inspected both example.org and www.example.org after 12 requests and 23,563 charged
bytes; the third host stayed unverified after transport failures. Provider
availability and returned names remain variable.

The live QScrape homepage originally exposed unsupported CSS token-selector syntax.
Canonical detection now uses supported attribute selectors with Rust rel-token
matching; a regression covers case-insensitive multiple tokens. Independent
fixtures also caught and fixed an absolute Map timeout misclassified as a byte
limit. Both fixes passed the focused suites before these live runs.

## Focused Rust benchmark

Command: `cargo bench --offline -p yosoi-map --bench discovery --profile dev -j 1`.
In one unoptimized dev-profile run, 10,000 normalize/admit operations took
76.801288 ms and 10,000 small XML sitemap parses took 44.232322 ms. These are
small reproducible helper measurements, not release throughput, network latency,
peak-memory bounds, or a comparison against Subfinder.

## Default integration and final live pass

Andrew requested convergence into default and Ready to land on 2026-10-03.
The current integration lives in `/home/andrew/Desktop/cl/YosoiOxide`, JJ change
`unzvkkzl`, bookmark `map-sdk-default-review`, atop CLI UX revision `76aacbd7`.
The reviewed Map paths were integrated without reverting the current CLI,
Search design, lockfile, or newer Requests bridge changes. The original isolated
candidate remains preserved at `map-sdk-reviewed` (`42e51313`).

The integrated default tree passed 43 public Map tests (24 E2E, 14 limits,
5 independent audit) and all 72 CLI tests (27 unit, 45 process), including Map
profile resolution and Request-to-Locate pipelines. Focused production Clippy
for Map/Policy/facade/CLI passed with warnings denied. The shared Search candidate's
three induced fixture conflicts were resolved separately, retaining both Search
fields and robots Ignore; its 13 focused Policy fixture checks passed.

A fresh default build ran QScrape News successfully: 21 requests, 19 URLs,
43 HTML-link relationships, selected work exhausted, and all harness invariants
passed. A real CLI Request-to-Locate pipe against the same seed matched `a[href]`
with both processes returning zero and empty stderr. The query `h1` returned a
legitimate NoMatch on this seed. No browser was launched. Exact default source,
executable hashes, test scope, and outputs are retained in the
[default smoke manifest](../evidence/map/default-smoke-2026-10-03-manifest.json),
[Map JSONL](../evidence/map/default-smoke-2026-10-03.jsonl), and
[CLI JSON](../evidence/map/default-cli-smoke-2026-10-03.json).

The earlier larger matrix above remains exact evidence for its recorded isolated
source, not the default tree. Independent review confirmed that its Map code and
harness paths match the integrated paths; the fresh default checks and smoke
provide the integration evidence. Yahoo coverage and passive-source availability
limitations remain as recorded above.

Map changes effective Policy identity from v2 to v3. Older Policy JSON without
Map reads as current defaults; archived run references carrying v2 identities
are rejected rather than silently relinked. Prior Map profile JSON without
`robots` resolves to Ignore. The subsequent CAS-528 adds a first-class
[Map CLI](../cli-map.md) using the same Policy and Document-stream conventions;
its separate verification records below cover that command.

The Map issues are Ready to land at Andrew's request. The next owner is Andrew
for a final joint SDK/CLI live pass. CAS-503 remains a separate unlanded dependency
in Final Boss. This is local default-workspace convergence; no remote main push,
PR merge, hosted CI certification, or project completion is claimed.

## First-class Map CLI

CAS-528 supplies `yosoi map` with the existing CLI file/Document pipe framework.
Its [separate verification](cli-map-verification.md) records CLI process checks,
PTY behavior, exact live output and default-workspace integration. The earlier
SDK-only review evidence above remains tied to its recorded source revisions.
