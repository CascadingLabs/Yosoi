---
title: Python workflows
description: Bind Rust-defaulted Policy and run async Requests, Map, and Search.
order: 4
---

# Python workflows

## Author and bind Policy

`Policy()` obtains defaults from the Rust SDK. Pydantic checks Python values,
then Rust validates the complete policy before an operation uses it.

```python
import yosoi as ys
from yosoi.policy import Documents, Policy, Request

policy = Policy(
    request=Request(maximum_elapsed=10_000_000),  # microseconds: 10 seconds
    documents=Documents(max_input_bytes=1_000_000, max_nodes=100_000),
)

authored_identity = policy.identity()
effective = policy.effective_policy()
snapshot = policy.snapshot()
```

Use `policy.to_json()` to save the Rust-validated declaration. `identity()`
returns its stable policy identity. `effective_policy()` resolves current
selections through Rust's registries; `snapshot()` includes authored and
effective values. A bound request, document, map, or search object keeps the
validated policy JSON it captured. Editing the original Python `Policy` later
does not change that existing binding.

Limits are typed values with explicit units: byte-named fields count bytes,
node and match fields count items, and concurrency fields count concurrent
operations. Request `maximum_elapsed` uses integer microseconds; Map's elapsed
limit uses a `seconds` and `nanoseconds` pair. Rust applies bounds at separate
stages. See [Errors and limits](errors-and-limits.md) and the Rust
[Policy](../sdk/policy.md) reference for the full default table.

## Requests

Requests are asynchronous. Bind a Policy when the operation needs settings
beyond defaults, and pass a caller-owned token to request cancellation.

```python
response = await ys.request.new("https://example.org/").bind(policy).send()

for document in response.documents:
    print(document.id, document.document_class, document.byte_len)
```

`Response` records the policy snapshot, request termination, acquisition
attempts, requested document representations, HTTP metadata, and typed
document outcomes. A representation can be `produced`, `partial`,
`unavailable`, or `unprojectable`. An `Ok(Response)` is not a promise that every
attempt produced every requested document.

The response retains native capture ownership while Python builds typed
outcomes. `response.documents` gives immutable `Document` handles for available
representations; use them with a locator plan or Contract without copying
payload bytes into a second parser stack. A returned document owns its Rust
handle and profile.

```python
token = ys.CancellationToken()
token.cancel()
cancelled = await ys.request.new("https://example.org/").send(cancellation=token)
print(cancelled.termination)
```

Cancellation is represented by the operation's typed result. It is not
reinterpreted as a successful empty document.

## Map

Map follows a bounded frontier from a seed URL. Its policy controls host/path
scope, robots behavior, sitemap and link depth, request budgets, response-byte
budgets, and whether source documents are discarded or retained within a
budget.

```python
from yosoi.policy import Map, Policy

map_policy = Policy(map=Map(documents="retain_within_budget"))
map_outcome = await ys.map.new("https://example.org/").bind(map_policy).send()
print(map_outcome.termination)
print(map_outcome.pages)
print(map_outcome.summary)
```

The outcome preserves observations, source outcomes, relationships, frontier
items, request traces, omissions, and termination. Use its
`policy_snapshot` to inspect the limits and settings used for that run. A page
can be inventoried without being explored, and passive sources can be sampled
or unavailable; inspect those statuses before drawing a coverage conclusion.

## Search

Search is an async, provider-neutral request. Select provider routes and
per-provider profiles through Policy; the response keeps each provider's
attempts and result status separate.

```python
from yosoi.policy import Policy, ProviderSelection, Search

search_policy = Policy(search=Search(providers=[ProviderSelection(provider="bing")]))
search_outcome = await ys.search.new("Yosoi Rust SDK").bind(search_policy).send()
for provider in search_outcome.providers:
    print(provider.provider, provider.outcome)
```

Provider outcomes distinguish results, empty pages, failures, cancellation,
and requests that did not start. Current built-in routes are previews pending
certification. Search returns candidates; use Requests to fetch selected URLs.

## Review locally

From the repository root, `python/examples/review.py contracts` shows the
typed Contract and its evidence; `python/examples/review.py local` starts a
loopback server for Requests and Map and demonstrates cancellation. Neither
command needs a public website. Current native-wheel verification for the new
Contract binding is pending; see [compatibility](compatibility.md).
