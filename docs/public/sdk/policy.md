---
title: Policy
description: Configure acquisition, parsing, discovery, and resource limits with ordinary Rust values.
order: 4
---

# Policy

Start with the default Policy, change the values your application needs, and bind it to an operation. Rust uses public struct fields; Python uses typed authoring models.

## Example: policy

### Rust

```rust
use std::error::Error;
use yosoi::prelude as ys;
use ys::policy::{CountLimit, MaximumElapsed};

fn main() -> Result<(), Box<dyn Error>> {
    let mut policy = ys::Policy::default();
    policy.request.maximum_elapsed = MaximumElapsed::try_from(5_000_000)?;
    policy.locators.max_matches = CountLimit::try_from(500)?;
    policy.validate()?;

    println!("{}", policy.to_canonical_json()?);
    Ok(())
}
```

The deadline uses microseconds, so five million means five seconds. The match limit bounds locator work. `validate` rejects unsupported settings before an operation.

### Python

```python
from yosoi.policy import Locators, Policy, Request

policy = Policy(
    request=Request(maximum_elapsed=5_000_000),
    locators=Locators(max_matches=500),
)
policy.check()
print(policy.to_json())
```

The typed Request and Locators models express the same limits. `check` validates them through Rust; `to_json` serializes the validated declaration.

## Walk through the result

`MaximumElapsed` uses microseconds. The example allows five seconds per acquisition attempt and up to 500 locator matches.

## Policy fields

| Field       | Controls                                                           |
| ----------- | ------------------------------------------------------------------ |
| `network`   | Opt-in IP family, local source IP, and proxy URL                   |
| `page`      | Ordered acquisition choices and requested documents                |
| `request`   | Attempt deadline, source and browser limits, Direct HTTP redirects |
| `documents` | Parser input bytes, nodes, and depth                               |
| `locators`  | Query work, matches, regions, captures, and output bytes           |
| `tuning`    | Execution tuning; currently only `Default` exists                  |
| `map`       | Discovery scope, robots rules, filters, retention, and budgets     |
| `search`    | Search provider choices, profiles and limits                       |

See [Networking](../concepts/network-routing.md) for request and Session routing, [Limits](limits.md) for defaults and units, and [Map](map.md) for discovery settings.

## Select acquisitions

```rust
use std::error::Error;
use yosoi::prelude as ys;
use ys::policy::{Acquisition, BrowserMode, DocumentRequest, Page};

fn main() -> Result<(), Box<dyn Error>> {
    let mut policy = ys::Policy::default();
    policy.page = Page::new(vec![
        Acquisition::DirectHttp,
        Acquisition::Browser(BrowserMode::Headless).documents([
            DocumentRequest::RenderedDom,
            DocumentRequest::AccessibilityTree,
        ]),
    ])?;
    policy.validate()?;
    Ok(())
}
```

This authors two acquisitions. Executing the browser acquisition also requires the [browser feature and browser installation](browser.md).

Bare `DirectHttp` and `Browser(mode)` declarations use the current default document set. Today, both resolve to `ResponseDocument`. Asking for a browser does not implicitly request its rendered DOM.

`.documents(...)` replaces the document set, including when the set is empty. Duplicate document requests and duplicate acquisition kinds are rejected. Headful and headless are distinct acquisition kinds. Direct HTTP accepts only `ResponseDocument`.

`NetworkTree` is an authorable document request, but the current projection returns `Unprojectable(NetworkTreeSchemaUnavailable)`. It is not a document you can locate through the SDK today.

## Redirects

Direct HTTP follows up to ten redirects by default, including redirects across HTTP and HTTPS origins. To constrain it:

```rust
use std::error::Error;
use yosoi::prelude as ys;
use ys::policy::{DirectHttpRedirects, DirectHttpRedirectTargets, RedirectHopLimit};

fn main() -> Result<(), Box<dyn Error>> {
    let mut policy = ys::Policy::default();
    policy.request.direct_http_redirects = DirectHttpRedirects::Follow {
        max_hops: RedirectHopLimit::try_from(3)?,
        targets: DirectHttpRedirectTargets::SameOrigin,
    };
    policy.validate()?;
    Ok(())
}
```

Use `DirectHttpRedirects::Disabled` to return the first response. These settings apply to Direct HTTP; browser navigation has its own redirect behavior.

## Save and load

Add `serde_json = "1"` to your application for this example:

