//! Validate Qscrape's cart Contract inside a Flow, then check its total.
//!
//! cargo run -p yosoi --features browser --example qscrape_cart_assertion -j 1 --
//!   .generated/qscrape-cart-assertion 10.00
//!
//! One pickaxe costs 14.50 GS. The default 10.00 expectation deliberately fails
//! and prevents the checkout click. Pass 14.50 to demonstrate success instead.
use std::{env, error::Error, fs, io, path::PathBuf};
use yosoi::{
    action::{self, check},
    flow::{self, Condition, FailureCapturePolicy},
    policy::{Acquisition, BrowserMode, DocumentRequest, Page, Policy},
    prelude as ys,
};

const PRODUCT_CARD: &str =
    "[data-slot='product-grid'] [data-fw]:not([hidden]) article[data-sku='VM-MIN-001']";
const ADD_TO_CART: &str = "[data-slot='product-grid'] [data-fw]:not([hidden]) [data-component='eshop-product-detail'][data-sku='VM-MIN-001'] [data-in-stock='true'] + button";
const CART_TOTAL: &str = "[data-slot='product-grid'] [data-fw]:not([hidden]) [data-component='eshop-cart'] [data-cart-total]";
const CHECKOUT_BUTTON: &str = "[data-slot='product-grid'] [data-fw]:not([hidden]) [data-component='eshop-cart'] > button:last-of-type";

#[derive(ys::Contract)]
#[ys(id="qscrape_cart", description="One Qscrape cart", root=ys::locator::css("[data-slot='product-grid'][data-active-fw='react'] [data-fw='react'] [data-component='eshop-cart'], [data-slot='product-grid'][data-active-fw='vue'] [data-fw='vue'] [data-component='eshop-cart'], [data-slot='product-grid'][data-active-fw='svelte'] [data-fw='svelte'] [data-component='eshop-cart'], [data-slot='product-grid'][data-active-fw='solid'] [data-fw='solid'] [data-component='eshop-cart']"))]
struct Cart {
    // Retain the shop's price text; application code owns its currency semantics.
    #[ys(description="GS total", locator=ys::locator::css("[data-cart-total]").attribute("data-cart-total"))]
    total: String,
    #[ys(description="Product identities", locator=ys::locator::css("[data-sku]").attribute("data-sku"))]
    skus: Vec<String>,
    #[ys(description="Quantity of the single cart line", locator=ys::locator::css("[data-qty]").attribute("data-qty"))]
    quantity: String,
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn Error>> {
    let mut args = env::args().skip(1);
    let output = PathBuf::from(args.next().ok_or_else(|| {
        io::Error::other("usage: qscrape_cart_assertion <evidence-dir> [expected-total]")
    })?);
    let expected_total = args.next().unwrap_or_else(|| "10.00".to_owned());
    if args.next().is_some() {
        return Err(io::Error::other("unexpected argument").into());
    }
    fs::create_dir_all(&output)?;
    println!("Expected cart total: {expected_total} GS");

    let shopping = flow::new([
        action::navigate("https://qscrape.dev/l2/eshop/"),
        action::wait_until(
            Condition::Visible {
                selector: PRODUCT_CARD.into(),
            },
            5_000,
        ),
        action::click(PRODUCT_CARD),
        action::wait_until(
            Condition::Visible {
                selector: ADD_TO_CART.into(),
            },
            5_000,
        ),
        action::click(ADD_TO_CART),
        action::wait_until(
            Condition::Visible {
                selector: CART_TOTAL.into(),
            },
            5_000,
        ),
        // Capture once, validate Cart, then run ordinary Rust comparisons.
        action::assert_all::<Cart>(
            Cart::plan()?,
            [
                check(move |cart: &Cart| cart.total == expected_total),
                check(|cart: &Cart| {
                    cart.skus.len() == 1 && cart.skus.first().is_some_and(|sku| sku == "VM-MIN-001")
                }),
                check(|cart: &Cart| cart.quantity == "1"),
            ],
        )
        .into(),
        // This action cannot run if the group fails.
        action::click(CHECKOUT_BUTTON),
    ])
    .with_failure_capture(FailureCapturePolicy::Screenshot);

    let policy = Policy {
        page: Page::new(vec![
            Acquisition::Browser(BrowserMode::Headless).documents([DocumentRequest::RenderedDom]),
        ])?,
        ..Policy::default()
    };
    let outcome = shopping.bind(&policy).invoke().await?;
    fs::write(
        output.join("outcome.json"),
        serde_json::to_vec_pretty(&outcome)?,
    )?;
    for step in &outcome.steps {
        if step.receipt.kind == "assert_all"
            && let Some(result) = &step.receipt.result
        {
            println!("{}", serde_json::to_string_pretty(result)?);
        }
    }
    println!(
        "Flow status: {:?}; executed {} of {} steps",
        outcome.terminal,
        outcome.steps.len(),
        outcome.flow.steps.len()
    );
    outcome.require_completed()?;
    Ok(())
}
