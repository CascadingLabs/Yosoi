---
title: Respectfulness
description: Share traffic constraints across matching URLs and cooperating callers.
order: 19
---

# Respectfulness

A Respectfulness policy decides whether a matching request may start. Use it to share concurrency, spacing, rolling request budgets and cooldowns across callers. With no Respectfulness policy, these controls are disabled.

A named group combines URL regexes with constraints. Any regex can match within a group; every matching group applies. A domain group and a stricter search-path group therefore constrain the same request together.

## Example: configure a shared group

These examples build one budget across `qscrape.dev` and its subdomains. They allow one active request, require two seconds between starts, and permit ten starts in a rolling minute. The numbers are application choices, not provider defaults.

Both examples validate the configuration without contacting the site. Calling `send` later performs the acquisition.

### Rust

```rust
use std::error::Error;
use yosoi::prelude as ys;
use ys::policy::respectfulness::{Cooldown, Group, RateBudget, Respectfulness};
use ys::registry::Registry;

fn main() -> Result<(), Box<dyn Error>> {
    let group = Group {
        concurrency: Some(1),
        spacing_ms: Some(2000),
        budgets: vec![RateBudget { requests: 10, window_ms: 60_000 }],
        cooldown: Some(Cooldown {
            statuses: vec![429, 503],
            fallback_ms: 30_000,
            transport_errors: false,
        }),
        ..Group::new("qscrape", [r"^https://(?:[a-z0-9-]+\.)*qscrape\.dev/"])
    };
    let policy = ys::Policy {
        respectfulness: Some(Respectfulness::new(vec![group])?),
        ..ys::Policy::default()
    };
    let registry = Registry::default();
    let bound = ys::request::new("https://qscrape.dev/")
        .bind(&policy)
        .with_registry(&registry);
    bound.validate()?;
    println!("{}", policy.to_canonical_json()?);
    Ok(())
}
```

Pass the same Registry to other bindings with `with_registry`. Cloning its handle shares the backend. The borrowed Policy remains declarative; its snapshot does not contain the live Registry.

### Python

```python
import yosoi as ys

group = ys.policy.RespectfulnessGroup(
    id="qscrape",
    patterns=[r"^https://(?:[a-z0-9-]+\.)*qscrape\.dev/"],
    concurrency=1,
    spacing_ms=2000,
    budgets=[ys.policy.RateBudget(requests=10, window_ms=60_000)],
    cooldown=ys.policy.RespectfulnessCooldown(
        statuses=[429, 503], fallback_ms=30_000
    ),
)
policy = ys.Policy(respectfulness=ys.policy.Respectfulness(groups=[group]))
registry = ys.registry.Registry()
bound = ys.request.new("https://qscrape.dev/").bind(policy).with_registry(registry)
bound.check()
print(policy.to_json())
```

The binding snapshots the Policy and retains a shared Registry handle. Later edits to the original Policy do not change that binding. Pass `registry` to other bindings to share the group's state.

## Choose the state lifetime

The default backend is in memory. Independent registries are independent scopes, and state disappears when the last owner or process disappears.

Choose `Registry.jsonl(path)` in Python or `Registry::jsonl(path)` in Rust for persistent local-process coordination. The global JSONL constructor uses the standard per-user location. Processes sharing the same canonical file share budgets and cooldowns.

The CLI accepts Respectfulness through its existing Policy profile. Select persistent state explicitly:

```sh
yosoi --profile research request https://qscrape.dev/ --registry-global --json
yosoi --profile research search "example query" --providers bing --registry ./traffic.jsonl --output json
```

Without a Registry flag, each CLI invocation uses isolated memory.

## Read a rejection or retry

Admission checks and charges all matching groups atomically before dispatch. A rejected start does not send a request. Successful admission consumes start/spacing budgets even if cancellation arrives before dispatch; those charges are not refunded.

Request responses expose `respectfulness` events. Each Search provider retains its own events, including the original and recovery requests. Inspect these independently of the final HTTP status or parser outcome: a successful retry can follow an earlier 429.

Configured cooldowns honor supported `Retry-After` delay and date values, using the authored fallback when unavailable. Successful empty responses and uncertain parser results do not automatically trigger an HTTP-error cooldown.

Retries are disabled by default. Explicit retry settings bound attempts and backoff, and every retry requires fresh admission. Redirect hops and same-provider recovery also consume the applicable budgets. Respectfulness does not choose another Search provider.

## Matching and operational limits

Patterns use Rust regex syntax against canonical HTTP(S) URLs. Hostnames use URL canonical form, trailing hostname dots are removed, fragments are discarded, and query strings remain part of the match. Credential-bearing URLs are rejected.

Unmatched URLs are allowed by default. Set `unmatched` to `reject` when every destination must match an explicit group. Group IDs select operational state; changing a registered group's settings returns a configuration error instead of silently resetting its budgets.

The initial bounded model supports 32 groups, eight patterns per group, 128 active leases per group, and rolling budgets of up to 512 starts over windows of up to one day. Invalid or oversized settings fail validation.

Required Registry operations fail loudly on unavailable or corrupt state. Operations do not silently switch to an empty backend. Crashed or abandoned callers leave deadline-bounded leases; subsequent admissions recover expired leases.

## Supported acquisition paths

Initial enforcement covers Direct HTTP Requests and Search child requests. Browser acquisitions currently return an explicit unsupported-enforcement error before dispatch. Sessions and Map do not yet accept an enabled Respectfulness policy. This keeps unsupported traffic visible while those consumers gain enforcement.
