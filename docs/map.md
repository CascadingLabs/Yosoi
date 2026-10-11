# Yosoi Map

Status: implemented public SDK and Policy contract. Local E2E, resource, kernel,
and Policy checks are recorded in [Map verification](archive/map-verification.md).
This is a review candidate; it has not been landed or release-certified.

Map starts at one HTTP(S) URL. In Explore mode it follows admitted HTML links
and reads same-origin robots and sitemap metadata. Robots allow/disallow
enforcement is opt-in with `Robots::Respect`; the default `Robots::Ignore`
continues page inspection without those rules. It returns page and host
inventories, source observations, graph relationships, a derived tree, and
unfinished work when a bound or cancellation stops exploration. Results
describe what this bounded run observed; `Exhausted` does not mean that every
URL on a site was found.

The public operation lives in `yosoi`; URL and host admission, source parsers,
and pure result helpers remain private under `crates/yosoi/src/internal/map`.
Map uses the existing Requests and Documents paths. It does not start a browser,
persist to Archive, or create a durable crawl job.

## Use the public operation

`Policy` is ordinary Rust data. Start with installed defaults and replace the
Map values you need:

```rust
use yosoi::prelude as ys;

let policy = ys::Policy {
    map: ys::policy::Map {
        scope: ys::policy::Scope {
            hosts: ys::policy::HostScope::RegistrableDomain,
            ..Default::default()
        },
        subdomains: ys::policy::Subdomains::Passive,
        ..Default::default()
    },
    ..Default::default()
};

let outcome = ys::map::new("https://example.com/docs/")
    .bind(&policy)
    .send()
    .await?;

for page in outcome.pages() {
    println!("{} {:?}", page.url, page.exploration);
}
```

`new()` and `bind()` only prepare values. `send()` performs HTTP requests. The
public example at [`crates/yosoi/examples/map.rs`](../crates/yosoi/examples/map.rs)
shows seed-host, passive-host, and combined policy authoring. Running it makes
requests to the supplied site and, in passive modes, to the configured
Certificate Transparency source.

Map checks the effective page policy before I/O. It requires one Direct HTTP
acquisition with a Response Document and rejects browser, multiple, or
incompatible acquisitions. General Policy still permits browser page choices;
Map does not.

The seed URL and cancellation token are operation inputs, not Policy fields.
Seed credentials are rejected. Policy contains no provider credentials,
callbacks, client objects, or live execution state; seed URLs are not included
in the effective Policy identity.

Use `send_cancellable(&token)` for caller cancellation. A rejected seed,
invalid policy, or unsupported acquisition returns `MapError` before network
work. Once execution starts, source errors and limits are represented in the
returned partial `MapOutcome`; inspect `termination()`, `sources()`, and
`frontier()`.

## Policy defaults and scope

`Policy::default().map` uses:

| Field | Default | Meaning |
| --- | --- | --- |
| `scope.hosts` | `SeedHost` | Admit only the seed host. |
| `scope.paths` | `SeedSubtree` | Admit the seed path and paths below it. |
| `pages` | `Explore` | Inspect pages and follow admitted links. |
| `subdomains` | `Disabled` | Do not query the passive host source. |
| `robots` | `Ignore` | Read robots metadata for sitemaps without enforcing allow/disallow rules. |
| `documents` | `DiscardAfterInspection` | Drop inspected response documents after mapping. |
| `filters.excluded_query_keys` | empty | Do not exclude URLs by query key. |
| `filters.excluded_path_prefixes` | empty | Do not exclude URLs by path prefix. |

The full numeric defaults are in [Policy defaults](policy-defaults.md). Map
defaults include link depth 2, 50 hosts, 500 page identities, 100 requests,
20 sitemaps, 2 MiB per response, 20 MiB total response bytes, 8 MiB charged
document retention, a 30-second absolute deadline, one active request, 8 KiB
URLs, 253-byte hostnames, and 4 MiB of inventory size accounting.

`SeedSubtree` uses path segment boundaries. A seed of `/about-us` admits that
path and `/about-us/team`, and excludes `/about` and `/about-us-old`. It does
not invent paths or fetch guessed descendants. `EntireOrigin` admits every path
on each host allowed by `scope.hosts`, while retaining the seed's scheme and
port. It keeps the supplied URL as the initial seed and does not silently
request `/`.

