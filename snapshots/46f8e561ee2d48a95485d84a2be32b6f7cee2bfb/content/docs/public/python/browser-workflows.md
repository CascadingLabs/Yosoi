---
title: Python browser workflows
description: Compose typed Flows with managed or borrowed browser ownership.
order: 4
---

# Python browser workflows

The browser SDK composes the same Rust Session, Work and Flow engine through
Python's async API. A recipe describes actions; invocation selects policy,
permissions and ownership. The browser executable is installed separately from
the wheel; use a supported regular Chrome or Chromium distribution with its
sandbox enabled.

## A reusable recipe

Site bindings supply action targets and a compiled Contract plan. Field
descriptions explain the observed record; they do not automatically discover
page elements.

```python
import yosoi as ys


class Cart(ys.Contract):
    total: ys.Money = ys.Field("The displayed cart total")
    items: list[str] = ys.Field("Names of products in the cart")


def checkout(url, add_to_cart, checkout_button, cart_plan):
    return ys.flow([
        ys.navigate(url),
        ys.click(add_to_cart),
        ys.assert_all(
            Cart,
            plan=cart_plan,
            checks=[
                ys.check("one item", lambda cart: len(cart.items) == 1),
                ys.check(
                    "expected total",
                    lambda cart: cart.total.minor_units == 450,
                ),
            ],
        ),
        ys.click(checkout_button),
    ], on_failure=ys.policy.Stop(scope="invocation"))
```

An assertion group captures one canonical observation, extracts and validates
the Contract through Rust, and passes the same record to every synchronous
predicate. A false result and a raised exception remain distinguishable in the
report. Predicates must return a boolean; async predicates are unsupported.
They are local executable callbacks, so a serialized recipe retains their
descriptors and requires explicit bindings before execution.

Assertions inspect the current state immediately. Use scoped `until` for a
bounded wait; timeout inputs use explicit milliseconds.

Rust's default Flow policy continues after recoverable failures. This checkout
recipe explicitly stops the invocation so that failed cart checks prevent the
dependent checkout action. A continued failure remains visible as a
`completed_with_issues` outcome; it does not pass `require_completed()`.

## Managed invocation

```python
recipe = checkout(url, add_to_cart, checkout_button, cart_plan)
outcome = await recipe.invoke()
outcome.require_completed()

outcome = await recipe.bind(policy).invoke()
outcome.require_completed()
```

Managed invocation acquires its own Session and releases owned resources.
Returning an outcome does not imply completion: inspect its terminal state and
receipts, or call `require_completed()` for the raising path. The error retains
the original structured outcome.

## Borrowed invocation

```python
async with ys.session(policy=policy) as session:
    async with session.work() as lease:
        outcome = await recipe.invoke(lease)
        outcome.require_completed()
        # The lease remains available to its caller here.
```

The caller owns the borrowed lease. Invocation neither closes its Session nor
grants permissions beyond that Session. Context managers release their own
resources on ordinary and exceptional exits, and retain cleanup failures
alongside operation errors.

## JavaScript permission and immutable sources

```python
recipe = ys.flow([
    ys.navigate(url),
    ys.evaluate_file("scripts/inspect.js"),
    ys.run_module_with_export("scripts/catalog.js", "summary"),
])
outcome = await recipe.bind(policy).allow_javascript().invoke()
outcome.require_completed()
```

File and module constructors snapshot bounded source through Rust before
invocation. Editing a source file later does not change the recipe. Module
export selection reads a JSON-compatible value without calling exported
functions. The existing local-module restrictions still apply; package or
network imports are not a new Python capability.

For borrowed invocation, JavaScript must already be permitted by the Session's
settings and allowed actions. A managed permission grant cannot elevate a
borrowed lease.

## Cancellation and evidence

```python
stop = ys.CancellationToken()
outcome = await recipe.invoke(cancellation=stop)
```

The stop token reaches the shared Rust executor. Cancelling a Python task also
signals the underlying operation; cancellation is not rollback of dispatched
effects. Inspect receipts for rejected, observed or uncertain execution, and
keep caller-owned leases under caller control.

An Until trigger can be observed while observer cleanup remains uncertain.
The report retains that cleanup failure and the receipt becomes unknown; the
Work may be fenced. Inspect these facts rather than treating cancellation as
confirmation that every browser effect or cleanup step settled.

Invocation waits observe cancellation and deadlines while local predicates run
on a blocking worker. Python cannot forcibly stop a synchronous function; a
cancelled predicate may finish later using its captured record. Keep predicates
short and pure, with no browser operations or external effects.

The Python beta exposes the initial Session tab through Work. Explicit tab
creation, watcher streams, remote attachment and the Rust Archive/View facade
are outside this Python surface. Structured Flow receipts and Until reports
remain available for inspection; stronger Archive guarantees remain separate
release work.

The repository's `python/examples/browser_beta.py` demonstrates caller-supplied
bindings. Installed-wheel browser tests use a deterministic loopback fixture
with positive and negative controls. Platform/interpreter claims follow the
actual artifact and runtime evidence; workflow configuration alone is not a
completed hosted check.
