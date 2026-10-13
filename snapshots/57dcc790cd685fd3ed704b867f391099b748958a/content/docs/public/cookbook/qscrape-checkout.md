---
title: A modular checkout with Flows
description: Compose a cart prerequisite and keep site bindings separate from the recipe.
order: 4
---

# A modular checkout with Flows

A checkout task needs more than a successful click. Check the selected item and cart total before advancing, then verify the order confirmation after submission.

Keep the site bindings separate from the recipe. A caller supplies the URL, the currently valid action targets, and a Plan whose outputs match the cart Contract.

1. Open the shop and add the selected item.
2. Extract and validate the cart record.
3. Stop if the item count or total is wrong.
4. Advance to checkout only after those checks pass.
5. Submit in a separate step chosen by the caller.
6. Check the final order confirmation and retain its identifier.

## Example: prepare checkout

### Rust

```rust
use yosoi::{action, flow, prelude as ys};
use yosoi::policy::{Continuation, StopScope};

#[derive(ys::Contract)]
#[ys(id = "cart", description = "Observed cart")]
struct Cart {
    #[ys(description = "Displayed cart total")]
    total: ys::Money,
    #[ys(description = "Names of items in the cart")]
    items: Vec<String>,
}

fn checkout(
    url: &str,
    add_to_cart: &str,
    checkout_button: &str,
    cart_plan: &ys::Plan,
) -> flow::Flow {
    flow::new([
        action::navigate(url),
        action::click(add_to_cart),
        action::assert_all::<Cart>(cart_plan, [
            action::check(|cart: &Cart| cart.total.minor_units() == 450),
            action::check(|cart: &Cart| cart.items.len() == 1),
        ]).into(),
        action::click(checkout_button),
    ]).on_failure(Continuation::Stop(StopScope::Invocation))
}
```

The helper describes a recipe and does not open a browser. The supplied Plan binds evidence to the Contract's `total` and `items` fields. Both predicates inspect the same validated cart record. Invocation stop behavior prevents the dependent checkout click when the prerequisite fails.

### Python

```python
import yosoi as ys

class Cart(ys.Contract):
    """Observed cart."""

    total: ys.Money = ys.Field("Displayed cart total")
    items: list[str] = ys.Field("Names of items in the cart")

def checkout(url, add_to_cart, checkout_button, cart_plan):
    return ys.flow([
        ys.navigate(url),
        ys.click(add_to_cart),
        ys.assert_all(Cart, plan=cart_plan, checks=[
            ys.check("expected total", lambda cart: cart.total.minor_units == 450),
            ys.check("one item", lambda cart: len(cart.items) == 1),
        ]),
        ys.click(checkout_button),
    ], on_failure=ys.policy.Stop(scope="invocation"))
```

The same helper takes explicit site bindings. Python authoring supplies named synchronous checks; Rust extracts and validates the record used by both predicates. The total is 450 minor units, or USD 4.50.

## Invoke under the right ownership

Use managed [Flow invocation](../sdk/flows.md) for a standalone task. Use borrowed [Work](../sdk/sessions/index.md) when preparation and submission must retain the same tab and cart state.

Separate preparation from submission so the caller can inspect the prepared checkout before taking the next action. Require a successful preparation outcome before submitting.

## Bind against current evidence

Descriptions explain fields; they do not discover selectors automatically. Resolve supported targets and the cart Plan from current site evidence. A selector from an old capture can become stale after the page changes.

The Qscrape-specific Rust program lives in `crates/yosoi/examples/qscrape_checkout.rs`. Its site bindings and receipt handling are concrete examples to inspect. The helpers above use the current 0.2.1 SDK and deliberately accept bindings from the caller.

## Verify the final result

A checkout button click is not an order. The submission recipe should check the confirmation and retain its order identifier or record.

On timeout or cancellation after dispatch, preserve the unknown effect and inspect domain evidence before retrying. A local test of recipe authoring does not establish a successful live checkout.
