---
title: Policy
description: Configure acquisition, parsing, discovery, and resource limits with ordinary Rust values.
order: 4
---

# Policy

Policy is a Rust struct with public fields. Start with the defaults, change the values your application needs, and bind it to an operation.

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

`MaximumElapsed` uses microseconds. The example allows five seconds per acquisition attempt and up to 500 locator matches.

## Policy fields

| Field       | Controls                                                                        |
| ----------- | ------------------------------------------------------------------------------- |
| `page`      | Ordered acquisition choices and requested documents                             |
| `request`   | Attempt deadline, source and browser limits, Direct HTTP redirects              |
| `documents` | Parser input bytes, nodes, and depth                                            |
| `locators`  | Query work, matches, regions, captures, and output bytes                        |
| `tuning`    | Execution tuning; currently only `Default` exists                               |
| `map`       | Discovery scope, robots rules, filters, retention, and budgets                  |
| `search`    | Stored Search configuration; Search execution is outside the current SDK facade |

See [Limits](limits.md) for defaults and units, and [Map](map.md) for discovery settings.

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
