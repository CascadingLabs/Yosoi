---
title: 'The same model in Python'
description: 'The implemented Python beta SDK, shared ownership model and current evidence.'
order: 7
---

# The same model in Python

The Python browser SDK is implemented for the 0.2.0 beta. CAS-574 is complete,
including installed-wheel consumer and controlled browser checks on the
integrated Rust/Python source. The original proposed helpers on this review
page are superseded by [Python browser workflows](../python/browser-workflows.md).

## Automatic ownership

Construct a reusable Flow from application-supplied action targets and Contract
plans, then invoke it with optional policy binding:

```python
outcome = await recipe.invoke()
outcome.require_completed()

outcome = await recipe.bind(policy).invoke()
outcome.require_completed()
```

Yosoi acquires and cleans up resources owned by the managed invocation. The
default continues after recoverable failures, retaining their receipts; choose
`on_failure=ys.policy.Stop(scope="invocation")` when later actions depend on
earlier success. `require_completed()` rejects failed or incomplete outcomes.

## Explicit Session and Work

```python
import yosoi as ys

async with ys.session(policy=policy) as session:
    async with session.work() as work:
        outcome = await recipe.invoke(work)
        outcome.require_completed()
```

Invocation borrows Work. Its caller retains Session ownership and permission
control; context managers release resources they own. Cleanup failures remain
visible alongside operation errors. Python task cancellation signals Rust and
does not roll back dispatched effects.

## Beta limits and evidence

The Python bridge exposes the initial Session tab and one borrowed Work lease.
Explicit tab creation, Watcher streams, remote attachment and Rust Archive/View
APIs remain outside this Python surface. Local assertion predicates are
synchronous and must stay short and pure; cancellation cannot forcibly stop a
running Python function.

The [compatibility page](../python/compatibility.md) records installed-wheel
results and source identity. Local Linux/Chrome checks do not certify the
entire interpreter/platform matrix. The [release checklist](release.md) tracks
remaining source CI, artifacts, notes and the publication decision.
