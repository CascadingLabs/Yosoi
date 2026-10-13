---
title: Assertions
description: Check one validated Contract observation with ordinary Rust predicates.
order: 14
---

# Assertions

Use an assertion group to check the state when execution reaches that step.
The browser captures one observation, locates the Contract evidence, validates
exactly one record, and evaluates every check against that record. Configure
stop behavior when an unsuccessful check must prevent the next action.

Checks use ordinary comparisons and collection operations. Rust accepts typed
closures; Python accepts named synchronous predicates.

## Example: author a cart prerequisite

### Rust

```rust
use std::error::Error;
use yosoi::{action::{self, check}, flow, prelude as ys};
use yosoi::policy::{Continuation, StopScope};

#[derive(ys::Contract)]
#[ys(id = "cart", description = "Observed cart")]
struct Cart {
    #[ys(description = "Total", locator = ys::locator::css(".total").text())]
    total: ys::Money,
    #[ys(description = "Items", locator = ys::locator::css(".item").text())]
    items: Vec<String>,
}

fn main() -> Result<(), Box<dyn Error>> {
    let checkout = flow::new([
        action::assert_all::<Cart>(Cart::plan()?, [
            check(|cart: &Cart| cart.total.minor_units() == 450),
            check(|cart: &Cart| !cart.items.is_empty()),
            check(|cart: &Cart| cart.items.iter().any(|item| item == "Tea")),
        ]).into(),
        action::click("#proceed-to-checkout"),
    ]).on_failure(Continuation::Stop(StopScope::Invocation));
    checkout.validate()?;
    println!("{checkout:?}");
    Ok(())
}
```

The Contract binds cart fields to the supplied page. Each check reads the same validated record. Stop behavior prevents the dependent click after an unsuccessful prerequisite. This program authors and validates a recipe without opening a browser.

### Python

```python
import yosoi as ys

class Cart(ys.Contract):
    """Observed cart."""

    total: ys.Money = ys.Field("Total", locator=ys.css(".total"))
    items: list[str] = ys.Field("Items", locator=ys.css(".item"))

checkout = ys.flow([
    ys.assert_all(Cart, checks=[
        ys.check("expected total", lambda cart: cart.total.minor_units == 450),
        ys.check("nonempty cart", lambda cart: len(cart.items) > 0),
        ys.check("Tea is present", lambda cart: "Tea" in cart.items),
    ]),
    ys.click("#proceed-to-checkout"),
], on_failure=ys.policy.Stop(scope="invocation"))
print(checkout.to_json())
```

The same Contract and checks use named synchronous predicates. Serializing validates the recipe without executing the checks. Invocation requires a Work lease whose page contains the cart bindings.

## Walk through the checks

The explicit `&Cart` parameter annotation gives Rust enough type information
for the free `check` helper. `Cart::plan()` is the existing locator Plan;
there is no new target or source-binding wrapper.

A `check` is an `Fn(&Cart) -> bool`. It can compare fields, use `!=`, `<`, `<=`,
`>`, `>=`, ranges and iterators, and inspect existing supported collection
fields. Contract validation remains separate from the business predicate.
This feature does not add new Contract value conversions.

An optional name improves a failure report:

In Rust, append `.named("one item")` to the check. In Python, pass the name
to `ys.check("one item", predicate)`.

Without a name, the report identifies a check by its zero-based group position.
A bool-returning closure does not automatically expose its source expression
or the operands of a comparison. The report retains located values and their
coordinates, along with validation issues and check results.

## Evaluate retained documents

A local group can borrow values and inspect an existing immutable Document
without a browser:

## Example: check a retained cart

### Rust

```rust
use std::error::Error;
use yosoi::{action::check, assertions::AssertionGroup, prelude as ys};

#[derive(ys::Contract)]
#[ys(id = "cart", description = "Observed cart")]
struct Cart {
    #[ys(description = "Total", locator = ys::locator::css(".total").text())]
    total: ys::Money,
    #[ys(description = "Items", locator = ys::locator::css(".item").text())]
    items: Vec<String>,
}

fn main() -> Result<(), Box<dyn Error>> {
    // Use a controlled local capture instead of opening a browser.
    let document = ys::Document::html(
        "cart",
        b"<b class='total'>$4.50</b><span class='item'>Tea</span>".to_vec(),
    )?;
    let expected = 450;

    // Each predicate reads the same validated Cart.
    let report = AssertionGroup::<Cart>::new(Cart::plan()?.clone(), [
        check(|cart: &Cart| cart.total.minor_units() == expected).named("expected total"),
        check(|cart: &Cart| cart.items.len() == 1).named("one item"),
    ]).evaluate(&document)?;
    println!("{report:?}");
    if !report.passed {
        return Err("cart checks failed".into());
    }
    Ok(())
}
```

