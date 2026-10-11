---
title: 'A modular checkout with Flows'
description: 'A live Qscrape example for the 0.2.0 Rust browser spike: reusable recipes, shared state, assertions, and simulated checkout.'
order: 4
---

# A modular checkout with Flows

A Flow describes a recipe. Invoking it performs that recipe on a leased browser
tab. This example uses [Qscrape's L2 e-shop](https://qscrape.dev/l2/eshop/) to
select a product, add it to the cart, increase its quantity, and complete a
simulated order.

The executable source is `crates/yosoi/examples/qscrape_checkout.rs`. It belongs
to the **0.2.0 browser spike**; it is not a claim that these APIs are available
in the published 0.1.0 SDK.

## Start with the task

The preparation recipe reads from top to bottom:

```rust
let prepare_order = compose([
    flow::new([action::navigate(SHOP)]),
    select_product(product),
    add_to_cart(product),
    increase_quantity_from_one(product, quantity),
    begin_checkout(product, quantity, &total),
]);

let prepared = prepare_order.with_lease(lease).invoke().await?;
record_and_require_completion("prepare-order", &prepared, output)?;
```

Each function returns a Flow. The same recipes accept a different product and
quantity; they do not need another copy of the checkout logic. The example
provides a Standard Iron Pickaxe (`VM-MIN-001`, 14.50 GS) and a Stone Chisel Set
(`VM-MIN-003`, 6.50 GS).

Preparation and submission are separate invocations:

```rust
let submit_order = compose([fill_test_checkout(), confirm_test_order()]);
let submitted = submit_order.with_lease(lease).invoke().await?;
record_and_require_completion("submit-order", &submitted, output)?;
```

Both invocations borrow the same lease, preserving the tab, selected product,
and cart. A caller could inspect the prepared checkout before invoking
submission. No additional workflow container is needed.

## Composition and nesting

Native nested Flow steps are supported through `child.into()`. This example
retains its small flat authoring helper, which collects child recipes into one
executable Flow and explicitly stops on a required checkout failure:

```rust
fn compose(children: impl IntoIterator<Item = Flow>) -> Flow {
    flow::new(children.into_iter().flat_map(|child| child.steps))
        .on_failure(Continuation::Stop(StopScope::Invocation))
        .with_failure_capture(FailureCapturePolicy::Screenshot)
}
```

This gives the source a modular structure while preserving execution order.
The receipts contain flat step indices; they do not retain child names or
nesting boundaries. The helper sets failure capture on the parent and does
not merge child policies. Use native nested steps when child timeout or
continuation overrides need to remain separate. The explicit stop policy keeps
a failed required check from proceeding to order submission; ordinary Flows
still default to Continue.

## Give each recipe a contract

| Recipe                       | Starting condition                                               | Verified result                                                            |
| ---------------------------- | ---------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `select_product`             | Catalog navigation completed; the requested card becomes visible | Detail view for the requested SKU is visible                               |
| `add_to_cart`                | Requested detail view is selected and in stock                   | That SKU is visible in the cart at quantity one                            |
| `increase_quantity_from_one` | That SKU is already at quantity one                              | Its exact requested quantity is visible                                    |
| `begin_checkout`             | Correct cart item, quantity, and line total                      | Checkout view and expected total are visible                               |
| `fill_test_checkout`         | Checkout is visible                                              | Synthetic fields have been typed; acceptance is checked by the next recipe |
| `confirm_test_order`         | Checkout fields are filled                                       | Confirmation view and a `VM-312-…` reference are visible                   |

`increase_quantity_from_one` deliberately declares its starting quantity.
It is not an idempotent “set quantity” operation. Reusing it against a cart
that already contains ten items stops at its precondition instead of
incrementing ten to nineteen. A future general `set_quantity` recipe would
need to observe the current quantity or use an absolute-value control.

The shop's Add to Cart button already opens the cart. This adapter therefore
does not add an unnecessary second navigation step.

## Keep selectors tied to the visible state

L2 randomly selects React, Vue, Svelte, or Solid implementations. Hidden
variants and decoy content can also appear in the document. The example
scopes every product operation to the active grid:

```rust
const ACTIVE_GRID: &str =
    "[data-slot=\"product-grid\"] [data-fw]:not([hidden])";
```

Within that scope, selectors use the SKU and semantic data attributes such as
`data-component`, `data-in-stock`, `data-qty`, and `data-checkout-total`.
Generated classes, framework names, and sidebar product mentions are not
part of the recipe. Button selectors still depend on this site's DOM
relationships; another shop would need its own adapter.

An exact quantity checkpoint is possible with today's conditions:

```rust
let quantity_check: flow::Step = action::assert(Condition::Visible {
    selector: format!("{row} [data-qty=\"{quantity}\"]"),
})
.into();
```

This checks the exposed quantity attribute. A future typed value/text
equality condition would express the same intent without requiring the site
to expose an attribute. Attribute presence does not prove the visible text
agrees with it.

## A click is not the business result

The live test clicked Place Order with empty fields. The click receipt was
observed and its single-action Flow completed, but the website displayed
validation errors. The completed click did not establish a completed order.

The example therefore waits for a confirmation element after submission.
The confirmation view uses the same URL as the catalog, so checking only the
URL would also be insufficient.

`with_lease(lease).invoke().await?` returns an outcome. Inspect `outcome.terminal` before
continuing. Failed, unknown, and cancelled outcomes must not be reported as
successful checkout. The example writes each outcome before checking it, so
stopped runs retain their receipts and captured observations.

## Run and inspect

Use regular sandboxed Chrome with the repository's browser configuration.
The container fixture runner uses `--network none`; this live example needs
outbound access to Qscrape and its assets. Keep the Chrome sandbox and resource
limits enabled.

```bash
cargo run -p yosoi --features browser --example qscrape_checkout -j 1 -- \
  .generated/qscrape-pickaxe pickaxe 10

cargo run -p yosoi --features browser --example qscrape_checkout -j 1 -- \
  .generated/qscrape-chisel chisel 3
```

The output directory receives `prepare-order.json` and `submit-order.json`,
containing the recipe and operation receipts. The confirmation screenshot is
saved as `submit-order.png`. A failed or unknown recipe attempts a bounded
failure screenshot; capture availability is recorded separately from the
original result.

Submission is specific to this simulated shop. Its inspected public code
validates the fields, generates a local order reference, clears the
localStorage cart, and displays confirmation. The example uses synthetic
shipping details and the test card advertised by the page. The confirmation
copy mentions an email; the inspected submission path does not send one.

## Live-test limits

During the October 9, 2026 exploration, the Rust SDK reached checkout with
React and Solid product-grid variants and completed a simulated Solid order
for ten pickaxes, totaling 145.00 GS. An intentionally wrong quantity
assertion stopped the Flow before its checkout click.

The executable above also completed two fresh-session React runs: ten
pickaxes for 145.00 GS and three chisel sets for 19.50 GS. Both retained
successful preparation and submission outcomes and confirmation screenshots.

Two Svelte selections left the active product grid blank and its Astro
island marked `ssr`. The readiness assertion stopped those runs, and a
screenshot confirmed the blank grid. The cause remains unresolved; this is
not evidence that every framework variant passes. Live-site behavior can
change, and the example stops on readiness failure rather than silently
reloading until a different variant works.
