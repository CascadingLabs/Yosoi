---
title: 'The same model in Python'
description: '0.2.0 concept review. Rust examples describe the local spike; Python examples are proposals.'
order: 7
---

# The same model in Python

This page proposes the Python API for review. These examples are not claims of
a verified Python implementation. Existing Python spike edits are parked.

## A task with automatic ownership

```python
import yosoi as ys

steps = ys.flow([
    ys.navigate(url),
    ys.click("#advance"),
    ys.enter_text("#query", "hello"),
    ys.wait_until(ys.visible("#status.ready"), timeout_ms=5_000),
    ys.assert_that(ys.count_at_least(".row", 12)),
    ys.screenshot(),
])

outcome = await steps.bind(browser_policy).invoke()
```

Python uses `invoke(lease=None)`: call `await steps.invoke()` for automatic
ownership or `await steps.invoke(lease)` to borrow an existing lease.
`bind(policy)` selects an explicit policy in these proposed examples.

The runner owns acquisition and cleanup. The outcome still needs inspection;
returning a value should not disguise a failed or unknown browser action.

## Explicit Session and Work

```python
async with ys.session(allow_arbitrary_js=True) as session:
    async with session.work() as work:
        await work.navigate(url)

        steps = ys.flow([
            ys.click("#advance"),
            ys.evaluate("40 + 2"),
            ys.screenshot(),
        ])
        outcome = await steps.invoke(work)
```

The context managers release Work and close the Session, including on errors.
The contract must retain cleanup failures and propagate Python cancellation to
Rust without silently releasing a tab while an action may still be running.

## What needs proof

- Installing an actual built wheel and running these workflows.
- Cancelling a Python task while waiting for a lease and after dispatch.
- Exceptions during an async context, including combined operation/cleanup errors.
- Watcher use and shutdown without blocking the Python event loop.
- Consistent receipts and Archive references across Rust and Python.

## Decision to review

Do async context managers feel right for explicit Sessions and Work? Should
simple Flow construction use these flat helpers or namespaces matching Rust?

**Recommendation:** preserve the same ownership model with Python-native async
cleanup. Final names should follow review of everyday examples.