```rust
use std::error::Error;
use yosoi::prelude as ys;
use ys::policy::PolicySnapshot;

fn main() -> Result<(), Box<dyn Error>> {
    let encoded = ys::Policy::default().to_canonical_json()?;
    let restored: ys::Policy = serde_json::from_str(&encoded)?;
    restored.validate()?;

    let snapshot = PolicySnapshot::from_policy(&restored)?;
    println!("Policy identity: {:?}", snapshot.identity());
    Ok(())
}
```

Serialize a complete Policy rather than guessing its JSON layout. Deserialization validates the wire shape and rejects invalid values. Keep saved policies tied to the SDK version your application uses.

## Snapshots

`PolicySnapshot::from_policy()` validates and clones the Policy, expands current document defaults, and computes its effective identity. Use `policy()` for the authored values and `effective_policy()` for resolved behavior.

Requests and Map return the snapshot they used. Changing your original Policy later does not change that recorded snapshot. The identity describes effective configuration; it does not identify a document or guarantee identical remote content.

## Example: keep a binding stable

Use the same query to compare an existing binding with a policy prepared for
the next operation. This example validates configuration without contacting a
provider.

### Rust

```rust
use std::error::Error;
use yosoi::{
    Policy,
    policy::{
        PolicySnapshot,
        search::{Provider, Search},
    },
};

fn main() -> Result<(), Box<dyn Error>> {
    let policy = Policy {
        search: Search::new([Provider::Bing])?.per_provider_limit(3)?,
        ..Policy::default()
    };
    let restored: Policy = serde_json::from_str(&policy.to_canonical_json()?)?;
    let snapshot = PolicySnapshot::from_policy(&policy)?;
    let bound = yosoi::search::new("photosynthesis")?.bind(&policy);
    bound.validate()?;

    let mut next = policy.clone();
    next.search = next.search.per_provider_limit(1)?;
    assert_eq!(policy.effective_identity()?, restored.effective_identity()?);
    assert_eq!(snapshot.policy().search.max_results_per_provider().get(), 3);
    assert_eq!(bound.policy().search.max_results_per_provider().get(), 3);
    assert_eq!(next.search.max_results_per_provider().get(), 1);
    Ok(())
}
```

A Rust binding borrows its Policy. Clone the declaration to prepare different
values while the original binding remains in use. The separate snapshot owns
its recorded policy and identity. This program also needs `serde_json = "1"`.

### Python

```python
import yosoi as ys
from yosoi.policy import Policy, ProviderSelection, Search

policy = Policy(
    search=Search(
        providers=[ProviderSelection(provider="bing")],
        max_results_per_provider=3,
        max_total_results=3,
    )
)
restored = Policy.model_validate_json(policy.to_json())
snapshot = policy.snapshot()
bound = ys.search.new("photosynthesis").bind(policy)
bound.check()
identity = policy.identity()

policy.search.max_results_per_provider = 1
assert restored.identity() == snapshot.identity == bound.policy.identity() == identity
assert bound.policy.search.max_results_per_provider == 3
assert policy.identity() != identity
```

Python bindings keep a serialized copy of the declaration. Editing the mutable
authoring model affects future bindings, while this binding and the immutable
snapshot retain their original configuration.

## Python Contract acceptance

> [!NOTE]
> **Python**
> `ys.Policy` governs document processing and locator budgets. `ys.ExtractionPolicy` governs accepted Contract results, minimum record count and extraction/validation work. It does not disable Pydantic validation.

```python
import yosoi as ys

class Heading(ys.Contract):
    """A required page heading."""

    title: str = ys.Field("Page title", locator=ys.css("h1"), min_length=1)

document = ys.Document.html("page", "<h1>Hello</h1>")
# callout: ExtractionPolicy controls acceptance of Python Contract records. The bound ys.Policy still controls document and locator work.
acceptance = ys.ExtractionPolicy(minimum_records=1)
headings = Heading.extract(document.bind(ys.Policy()), policy=acceptance)
for heading in headings:
    print(heading.title)
```

The document uses the ordinary processing Policy. Extraction validates each Heading through Pydantic and requires at least one accepted record. Set `on_rejected_record="collect"` to return only valid records despite rejected candidates; use `Heading.extract_report` to retain every issue and its evidence. Incomplete or failed extraction always prevents ordinary success.

> [!NOTE]
> **Rust**
> Rust's public Contract API retains explicit validation and `require_all()`. The Python acceptance options do not add fields to Rust's shared Policy.
