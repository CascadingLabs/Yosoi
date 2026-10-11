---
title: 'JavaScript is an action with extra permission'
description: 'Explicit JavaScript permission, construction-time file snapshots, and local ES module actions.'
order: 4
---

# JavaScript is an action with extra permission

JavaScript runs through the same tab-control lease as other actions. A valid
lease and explicit JavaScript permission are both required.

## JavaScript inside a Flow

```rust
use yosoi::{action, flow, session};
use yosoi::session::SessionPolicy;

let session = session::new()
    .bind(&browser_policy)
    .configure(SessionPolicy {
        allow_arbitrary_js: true,
        ..SessionPolicy::default()
    })
    .acquire()
    .await?;

let work = session.work().await?;
let steps = flow::new([
    action::navigate(url),
    action::click("#advance"),
    action::evaluate(
        "document.body.dataset.reviewed = 'yes'; \
         document.body.dataset.reviewed"
    ),
    action::screenshot(),
]);

let run = steps.with_lease(&work).invoke().await;
let release = work.release().await;
let close = session.close().await;
let outcome = run?;
release?;
close?;
```

The JavaScript step's receipt retains its returned value. Here the page is
mutated and the result is the string `"yes"`. A rejected or unknown step stops
the Flow before the next step.

## Direct evaluation

While the lease is held, the same capability is available directly:

```rust
let receipt = work.evaluate("40 + 2").await?;
println!("{:?}", receipt.result); // Some(42)
println!("{:?}", receipt.status);
```

This line belongs before `work.release()` in the previous example.

## Current limits

JavaScript is disabled by default. A managed invocation can opt in explicitly:

```rust
let recipe = flow::new([
    action::navigate(url),
    action::evaluate_file("scripts/review.js")?,
    action::run_module_with_export("scripts/review.mjs", "result")?,
]);
let outcome = recipe.bind(&browser_policy).allow_javascript().invoke().await?;
outcome.require_completed()?;
```

`evaluate_file` snapshots UTF-8 text when constructing the action and evaluates
it as a script. `run_module` snapshots a local ES module graph and executes its
entry for effects, returning JSON null. `run_module_with_export` selects a named
export (including `"default"`) as the JSON result; it does not call exported
functions. For example:

```js
// scripts/review.mjs
import { answer } from './answer.mjs';
document.body.dataset.reviewed = 'yes';
export const result = { reviewed: true, answer };
```

Selected results accept finite JSON primitives, dense arrays, and plain objects
with data fields. Functions, undefined, non-finite numbers, accessors, cycles and
non-plain objects produce an Unknown receipt after execution rather than a
silently changed value. Validation is bounded to 16,384 values, depth 128 and
1,048,576 text code units; the Session's retained-result byte limit also applies.

Imports, exports, re-exports, cycles, live bindings, top-level await, and literal
dynamic imports use Chrome's native module semantics. Dependencies must be
explicit relative local file paths. Bare package imports, network URLs,
computed dynamic imports, and import attributes return typed
construction errors. File extensions do not select execution semantics.

By default, the entry file's parent directory is the bundle root. To include
parent-relative imports from a nested entry, use
`action::run_module_from_root("scripts", "tasks/review.mjs")` or
`action::run_module_from_root_with_export("scripts", "tasks/review.mjs", "result")`.
Dependencies must stay within that root, including through symlinks.

The graph is bounded to 64 modules and 65,536 source bytes. Exact sources,
paths, digests and dependency edges are retained in the recipe and Archive.
Changing or deleting files after construction cannot change invocation. A
deserialized graph is revalidated before execution.

`allow_javascript()` also exists on the Session builder. On a borrowed Flow
invocation, the Session's existing permission remains authoritative; the
managed opt-in cannot elevate a denied lease. Child recipes share that authority.

Main-world evaluation and unique frame targeting exist. Isolated worlds and
remote module resolution are unsupported. Module execution uses blob sources
and an import map in the selected document; page CSP can reject them. Each run
uses fresh module identities. Blob URLs and merged import-map registrations
remain available for deferred literal imports until the document is replaced.
The runtime caps retained registrations at 16 bundles and 8 MiB of bundle
payload per context; later module actions fail when that capacity is exhausted.
Module results have structural validation before transfer and a retained-result
byte limit after CDP transfer. Those checks do not prevent transient large
allocations in Chrome or CDP. Execution remains in the page world and relies on
its browser globals; the structural guard does not isolate hostile globals or
Proxy traps.

JavaScript can have effects before throwing or timing out. An exception can
produce an Unknown receipt. Cancellation does not roll back page mutations.

Inspect the terminal status and receipt before treating invocation as successful.
