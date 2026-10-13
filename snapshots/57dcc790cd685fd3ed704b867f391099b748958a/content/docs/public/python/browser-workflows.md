---
title: Python browser workflows
description: Run managed or borrowed Flows with the supported Python SDK.
order: 4
---

# Python browser workflows

The shared [Flow guide](../sdk/flows.md) explains recipes and invocation. This existing URL collects complete Python programs for the same supported tasks.

## Managed invocation

This program owns its temporary Session and Work. Configure stop behavior so a failed prerequisite prevents dependent actions.

```python
import asyncio
import yosoi as ys

async def main():
    recipe = ys.flow([
        ys.navigate("https://example.org/"),
        ys.assert_that(ys.exists("h1")),
    ], on_failure=ys.policy.Stop(scope="invocation"))
    recipe.to_json()
    outcome = await recipe.invoke()
    outcome.require_completed()

asyncio.run(main())
```

## Borrowed Work

The outer context owns the Session. The inner context owns tab control. Invocation borrows that control, and context exit attempts cleanup on success or failure.

```python
import asyncio
import yosoi as ys

async def main():
    recipe = ys.flow([ys.navigate("https://example.org/")])
    async with ys.session() as session:
        async with session.work() as work:
            outcome = await recipe.invoke(work)
            outcome.require_completed()

asyncio.run(main())
```

## JavaScript permission

Managed JavaScript evaluation requires explicit permission. A borrowed invocation retains its existing Session's authority.

```python
import asyncio
import yosoi as ys

async def main():
    recipe = ys.flow([
        ys.navigate("https://example.org/"),
        # The expression runs in the browser, where document is available.
        ys.evaluate("(() => { document.body.dataset.reviewed = 'yes'; return { reviewed: true }; })()"),
        ys.assert_that(ys.exists("body[data-reviewed='yes']")),
    ], on_failure=ys.policy.Stop(scope="invocation"))

    # Permit JavaScript explicitly for the managed Session.
    outcome = await recipe.allow_javascript().invoke()
    outcome.require_completed()

asyncio.run(main())
```

See [Run JavaScript](../cookbook/run-javascript.md) for the explanation and immutable source snapshots.

## Assertions and waits

Use the [typed assertion programs](../sdk/assertions.md) to check a current observation. Use [bounded Until](../cookbook/assert-and-wait.md) when the task needs to wait for supported evidence. Predicates are synchronous and must return promptly.

## Cancellation and cleanup

Pass a caller-owned cancellation token when another task decides when invocation should stop. Cancellation preserves execution facts and does not undo dispatched effects. Retain unknown receipts and inspect domain state before repeating a potentially irreversible operation.

The current Python bridge exposes the initial tab and borrowed Work. Rust's explicit tab creation, Watcher stream and Archive/View controls are not exposed through this bridge.
