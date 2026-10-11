//! Ordinary Rust assertions over one existing Contract plan.
//! Run without a browser: cargo run -p yosoi --example assertion_groups
use std::error::Error;
use yosoi::{
    action::{self, check},
    assertions::AssertionGroup,
    flow, prelude as ys,
};

#[derive(ys::Contract)]
#[ys(id = "cart", description = "Observed cart")]
struct Cart {
    #[ys(description="Cart total",locator=ys::locator::css(".total").text())]
    total: ys::Money,
    #[ys(description="Product names",locator=ys::locator::css(".item").text())]
    items: Vec<String>,
}
fn main() -> Result<(), Box<dyn Error>> {
    let document = ys::Document::html(
        "cart-example",
        b"<b class=total>$4.50</b><span class=item>Tea</span>".to_vec(),
    )?;
    let expected_minor_units = 450;
    // A local group may borrow values. Every check sees this same validated Cart.
    let report = AssertionGroup::<Cart>::new(
        Cart::plan()?.clone(),
        [
            check(|cart: &Cart| cart.total.minor_units() == expected_minor_units),
            check(|cart: &Cart| cart.items.len() == 1),
            check(|cart: &Cart| cart.items.iter().any(|name| name == "Tea")),
        ],
    )
    .evaluate(&document)?;
    println!("{}", serde_json::to_string_pretty(&report)?);
    // Stored Flow checks own captures, because the recipe can outlive this scope.
    let checkout = flow::new([
        action::assert_all::<Cart>(
            Cart::plan()?,
            [
                check(move |cart: &Cart| cart.total.minor_units() == expected_minor_units),
                check(|cart: &Cart| cart.items.len() == 1),
            ],
        )
        .on_failure(ys::Stop(ys::Invocation))
        .into(),
        action::click("#proceed-to-checkout"),
    ]);
    checkout.validate()?;
    // With a browser lease whose current page contains the cart:
    // checkout.with_lease(&lease).invoke().await?.require_completed()?;
    if !report.passed {
        return Err("cart checks failed".into());
    }
    Ok(())
}
