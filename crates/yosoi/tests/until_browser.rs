#![cfg(feature = "browser")]

//! Event-gated browser acceptance for eventual assertions.
//!
//! Opt in with `YOSOI_BROWSER_TESTS=1` when running on regular Chrome Stable.

use std::fs as std_fs;
use std::future as std_future;
use std::path as std_path;
use std::{
    env,
    error::Error,
    future::Future,
    io,
    pin::Pin,
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
    task::Poll,
    time::Duration,
};
use yosoi::expect as yosoi_expect;

use tokio::time::timeout;
use tokio_util::sync::CancellationToken;
use yosoi::{
    action::{self, check},
    assertions::{AssertionReport, CheckError, SourceError},
    automation_record::{AutomationRecord, OperationStatus},
    expect,
    flow::{
        self, Condition, Continuation, FlowInvokeError, FlowOutcome, FlowTermination, StopScope,
    },
    prelude as ys,
    session::{
        self, ExecutionPool, SessionPolicy, UntilCheck, UntilCheckState, UntilReport,
        UntilTermination,
    },
};

#[path = "support/until_fixture.rs"]
mod fixture;

type TestError = Box<dyn Error + Send + Sync>;
type Invocation<'a> = Pin<Box<dyn Future<Output = Result<FlowOutcome, FlowInvokeError>> + 'a>>;

#[derive(ys::Contract)]
#[ys(
    id = "until-contract",
    description = "A fixture receipt and status",
    root = ys::locator::css("#contract")
)]
struct UntilContract {
    #[ys(
        description = "Receipt",
        locator = ys::locator::css("#contract-receipt").text()
    )]
    receipt: String,
    #[ys(
        description = "Status",
        locator = ys::locator::css("#contract-status").text()
    )]
    status: String,
}

