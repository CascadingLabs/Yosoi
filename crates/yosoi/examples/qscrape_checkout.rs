//! A modular, live-browser checkout example for the 0.2.0 Rust spike.
//!
//! Run from the repository root with regular sandboxed Chrome available:
//! cargo run -p yosoi --features browser --example qscrape_checkout --
//!   .generated/qscrape-checkout pickaxe 10
//!
//! `chisel 3` uses the same recipes for another product. The fixed destination
//! is Qscrape's simulated shop; every checkout field below is synthetic.
//! See docs/public/sdk/flows.md for Flow execution and failure behavior.

use std::{env, error::Error, fs, io, path::Path};
use yosoi::{
    action,
    flow::{
        self, Condition, Continuation, FailureCapturePolicy, Flow, FlowOutcome, FlowTermination,
        StopScope,
    },
    policy::{Acquisition, BrowserMode, DocumentRequest, Page, Policy},
    session::{self, SessionPolicy, Work},
};

const SHOP: &str = "https://qscrape.dev/l2/eshop/";
// L2 mounts several framework variants. Only one product-grid variant is visible.
const ACTIVE_GRID: &str = "[data-slot=\"product-grid\"] [data-fw]:not([hidden])";
const READY_TIMEOUT_MS: u64 = 5_000;

#[derive(Clone, Copy)]
struct Product {
    sku: &'static str,
    unit_price_cents: u32,
}

const PICKAXE: Product = Product {
    sku: "VM-MIN-001",
    unit_price_cents: 1_450,
};
const CHISEL: Product = Product {
    sku: "VM-MIN-003",
    unit_price_cents: 650,
};

#[tokio::main(flavor = "current_thread")]
#[expect(
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn main() -> Result<(), Box<dyn Error>> {
    let mut args = env::args().skip(1);
    let output = args.next().ok_or_else(|| {
        io::Error::other("usage: qscrape_checkout <evidence-dir> [pickaxe|chisel] [quantity:1..20]")
    })?;
    let product = match args.next().as_deref() {
        None | Some("pickaxe") => PICKAXE,
        Some("chisel") => CHISEL,
        Some(_) => return Err(io::Error::other("choose pickaxe or chisel").into()),
    };
    let quantity = args
        .next()
        .map(|value| value.parse::<u32>())
        .transpose()?
        .unwrap_or(10);
    if !(1..=20).contains(&quantity) || args.next().is_some() {
        return Err(
            io::Error::other("quantity must be 1..20; unexpected arguments are rejected").into(),
        );
    }
    fs::create_dir_all(&output)?;

    let policy = Policy {
        page: Page::new(vec![
            Acquisition::Browser(BrowserMode::Headless).documents([DocumentRequest::RenderedDom]),
        ])?,
        ..Policy::default()
    };
    // No arbitrary JavaScript is needed: navigation, clicks, typing and assertions
    // all use the SDK's typed operations. A fresh Session owns an isolated cart.
    let session = session::new()
        .bind(&policy)
        .configure(SessionPolicy::default())
        .acquire()
        .await?;
    let lease = match session.work().await {
        Ok(lease) => lease,
        Err(error) => {
            session.close().await?;
            return Err(error.into());
        }
    };

    let result = shop(&lease, product, quantity, Path::new(&output)).await;
    // Both cleanup operations run even when a recipe or assertion fails.
    let released = lease.release().await;
    let closed = session.close().await;
    if let Err(error) = &released {
        eprintln!("lease release: {error}");
    }
    if let Err(error) = &closed {
        eprintln!("Session close: {error}");
    }
    result?;
    released?;
    closed?;
    Ok(())
}

async fn shop(
    lease: &Work,
    product: Product,
    quantity: u32,
    output: &Path,
) -> Result<(), Box<dyn Error>> {
    let total_cents = product
        .unit_price_cents
        .checked_mul(quantity)
        .ok_or_else(|| io::Error::other("order total exceeded its numeric bound"))?;
    let total = format!("{}.{:02}", total_cents / 100, total_cents % 100);

    // Each child is itself a Flow. Swapping the product reuses all four recipes.
    let prepare_order = compose([
        flow::new([action::navigate(SHOP)]),
        select_product(product),
        add_to_cart(product),
        increase_quantity_from_one(product, quantity),
        begin_checkout(product, quantity, &total),
    ]);
    let prepared = prepare_order.with_lease(lease).invoke().await?;
    record_and_require_completion("prepare-order", &prepared, output)?;
    println!("Checkout ready: {} × {quantity}, {total} GS", product.sku);

    // Keeping submission separate gives callers a natural inspection boundary.
    // This page's submission only generates a local reference and clears its
    // localStorage cart. These synthetic values are not a real payment method.
    let submit_order = compose([fill_test_checkout(), confirm_test_order()]);
    let submitted = submit_order.with_lease(lease).invoke().await?;
    record_and_require_completion("submit-order", &submitted, output)?;
    println!("Simulated order confirmed; evidence: {}", output.display());
    Ok(())
}

