# Policy defaults

Status: current default values for passive policy declarations. These defaults
are bounded design choices, not measured limits or browser certification.

`yosoi_policy::Policy::default()` produces the complete default value. Policy
is an ordinary Rust struct with public `page`, `request`, `documents`,
`locators`, `tuning`, and `map` fields. Values are validated before JSON
serialization and identity calculation; deserialization uses the same checks
and rejects unknown fields.

## Default values

| Value | Default |
| --- | ---: |
| Ordered page acquisitions | Direct HTTP |
| Direct HTTP documents | Current, resolving to Response Document |
| Shared maximum elapsed time | 10,000,000 microseconds |
| Content-coded source bytes | 8,000,000 bytes |
| Decoded source representation bytes | 16,000,000 bytes |
| Derived Unicode UTF-8 bytes | 32,000,000 bytes |
| Rendered DOM UTF-8 bytes | 16,000,000 bytes |
| Accessibility JSON UTF-8 bytes | 16,000,000 bytes |
| Browser events | 10,000 |
| Browser resources | 1,000 |
| Accessibility nodes | 10,000 |
| Direct HTTP redirect transitions | Follow up to 10 |
| Direct HTTP redirect targets | HTTP and HTTPS, including cross-origin |
| Document input bytes | 67,108,864 bytes |
| Document nodes | 1,000,000 |
| Document depth | 1,024 |
| Locator selector visits | 10,000,000 |
| Locator query bytes | 65,536 bytes |
| Locator query steps | 256 |
| Locator regions | 64 |
| Locator matches | 100,000 |
| Locator captures | 16,384 |
| Locator output bytes | 16,777,216 bytes |
| Map link depth | 2 |
| Map hosts | 50 |
| Map URLs | 500 |
| Map relationships | 2,000 |
| Map observations | 4,000 |
| Map pending URLs | 500 |
| Map requests | 100 |
| Map sitemaps | 20 |
| Map sitemap depth | 3 |
| Map response bytes | 2,097,152 bytes |
| Map total response bytes | 20,971,520 bytes |
| Map retained document bytes | 8,388,608 bytes |
| Map concurrency | 1 |
| Map elapsed time | 30 seconds |
| Map URL bytes | 8,192 bytes |
| Map inventory bytes | 4,194,304 bytes |
| Map parser entries | 10,000 |
| Map hostname bytes | 253 bytes |
| Map query-key and path-prefix filters | empty |

The shared attempt deadline defaults to 10 seconds. Browser cleanup is bounded
separately so owned contexts and processes are not abandoned when acquisition
reaches that deadline.
The browser count values match existing capture fixtures; those fixtures
exercise bounds but are not certification evidence. The numeric defaults are
design choices, not measured hard limits or claims that a provider enforces a
bound at the same stage.

Map's elapsed time is a positive `Duration` serialized as seconds and
nanoseconds. Map budgets are positive; link depth and sitemap depth are raw
`u16` values where zero is meaningful. Each filter list is capped at 128
strings, and each string is capped at 1,024 UTF-8 bytes. Empty path prefixes
are rejected because they exclude every URL; an empty query key is permitted.

## Bound meanings

Source limits name separate body stages. `content_coded_bytes` limits bytes
admitted before decompression. `representation_bytes` limits the decoded
source representation. `unicode_utf8_bytes` limits a derived Unicode view
measured after encoding it as UTF-8. None of these values substitutes for a
different stage's bound.

Browser limits name rendered-DOM UTF-8 bytes, accessibility JSON UTF-8 bytes,
observation events, observed resources, and accessibility nodes. Existing
browser byte bounds apply after provider materialization, so those byte values
bound retained output rather than Chromium's peak memory. Event, resource, and
node counts are separate bounds; one does not imply another.

All byte bounds are positive and must fit `usize` on the current target before
they can enter policy values. `ByteLimit::try_from(u64)` alone checks only
positivity, so `AddressableByteLimit` also verifies platform addressability.
Event limits receive the same addressability check. Resource and
accessibility-node limits are positive `u32` values and are checked before
conversion to the provider's nonzero bound types.

Page policy is an ordered list of at most three unique acquisition kinds:
Direct HTTP, Browser Headless, and Browser Headful. A bare acquisition records
Current document selection, which currently resolves to Response Document.
Calling `.documents([...])` authors an Exact replacement set, which may be
empty. Browser acquisitions can request Response Document, Rendered DOM,
Accessibility Tree, and Network Tree. Direct HTTP accepts only Response
Document. Document sets are canonicalized while acquisition order remains
behaviorally significant.