#[derive(ys::Contract)]
#[ys(
    id = "until-invalid-money",
    description = "A deliberately invalid money field",
    root = ys::locator::css("#contract")
)]
struct InvalidMoneyContract {
    #[ys(
        description = "Price",
        locator = ys::locator::css("#contract-price").text()
    )]
    price: ys::Money,
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn trigger_until_correlates_fresh_response_waits_for_all_evidence_and_yields_capacity()
-> Result<(), TestError> {
    if !enabled() {
        return Ok(());
    }

    let mut fixture = fixture::UntilFixture::start().await?;
    let pool = ExecutionPool::new(1, 4)?;
    let browser = session::new()
        .configure(browser_settings(2))
        .execution_pool(&pool)
        .acquire()
        .await?;
    let a = browser.work().await?;
    let b_tab = browser.new_tab().await?;
    let b = b_tab.work().await?;
    a.navigate(&fixture.url("/until?attempt=current&stale=1&stages=1&noise=512"))
        .await?;
    b.navigate(&fixture.url("/until?attempt=other")).await?;

    let expectation = expect::all([
        expect::response(fixture.url("/api?attempt=current"))
            .status(200)
            .json("/attempt", "current")
            .into(),
        expect::ax("Ready current").role("button").into(),
        expect::visible("#receipt"),
    ]);
    let flow = flow::new([action::click("#trigger").until(expectation).timeout(10_000)]);
    let bound = flow.with_lease(&a);
    let mut invocation: Invocation<'_> = Box::pin(bound.invoke());

    let trigger =
        request_before_result(&mut invocation, &mut fixture, "/trigger?attempt=current").await?;
    assert_eq!(trigger.method, "GET");

    // An earlier response from the same endpoint carries a different attempt ID.
    // It must remain pending until the current response arrives.
    let old = correlated_request_before_result(
        &mut invocation,
        &mut fixture,
        "/api?attempt=current",
        "old",
    )
    .await?;
    fixture.release("api:old")?;
    let current = correlated_request_before_result(
        &mut invocation,
        &mut fixture,
        "/api?attempt=current",
        "current",
    )
    .await?;
    assert_eq!(old.method, current.method);
    assert_eq!(old.target, current.target);
    assert_eq!(old.correlation.as_deref(), Some("old"));
    assert_eq!(current.correlation.as_deref(), Some("current"));

    // The current response is deliberately held while a second tab uses the
    // single shared worker. A competing write to the waiting tab stays fenced.
    let mut other_tab_observation = Box::pin(b.observe());
    let observed_b = tokio::select! {
        biased;
        result = invocation.as_mut() => {
            let outcome = result?;
            return Err(io::Error::other(format!(
                "Until passed before current response release: {:?}", outcome.terminal
            )).into());
        }
        result = timeout(Duration::from_secs(5), other_tab_observation.as_mut()) => result??,
    };
    assert_eq!(
        observed_b.url.as_deref(),
        Some(fixture.url("/until?attempt=other").as_str())
    );

    let mut competing_write = Box::pin(a.click("#trigger"));
    let write_result = std_future::poll_fn(|context| {
        Poll::Ready(match competing_write.as_mut().poll(context) {
            Poll::Pending => None,
            Poll::Ready(result) => Some(result),
        })
    })
    .await;
    assert!(
        write_result.is_none() || write_result.as_ref().is_some_and(Result::is_err),
        "a second write reached the tab while Until retained ownership"
    );
    drop(competing_write);
    assert_eq!(fixture.request_count("/trigger?attempt=current")?, 1);

    // The response is released immediately after the click has started. Until
    // still waits for the separately gated DOM and accessibility updates.
    fixture.release("api:current")?;
    request_before_result(&mut invocation, &mut fixture, "/gate/dom?attempt=current").await?;
    fixture.release("dom:current")?;
    request_before_result(&mut invocation, &mut fixture, "/gate/ax?attempt=current").await?;
    fixture.release("ax:current")?;

    let outcome = timeout(Duration::from_secs(12), &mut invocation).await??;
    save_outcome("until-multi-source-confirmation", &outcome)?;
    assert_eq!(outcome.terminal, FlowTermination::Completed);
    let step = outcome
        .steps
        .first()
        .ok_or("Until did not retain its result")?;
    assert_eq!(step.receipt.status, OperationStatus::Observed);
    let report = until_report(&outcome)?;
    assert_eq!(report.termination, UntilTermination::Satisfied);
    assert_eq!(
        report.trigger.as_ref().map(|receipt| receipt.status),
        Some(OperationStatus::Observed)
    );
    assert!(
        report.evaluations >= 2,
        "the expectation was not re-evaluated"
    );
    assert!(
        report
            .checks
            .iter()
            .all(|check| check.state == UntilCheckState::Satisfied)
    );
    let dom_check = report
        .checks
        .get(2)
        .ok_or("Until omitted its DOM confirmation")?;
    assert_eq!(
        dom_check
            .evidence
            .as_ref()
            .and_then(|evidence| evidence.get("actual"))
            .and_then(serde_json::Value::as_bool),
        Some(true)
    );
    let ax_check = report
        .checks
        .get(1)
        .ok_or("Until omitted its accessibility confirmation")?;
    assert_eq!(
        ax_check
            .evidence
            .as_ref()
            .and_then(|evidence| evidence.get("name"))
            .and_then(serde_json::Value::as_str),
        Some("Ready current")
    );
    assert_eq!(
        ax_check
            .evidence
            .as_ref()
            .and_then(|evidence| evidence.get("role"))
            .and_then(serde_json::Value::as_str),
        Some("button")
    );
    assert_eq!(fixture.request_count("/trigger?attempt=current")?, 1);
    assert_eq!(fixture.request_count("/api?attempt=current")?, 2);
    assert_eq!(pool.snapshot().active, 0);
    assert_eq!(pool.snapshot().parked, 0);
    assert_eq!(pool.snapshot().queued, 0);

    drop(invocation);

    drop(other_tab_observation);
    a.release().await?;
    b.release().await?;
    browser.close().await?;
    fixture.shutdown().await?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn immediate_trigger_response_is_not_lost_by_observation_setup() -> Result<(), TestError> {
    if !enabled() {
        return Ok(());
    }

    let mut fixture = fixture::UntilFixture::start().await?;
    let pool = ExecutionPool::new(1, 4)?;
    let browser = session::new()
        .configure(browser_settings(1))
        .execution_pool(&pool)
        .acquire()
        .await?;
    let work = browser.work().await?;
    work.navigate(&fixture.url("/until?attempt=fast&fast=1"))
        .await?;
    let flow = flow::new([action::click("#trigger").until(
        expect::response(fixture.url("/api?attempt=fast&fast=1"))
            .method("GET")
            .status(200)
            .json("/attempt", "fast"),
    )]);
    let bound = flow.with_lease(&work);
    let outcome = timeout(Duration::from_secs(12), bound.invoke()).await??;
    save_outcome("until-immediate-response-confirmation", &outcome)?;

    let trigger = fixture.wait_for("/trigger?attempt=fast").await?;
    let response = fixture.wait_for("/api?attempt=fast&fast=1").await?;
    assert_eq!(trigger.method, "GET");
    assert_eq!(response.method, "GET");
    assert_eq!(outcome.terminal, FlowTermination::Completed);
    let report = until_report(&outcome)?;
    assert_eq!(report.termination, UntilTermination::Satisfied);
    assert_eq!(
        report.trigger.as_ref().map(|receipt| receipt.status),
        Some(OperationStatus::Observed)
    );
    assert_eq!(fixture.request_count("/trigger?attempt=fast")?, 1);
    assert_eq!(fixture.request_count("/api?attempt=fast&fast=1")?, 1);

    work.release().await?;
    browser.close().await?;
    fixture.shutdown().await?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn background_enter_text_until_yields_capacity_and_confirms_the_typed_value()
-> Result<(), TestError> {
    if !enabled() {
        return Ok(());
    }

    let mut fixture = fixture::UntilFixture::start().await?;
    let pool = ExecutionPool::new(1, 4)?;
    let browser = session::new()
        .configure(input_session_policy(2))
        .execution_pool(&pool)
        .acquire()
        .await?;
    let work_a = browser.work().await?;
    work_a
        .navigate(&fixture.url("/enter-until?attempt=typing-a&expected=Blueberry-42"))
        .await?;
    let tab_b = browser.new_tab().await?;
    let work_b = tab_b.work().await?;
    work_b
        .navigate(&fixture.url("/enter-until?attempt=foreground-b"))
        .await?;

    let typed_value = "Blueberry-42";
    let confirmation = format!("#confirmation[data-value=\"{typed_value}\"]");
    let expectation = expect::all([
        expect::visible(confirmation),
        expect::ax(format!("Entered {typed_value}"))
            .role("status")
            .into(),
    ]);
    let flow = flow::new([action::enter_text("#entry", typed_value)
        .until(expectation)
        .timeout(10_000)]);
    let bound = flow.with_lease(&work_a);
    let mut invocation: Invocation<'_> = Box::pin(bound.invoke());
    let input_event = request_before_result(
        &mut invocation,
        &mut fixture,
        "/gate/contract?attempt=typing-a&phase=input",
    )
    .await?;
    assert_eq!(input_event.method, "GET");

    // The page holds DOM and AX confirmation behind this gate. A second tab
    // must still use the single controller worker while A retains its lease.
    let foreground = tokio::select! {
        result = invocation.as_mut() => {
            let outcome = result?;
            save_outcome("until-typing-before-gate-release", &outcome)?;
            return Err(io::Error::other("typing Until completed before the confirmation gate was released").into());
        }
        result = timeout(Duration::from_secs(5), work_b.observe()) => result??,
    };
    assert_eq!(
        foreground.url.as_deref(),
        Some(fixture.url("/enter-until?attempt=foreground-b").as_str())
    );
    fixture.release("contract:typing-a:input")?;

    let outcome = timeout(Duration::from_secs(12), &mut invocation).await??;
    save_outcome("until-background-enter-text", &outcome)?;
    assert_eq!(outcome.terminal, FlowTermination::Completed);
    let step = outcome
        .steps
        .first()
        .ok_or("EnterText Until lost its Flow step")?;
    assert_eq!(step.receipt.status, OperationStatus::Observed);
    let report = until_report(&outcome)?;
    assert_eq!(report.termination, UntilTermination::Satisfied);
    assert_eq!(report.checks.len(), 2);
    assert_eq!(
        report
            .checks
            .iter()
            .map(|check| check.source.as_str())
            .collect::<Vec<_>>(),
        ["dom", "accessibility"]
    );
    assert!(
        report
            .checks
            .iter()
            .all(|check| check.state == UntilCheckState::Satisfied)
    );
    let trigger = report
        .trigger
        .as_ref()
        .ok_or("EnterText Until omitted its trigger receipt")?;
    let dom_check = report
        .checks
        .first()
        .ok_or("EnterText Until omitted its DOM confirmation")?;
    assert_eq!(
        dom_check
            .evidence
            .as_ref()
            .and_then(|evidence| evidence.get("actual"))
            .and_then(serde_json::Value::as_bool),
        Some(true)
    );
    let ax_check = report
        .checks
        .get(1)
        .ok_or("EnterText Until omitted its accessibility confirmation")?;
    assert_eq!(
        ax_check
            .evidence
            .as_ref()
            .and_then(|evidence| evidence.get("name"))
            .and_then(serde_json::Value::as_str),
        Some("Entered Blueberry-42")
    );
    assert_eq!(
        ax_check
            .evidence
            .as_ref()
            .and_then(|evidence| evidence.get("role"))
            .and_then(serde_json::Value::as_str),
        Some("status")
    );
    assert_eq!(trigger.kind, "enter_text");
    assert_eq!(trigger.status, OperationStatus::Observed);
    assert_eq!(
        fixture.request_count("/gate/contract?attempt=typing-a&phase=input")?,
        1
    );

    // Verify the live input property directly, then confirm the foreground B
    // tab kept its own input untouched.
    let value_receipt = work_a
        .evaluate("document.querySelector('#entry').value")
        .await?;
    assert_eq!(value_receipt.status, OperationStatus::Observed);
    assert_eq!(
        value_receipt
            .result
            .as_ref()
            .and_then(serde_json::Value::as_str),
        Some(typed_value)
    );
    let b_value = work_b
        .evaluate("document.querySelector('#entry').value")
        .await?;
    assert_eq!(
        b_value.result.as_ref().and_then(serde_json::Value::as_str),
        Some("")
    );
    let captured_html = step
        .receipt
        .observation
        .as_ref()
        .and_then(|observation| observation.html.as_deref())
        .ok_or("confirmed text entry omitted its DOM observation")?;
    assert_ne!(captured_html, "");
    let fresh_observation = timeout(Duration::from_secs(5), work_a.observe()).await??;
    assert_eq!(
        fresh_observation.document_epoch,
        report.scope.document_epoch
    );
    let fresh_html = fresh_observation
        .html
        .as_deref()
        .ok_or("fresh post-confirmation observation omitted rendered DOM")?;
    assert!(fresh_html.contains("data-value=\"Blueberry-42\""));
    assert!(fresh_html.contains("Entered Blueberry-42"));

    assert_eq!(pool.snapshot().active, 0);
    assert_eq!(pool.snapshot().parked, 0);
    assert_eq!(pool.snapshot().queued, 0);
    drop(invocation);

    work_a.release().await?;
    work_b.release().await?;
    browser.close().await?;
    fixture.shutdown().await?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn enter_text_rejects_a_focus_replaced_target_without_typing_into_the_trap()
-> Result<(), TestError> {
    if !enabled() {
        return Ok(());
    }

    let fixture = fixture::UntilFixture::start().await?;
    let pool = ExecutionPool::new(1, 4)?;
    let browser = session::new()
        .configure(input_session_policy(2))
        .execution_pool(&pool)
        .acquire()
        .await?;
    let work_a = browser.work().await?;
    work_a
        .navigate(&fixture.url("/enter-until?attempt=replace-a&replace-on-focus=1"))
        .await?;
    let tab_b = browser.new_tab().await?;
    let work_b = tab_b.work().await?;
    work_b
        .navigate(&fixture.url("/enter-until?attempt=foreground-replace-b"))
        .await?;

    let flow = flow::new([action::enter_text("#entry", "must-not-reach-trap")
        .until(expect::visible(
            "#confirmation[data-value='must-not-reach-trap']",
        ))
        .timeout(5_000)]);
    let bound = flow.with_lease(&work_a);
    let outcome = timeout(Duration::from_secs(8), bound.invoke()).await??;
    save_outcome("until-enter-text-focus-replacement", &outcome)?;
    assert_eq!(outcome.terminal, FlowTermination::CompletedWithIssues);
    let step = outcome
        .steps
        .first()
        .ok_or("focus replacement lost its EnterText Until step")?;
    assert_eq!(step.receipt.status, OperationStatus::Rejected);
    let report = until_report(&outcome)?;
    assert_eq!(report.termination, UntilTermination::TriggerFailed);
    let trigger = report
        .trigger
        .as_ref()
        .ok_or("focus replacement lost the attempted trigger receipt")?;
    assert_eq!(trigger.kind, "enter_text");
    assert_eq!(trigger.status, OperationStatus::Rejected);
    assert!(trigger.error.is_some());
    // Read the live property: checking markup alone would not prove whether
    // page-level typing reached the replacement input.
    let trap_receipt = work_a
        .evaluate(
            "(() => { const trap = document.querySelector('#trap'); return { exists: !!trap, value: trap ? trap.value : null, active: !!trap && document.activeElement === trap }; })()",
        )
        .await?;
    assert_eq!(trap_receipt.status, OperationStatus::Observed);
    let trap_state = trap_receipt
        .result
        .as_ref()
        .and_then(serde_json::Value::as_object)
        .ok_or("trap probe did not return a state object")?;
    assert_eq!(
        trap_state
            .get("exists")
            .and_then(serde_json::Value::as_bool),
        Some(true)
    );
    assert_eq!(
        trap_state.get("value").and_then(serde_json::Value::as_str),
        Some("")
    );
    assert_eq!(
        trap_state
            .get("active")
            .and_then(serde_json::Value::as_bool),
        Some(true)
    );

    let b_value = work_b
        .evaluate("document.querySelector('#entry').value")
        .await?;
    assert_eq!(
        b_value.result.as_ref().and_then(serde_json::Value::as_str),
        Some("")
    );
    assert_eq!(
        fixture.request_count("/gate/contract?attempt=replace-a&phase=input")?,
        0
    );
    assert_eq!(pool.snapshot().active, 0);
    assert_eq!(pool.snapshot().parked, 0);
    assert_eq!(pool.snapshot().queued, 0);

    work_a.release().await?;
    work_b.release().await?;
    browser.close().await?;
    fixture.shutdown().await?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn identical_network_response_started_before_trigger_cannot_satisfy_until()
-> Result<(), TestError> {
    if !enabled() {
        return Ok(());
    }

    let mut fixture = fixture::UntilFixture::start().await?;
    let browser = session::new()
        .configure(browser_settings(1))
        .acquire()
        .await?;
    let work = browser.work().await?;
    work.navigate(&fixture.url("/until?attempt=pretrigger&pretrigger=1"))
        .await?;
    let target = "/api?attempt=pretrigger";
    fixture.wait_for_correlated(target, "pretrigger").await?;

    let expected_url = fixture.url(target);
    let flow = flow::new([action::click("#trigger").until(
        expect::response(expected_url)
            .method("GET")
            .status(200)
            .json("/attempt", "current"),
    )]);
    let bound = flow.with_lease(&work);
    let mut invocation: Invocation<'_> = Box::pin(bound.invoke());
    request_before_result(&mut invocation, &mut fixture, "/trigger?attempt=pretrigger").await?;
    correlated_request_before_result(&mut invocation, &mut fixture, target, "trigger").await?;

    // The pre-trigger request has the same URL, method, status, and JSON body
    // as the expected response. Its request started before the trigger.
    fixture.release("api:pretrigger")?;
    request_before_result(&mut invocation, &mut fixture, "/marker?attempt=pretrigger").await?;
    fixture.release("api:trigger")?;

    let outcome = timeout(Duration::from_secs(8), &mut invocation).await??;
    assert_eq!(outcome.terminal, FlowTermination::Completed);
    let report = until_report(&outcome)?;
    assert_eq!(report.termination, UntilTermination::Satisfied);
    let trigger = report
        .trigger
        .as_ref()
        .ok_or("network Until lost its trigger")?;
    assert_eq!(trigger.status, OperationStatus::Observed);
    let trigger_started = trigger
        .result
        .as_ref()
        .and_then(|result| result.get("started_at_unix_us"))
        .and_then(serde_json::Value::as_u64)
        .ok_or("trigger start timestamp missing")?;
    let network_check = report.checks.first().ok_or("network check missing")?;
    let evidence = network_check
        .evidence
        .as_ref()
        .ok_or("matched network evidence missing")?;
    let network_started = evidence
        .get("started_at_unix_us")
        .and_then(serde_json::Value::as_u64)
        .ok_or("network start timestamp missing")?;
    assert!(network_started >= trigger_started);
    assert!(
        evidence
            .get("request_id")
            .and_then(serde_json::Value::as_str)
            .is_some_and(|request_id| !request_id.is_empty())
    );
    assert_eq!(fixture.request_count(target)?, 2);
    assert_eq!(fixture.request_count("/marker?attempt=pretrigger")?, 1);

    drop(invocation);

    work.release().await?;
    browser.close().await?;
    fixture.shutdown().await?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn standalone_until_uses_fresh_dom_evidence_after_the_page_changes() -> Result<(), TestError>
{
    if !enabled() {
        return Ok(());
    }

    let mut fixture = fixture::UntilFixture::start().await?;
    let pool = ExecutionPool::new(1, 4)?;
    let browser = session::new()
        .configure(browser_settings(1))
        .execution_pool(&pool)
        .acquire()
        .await?;
    let work = browser.work().await?;
    work.navigate(&fixture.url("/until?attempt=current&auto=1&stages=1"))
        .await?;
    fixture.wait_for("/api?attempt=current").await?;

    let flow = flow::new([expect::visible("#receipt").until().timeout(5_000)]);
    let bound = flow.with_lease(&work);
    let mut events = pool.subscribe();
    let mut invocation: Invocation<'_> = Box::pin(bound.invoke());
    let parked = async {
        loop {
            if events.recv().await?.parked > 0 {
                return Ok::<(), TestError>(());
            }
        }
    };
    wait_for_parked(&mut invocation, parked, "standalone Until").await?;
    fixture.release("api:current")?;
    request_before_result(&mut invocation, &mut fixture, "/gate/dom?attempt=current").await?;
    fixture.release("dom:current")?;

    let outcome = timeout(Duration::from_secs(8), &mut invocation).await??;
    assert_eq!(outcome.terminal, FlowTermination::Completed);
    let report = until_report(&outcome)?;
    assert_eq!(report.termination, UntilTermination::Satisfied);
    assert!(report.trigger.is_none());
    assert!(report.evaluations >= 2);
    assert!(
        report
            .checks
            .iter()
            .all(|check| check.state == UntilCheckState::Satisfied)
    );

    drop(invocation);

    work.release().await?;
    browser.close().await?;
    fixture.shutdown().await?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn contract_until_checks_one_fresh_record_and_immediate_assertion_stays_one_shot()
-> Result<(), TestError> {
    if !enabled() {
        return Ok(());
    }

    let mut fixture = fixture::UntilFixture::start().await?;
    let pool = ExecutionPool::new(1, 4)?;
    let browser = session::new()
        .configure(browser_settings(1))
        .execution_pool(&pool)
        .acquire()
        .await?;
    let work = browser.work().await?;

    // The ContractBuilder::until form observes a page-driven update with no
    // trigger. The first two states satisfy opposite predicates; both only
    // pass together in the final captured record.
    work.navigate(&fixture.url("/until?attempt=standalone&auto=1&contract=1"))
        .await?;
    fixture.wait_for("/api?attempt=standalone").await?;
    let flow = flow::new([until_contract_assertion("standalone")?
        .timeout(10_000)
        .until()]);
    let bound = flow.with_lease(&work);
    let mut events = pool.subscribe();
    let mut invocation: Invocation<'_> = Box::pin(bound.invoke());
    let parked = async {
        loop {
            if events.recv().await?.parked > 0 {
                return Ok::<(), TestError>(());
            }
        }
    };
    wait_for_parked(&mut invocation, parked, "Contract assertion").await?;
    fixture.release("api:standalone")?;
    request_before_result(
        &mut invocation,
        &mut fixture,
        "/gate/contract?attempt=standalone&phase=first",
    )
    .await?;
    fixture.release("contract:standalone:first")?;
    request_before_result(
        &mut invocation,
        &mut fixture,
        "/gate/contract?attempt=standalone&phase=second",
    )
    .await?;
    fixture.release("contract:standalone:second")?;
    request_before_result(
        &mut invocation,
        &mut fixture,
        "/gate/contract?attempt=standalone&phase=final",
    )
    .await?;
    fixture.release("contract:standalone:final")?;
    let outcome = timeout(Duration::from_secs(10), &mut invocation).await??;
    save_outcome("contract-standalone", &outcome)?;
    assert_eq!(
        outcome.terminal,
        FlowTermination::Completed,
        "{}",
        serde_json::to_string(&outcome)?
    );
    let report = until_report(&outcome)?;
    assert_eq!(report.termination, UntilTermination::Satisfied);
    assert!(report.trigger.is_none());
    assert_eq!(report.checks.len(), 1);
    let contract_check = report
        .checks
        .first()
        .ok_or("Until report lost its Contract check")?;
    assert_eq!(contract_check.source, "dom");
    assert_eq!(contract_check.state, UntilCheckState::Satisfied);
    let evidence = contract_check
        .evidence
        .as_ref()
        .ok_or("Contract check has no captured evidence")?;
    assert_eq!(
        evidence
            .get("document_epoch")
            .and_then(serde_json::Value::as_u64),
        Some(report.scope.document_epoch)
    );
    let contract_report = embedded_assertion_report(contract_check)?;
    assert_eq!(
        contract_report
            .checks
            .iter()
            .map(|check| check.passed)
            .collect::<Vec<_>>(),
        [Some(true), Some(true)]
    );
    assert!(contract_report.source_error.is_none());

    drop(invocation);

    // The attached builder uses the same record semantics after one click.
    work.navigate(&fixture.url("/until?attempt=attached&contract=1"))
        .await?;
    let flow = flow::new([
        action::click("#trigger").until(until_contract_assertion("attached")?.timeout(10_000))
    ]);
    let bound = flow.with_lease(&work);
    let mut attached: Invocation<'_> = Box::pin(bound.invoke());
    request_before_result(&mut attached, &mut fixture, "/trigger?attempt=attached").await?;
    request_before_result(&mut attached, &mut fixture, "/api?attempt=attached").await?;
    fixture.release("api:attached")?;
    request_before_result(
        &mut attached,
        &mut fixture,
        "/gate/contract?attempt=attached&phase=first",
    )
    .await?;
    fixture.release("contract:attached:first")?;
    request_before_result(
        &mut attached,
        &mut fixture,
        "/gate/contract?attempt=attached&phase=second",
    )
    .await?;
    fixture.release("contract:attached:second")?;
    request_before_result(
        &mut attached,
        &mut fixture,
        "/gate/contract?attempt=attached&phase=final",
    )
    .await?;
    fixture.release("contract:attached:final")?;
    let attached_outcome = timeout(Duration::from_secs(10), &mut attached).await??;
    assert_eq!(attached_outcome.terminal, FlowTermination::Completed);
    let attached_report = until_report(&attached_outcome)?;
    assert_eq!(attached_report.termination, UntilTermination::Satisfied);
    assert_eq!(
        attached_report
            .trigger
            .as_ref()
            .map(|receipt| receipt.status),
        Some(OperationStatus::Observed)
    );
    let attached_observation = attached_outcome
        .steps
        .first()
        .and_then(|step| step.receipt.observation.as_ref())
        .ok_or("Contract Until omitted its canonical observation")?;
    assert!(attached_observation.html.is_some());
    assert_eq!(fixture.request_count("/trigger?attempt=attached")?, 1);

    drop(attached);

    // A plain builder converted into a Step captures once while the page's
    // network response is still held, then retains that false result.
    work.navigate(&fixture.url("/until?attempt=oneshot&auto=1&stages=1"))
        .await?;
    fixture.wait_for("/api?attempt=oneshot").await?;
    let one_shot = flow::new([until_contract_assertion("oneshot")?.into()]);
    let bound = one_shot.with_lease(&work);
    let outcome = timeout(Duration::from_secs(5), bound.invoke()).await??;
    assert_eq!(outcome.terminal, FlowTermination::CompletedWithIssues);
    let receipt = &outcome
        .steps
        .first()
        .ok_or("one-shot assertion lost its receipt")?
        .receipt;
    let one_shot_report: AssertionReport =
        serde_json::from_value(receipt.result.clone().ok_or("assertion report missing")?)?;
    assert_eq!(
        one_shot_report
            .checks
            .iter()
            .map(|check| check.passed)
            .collect::<Vec<_>>(),
        [Some(false), Some(false)]
    );
    assert_eq!(fixture.request_count("/trigger?attempt=oneshot")?, 0);
    fixture.release("api:oneshot")?;
    fixture.wait_for("/gate/dom?attempt=oneshot").await?;
    fixture.release("dom:oneshot")?;
    fixture.wait_for("/gate/ax?attempt=oneshot").await?;
    fixture.release("ax:oneshot")?;
    let later_observation = timeout(Duration::from_secs(5), work.observe()).await??;
    let html = later_observation
        .html
        .as_deref()
        .ok_or("one-shot fixture has no rendered DOM")?;
    assert!(html.contains("receipt:oneshot"));
    assert!(html.contains("ready"));
    assert!(
        one_shot_report
            .checks
            .iter()
            .all(|check| check.passed == Some(false))
    );

    work.release().await?;
    browser.close().await?;
    fixture.shutdown().await?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn contract_no_record_stays_pending_while_invalid_source_and_panics_are_terminal()
-> Result<(), TestError> {
    if !enabled() {
        return Ok(());
    }

    let mut fixture = fixture::UntilFixture::start().await?;
    let pool = ExecutionPool::new(1, 4)?;
    let browser = session::new()
        .configure(browser_settings(1))
        .execution_pool(&pool)
        .acquire()
        .await?;
    let work = browser.work().await?;

    work.navigate(&fixture.url("/until?attempt=no-record&auto=1&stages=1&no-record=1"))
        .await?;
    fixture.wait_for("/api?attempt=no-record").await?;
    let flow = flow::new([until_contract_assertion("no-record")?
        .timeout(1_500)
        .until()]);
    let bound = flow.with_lease(&work);
    let mut events = pool.subscribe();
    let mut invocation: Invocation<'_> = Box::pin(bound.invoke());
    let parked = async {
        loop {
            if events.recv().await?.parked > 0 {
                return Ok::<(), TestError>(());
            }
        }
    };
    wait_for_parked(&mut invocation, parked, "no-record Contract assertion").await?;
    fixture.release("api:no-record")?;
    request_before_result(&mut invocation, &mut fixture, "/gate/dom?attempt=no-record").await?;
    fixture.release("dom:no-record")?;
    let no_record_outcome = timeout(Duration::from_secs(5), &mut invocation).await??;
    let no_record_report = until_report(&no_record_outcome)?;
    assert_eq!(no_record_report.termination, UntilTermination::TimedOut);
    let pending = no_record_report
        .checks
        .first()
        .ok_or("no-record report lost its check")?;
    assert_eq!(pending.state, UntilCheckState::Pending);
    let no_record_assertion = embedded_assertion_report(pending)?;
    assert_eq!(
        no_record_assertion.source_error,
        Some(SourceError::RecordCount { actual: 0 })
    );
    fixture.release_all()?;

    drop(invocation);

    work.navigate(&fixture.url("/until?attempt=invalid"))
        .await?;
    let calls = Arc::new(AtomicUsize::new(0));
    let captured = Arc::clone(&calls);
    let invalid = action::assert_all::<InvalidMoneyContract>(
        InvalidMoneyContract::plan()?,
        [check(move |_contract: &InvalidMoneyContract| {
            captured.fetch_add(1, Ordering::SeqCst);
            true
        })],
    );
    let flow = flow::new([invalid.timeout(5_000).until()]);
    let bound = flow.with_lease(&work);
    let invalid_outcome = timeout(Duration::from_secs(8), bound.invoke()).await??;
    let invalid_report = until_report(&invalid_outcome)?;
    assert_eq!(invalid_report.termination, UntilTermination::Rejected);
    let invalid_check = invalid_report
        .checks
        .first()
        .ok_or("invalid source report lost its check")?;
    assert_eq!(invalid_check.state, UntilCheckState::Rejected);
    let invalid_assertion = embedded_assertion_report(invalid_check)?;
    assert_eq!(
        invalid_assertion.source_error,
        Some(SourceError::InvalidContract)
    );
    assert_eq!(calls.load(Ordering::SeqCst), 0);

    let panic_assertion = action::assert_all::<UntilContract>(
        UntilContract::plan()?,
        [check(|_contract: &UntilContract| {
            panic!("Until predicate panic fixture")
        })],
    );
    let flow = flow::new([panic_assertion.timeout(5_000).until()]);
    let bound = flow.with_lease(&work);
    let panic_outcome = timeout(Duration::from_secs(8), bound.invoke()).await??;
    let panic_report = until_report(&panic_outcome)?;
    assert_eq!(panic_report.termination, UntilTermination::Rejected);
    let panic_check = panic_report
        .checks
        .first()
        .ok_or("panic report lost its check")?;
    assert_eq!(panic_check.state, UntilCheckState::Rejected);
    let panic_assertion = embedded_assertion_report(panic_check)?;
    assert_eq!(
        panic_assertion
            .checks
            .first()
            .and_then(|check| check.error.clone()),
        Some(CheckError::Panicked)
    );

    work.release().await?;
    browser.close().await?;
    fixture.shutdown().await?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn ax_only_and_network_only_until_keep_source_evidence_without_html() -> Result<(), TestError>
{
    if !enabled() {
        return Ok(());
    }

    let mut fixture = fixture::UntilFixture::start().await?;
    let browser = session::new()
        .configure(browser_settings(1))
        .acquire()
        .await?;
    let work = browser.work().await?;

    work.navigate(&fixture.url("/until?attempt=ax-only&stages=1"))
        .await?;
    let ax_flow =
        flow::new([action::click("#trigger").until(expect::ax("Ready ax-only").role("button"))]);
    let ax_bound = ax_flow.with_lease(&work);
    let mut ax_wait: Invocation<'_> = Box::pin(ax_bound.invoke());
    request_before_result(&mut ax_wait, &mut fixture, "/trigger?attempt=ax-only").await?;
    request_before_result(&mut ax_wait, &mut fixture, "/api?attempt=ax-only").await?;
    fixture.release("api:ax-only")?;
    request_before_result(&mut ax_wait, &mut fixture, "/gate/dom?attempt=ax-only").await?;
    fixture.release("dom:ax-only")?;
    request_before_result(&mut ax_wait, &mut fixture, "/gate/ax?attempt=ax-only").await?;
    fixture.release("ax:ax-only")?;
    let ax_outcome = timeout(Duration::from_secs(8), &mut ax_wait).await??;
    assert_eq!(ax_outcome.terminal, FlowTermination::Completed);
    let ax_report = until_report(&ax_outcome)?;
    assert_eq!(ax_report.termination, UntilTermination::Satisfied);
    assert_eq!(ax_report.checks.len(), 1);
    let ax_check = ax_report.checks.first().ok_or("AX check missing")?;
    assert_eq!(ax_check.source, "accessibility");
    assert_eq!(ax_check.state, UntilCheckState::Satisfied);
    assert!(
        ax_check
            .evidence
            .as_ref()
            .and_then(|value| value.get("nodes"))
            .and_then(serde_json::Value::as_array)
            .is_some_and(|nodes| !nodes.is_empty())
    );
    let ax_receipt = &ax_outcome
        .steps
        .first()
        .ok_or("AX flow step missing")?
        .receipt;
    assert!(
        ax_receipt
            .observation
            .as_ref()
            .ok_or("AX Until omitted its observation")?
            .html
            .is_none()
    );

    drop(ax_wait);

    work.navigate(&fixture.url("/until?attempt=network-only&fast=1"))
        .await?;
    let network_flow = flow::new([action::click("#trigger").until(
        expect::response(fixture.url("/api?attempt=network-only&fast=1"))
            .method("GET")
            .status(200)
            .json("/attempt", "network-only"),
    )]);
    let network_bound = network_flow.with_lease(&work);
    let mut network_wait: Invocation<'_> = Box::pin(network_bound.invoke());
    let network_outcome = timeout(Duration::from_secs(8), &mut network_wait).await??;
    assert_eq!(network_outcome.terminal, FlowTermination::Completed);
    let network_report = until_report(&network_outcome)?;
    assert_eq!(network_report.termination, UntilTermination::Satisfied);
    assert_eq!(network_report.checks.len(), 1);
    let network_check = network_report
        .checks
        .first()
        .ok_or("network check missing")?;
    assert_eq!(network_check.source, "network");
    assert_eq!(network_check.state, UntilCheckState::Satisfied);
    let network_evidence = network_check
        .evidence
        .as_ref()
        .ok_or("network response evidence missing")?;
    assert!(network_evidence.get("request_id").is_some());
    assert_eq!(
        network_evidence
            .get("body")
            .and_then(|body| body.get("attempt"))
            .and_then(serde_json::Value::as_str),
        Some("network-only")
    );
    let network_receipt = &network_outcome
        .steps
        .first()
        .ok_or("network flow step missing")?
        .receipt;
    assert!(
        network_receipt
            .observation
            .as_ref()
            .ok_or("network Until omitted its observation")?
            .html
            .is_none()
    );

    assert_eq!(fixture.request_count("/trigger?attempt=ax-only")?, 1);
    assert_eq!(fixture.request_count("/trigger?attempt=network-only")?, 1);
    drop(network_wait);

    work.release().await?;
    browser.close().await?;
    fixture.shutdown().await?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn oversized_trigger_result_returns_unknown_with_structured_until_metadata()
-> Result<(), TestError> {
    if !enabled() {
        return Ok(());
    }

    let fixture = fixture::UntilFixture::start().await?;
    let settings = SessionPolicy {
        mode: browser_mode(),
        maximum_result_bytes: 1_024,
        allow_arbitrary_js: true,
        allowed_actions: vec![
            session::ActionKind::Navigate,
            session::ActionKind::Click,
            session::ActionKind::EnterText,
            session::ActionKind::Screenshot,
            session::ActionKind::Wait,
            session::ActionKind::Assert,
            session::ActionKind::Evaluate,
        ],
        ..SessionPolicy::default()
    };
    let browser = session::new().configure(settings).acquire().await?;
    let work = browser.work().await?;
    work.navigate(&fixture.url("/until?attempt=oversized-trigger"))
        .await?;
    let script = "(() => { const receipt = document.querySelector('#receipt'); receipt.hidden = false; receipt.textContent = 'receipt:oversized-trigger'; return 'x'.repeat(4096); })()";
    let flow = flow::new([action::evaluate(script).until(expect::visible("#receipt"))]);
    let bound = flow.with_lease(&work);
    let outcome = timeout(Duration::from_secs(8), bound.invoke()).await??;
    assert_eq!(outcome.terminal, FlowTermination::Unknown);
    let step = outcome.steps.first().ok_or("unknown Until step missing")?;
    assert_eq!(step.receipt.status, OperationStatus::Unknown);
    assert!(step.receipt.result.is_some());
    let report = until_report(&outcome)?;
    assert_eq!(report.termination, UntilTermination::Unavailable);
    let trigger = report
        .trigger
        .as_ref()
        .ok_or("oversized trigger receipt was dropped")?;
    assert_eq!(trigger.kind, "evaluate");
    assert_eq!(trigger.status, OperationStatus::Unknown);
    assert!(trigger.result.is_none());
    assert!(trigger.error.is_some());

    work.release().await?;
    browser.close().await?;
    fixture.shutdown().await?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn aggregate_evidence_fallback_preserves_the_observed_trigger_receipt()
-> Result<(), TestError> {
    if !enabled() {
        return Ok(());
    }

    let mut fixture = fixture::UntilFixture::start().await?;
    let settings = SessionPolicy {
        maximum_result_bytes: 7_500,
        ..browser_settings(1)
    };
    let browser = session::new().configure(settings).acquire().await?;
    let work = browser.work().await?;
    work.navigate(&fixture.url("/until?attempt=aggregate-budget&fast=1"))
        .await?;

    // Every selector is valid CSS and below the 4 KiB per-selector limit.
    // Each leaf can carry its evidence independently, while the combined
    // pending report exceeds this session's aggregate result limit.
    let checks = (0..64)
        .map(|index| {
            let selector = format!(".until-evidence-{}-{index}", "x".repeat(512));
            expect::visible(selector)
        })
        .collect::<Vec<yosoi_expect::Expectation>>();
    let flow = flow::new([action::click("#trigger")
        .until(expect::all(checks))
        .timeout(10_000)]);
    let bound = flow.with_lease(&work);
    let outcome = timeout(Duration::from_secs(12), bound.invoke()).await??;
    save_outcome("until-aggregate-evidence-fallback", &outcome)?;

    assert_eq!(outcome.terminal, FlowTermination::Unknown);
    let step = outcome
        .steps
        .first()
        .ok_or("aggregate fallback lost its step")?;
    assert_eq!(step.receipt.status, OperationStatus::Unknown);
    let report = until_report(&outcome)?;
    report.validate()?;
    assert_eq!(report.termination, UntilTermination::Unavailable);
    assert_eq!(
        report.error.as_deref(),
        Some("confirmation report exceeded its retained byte budget"),
        "the test must exercise aggregate overflow, not cancellation or timeout"
    );
    let trigger = report
        .trigger
        .as_ref()
        .ok_or("aggregate fallback lost the trigger receipt")?;
    assert_eq!(trigger.kind, "click");
    assert_eq!(trigger.status, OperationStatus::Observed);
    assert!(trigger.error.is_none());
    let trigger_result = trigger
        .result
        .as_ref()
        .ok_or("observed trigger receipt lost its result")?;
    assert_eq!(trigger_result.get("value"), Some(&serde_json::Value::Null));
    assert!(
        trigger_result
            .get("started_at_unix_us")
            .and_then(serde_json::Value::as_u64)
            .is_some_and(|started| started > 0),
        "trigger watermark is missing or zero"
    );
    let trigger_event = timeout(
        Duration::from_secs(5),
        fixture.wait_for("/trigger?attempt=aggregate-budget"),
    )
    .await??;
    assert_eq!(trigger_event.method, "GET");
    let api_event = timeout(
        Duration::from_secs(5),
        fixture.wait_for("/api?attempt=aggregate-budget&fast=1"),
    )
    .await??;
    assert_eq!(api_event.method, "GET");
    assert_eq!(
        fixture.request_count("/trigger?attempt=aggregate-budget")?,
        1
    );
    assert_eq!(
        fixture.request_count("/api?attempt=aggregate-budget&fast=1")?,
        1
    );

    let _record = AutomationRecord::new("aggregate-until-fallback", Vec::new(), Vec::new())?
        .with_flow_outcome(outcome.clone())?;

    let fenced = timeout(Duration::from_secs(5), work.observe()).await?;
    assert!(matches!(fenced, Err(session::SessionError::Closed)));

    work.release().await?;
    browser.close().await?;
    fixture.shutdown().await?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn direct_work_until_shares_one_session_deadline_with_its_trigger_and_wait()
-> Result<(), TestError> {
    if !enabled() {
        return Ok(());
    }

    let mut fixture = fixture::UntilFixture::start().await?;
    let settings = SessionPolicy {
        operation_timeout_ms: 10_000,
        ..browser_settings(1)
    };
    let browser = session::new().configure(settings).acquire().await?;
    let work = browser.work().await?;
    work.navigate(&fixture.url("/until?attempt=direct-budget"))
        .await?;
    let trigger = action::click("#trigger");
    let expectation: yosoi_expect::Expectation =
        expect::response(fixture.url("/api?attempt=direct-budget"))
            .status(200)
            .json("/attempt", "direct-budget")
            .into();
    let mut waiting = Box::pin(work.until(Some(&trigger), &expectation));

    let trigger_event = tokio::select! {
        biased;
        result = waiting.as_mut() => {
            let receipt = result?;
            return Err(io::Error::other(format!(
                "direct Work::until ended before its trigger request: {:?}", receipt.status
            )).into());
        }
        result = timeout(
            Duration::from_secs(12),
            fixture.wait_for("/trigger?attempt=direct-budget"),
        ) => result??,
    };
    assert_eq!(trigger_event.method, "GET");
    tokio::select! {
        biased;
        result = waiting.as_mut() => {
            let receipt = result?;
            return Err(io::Error::other(format!(
                "direct Work::until ended before the gated response: {:?}", receipt.status
            )).into());
        }
        result = timeout(
            Duration::from_secs(5),
            fixture.wait_for("/api?attempt=direct-budget"),
        ) => result??,
    };

    let receipt = timeout(Duration::from_secs(12), &mut waiting).await??;
    assert_eq!(receipt.kind, "until");
    assert_eq!(receipt.status, OperationStatus::Rejected);
    let report: UntilReport = serde_json::from_value(
        receipt
            .result
            .clone()
            .ok_or("direct Until report missing")?,
    )?;
    assert_eq!(report.termination, UntilTermination::TimedOut);
    assert_eq!(
        report.trigger.as_ref().map(|trigger| trigger.status),
        Some(OperationStatus::Observed)
    );
    assert_eq!(fixture.request_count("/trigger?attempt=direct-budget")?, 1);

    drop(waiting);
    fixture.release("api:direct-budget")?;
    let _ = timeout(Duration::from_secs(5), work.observe()).await??;
    work.release().await?;
    browser.close().await?;
    fixture.shutdown().await?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn stress_reordered_updates_across_four_tabs_and_one_worker() -> Result<(), TestError> {
    let Some(rounds) = configured_stress_rounds()? else {
        eprintln!("SKIPPED: set YOSOI_UNTIL_STRESS_ROUNDS to 1..=20 for serial stress");
        return Ok(());
    };
    if !enabled() {
        return Ok(());
    }

    let mut fixture = fixture::UntilFixture::start().await?;
    let pool = ExecutionPool::new(1, 16)?;
    let browser = session::new()
        .configure(browser_settings(4))
        .execution_pool(&pool)
        .acquire()
        .await?;
    let work0 = browser.work().await?;
    let tab1 = browser.new_tab().await?;
    let work1 = tab1.work().await?;
    let tab2 = browser.new_tab().await?;
    let work2 = tab2.work().await?;
    let tab3 = browser.new_tab().await?;
    let work3 = tab3.work().await?;

    for round in 0..rounds {
        eprintln!("until stress round {round}");
        let attempts = [
            format!("stress-{round}-0"),
            format!("stress-{round}-1"),
            format!("stress-{round}-2"),
            format!("stress-{round}-3"),
        ];
        for (work, attempt) in [
            (&work0, &attempts[0]),
            (&work1, &attempts[1]),
            (&work2, &attempts[2]),
            (&work3, &attempts[3]),
        ] {
            work.navigate(&fixture.url(&format!(
                "/until?attempt={attempt}&stale=1&stages=1&noise=50"
            )))
            .await?;
        }

        let flow0 = stress_flow(&fixture, &attempts[0]);
        let flow1 = stress_flow(&fixture, &attempts[1]);
        let flow2 = stress_flow(&fixture, &attempts[2]);
        let flow3 = stress_flow(&fixture, &attempts[3]);
        let bound0 = flow0.with_lease(&work0);
        let bound1 = flow1.with_lease(&work1);
        let bound2 = flow2.with_lease(&work2);
        let bound3 = flow3.with_lease(&work3);
        let mut all = Box::pin(async {
            tokio::join!(
                bound0.invoke(),
                bound1.invoke(),
                bound2.invoke(),
                bound3.invoke(),
            )
        });

        for attempt in &attempts {
            event_before_completion(
                &mut all,
                fixture.wait_for(&format!("/trigger?attempt={attempt}")),
                "four-tab stress trigger",
            )
            .await?;
        }
        for attempt in &attempts {
            let target = format!("/api?attempt={attempt}");
            event_before_completion(
                &mut all,
                fixture.wait_for_correlated(&target, "old"),
                "four-tab stale response",
            )
            .await?;
        }
        fixture.release("api:old")?;
        for attempt in &attempts {
            let target = format!("/api?attempt={attempt}");
            event_before_completion(
                &mut all,
                fixture.wait_for_correlated(&target, attempt),
                "four-tab current response",
            )
            .await?;
        }
        for attempt in attempts.iter().rev() {
            fixture.release(&format!("api:{attempt}"))?;
        }
        for attempt in attempts.iter().rev() {
            event_before_completion(
                &mut all,
                fixture.wait_for(&format!("/gate/dom?attempt={attempt}")),
                "four-tab DOM update",
            )
            .await?;
        }
        for attempt in attempts.iter().rev() {
            fixture.release(&format!("dom:{attempt}"))?;
        }
        for attempt in attempts.iter().rev() {
            event_before_completion(
                &mut all,
                fixture.wait_for(&format!("/gate/ax?attempt={attempt}")),
                "four-tab accessibility update",
            )
            .await?;
        }
        for attempt in attempts.iter().rev() {
            fixture.release(&format!("ax:{attempt}"))?;
        }

        let (outcome0, outcome1, outcome2, outcome3) =
            timeout(Duration::from_secs(30), &mut all).await?;
        for (attempt, outcome) in attempts
            .iter()
            .zip([outcome0?, outcome1?, outcome2?, outcome3?])
        {
            save_outcome(attempt, &outcome)?;
            assert_eq!(
                outcome.terminal,
                FlowTermination::Completed,
                "{attempt}: {}",
                serde_json::to_string(&outcome)?
            );
            let report = until_report(&outcome)?;
            assert_eq!(report.termination, UntilTermination::Satisfied);
            assert_eq!(
                report.trigger.as_ref().map(|receipt| receipt.status),
                Some(OperationStatus::Observed)
            );
            assert_eq!(
                fixture.request_count(&format!("/trigger?attempt={attempt}"))?,
                1
            );
            assert_eq!(
                fixture.request_count(&format!("/api?attempt={attempt}"))?,
                2
            );
        }
        assert_eq!(pool.snapshot().active, 0);
        assert_eq!(pool.snapshot().parked, 0);
        assert_eq!(pool.snapshot().queued, 0);
        drop(all);

        if round % 5 == 0 {
            let attempt = format!("stress-cancel-{round}");
            work0
                .navigate(&fixture.url(&format!("/until?attempt={attempt}&stages=1")))
                .await?;
            let cancellation = CancellationToken::new();
            let flow = flow::new([action::click("#trigger")
                .until(
                    expect::response(fixture.url(&format!("/api?attempt={attempt}")))
                        .status(200)
                        .json("/attempt", attempt.clone()),
                )
                .with_cancellation(&cancellation)]);
            let bound = flow.with_lease(&work0);
            let mut cancelled_events = pool.subscribe();
            let mut invocation: Invocation<'_> = Box::pin(bound.invoke());
            request_before_result(
                &mut invocation,
                &mut fixture,
                &format!("/trigger?attempt={attempt}"),
            )
            .await?;
            request_before_result(
                &mut invocation,
                &mut fixture,
                &format!("/api?attempt={attempt}"),
            )
            .await?;
            let parked = async {
                loop {
                    if cancelled_events.recv().await?.parked > 0 {
                        return Ok::<(), TestError>(());
                    }
                }
            };
            wait_for_parked(&mut invocation, parked, "stress cancellation while parked").await?;
            cancellation.cancel();
            let cancelled = timeout(Duration::from_secs(5), &mut invocation).await??;
            let report = until_report(&cancelled)?;
            assert_eq!(report.termination, UntilTermination::Cancelled);
            assert_eq!(
                report.trigger.as_ref().map(|receipt| receipt.status),
                Some(OperationStatus::Observed)
            );
            drop(invocation);

            fixture.release(&format!("api:{attempt}"))?;
            assert_eq!(pool.snapshot().active, 0);
            assert_eq!(pool.snapshot().parked, 0);
            assert_eq!(pool.snapshot().queued, 0);
        }
    }

    // Exercise a queued deadline once after the repeated rounds, then ensure
    // the one worker is available again for a fresh observation.
    work0
        .navigate(&fixture.url("/until?attempt=stress-queue"))
        .await?;
    let permit = pool.acquire().await?;
    let mut events = pool.subscribe();
    let queued_flow = flow::new([action::click("#trigger")
        .until(expect::visible("#receipt"))
        .timeout(150)]);
    let queued_bound = queued_flow.with_lease(&work0);
    let mut queued: Invocation<'_> = Box::pin(queued_bound.invoke());
    let queued_event = async {
        loop {
            if events.recv().await?.queued > 0 {
                return Ok::<(), TestError>(());
            }
        }
    };
    tokio::select! {
        biased;
        result = queued.as_mut() => {
            let outcome = result?;
            return Err(io::Error::other(format!(
                "stress queue expired before recording admission: {:?}", outcome.terminal
            )).into());
        }
        result = timeout(Duration::from_secs(5), queued_event) => result??,
    }
    let queued_outcome = timeout(Duration::from_secs(5), &mut queued).await??;
    let queued_receipt = &queued_outcome
        .steps
        .first()
        .ok_or("queued result missing")?
        .receipt;
    assert_eq!(queued_receipt.status, OperationStatus::Rejected);
    assert_eq!(queued_receipt.kind, "not-dispatched:until");
    assert_eq!(fixture.request_count("/trigger?attempt=stress-queue")?, 0);
    drop(queued);

    drop(permit);
    let _ = timeout(Duration::from_secs(5), work0.observe()).await??;
    assert_eq!(pool.snapshot().active, 0);
    assert_eq!(pool.snapshot().parked, 0);
    assert_eq!(pool.snapshot().queued, 0);

    work0.release().await?;
    work1.release().await?;
    work2.release().await?;
    work3.release().await?;
    browser.close().await?;
    fixture.shutdown().await?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn queued_deadline_expires_before_trigger_and_leaves_the_tab_reusable()
-> Result<(), TestError> {
    if !enabled() {
        return Ok(());
    }

    let fixture = fixture::UntilFixture::start().await?;
    let pool = ExecutionPool::new(1, 4)?;
    let browser = session::new()
        .configure(browser_settings(1))
        .execution_pool(&pool)
        .acquire()
        .await?;
    let work = browser.work().await?;
    work.navigate(&fixture.url("/until?attempt=current"))
        .await?;

    let permit = pool.acquire().await?;
    let mut events = pool.subscribe();
    let flow = flow::new([action::click("#trigger")
        .until(expect::visible("#receipt"))
        .timeout(250)]);
    let bound = flow.with_lease(&work);
    let mut invocation: Invocation<'_> = Box::pin(bound.invoke());
    let queued = async {
        loop {
            if events.recv().await?.queued > 0 {
                return Ok::<(), TestError>(());
            }
        }
    };
    tokio::select! {
        biased;
        result = invocation.as_mut() => {
            let outcome = result?;
            return Err(io::Error::other(format!(
                "queued Until returned before observing its deadline: {:?}", outcome.terminal
            )).into());
        }
        result = timeout(Duration::from_secs(5), queued) => result??,
    };
    let outcome = timeout(Duration::from_secs(5), &mut invocation).await??;
    assert_eq!(outcome.terminal, FlowTermination::CompletedWithIssues);
    let receipt = &outcome
        .steps
        .first()
        .ok_or("queued Until did not retain its pre-dispatch result")?
        .receipt;
    assert_eq!(receipt.status, OperationStatus::Rejected);
    assert_eq!(receipt.kind, "not-dispatched:until");
    assert!(receipt.result.is_none());
    assert_eq!(fixture.request_count("/trigger?attempt=current")?, 0);
    drop(invocation);

    drop(permit);
    let _ = timeout(Duration::from_secs(5), work.observe()).await??;
    assert_eq!(pool.snapshot().queued, 0);
    assert_eq!(pool.snapshot().active, 0);
    assert_eq!(pool.snapshot().parked, 0);

    work.release().await?;
    browser.close().await?;
    fixture.shutdown().await?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn navigation_during_input_preparation_is_unknown_before_trigger_dispatch()
-> Result<(), TestError> {
    if !enabled() {
        return Ok(());
    }

    let mut fixture = fixture::UntilFixture::start().await?;
    let browser = session::new()
        .configure(browser_settings(2))
        .acquire()
        .await?;
    let work = browser.work().await?;
    work.navigate(&fixture.url("/until?attempt=target-scope&target-resolution-gate=1"))
        .await?;
    let foreground_tab = browser.new_tab().await?;
    let foreground = foreground_tab.work().await?;
    foreground
        .navigate(&fixture.url("/until?attempt=scope-foreground"))
        .await?;
    timeout(
        Duration::from_secs(8),
        fixture.wait_for("/gate/contract?attempt=target-scope&phase=arm-input"),
    )
    .await??;
    fixture.release("contract:target-scope:arm-input")?;
    timeout(
        Duration::from_secs(8),
        fixture.wait_for("/marker?attempt=target-scope&phase=input-armed"),
    )
    .await??;

    let flow = flow::new([action::click("#trigger").until(expect::visible("#receipt"))]);
    let bound = flow.with_lease(&work);
    let mut invocation: Invocation<'_> = Box::pin(bound.invoke());
    let target_lookup = request_before_result(
        &mut invocation,
        &mut fixture,
        "/gate/contract?attempt=target-scope&phase=input-preparation",
    )
    .await?;
    assert_eq!(target_lookup.method, "GET");

    // Releasing the activation handler navigates after the original element
    // was resolved. The replacement marker proves that the document changed.
    fixture.release("contract:target-scope:input-preparation")?;
    let replacement = timeout(
        Duration::from_secs(8),
        fixture.wait_for("/replacement?attempt=target-scope"),
    )
    .await??;
    assert_eq!(replacement.method, "GET");
    let replacement_loaded = timeout(
        Duration::from_secs(8),
        fixture.wait_for("/marker?attempt=target-scope"),
    )
    .await??;
    assert_eq!(replacement_loaded.method, "GET");

    let outcome = timeout(Duration::from_secs(8), &mut invocation).await??;
    save_outcome("until-input-preparation-scope-change", &outcome)?;
    assert_eq!(outcome.terminal, FlowTermination::Unknown);
    let step = outcome
        .steps
        .first()
        .ok_or("target-resolution scope failure lost its step")?;
    assert_eq!(step.receipt.status, OperationStatus::Unknown);
    let report = until_report(&outcome)?;
    report.validate()?;
    assert_eq!(report.termination, UntilTermination::Unavailable);
    // Input preparation is already inside the attempted trigger. Retain its
    // uncertainty without claiming a successful native pointer dispatch.
    let trigger = report
        .trigger
        .as_ref()
        .ok_or("lost attempted input receipt")?;
    assert_eq!(trigger.kind, "click");
    assert_eq!(trigger.status, OperationStatus::Unknown);
    assert!(trigger.result.is_none());
    assert!(trigger.error.is_some());
    assert_eq!(fixture.request_count("/trigger?attempt=target-scope")?, 0);
    assert_eq!(
        fixture.request_count("/replacement?attempt=target-scope")?,
        1
    );
    assert_eq!(fixture.request_count("/marker?attempt=target-scope")?, 1);

    let fenced = timeout(Duration::from_secs(5), work.observe()).await?;
    assert!(matches!(fenced, Err(session::SessionError::Closed)));
    drop(invocation);

    work.release().await?;
    foreground.release().await?;
    browser.close().await?;
    fixture.shutdown().await?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn navigation_invalidates_a_pending_check_in_its_original_document() -> Result<(), TestError>
{
    if !enabled() {
        return Ok(());
    }

    let mut fixture = fixture::UntilFixture::start().await?;
    let pool = ExecutionPool::new(1, 4)?;
    let browser = session::new()
        .configure(browser_settings(1))
        .execution_pool(&pool)
        .acquire()
        .await?;
    let work = browser.work().await?;
    work.navigate(&fixture.url("/until?attempt=navigate&auto=1&navigate=1"))
        .await?;
    let original_document = work.observe().await?;
    fixture.wait_for("/api?attempt=navigate").await?;

    let flow = flow::new([expect::visible("#receipt").until().timeout(4_000)]);
    let bound = flow.with_lease(&work);
    let mut events = pool.subscribe();
    let mut invocation: Invocation<'_> = Box::pin(bound.invoke());
    let parked = async {
        loop {
            if events.recv().await?.parked > 0 {
                return Ok::<(), TestError>(());
            }
        }
    };
    tokio::select! {
        biased;
        result = invocation.as_mut() => {
            let outcome = result?;
            return Err(io::Error::other(format!(
                "navigation-scope Until ended before navigation: {:?}", outcome.terminal
            )).into());
        }
        result = timeout(Duration::from_secs(5), parked) => result??,
    };
    fixture.release("api:navigate")?;
    fixture.wait_for("/replacement").await?;

    let outcome = timeout(Duration::from_secs(7), &mut invocation).await??;
    assert_ne!(outcome.terminal, FlowTermination::Completed);
    if let Ok(report) = until_report(&outcome) {
        assert_ne!(report.termination, UntilTermination::Satisfied);
        assert_eq!(
            report.scope.document_epoch,
            original_document.document_epoch
        );
    }
    fixture.release_all()?;
    // Navigation invalidates the original confirmation scope and fences its
    // control. The replacement must not make the old invocation succeed.
    assert_eq!(outcome.terminal, FlowTermination::Unknown);
    assert!(matches!(
        work.observe().await,
        Err(session::SessionError::Closed)
    ));

    drop(invocation);

    work.release().await?;
    browser.close().await?;
    fixture.shutdown().await?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn cancellation_and_timeout_keep_the_trigger_receipt_and_release_resources()
-> Result<(), TestError> {
    if !enabled() {
        return Ok(());
    }

    let mut fixture = fixture::UntilFixture::start().await?;
    let pool = ExecutionPool::new(1, 4)?;
    let browser = session::new()
        .configure(browser_settings(1))
        .execution_pool(&pool)
        .acquire()
        .await?;
    let work = browser.work().await?;
    work.navigate(&fixture.url("/until?attempt=current&stages=1"))
        .await?;

    let before_trigger = CancellationToken::new();
    before_trigger.cancel();
    let cancelled_before_flow = flow::new([action::click("#trigger")
        .until(expect::visible("#receipt"))
        .with_cancellation(&before_trigger)]);
    let cancelled_before_bound = cancelled_before_flow.with_lease(&work);
    let cancelled_before = cancelled_before_bound.invoke().await?;
    let before_step = cancelled_before
        .steps
        .first()
        .ok_or("pre-dispatch cancellation result missing")?;
    assert_eq!(before_step.receipt.status, OperationStatus::Rejected);
    assert_eq!(before_step.receipt.kind, "not-dispatched:until");
    assert!(before_step.receipt.result.is_none());
    assert_eq!(fixture.request_count("/trigger?attempt=current")?, 0);

    let after_trigger = CancellationToken::new();
    let flow = flow::new([
        action::click("#trigger")
            .until(
                expect::response(fixture.url("/api?attempt=current"))
                    .status(200)
                    .json("/attempt", "current"),
            )
            .with_cancellation(&after_trigger)
            .on_cancellation(Continuation::Continue)
            .timeout(10_000),
        action::assert(Condition::Visible {
            selector: "#trigger".into(),
        })
        .into(),
    ])
    .on_cancellation(Continuation::Stop(StopScope::Invocation));
    let bound = flow.with_lease(&work);
    let mut cancellation_events = pool.subscribe();
    let mut invocation: Invocation<'_> = Box::pin(bound.invoke());
    request_before_result(&mut invocation, &mut fixture, "/trigger?attempt=current").await?;
    request_before_result(&mut invocation, &mut fixture, "/api?attempt=current").await?;
    let parked = async {
        loop {
            if cancellation_events.recv().await?.parked > 0 {
                return Ok::<(), TestError>(());
            }
        }
    };
    wait_for_parked(&mut invocation, parked, "cancellation after trigger").await?;
    after_trigger.cancel();
    let cancelled_after = timeout(Duration::from_secs(5), &mut invocation).await??;
    let after_report = until_report(&cancelled_after)?;
    assert_eq!(after_report.termination, UntilTermination::Cancelled);
    assert_eq!(
        after_report.trigger.as_ref().map(|receipt| receipt.status),
        Some(OperationStatus::Observed)
    );
    assert_eq!(
        cancelled_after.terminal,
        FlowTermination::CompletedWithIssues
    );
    assert_eq!(cancelled_after.steps.len(), 2);
    assert_eq!(
        cancelled_after.steps[1].receipt.status,
        OperationStatus::Observed
    );
    drop(invocation);

    fixture.release("api:current")?;
    assert_eq!(pool.snapshot().active, 0);
    assert_eq!(pool.snapshot().parked, 0);
    assert_eq!(pool.snapshot().queued, 0);

    work.navigate(&fixture.url("/until?attempt=deadline&stages=1"))
        .await?;
    let timed_flow = flow::new([action::click("#trigger")
        .until(
            expect::response(fixture.url("/api?attempt=deadline"))
                .status(200)
                .json("/attempt", "deadline"),
        )
        .timeout(2_000)]);
    let timed_bound = timed_flow.with_lease(&work);
    let mut timed: Invocation<'_> = Box::pin(timed_bound.invoke());
    request_before_result(&mut timed, &mut fixture, "/trigger?attempt=deadline").await?;
    request_before_result(&mut timed, &mut fixture, "/api?attempt=deadline").await?;
    let timed_out = timeout(Duration::from_secs(5), &mut timed).await??;
    let timeout_report = until_report(&timed_out)?;
    assert_eq!(timeout_report.termination, UntilTermination::TimedOut);
    assert_eq!(
        timeout_report
            .trigger
            .as_ref()
            .map(|receipt| receipt.status),
        Some(OperationStatus::Observed)
    );
    drop(timed);

    fixture.release("api:deadline")?;
    let _ = timeout(Duration::from_secs(5), work.observe()).await??;
    assert_eq!(pool.snapshot().active, 0);
    assert_eq!(pool.snapshot().parked, 0);
    assert_eq!(pool.snapshot().queued, 0);

    work.navigate(&fixture.url("/until?attempt=drop&stages=1"))
        .await?;
    let dropped_flow = flow::new([action::click("#trigger").until(
        expect::response(fixture.url("/api?attempt=drop"))
            .status(200)
            .json("/attempt", "drop"),
    )]);
    let dropped_bound = dropped_flow.with_lease(&work);
    let mut dropped: Invocation<'_> = Box::pin(dropped_bound.invoke());
    request_before_result(&mut dropped, &mut fixture, "/trigger?attempt=drop").await?;
    request_before_result(&mut dropped, &mut fixture, "/api?attempt=drop").await?;
    drop(dropped);

    fixture.release_all()?;
    assert!(matches!(
        work.observe().await,
        Err(session::SessionError::Closed)
    ));
    assert_eq!(pool.snapshot().active, 0);
    assert_eq!(pool.snapshot().parked, 0);
    assert_eq!(pool.snapshot().queued, 0);

    work.release().await?;
    browser.close().await?;
    fixture.shutdown().await?;
    Ok(())
}

async fn request_before_result<F>(
    invocation: &mut Pin<Box<F>>,
    fixture: &mut fixture::UntilFixture,
    target: &str,
) -> Result<fixture::RequestEvent, TestError>
where
    F: Future<Output = Result<FlowOutcome, FlowInvokeError>> + ?Sized,
{
    let request = timeout(Duration::from_secs(8), fixture.wait_for(target));
    tokio::select! {
        biased;
        result = invocation.as_mut() => {
            let outcome = result?;
            save_outcome("unexpected-before-fixture-event", &outcome)?;
            Err(io::Error::other(format!(
                "Until completed before fixture reached {target}: {}", serde_json::to_string(&outcome)?
            )).into())
        }
        result = request => if let Ok(event) = result { Ok(event?) } else {
            if let Ok(Ok(outcome)) = timeout(Duration::from_secs(4), invocation.as_mut()).await {
                save_outcome("until-fixture-event-timeout", &outcome)?;
            }
            Err(io::Error::other(format!("fixture event did not arrive: {target}")).into())
        },
    }
}

async fn correlated_request_before_result<F>(
    invocation: &mut Pin<Box<F>>,
    fixture: &mut fixture::UntilFixture,
    target: &str,
    correlation: &str,
) -> Result<fixture::RequestEvent, TestError>
where
    F: Future<Output = Result<FlowOutcome, FlowInvokeError>> + ?Sized,
{
    let request = timeout(
        Duration::from_secs(8),
        fixture.wait_for_correlated(target, correlation),
    );
    tokio::select! {
        biased;
        result = invocation.as_mut() => {
            let outcome = result?;
            Err(io::Error::other(format!(
                "Until completed before fixture reached {target} with {correlation}: {:?}",
                outcome.terminal
            )).into())
        }
        result = request => Ok(result??),
    }
}

async fn event_before_completion<F, E>(
    running: &mut Pin<Box<F>>,
    event: E,
    label: &str,
) -> Result<fixture::RequestEvent, TestError>
where
    F: Future + ?Sized,
    E: Future<Output = io::Result<fixture::RequestEvent>>,
{
    let event = timeout(Duration::from_secs(8), event);
    tokio::select! {
        biased;
        _ = running.as_mut() => Err(io::Error::other(format!(
            "{label}: all invocations completed before the gated event"
        )).into()),
        result = event => Ok(result??),
    }
}

async fn wait_for_parked<F, P>(
    invocation: &mut Pin<Box<F>>,
    parked: P,
    label: &str,
) -> Result<(), TestError>
where
    F: Future<Output = Result<FlowOutcome, FlowInvokeError>> + ?Sized,
    P: Future<Output = Result<(), TestError>>,
{
    tokio::select! {
        biased;
        result = invocation.as_mut() => {
            let outcome = result?;
            Err(io::Error::other(format!(
                "{label} completed instead of parking: {:?}", outcome.terminal
            )).into())
        }
        result = timeout(Duration::from_secs(5), parked) => {
            result??;
            Ok(())
        }
    }
}

fn save_outcome(name: &str, outcome: &FlowOutcome) -> Result<(), TestError> {
    if let Some(directory) = env::var_os("YOSOI_BROWSER_OUTPUT_DIR") {
        std_fs::write(
            std_path::PathBuf::from(directory).join(format!("{name}.json")),
            serde_json::to_vec_pretty(outcome)?,
        )?;
    }
    Ok(())
}

fn until_contract_assertion(attempt: &str) -> Result<action::AssertionBuilder, TestError> {
    let expected_receipt = format!("receipt:{attempt}");
    Ok(action::assert_all::<UntilContract>(
        UntilContract::plan()?,
        [
            check(move |contract: &UntilContract| contract.receipt == expected_receipt)
                .named("receipt"),
            check(|contract: &UntilContract| contract.status == "ready").named("status"),
        ],
    ))
}

fn stress_flow(fixture: &fixture::UntilFixture, attempt: &str) -> flow::Flow {
    let expectation = expect::all([
        expect::response(fixture.url(&format!("/api?attempt={attempt}")))
            .status(200)
            .json("/attempt", attempt)
            .into(),
        expect::ax(format!("Ready {attempt}")).role("button").into(),
        expect::visible("#receipt"),
    ]);
    flow::new([action::click("#trigger").until(expectation).timeout(15_000)])
}

fn configured_stress_rounds() -> Result<Option<usize>, TestError> {
    let value = match env::var("YOSOI_UNTIL_STRESS_ROUNDS") {
        Ok(value) => value,
        Err(env::VarError::NotPresent) => return Ok(None),
        Err(error) => return Err(error.into()),
    };
    let rounds = value.parse::<usize>()?;
    if !(1..=20).contains(&rounds) {
        return Err(io::Error::other("YOSOI_UNTIL_STRESS_ROUNDS must be in 1..=20").into());
    }
    Ok(Some(rounds))
}

fn embedded_assertion_report(check: &UntilCheck) -> Result<AssertionReport, TestError> {
    let report = check
        .evidence
        .as_ref()
        .and_then(|evidence| evidence.get("report"))
        .cloned()
        .ok_or_else(|| io::Error::other("Contract check omitted its assertion report"))?;
    Ok(serde_json::from_value(report)?)
}

fn until_report(outcome: &FlowOutcome) -> Result<UntilReport, TestError> {
    let receipt = outcome
        .steps
        .first()
        .ok_or_else(|| io::Error::other("flow outcome has no Until step"))?
        .receipt
        .result
        .clone()
        .ok_or_else(|| io::Error::other("Until receipt has no report"))?;
    Ok(serde_json::from_value(receipt)?)
}

fn browser_settings(maximum_tabs: u32) -> SessionPolicy {
    SessionPolicy {
        maximum_tabs,
        execution_concurrency: 1,
        mode: browser_mode(),
        ..SessionPolicy::default()
    }
}

fn input_session_policy(maximum_tabs: u32) -> SessionPolicy {
    SessionPolicy {
        allow_arbitrary_js: true,
        allowed_actions: vec![
            session::ActionKind::Navigate,
            session::ActionKind::Click,
            session::ActionKind::EnterText,
            session::ActionKind::Screenshot,
            session::ActionKind::Wait,
            session::ActionKind::Assert,
            session::ActionKind::Evaluate,
        ],
        ..browser_settings(maximum_tabs)
    }
}

fn browser_mode() -> session::BrowserMode {
    if env::var("YOSOI_YIELD_MODE").as_deref() == Ok("headful") {
        session::BrowserMode::Headful
    } else {
        session::BrowserMode::Headless
    }
}

fn enabled() -> bool {
    if env::var("YOSOI_BROWSER_TESTS").as_deref() == Ok("1") {
        true
    } else {
        eprintln!("SKIPPED: set YOSOI_BROWSER_TESTS=1 for Until browser acceptance");
        false
    }
}