fn select_product(product: Product) -> Flow {
    let card = active(format!("article[data-sku=\"{}\"]", product.sku));
    let detail = active(format!(
        "[data-component=\"eshop-product-detail\"][data-sku=\"{}\"]",
        product.sku
    ));
    flow::new([
        wait_visible(card.clone()),
        action::click(card),
        wait_visible(detail),
    ])
}

fn add_to_cart(product: Product) -> Flow {
    let detail = active(format!(
        "[data-component=\"eshop-product-detail\"][data-sku=\"{}\"]",
        product.sku
    ));
    flow::new([
        assert_visible(format!("{detail} [data-in-stock=\"true\"]")),
        action::click(format!("{detail} [data-in-stock=\"true\"] + button")),
        // Add to Cart already changes the view to cart on this shop.
        wait_visible(format!("{} [data-qty=\"1\"]", cart_row(product))),
    ])
}

fn increase_quantity_from_one(product: Product, quantity: u32) -> Flow {
    let row = cart_row(product);
    // This recipe has a real precondition. Repeating it on a nonempty cart must
    // fail instead of silently adding another nine items and calling that ten.
    let mut steps = vec![assert_visible(format!("{row} [data-qty=\"1\"]"))];
    for _ in 1..quantity {
        steps.push(action::click(format!("{row} [data-qty] + button")));
    }
    steps.push(assert_visible(format!("{row} [data-qty=\"{quantity}\"]")));
    flow::new(steps)
}

fn begin_checkout(product: Product, quantity: u32, total: &str) -> Flow {
    let row = cart_row(product);
    flow::new([
        assert_visible(format!("{row} [data-qty=\"{quantity}\"]")),
        assert_visible(format!("{row} [data-line-total=\"{total}\"]")),
        action::click(active(
            "[data-component=\"eshop-cart\"] > button:last-of-type",
        )),
        wait_visible(active(format!(
            "[data-component=\"eshop-checkout\"] [data-checkout-total=\"{total}\"]"
        ))),
    ])
}

fn fill_test_checkout() -> Flow {
    let fields = [
        ("First name", "Aldric"),
        ("Last name", "Blackwood"),
        ("Email", "flow-test@example.com"),
        ("Address", "12 Irongate Lane"),
        ("City", "Stonehaven"),
        ("Province", "Valdris"),
        ("Post code", "VD-1401"),
        ("Card number", "4111 1111 1111 1111"),
        ("Expiry", "12 / 30"),
        ("CVV", "123"),
    ];
    flow::new(fields.into_iter().map(|(label, value)| {
        action::enter_text(
            active(format!(
                "[data-component=\"eshop-checkout\"] input[data-label=\"{label}\"]"
            )),
            value,
        )
    }))
}

fn confirm_test_order() -> Flow {
    flow::new([
        action::click(active("[data-component=\"eshop-checkout\"] div button")),
        // A successful click can still leave validation errors on the page.
        // Confirmation shares the catalog's URL, so verify the view and reference.
        wait_visible(active(
            "[data-component=\"eshop-confirm\"] [data-order-id^=\"VM-312-\"]",
        )),
        action::screenshot(),
    ])
}

/// Authoring composition for this spike, not native nested execution.
/// Child order is preserved; child names/boundaries are flattened in receipts.
/// Failure capture is configured once on the resulting parent recipe.
fn compose(children: impl IntoIterator<Item = Flow>) -> Flow {
    flow::new(children.into_iter().flat_map(|child| child.steps))
        .on_failure(Continuation::Stop(StopScope::Invocation))
        .with_failure_capture(FailureCapturePolicy::Screenshot)
}

fn active(selector: impl AsRef<str>) -> String {
    format!("{ACTIVE_GRID} {}", selector.as_ref())
}

fn cart_row(product: Product) -> String {
    active(format!(
        "[data-component=\"eshop-cart\"] [data-sku=\"{}\"]",
        product.sku
    ))
}

fn assert_visible(selector: String) -> flow::Step {
    action::assert(Condition::Visible { selector }).into()
}

const fn wait_visible(selector: String) -> flow::Step {
    action::wait_until(Condition::Visible { selector }, READY_TIMEOUT_MS)
}

fn record_and_require_completion(
    name: &str,
    outcome: &FlowOutcome,
    output: &Path,
) -> Result<(), Box<dyn Error>> {
    // Persist receipts before checking success, so a stopped run stays inspectable.
    fs::write(
        output.join(format!("{name}.json")),
        serde_json::to_vec_pretty(outcome)?,
    )?;
    let screenshot = outcome
        .failure_capture
        .as_ref()
        .and_then(|receipt| receipt.observation.as_ref())
        .and_then(|observation| observation.screenshot.as_ref())
        .or_else(|| {
            outcome.steps.iter().rev().find_map(|step| {
                step.receipt
                    .observation
                    .as_ref()
                    .and_then(|observation| observation.screenshot.as_ref())
            })
        });
    if let Some(bytes) = screenshot {
        fs::write(output.join(format!("{name}.png")), bytes)?;
    }
    if outcome.terminal != FlowTermination::Completed {
        return Err(io::Error::other(format!(
            "{name} stopped with {:?}; inspect {name}.json for the terminal step",
            outcome.terminal,
        ))
        .into());
    }
    Ok(())
}