`direct_http_redirects` governs automatic redirect following by Direct HTTP
only. It counts redirect transitions. `targets` selects either HTTP and HTTPS
targets across origins or same-origin targets only. The default follows HTTP
and HTTPS across origins, matching the existing Direct HTTP engine default.
Browser navigation keeps the semantics of the existing browser capture
specification and does not inherit this HTTP hop or target policy. The redirect
field remains an ordinary request value when browser acquisition is selected;
it has no effect on browser navigation.

For a requested browser source artifact, `SourceLimits.representation_bytes`
maps to the browser `CdpDecodedBody` byte domain. Chromium already removes
content codings from that body, so the `content_coded_bytes` bound does not
apply to it. Policy resolution and wiring use the same declared limits.

## JSON and identity

Policy JSON is a direct, strict object with no public schema-version envelope:

```json
{
  "page": {
    "acquisitions": [
      {
        "kind": "direct_http",
        "documents": {
          "kind": "current"
        }
      }
    ]
  },
  "request": {
    "maximum_elapsed": 10000000,
    "source": {
      "content_coded_bytes": 8000000,
      "representation_bytes": 16000000,
      "unicode_utf8_bytes": 32000000
    },
    "browser": {
      "dom_utf8_bytes": 16000000,
      "ax_json_utf8_bytes": 16000000,
      "max_events": 10000,
      "max_resources": 1000,
      "max_accessibility_nodes": 10000
    },
    "direct_http_redirects": {
      "kind": "follow",
      "max_hops": 10,
      "targets": "allow_http_and_https"
    }
  },
  "documents": {
    "max_input_bytes": 67108864,
    "max_nodes": 1000000,
    "max_depth": 1024
  },
  "locators": {
    "max_selector_visits": 10000000,
    "max_query_bytes": 65536,
    "max_query_steps": 256,
    "max_regions": 64,
    "max_matches": 100000,
    "max_captures": 16384,
    "max_output_bytes": 16777216
  },
  "map": {
    "scope": {
      "hosts": "seed_host",
      "paths": "seed_subtree"
    },
    "pages": "explore",
    "robots": "ignore",
    "subdomains": "disabled",
    "limits": {
      "max_link_depth": 2,
      "max_hosts": 50,
      "max_urls": 500,
      "max_relationships": 2000,
      "max_observations": 4000,
      "max_pending": 500,
      "max_requests": 100,
      "max_sitemaps": 20,
      "max_sitemap_depth": 3,
      "max_response_bytes": 2097152,
      "max_total_response_bytes": 20971520,
      "max_retained_document_bytes": 8388608,
      "max_concurrency": 2,
      "maximum_elapsed": {
        "seconds": 30,
        "nanoseconds": 0
      },
      "max_url_bytes": 8192,
      "max_inventory_bytes": 4194304,
      "max_parser_entries": 10000,
      "max_hostname_bytes": 253
    },
    "documents": "discard_after_inspection",
    "filters": {
      "excluded_query_keys": [],
      "excluded_path_prefixes": []
    }
  },
  "search": {
    "providers": [
      { "provider": "brave", "profile": { "kind": "current" } },
      { "provider": "bing", "profile": { "kind": "current" } },
      { "provider": "duck_duck_go", "profile": { "kind": "current" } }
    ],
    "max_in_flight": 2,
    "max_browser_in_flight": 1,
    "max_results_per_provider": 5,
    "max_total_results": 15,
    "max_retained_content_bytes": 16777216,
    "maximum_elapsed": 30000000
  }
}
```

The default Search plan selects all three providers with five hits each.
Its resolved Requests profiles are versioned local previews: Brave and
DuckDuckGo use headless Browser Requests, while Bing uses Direct HTTP.
These are not certified provider behavior. `Search::disabled()` opts out of Search, including for
historical Policy values that predate this namespace and for child Requests.

`Policy::to_canonical_json()` emits compact JSON in direct field order.
Document request lists are semantic sets, so canonical output uses Response
Document, Rendered DOM, Accessibility Tree, then Network Tree. Input object-key
order and whitespace do not affect identity.

There is no public Policy schema-version envelope. The effective identity
separately exposes projection version 5 and a SHA-256 digest over canonical
effective behavior with a fixed, private domain discriminator.
That private marker is not a versioned defaults API. `Policy::default()` is the
only source of current defaults.

The identity projection includes every policy value. Policy values do not
accept URLs, credentials, profile paths, runtime handles, or other secrets, so
none enter this identity. A future value that carries a secret or handle must
not be added to the projection.

The `yosoi-policy` crate defines passive values only. The separate `yosoi`
facade resolves an attempt-specific capture specification and executes it;
those operations do not add runtime ownership or mutation to the declaration.
