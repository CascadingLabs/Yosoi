use std::{
    error::Error,
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
};
use yosoi::assertions as yosoi_assertions;
use yosoi::contracts::FieldIssue;
use yosoi::{
    action::{self, check},
    assertions::{AssertionGroup, SourceError},
    flow::{self, Flow, FlowInvokeError, FlowValidationError, Step},
    prelude as ys,
};

#[derive(ys::Contract)]
#[ys(id = "cart", description = "Cart observation", root = ys::locator::css("article"))]
struct Cart {
    #[ys(description = "Price", locator = ys::locator::css(".price").text())]
    price: ys::Money,
    #[ys(description = "Items", locator = ys::locator::css(".item").text())]
    items: Vec<String>,
}
fn document(html: &str) -> Result<ys::Document, Box<dyn Error>> {
    Ok(ys::Document::html(
        "cart-fixture",
        html.as_bytes().to_vec(),
    )?)
}
const CART: &str =
    "<article><b class=price>$4.50</b><i class=item>A</i><i class=item>B</i></article>";

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
fn normal_operators_borrowed_captures_and_all_results() -> Result<(), Box<dyn Error>> {
    let expected = 450i64;
    let calls = AtomicUsize::new(0);
    let group = AssertionGroup::<Cart>::new(
        Cart::plan()?.clone(),
        [
            check(|cart: &Cart| {
                calls.fetch_add(1, Ordering::SeqCst);
                cart.price.minor_units() == expected
            }),
            check(|cart: &Cart| {
                calls.fetch_add(1, Ordering::SeqCst);
                cart.items.len() > 2
            })
            .named("count"),
            check(|cart: &Cart| {
                calls.fetch_add(1, Ordering::SeqCst);
                cart.items.contains(&"C".to_owned())
            }),
            check(|cart: &Cart| {
                calls.fetch_add(1, Ordering::SeqCst);
                (400..=500).contains(&cart.price.minor_units())
            }),
        ],
    );
    let report = group.evaluate(&document(CART)?)?;
    assert!(!report.passed);
    assert_eq!(calls.load(Ordering::SeqCst), 4);
    assert_eq!(
        report
            .checks
            .iter()
            .map(|check| check.passed)
            .collect::<Vec<_>>(),
        [Some(true), Some(false), Some(false), Some(true)]
    );
    assert_eq!(
        report.checks.get(1).and_then(|check| check.name.as_deref()),
        Some("count")
    );
    let encoded = serde_json::to_string(&report)?;
    let reopened: yosoi_assertions::AssertionReport = serde_json::from_str(&encoded)?;
    assert_eq!(reopened.checks, report.checks);
    assert_eq!(calls.load(Ordering::SeqCst), 4); // Opening results executes no predicates.
    Ok(())
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
fn invalid_contract_never_runs_predicates() -> Result<(), Box<dyn Error>> {
    let calls = AtomicUsize::new(0);
    let group = AssertionGroup::<Cart>::new(
        Cart::plan()?.clone(),
        [check(|_| {
            calls.fetch_add(1, Ordering::SeqCst);
            true
        })],
    );
    for html in [
        "<article><i class=item>A</i></article>",
        "<article><b class=price>bad</b></article>",
        "<article><b class=price>$4.50</b><b class=price>$5.00</b></article>",
    ] {
        let report = group.evaluate(&document(html)?)?;
        assert!(!report.passed);
        assert_eq!(report.source_error, Some(SourceError::InvalidContract));
        assert!(report.checks.iter().all(|check| check.passed.is_none()));
        assert_ne!(report.field_issues, Vec::<FieldIssue>::new());
    }
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    let missing = group.evaluate(&document("<p>empty</p>")?)?;
    assert_eq!(
        missing.source_error,
        Some(SourceError::RecordCount { actual: 0 })
    );
    let repeated = group.evaluate(&document(&format!("{CART}{CART}"))?)?;
    assert_eq!(
        repeated.source_error,
        Some(SourceError::RecordCount { actual: 2 })
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn saved_recipes_require_explicit_rebinding_before_acquisition() -> Result<(), Box<dyn Error>>
{
    let calls = Arc::new(AtomicUsize::new(0));
    let captured = calls.clone();
    let step = action::assert_all::<Cart>(
        Cart::plan()?,
        [check(move |cart: &Cart| {
            captured.fetch_add(1, Ordering::SeqCst);
            !cart.items.is_empty()
        })],
    )
    .into();
    let original = flow::new([step, action::click("#next")]);
    let encoded = serde_json::to_string(&original)?;
    assert!(encoded.contains("assert_all"));
    let mut decoded: Flow = serde_json::from_str(&encoded)?;
    assert_eq!(decoded, original);
    assert!(matches!(
        decoded.invoke().await,
        Err(FlowInvokeError::InvalidFlow(
            FlowValidationError::Assertion(yosoi_assertions::AssertionError::Unbound)
        ))
    ));
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    let nested =
        flow::new([flow::new([original.clone().into()]).timeout(30_000).into()]).timeout(10_000);
    let saved_nested: Flow = serde_json::from_str(&serde_json::to_string(&nested)?)?;
    saved_nested.validate()?;
    assert!(matches!(
        saved_nested.invoke().await,
        Err(FlowInvokeError::InvalidFlow(
            FlowValidationError::Assertion(yosoi_assertions::AssertionError::Unbound)
        ))
    ));
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    match decoded.steps.first_mut() {
        Some(Step::AssertAll { assertion }) => {
            assert!(!assertion.is_bound());
            assertion.rebind::<Cart>([check(|cart: &Cart| !cart.items.is_empty())])?;
            assert!(assertion.is_bound());
        }
        _ => panic!("fixture assertion missing"),
    }
    Ok(())
}

#[test]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
fn empty_and_excessive_groups_and_bad_names_are_rejected() -> Result<(), Box<dyn Error>> {
    for count in [0, 129] {
        let group =
            AssertionGroup::<Cart>::new(Cart::plan()?.clone(), (0..count).map(|_| check(|_| true)));
        assert_eq!(
            group.evaluate(&document(CART)?).unwrap_err(),
            yosoi_assertions::AssertionError::CheckCount
        );
    }
    let group = AssertionGroup::<Cart>::new(Cart::plan()?.clone(), [check(|_| true).named(" ")]);
    assert_eq!(
        group.evaluate(&document(CART)?).unwrap_err(),
        yosoi_assertions::AssertionError::CheckName
    );
    Ok(())
}
