# Reusable Policy core

This crate defines and checks the settings that control Yosoi’s work, such as how pages are fetched and how much data or time an operation may use. It produces stable snapshots of those settings for other crates to apply.

Typed declarations, validation, current document defaults, canonical identity,
and immutable snapshots. Policy neither constructs a runtime nor executes
work. Operations in their owning SDK borrow a policy declaration and prepare a
validated snapshot before I/O.

```rust
use yosoi_policy::{Policy, PolicySnapshot};

let policy = Policy::default();
let snapshot = PolicySnapshot::from_policy(&policy)?;
// `policy` remains caller-owned; the snapshot owns authored and resolved values.
```

Page policies contain an ordered list of acquisitions. Bare
`Acquisition::DirectHttp` and `Acquisition::Browser(mode)` declarations use
Current document selection. Current currently resolves to
`[DocumentRequest::ResponseDocument]` for each acquisition. Calling
`.documents([...])` replaces that selection with an Exact set; an empty list is
valid and means no documents are requested for that acquisition.

Each snapshot retains the authored `Policy` and exposes an `EffectivePolicy`.
Its page lists acquisitions in authored order, records whether each selection
was Current or Exact, and provides the expanded document requests in canonical
order. The effective identity is computed from this fully expanded behavior,
so Current and an equivalent Exact set have the same identity. Document order
inside an Exact set does not affect canonical JSON or identity; acquisition
order does.

Policy serialization writes the Policy value directly. Effective policy
identities use projection version 5 and include the Map and Search policy namespaces.
The Search default selects Brave, Bing, and DuckDuckGo through versioned local
preview profiles and retains five hits from each. `Search::disabled()` opts out
explicitly; preview status does not imply provider certification.
Request deadlines, capture bounds, and Direct HTTP redirect values retain
their existing policy types and defaults.

Application code can reuse a declaration through a borrow or ordinary
`Arc<Policy>`. Borrowing does not consume invalid input: callers receive a
typed `PolicyError` and retain their declaration. Snapshots stay stable after
the original value changes or is dropped. There is no process-global
registry, merge, runtime constructor, PolicyTarget bridge, or Policy::bind
method.

Other workspace crates may use `yosoi-policy.workspace = true`. Requests owns
its public request.bind/send API and provider resources. SDK projects own their
namespace-specific policy semantics and enforcement; this core adds no generic
configuration or inheritance framework.

The `documents` namespace declares input, node, and depth bounds. The `locators`
namespace declares selector visits, query bytes and steps, regions, matches,
captures, and output bytes. Document and Locator operations derive their
resource budgets privately when using the default policy or borrowing a custom
one. Plans do not own those caps. Document profiles, locator semantics,
coordinates, completeness, and typed failures remain domain-owned. Policy does
not authorize truncation or cross-representation substitution.

The `map` namespace declares host and path scope, page discovery, robots-rule
behavior, passive subdomain discovery, request and inventory limits,
discovery-document retention, and bounded URL filters. Robots enforcement
defaults to `Robots::Ignore`; `Robots::Respect` opts into applying discovered
rules to page exploration. Robots metadata may still be inspected for sitemap
declarations in either mode. Passive subdomain discovery requires
registrable-domain host scope. Map filters contain only query-key names and
path prefixes; they do not carry credentials, callbacks, or execution handles.
Older archived Policy values that omit `map` deserialize with `Map::default()`
and serialize in the current complete shape.
Existing Map values that omit `robots` migrate to `Robots::Ignore`.
Map depth limits may be zero: zero link depth still inventories seed links,
and zero sitemap depth disables nested sitemap-index traversal. Other Map
budgets and the elapsed duration must be positive. Each filter list accepts at
most 128 strings, and each string is limited to 1,024 UTF-8 bytes. Empty path
prefixes are rejected because they would exclude every URL; an empty query key
remains valid.

Canonical JSON is the unversioned `Policy` value directly, with top-level fields
in page, request, documents, locators, tuning, and map order (default tuning is
omitted). Unknown fields are rejected. The only compatibility rule is the
explicit default Map migration for persisted Policy values that predate Map.