The local group returns structured predicate results and retained evidence. Its checks
can borrow the expected value because this group is evaluated in the same scope.

### Python

```python
import yosoi as ys

class Cart(ys.Contract):
    """Observed cart."""

    total: ys.Money = ys.Field("Total", locator=ys.css(".total"))
    items: list[str] = ys.Field("Items", locator=ys.css(".item"))

# Keep the input local so this example needs no browser.
document = ys.Document.html(
    "cart",
    "<b class='total'>$4.50</b><span class='item'>Tea</span>",
)

# Validate the record before checking the business rules.
cart, = ys.extract(document, Cart).validate().require_all()
assert cart.total.minor_units == 450
assert len(cart.items) == 1
print(cart)
```

Python uses the supported local Contract extraction API, followed by ordinary assertions.
The Rust local `AssertionGroup` report is not exposed as a Python local group API.

## Owned and borrowed predicates

The complete runnable example is `crates/yosoi/examples/assertion_groups.rs`:

```bash
cargo run -p yosoi --example assertion_groups -j 1
```

Stored Flow steps own their predicates and captures. They therefore require
owned, `Send + Sync + 'static` checks; `move` captures a value into the recipe.
The separate local `AssertionGroup` supports borrowed captures. Sharing a
recipe uses immutable `Fn` predicates rather than hidden mutable SDK state.
User predicates should be short comparisons and return promptly. A synchronous
Rust function cannot be forcibly interrupted mid-computation; it is not an
async task or an arbitrary-code isolation boundary. The browser operation
checks cancellation and the action budget around evaluation.

## Failure and waiting

Every normal predicate runs, including predicates after a false result.
Missing or multiple records, duplicate scalar fields, incomplete evidence,
and failed conversion prevent predicate evaluation and retain diagnostics.
A check has `passed: null` when it could not run. An unwinding predicate panic
is retained as a check error, while other normal checks still run; aborting
panics cannot be recovered.

The group accepts 1–128 checks and optional nonempty names of at most 256 bytes.
Recipe, capture and result bounds still apply.

Immediate assertions check once. Use [Until](../cookbook/assert-and-wait.md)
to observe a supported condition within a bounded scope. Async capture and ordered execution do not introduce polling
or retries. Checking after a click observes later state; it does not establish
that the click caused the observed state.

## Save results and recipes honestly

Assertion reports and the observed evidence are serializable. A saved recipe
retains the Plan, Contract type description, group identity and check names,
but not executable Rust closure code. Reopening results never runs checks.

A deserialized Flow with local checks refuses invocation before acquiring a
browser until those checks are explicitly rebound. Rebinding must match the
saved Contract type and check names/positions; callers supply the actual
predicate semantics again. Saved success is not proof of a new invocation.

Existing recipes without these steps retain their wire shape and behavior.
Use `FlowOutcome::require_completed()` to distinguish a returned outcome from
actual completion while keeping its receipts available for inspection.

## Check Qscrape's cart in a Flow

`crates/yosoi/examples/qscrape_cart_assertion.rs` opens the live L2 shop, selects
one pickaxe, validates its cart Contract, and compares the observed total in
an anonymous check. Qscrape uses GS; the example reads its total as a String
because the existing Money type supports USD.

```bash
cargo run -p yosoi --features browser --example qscrape_cart_assertion -j 1 -- \
  .generated/qscrape-cart-assertion 10.00
```

One pickaxe was observed at 14.50 GS. Expecting 10.00 therefore demonstrates a
failed business predicate after successful Contract validation. The checkout
click is skipped. Pass `14.50` to test the successful path. Each run saves an
`outcome.json` with its check results, located evidence and operation receipts.

The browser actions use native CSS, while the Contract Plan uses the document
engine's supported CSS subset. Its active-framework scope uses attribute
selectors rather than unsupported `:not(...)`. Hidden framework copies must
not become extra cart records. Unavailable live grids stop at the explicit
readiness wait; the example does not silently reload until a variant works.