`RegistrableDomain` scope and passive subdomain discovery are independent. A
link may reveal an in-scope subdomain even when passive discovery is disabled.
Passive discovery requires `RegistrableDomain`, and adds candidate hosts from
certificate data. `PageDiscovery::Disabled` records seed/passive hosts without
page exploration. When page exploration is enabled, a passive candidate is
shown as unverified until its bounded page request returns an HTTP response.
That response is evidence of an HTTP observation, not a content or service
quality check.

The PSL snapshot is vendored at
[`crates/yosoi/src/internal/map/data/public_suffix_list.dat`](../crates/yosoi/src/internal/map/data/public_suffix_list.dat).
It includes ICANN and PRIVATE sections and records upstream VERSION
`2026-10-01_23-02-52_UTC`, commit
`6cd82aff889e3d64e5e03bc5c1f43da1934a960a`, and SHA-256
`e0fe072d26b0536525badea237953ff451c9f8e64c9d02c6daa81a4491d2fc66` in its
header. Domain scope for IP and unsupported public-suffix inputs is rejected
before requests; `SeedHost` may still use ordinary HTTP(S) targets that do not
have a registrable domain.

## URL identity and filters

Admission accepts HTTP(S) URLs with hosts and rejects user information,
unsupported schemes, malformed references, out-of-scope hosts/origins/paths,
and configured length violations. URL parsing canonicalizes scheme, host,
IDNA form, and default ports; it removes fragments. Path case, trailing slash,
query order, repeated keys, values, and meaningful escaping remain significant.
Fragments are not page identity. Map does not merge URLs based on a canonical
link or similar content. Canonical hints are normalized metadata relationships;
they do not queue a page, widen scope, or join the traversal tree. The `rel`
attribute is matched as whitespace-separated, case-insensitive tokens.

Relative and protocol-relative links resolve against the final response URL,
using the first syntactically valid HTTP(S) HTML `<base href>` when present.
Map applies scope and filters after resolving each link, so an out-of-scope base
cannot widen access and may cause relative links to be omitted. A filtered URL
is omitted from page inventory; Map does not rewrite it or silently remove its
query. Query-key filters compare parsed parameter names exactly after URL
query parsing. Path-prefix filters use literal starts-with matching, so a
prefix such as `/private` also matches `/private-old`. An empty query key is
valid; an empty path prefix is rejected because it would exclude every path.
Each filter list accepts at most 128 strings, and each string is limited to
1,024 UTF-8 bytes. URLs and source URLs are outcome data; query values remain
present unless the whole URL matches an exclusion filter.

The shared admission code draws on Google's published URL and crawling
guidance, but it is not Google's normalization algorithm and does not claim
Google indexing equivalence:

- [URL structure best practices](https://developers.google.com/search/docs/crawling-indexing/url-structure)
- [Managing faceted navigation crawling](https://developers.google.com/crawling/docs/faceted-navigation)
- [Consolidating duplicate URLs](https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls)

## Requests, redirects, robots, and sitemaps

Map sends Direct HTTP requests through Requests and disables its automatic
redirect following for each dispatch. It observes the bounded `Location`
response fact, resolves and normalizes the next URL, applies origin and Map
scope/filter admission, then dispatches that next request. Each hop consumes
the request budget and may add a redirect relationship. Page redirects cannot
escape the declared host/path scope. Support and provider redirects must remain
on their starting origin.

For each admitted page origin that Map explores, it lazily requests
`/robots.txt`, including when `robots` is `Ignore`, so it can read sitemap
declarations. Host-only mode does not fetch robots or sitemaps. The default
`Robots::Ignore` records robots-source outcomes, continues page inspection when
robots retrieval or parsing fails, and uses any sitemap metadata without
enforcing allow/disallow rules. Set `Robots::Respect` to opt in to bounded
matching for the `YosoiMap` product token based on
[RFC 9309, Robots Exclusion Protocol](https://www.rfc-editor.org/rfc/rfc9309.html).
In Respect mode, HTTP 404 and 410 mean no robots policy, so inspection is
allowed. Other HTTP errors, transport failures, and malformed robots content
block page inspection for that origin and remain typed support outcomes. A
robots sitemap declaration is only a same-origin discovery source; it cannot
authorize another host.
Conventional probes for `/sitemap.xml` and `/sitemap_index.xml` use the same
origin constraint. These support paths and the passive service endpoint are
separate narrow allowlists. Neither expands the mapped site's host scope.

Sitemap indexes are parsed as bounded XML, including bounded gzip expansion.
Index cycles, counts, nesting, request count, per-response bytes, total
response bytes, parser entries, URL length, and the operation deadline are
limited. A sitemap URL is inventoried with sitemap provenance and unknown
link depth; Map does not fetch every sitemap entry or invent link edges.
Malformed or incomplete source documents produce typed source outcomes. Guessed
conventional sitemap paths that return HTML are skipped as `not_sitemap`; an
explicitly declared sitemap returning HTML remains a failure.

Page inspection also reads XML link text and Atom `href` links, resolves inherited
`xml:base`, and applies the same normalization, scope, depth, and inventory limits
as HTML links. RSS query values are preserved. XML link discovery has its own
source provenance; malformed feeds remain visible as source failures.

Page exploration is breadth-first. The seed is link depth zero. At the default
depth of two, Map inspects pages reached at depths 0, 1, and 2, and inventories
admitted outbound links at the boundary without inspecting depth 3. Sitemap
entries keep `minimum_link_depth: None`. Map caches parsed links so a later
shorter path can make further exploration eligible without refetching the
page.

The graph retains link and redirect relationships, cycles, and multiple
parents. `tree()` is a deterministic spanning view; it does not replace the
graph. `frontier()` reports depth-boundary pages, queued pages stopped before
inspection, and passive host-probe candidates that remain unfinished. A
returned page inventory can include completed, skipped, failed, and
not-yet-inspected pages.

## Passive host sources

The fixed public catalog queries crt.sh, HackerTarget hostsearch, Subdomain
Center, and Wayback CDX for the seed's registrable domain. See
[public-source formats and limits](map-public-sources.md). Providers do not
accept API keys, authentication, endpoint overrides, or plugins. Map performs
no DNS brute force, active enumeration, Go process invocation, pagination, or
hidden retries.

Results can be stale, incomplete, or sampled. A passive hostname remains
unverified until separately enabled page exploration observes an HTTP response.
Duplicate host identities retain distinct source observations. Wildcard patterns
retain their own source observations and never become invented concrete hosts.
Provider sampling is reported separately from local retention truncation.

Request, response, parser, URL, inventory, queue, and deadline budgets apply to
all sources. Failures retain source identity without discarding successful
providers. Published anonymous quotas have process-local admission gates; this
is not a cross-process quota guarantee or an availability SLA. The implementation
is original Rust and does not copy or substantially adapt Subfinder code.

## Results, retention, and limits

`MapOutcome` exposes read-only accessors for hosts, pages, relationships,
frontier, support documents, source outcomes, tree entries, retained captures,
wildcard observations, termination, and the policy snapshot/summary.
`Exploration` distinguishes inventoried, pending, inspected, skipped, and
failed pages. The `SourceStatus` vocabulary includes disabled, completed,
failed, sampled, skipped, truncated, and not-started sources. Cancellation and bounds preserve
pending pages and identify unstarted support/provider work. `MapTermination`
distinguishes exhausted selected work, a named limit, deadline, and caller
cancellation. Runtime failures after execution begins leave already collected
results in the outcome.

The `max_pending` value bounds pending page work and nested sitemap work. It
does not limit returned page inventory: discovered items may remain in
`pages()` after a queue limit prevents their inspection. `frontier()` reports
the outstanding or boundary work up to that same limit; excess entries remain
visible as pending page inventory with omission counts. Initial support-source
declarations are processed lazily. Nested sitemap queue admission accounts for
already queued page work, so the combined scheduling queue stays bounded.

`max_response_bytes` and `max_total_response_bytes` apply to charged response
payload bytes. Existing Request source-stage byte limits remain active too.
The runner charges factual Source extents and projected Document lengths, and
accounts for decoded gzip sitemap bytes. If a producer supplies no byte extent,
it charges the bounded response reservation conservatively. These are budget
charges, not a claim of exact network traffic. HTTP headers and transport
overhead are not response payload bytes.

`max_inventory_bytes` is the runner's charged size accounting for URLs,
observations, relationships, result entries, frontier, and tree output. It is
not an exact serialized size, allocator measurement, or peak-RAM limit.
`max_retained_document_bytes` charges projected Document payloads and any retained
complete raw unsupported response payload. Opt-in retention returns the original
Requests `Response` so callers can reuse its Document. The bound is not a
peak-memory promise for the whole response object.

Map uses `policy.map.limits.max_concurrency` for both public providers and page
acquisition, defaulting to two. The phases run separately. Page requests overlap
in bounded frontier batches; metadata and redirect follow-up requests remain
coordinated, and link inspection/commit follows frontier order. Admission reserves
request count, response-byte extent, and trace inventory before dispatch. Pending
work and all other bounds still apply. Requests' own attempt deadline,
source-stage limits, and redirect
policy remain independently active, and Map clamps each attempt to the
remaining absolute Map deadline and response budget.

Map writes nothing to Archive and provides no durable checkpoint/resume.
Callers can pass returned `Response` values into existing Requests,
Documents, and Locators operations explicitly.

## Live examples

Run one fixed case at a time:

```sh
cargo run -p yosoi --example map_live_stress -j 1 -- qscrape-root
cargo run -p yosoi --example map_live_stress -j 1 -- qscrape-stress
cargo run -p yosoi --example map_live_stress -j 1 -- yahoo-root
```

`--list` shows the available cases. Each emits JSONL with its complete configured
limits, policy identity, elapsed time, source outcomes, and actual request trace.
`MapRequest::validate()` checks seed, scope, acquisition, and deadline constraints
without network I/O. `MapOutcome::request_trace()` exposes dispatched URLs, observed HTTP statuses,
and charged response bytes. Charging includes bounded decode reservations and
is not an exact network-traffic or peak-memory measurement. Public-site blocks
remain failures in the report; QScrape cases require seed inspection and HTML
link discovery to pass.

## Hands-on review script

From the default workspace, `./scripts/map/try-map-and-cli.sh` builds the CLI and
`map_review` SDK example with one Cargo worker, then exercises Policy, HTTP
Requests, a typed Request-to-Locate pipe, and bounded page mapping on QScrape.
The Rust example shows ordinary Policy structs and original-Document reuse.
Its page mode uses depth two and at most twenty requests; it prints source
failures, omissions, consumed bounds, request traces, tree, and unfinished work.

```sh
./scripts/map/try-map-and-cli.sh
./scripts/map/try-map-and-cli.sh https://anthropic.com passive
cargo run --offline -p yosoi --example map_review -j 1 -- https://qscrape.dev/l1/news/ pages
```

`passive` skips the script's target-site CLI requests, disables SDK page
exploration, and queries the Certificate Transparency source only. The example
caps passive hosts at 2,000, parser entries at 50,000, and execution at 60 seconds;
these are explicit review choices, not a promise to find every subdomain. Inspect
source outcomes and termination before treating a returned list as complete.
`combined` explicitly enables both passive discovery and normal page requests
on admitted discovered hosts. The CLI now provides `yosoi map`; see [Map CLI](cli-map.md) for saved JSON,
terminal output, and typed Map-to-Locate JSONPath pipes. The wrapper compares
that command with the editable SDK example.

## Policy and persisted artifacts

Map adds `Policy.map`; the current effective-policy projection includes Map and
Search at v5. A previously persisted Policy JSON value without `map`
deserializes with `Map::default()` and serializes in the current complete form.
A newly written snapshot uses the current identity projection. Archive reads
retain a historical pre-Map Policy's v2 identity for its own RequestRun and
preserve Map-era v3 identities with or without an authored robots value;
pre-robots Search-era v4 identities are also preserved.

See [Policy defaults](policy-defaults.md) for the complete default values and
canonical JSON. Public Policy remains an ordinary typed struct; no policy
macro, CLI, runtime builder, or policy merge framework is introduced by Map.

## Implementation evidence and current limits

The repository contains deterministic kernel/source tests and a local
end-to-end site fixture. Those checks do not establish live `crt.sh` coverage,
current provider availability, service terms, or production performance. The
bounded live-provider QA and focused Map benchmark evidence are recorded in
[Map verification](archive/map-verification.md), separately from regression fixtures.

## Source inspiration identity

Subfinder's `dev` head inspected during this implementation was
`4debdd5fdba0278931421239fe00167b29fa8d7d` (queried on 2026-10-03).
The source orchestration, deduplication, and provenance patterns informed the
narrow native implementation; no Subfinder source was copied or substantially
adapted. Production host discovery uses the fixed public index catalog, with no
Go process, SQL connection, active DNS, or target liveness probe. This does not
claim feature or coverage parity with Subfinder's full source registry.

Map requests supply `YosoiMap/0.1.0` as a bounded HTTP User-Agent and retain the
known value in capture environment facts. `Robots::Respect` matches rules with
the `YosoiMap` product token. Other Requests without an explicit agent keep
their prior configuration.
