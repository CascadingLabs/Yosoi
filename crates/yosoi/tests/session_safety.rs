#![cfg(feature = "browser")]

//! Opt-in browser safety regressions against a loopback-only HTTP fixture.
//!
//! Run serially with a regular Stable browser selected by the environment:
//! `YOSOI_BROWSER_TESTS=1 cargo test -p yosoi --features browser --test session_safety -- --nocapture --test-threads=1`

use std::iter as std_iter;
use std::net as std_net;
use std::sync as std_sync;
use std::task as std_task;
use std::{env, error::Error, io, time::Duration};
use tokio::task as tokio_task;
use tokio::time as tokio_time;
use yosoi::automation_record as yosoi_automation_record;

use tokio::time::timeout;
use tokio_util::sync::CancellationToken;
use yosoi::{
    action,
    flow::{Condition, Flow, FlowTermination, Step},
    policy::{
        Acquisition, AddressableByteLimit, BrowserMode, DocumentRequest, MaximumElapsed, Page,
        Policy,
    },
    request::{self, AttemptState, DocumentOutcome, ResponseTermination},
    session::{self, SessionError, SessionPolicy},
};

#[path = "support/session_fixture.rs"]
mod session_fixture;

fn enabled(test_name: &str) -> bool {
    if env::var("YOSOI_BROWSER_TESTS").ok().as_deref() == Some("1") {
        true
    } else {
        eprintln!("SKIPPED {test_name}: set YOSOI_BROWSER_TESTS=1 to opt in");
        false
    }
}

fn browser_policy(maximum_elapsed_micros: u64) -> Result<Policy, Box<dyn Error>> {
    let mut policy = Policy {
        page: Page::new(vec![
            Acquisition::Browser(BrowserMode::Headless).documents([DocumentRequest::RenderedDom]),
        ])?,
        ..Policy::default()
    };
    policy.request.maximum_elapsed = MaximumElapsed::try_from(maximum_elapsed_micros)?;
    Ok(policy)
}

fn settings(maximum_tabs: u32, operation_timeout_ms: u64) -> SessionPolicy {
    SessionPolicy {
        maximum_tabs,
        operation_timeout_ms,
        ..SessionPolicy::default()
    }
}

fn allow_javascript(mut settings: SessionPolicy) -> SessionPolicy {
    settings.allow_arbitrary_js = true;
    settings.allowed_actions.push(session::ActionKind::Evaluate);
    settings
}

async fn close(session: &session::Session) -> Result<(), Box<dyn Error>> {
    timeout(Duration::from_secs(10), session.close())
        .await
        .map_err(|_| io::Error::other("Session close did not finish within 10 seconds"))??;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn same_tab_has_one_control_owner_and_held_work_reuse_completes() -> Result<(), Box<dyn Error>>
{
    if !enabled("same_tab_has_one_control_owner_and_held_work_reuse_completes") {
        return Ok(());
    }

    let fixture = session_fixture::SessionFixture::start().await?;
    let policy = browser_policy(5_000_000)?;
    let session = session::new()
        .bind(&policy)
        .configure(settings(1, 5_000))
        .acquire()
        .await?;
    let first = session.work().await?;
    first.navigate(&fixture.url("/")).await?;
    let first_observation = first.observe().await?;

    // Poll the competing acquisition once while the first Work still owns its tab.
    // The yield branch wins only after `session.work()` has reached Pending.
    let mut competing = Box::pin(session.work());
    let (early_result, queued_behind_owner) = tokio::select! {
        biased;
        result = &mut competing => (Some(result), false),
        () = tokio_task::yield_now() => (None, true),
    };
    first.release().await?;
    let second = match early_result {
        Some(result) => result?,
        None => timeout(Duration::from_secs(5), competing)
            .await
            .map_err(|_| {
                io::Error::other("same-tab control did not become available after release")
            })??,
    };
    let second_observation = second.observe().await?;

    let response = timeout(
        Duration::from_secs(5),
        request::new(fixture.url("/")).with_work(&second).send(),
    )
    .await
    .map_err(|_| io::Error::other("Work-bound Request deadlocked"))??;
    let flow = Flow::new([action::assert(Condition::Exists {
        selector: "h1".to_owned(),
    })
    .into()]);
    let invocation = flow.with_lease(&second);
    let outcome = timeout(Duration::from_secs(5), invocation.invoke())
        .await
        .map_err(|_| io::Error::other("Work-bound Flow deadlocked"))??;

    // Cancellation before dispatch must preserve the caller's lease and recipe.
    let cancellation = CancellationToken::new();
    cancellation.cancel();
    let cancelled = flow
        .with_lease(&second)
        .with_cancellation(&cancellation)
        .invoke()
        .await?;
    let rerun = flow.with_lease(&second).invoke().await?;

    let same_tab = first_observation.tab_id == second_observation.tab_id;
    let request_completed = response.termination() == ResponseTermination::Completed
        && response
            .attempts()
            .all(|attempt| attempt.state() == AttemptState::Completed);
    let flow_completed = outcome.terminal == FlowTermination::Completed;
    let invocation_reused_tab = outcome.steps.iter().all(|step| {
        step.receipt
            .observation
            .as_ref()
            .is_some_and(|observation| {
                observation.session_id == second_observation.session_id
                    && observation.tab_id == second_observation.tab_id
            })
    });
    second.release().await?;
    close(&session).await?;
    fixture.shutdown().await?;

    assert!(
        queued_behind_owner,
        "a second Work acquired the same tab while it was held"
    );
    assert!(
        same_tab,
        "sequential Work leases did not identify the same tab"
    );
    assert!(
        request_completed,
        "Work-bound Request did not complete on held Work"
    );
    assert!(
        flow_completed,
        "Work-bound Flow did not complete on held Work"
    );
    assert_eq!(cancelled.terminal, FlowTermination::Cancelled);
    assert!(
        invocation_reused_tab,
        "with_lease changed the caller's Session or tab"
    );
    assert_eq!(cancelled.flow, flow);
    assert_eq!(rerun.terminal, FlowTermination::Completed);
    assert_eq!(rerun.flow, flow);
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn borrowed_flow_child_timeout_overrides_parent_and_session_operation_default()
-> Result<(), Box<dyn Error>> {
    if !enabled("borrowed_flow_child_timeout_overrides_parent_and_session_operation_default") {
        return Ok(());
    }

    let fixture = session_fixture::SessionFixture::start().await?;
    let mut policy = browser_policy(5_000_000)?;
    policy.default_action_timeout_ms = 4_000;
    let session = session::new()
        .bind(&policy)
        .configure(settings(1, 100))
        .acquire()
        .await?;
    let work = session.work().await?;

    let unannotated = Flow::new([action::wait(150)]);
    let default_started = tokio_time::Instant::now();
    let default_result = timeout(
        Duration::from_secs(5),
        unannotated.with_lease(&work).invoke(),
    )
    .await;
    let default_elapsed = default_started.elapsed();

    let child = Flow::new([action::wait(350)]).timeout(3_000);
    let flow = Flow::new([child.into(), action::screenshot().timeout(3_000)]).timeout(200);
    let started = tokio_time::Instant::now();
    let result = timeout(Duration::from_secs(10), flow.with_lease(&work).invoke()).await;
    let elapsed = started.elapsed();

    let release_result = work.release().await;
    let close_result = close(&session).await;
    let fixture_result = fixture.shutdown().await;
    let default_outcome = default_result.map_err(|_| {
        io::Error::other("unannotated Flow did not use the Session Policy default")
    })??;
    let outcome =
        result.map_err(|_| io::Error::other("nested Flow exceeded the 10-second test guard"))??;
    release_result?;
    close_result?;
    fixture_result?;

    assert_eq!(outcome.terminal, FlowTermination::Completed);
    assert_eq!(default_outcome.terminal, FlowTermination::Completed);
    assert!(default_elapsed >= Duration::from_millis(150));
    assert!(elapsed >= Duration::from_millis(350));
    assert_eq!(outcome.steps.len(), 2);
    assert_eq!(
        outcome.steps.first().map(|step| step.flow_path.as_slice()),
        Some(&[0, 0][..])
    );
    assert_eq!(
        outcome.steps.get(1).map(|step| step.flow_path.as_slice()),
        Some(&[1][..])
    );
    assert_eq!(
        outcome.steps.first().map(|step| step.receipt.status),
        Some(yosoi_automation_record::OperationStatus::Observed)
    );
    assert!(
        outcome
            .steps
            .first()
            .and_then(|step| step.receipt.observation.as_ref())
            .is_some()
    );
    assert!(
        outcome
            .steps
            .get(1)
            .and_then(|step| step.receipt.observation.as_ref())
            .and_then(|observation| observation.screenshot.as_ref())
            .is_some()
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn tabs_share_session_cookies_while_fresh_sessions_are_isolated() -> Result<(), Box<dyn Error>>
{
    if !enabled("tabs_share_session_cookies_while_fresh_sessions_are_isolated") {
        return Ok(());
    }

    let fixture = session_fixture::SessionFixture::start().await?;
    let policy = browser_policy(5_000_000)?;
    let session = session::new()
        .bind(&policy)
        .configure(settings(2, 5_000))
        .acquire()
        .await?;
    let first = session.work().await?;
    let seeded = first.navigate(&fixture.url("/seed")).await?;
    let tab = session.new_tab().await?;
    let second = tab.work().await?;
    // Distinct URLs avoid Chrome's identical-resource request coalescing.
    let first_url = fixture.url("/rendezvous?tab=first");
    let second_url = fixture.url("/rendezvous?tab=second");
    let concurrent_navigations = Box::pin(timeout(Duration::from_secs(5), async {
        tokio::join!(first.navigate(&first_url), second.navigate(&second_url),)
    }))
    .await;
    let first_observation = first.observe().await;
    let second_observation = second.observe().await;
    let same_session_shared = matches!((&first_observation, &second_observation),
        (Ok(first), Ok(second))
            if first.html.as_deref().is_some_and(|html| html.contains("shared-context"))
                && second.html.as_deref().is_some_and(|html| html.contains("shared-context"))
    );
    let distinct_tabs = matches!((&first_observation, &second_observation),
        (Ok(first), Ok(second)) if first.tab_id != second.tab_id
    );
    let navigations_completed = matches!(concurrent_navigations,
        Ok((Ok(first_receipt), Ok(second_receipt)))
            if first_receipt.status == yosoi_automation_record::OperationStatus::Observed
                && second_receipt.status == yosoi_automation_record::OperationStatus::Observed
    );

    first.release().await?;
    second.release().await?;
    close(&session).await?;

    let fresh = session::new()
        .bind(&policy)
        .configure(settings(1, 5_000))
        .acquire()
        .await?;
    let fresh_work = fresh.work().await?;
    let fresh_navigation = fresh_work.navigate(&fixture.url("/check")).await?;
    let fresh_observation = fresh_work.observe().await?;
    let fresh_isolated = fresh_observation
        .html
        .as_deref()
        .is_some_and(|html| html.contains("isolated-context"));
    fresh_work.release().await?;
    close(&fresh).await?;
    fixture.shutdown().await?;

    assert_eq!(
        seeded.status,
        yosoi_automation_record::OperationStatus::Observed,
        "fixture did not seed the session cookie"
    );
    assert!(
        navigations_completed,
        "a tab failed to navigate concurrently"
    );
    assert!(distinct_tabs, "new_tab returned the original tab");
    assert!(
        same_session_shared,
        "tabs did not share their Session cookie context"
    );
    assert_eq!(
        fresh_navigation.status,
        yosoi_automation_record::OperationStatus::Observed,
        "fresh Session navigation failed"
    );
    assert!(
        fresh_isolated,
        "a fresh Session inherited the prior Session cookie"
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn close_revokes_held_work_and_wakes_watchers_on_close_and_cancel()
-> Result<(), Box<dyn Error>> {
    if !enabled("close_revokes_held_work_and_wakes_watchers_on_close_and_cancel") {
        return Ok(());
    }

    let policy = browser_policy(5_000_000)?;
    let session = session::new()
        .bind(&policy)
        .configure(settings(1, 5_000))
        .acquire()
        .await?;
    let work = session.work().await?;
    let mut watcher = session.watch();
    let mut watcher_next = Box::pin(watcher.next());
    let (early_watcher_result, watcher_was_pending) = tokio::select! {
        biased;
        result = &mut watcher_next => (Some(result), false),
        () = tokio_task::yield_now() => (None, true),
    };

    let close_result = timeout(Duration::from_secs(8), session.close()).await;
    let close_finished = matches!(close_result, Ok(Ok(())));
    let watcher_result = match early_watcher_result {
        Some(result) => Some(result),
        None => timeout(Duration::from_secs(2), watcher_next).await.ok(),
    };
    let watcher_woke_on_close = matches!(
        watcher_result,
        Some(Err(SessionError::Cancelled | SessionError::Closed))
    );
    let old_authority_rejected = work.observe().await.is_err();
    drop(work);
    if !close_finished {
        let _ = timeout(Duration::from_secs(8), session.close()).await;
    }
    assert!(
        watcher_was_pending,
        "watcher returned before Session close or cancellation"
    );
    assert!(
        close_finished,
        "Session::close did not finish with idle Work held"
    );
    assert!(
        watcher_woke_on_close,
        "pending watcher did not wake when Session closed"
    );
    assert!(
        old_authority_rejected,
        "held Work remained usable after Session close"
    );

    let cancelled = session::new()
        .bind(&policy)
        .configure(settings(1, 5_000))
        .acquire()
        .await?;
    let mut cancelled_watcher = cancelled.watch();
    let mut cancelled_next = Box::pin(cancelled_watcher.next());
    let (early_cancel_result, watcher_was_pending) = tokio::select! {
        biased;
        result = &mut cancelled_next => (Some(result), false),
        () = tokio_task::yield_now() => (None, true),
    };
    cancelled.cancel();
    let cancel_result = match early_cancel_result {
        Some(result) => Some(result),
        None => timeout(Duration::from_secs(2), cancelled_next).await.ok(),
    };
    close(&cancelled).await?;
    assert!(
        watcher_was_pending
            && matches!(
                cancel_result,
                Some(Err(SessionError::Cancelled | SessionError::Closed))
            ),
        "pending watcher did not wake when Session was cancelled"
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn default_policy_denies_scripts_and_domless_observations_keep_document_epoch()
-> Result<(), Box<dyn Error>> {
    if !enabled("default_policy_denies_scripts_and_domless_observations_keep_document_epoch") {
        return Ok(());
    }

    let fixture = session_fixture::SessionFixture::start().await?;
    let policy = browser_policy(5_000_000)?;
    let default_session = session::new()
        .bind(&policy)
        .configure(settings(1, 5_000))
        .acquire()
        .await?;
    let default_work = default_session.work().await?;
    default_work.navigate(&fixture.url("/")).await?;
    let denied = default_work
        .evaluate("document.body.dataset.ysSentinel = 'script-was-sent'")
        .await;
    let default_observation = default_work.observe().await?;
    let script_not_sent = matches!(denied, Err(SessionError::Denied))
        && default_observation
            .html
            .as_deref()
            .is_some_and(|html| !html.contains("script-was-sent"));
    default_work.release().await?;
    close(&default_session).await?;

    let domless_settings = SessionPolicy {
        dom: false,
        ..SessionPolicy::default()
    };
    let domless_session = session::new()
        .bind(&policy)
        .configure(domless_settings)
        .acquire()
        .await?;
    let domless_work = domless_session.work().await?;
    domless_work.navigate(&fixture.url("/seed")).await?;
    let first = domless_work.observe().await?;
    let stable = domless_work.observe().await?;
    domless_work.navigate(&fixture.url("/check")).await?;
    let after_navigation = domless_work.observe().await?;
    let epoch_is_truthful = first.document_epoch == stable.document_epoch
        && after_navigation.document_epoch > stable.document_epoch;
    let dom_omitted =
        first.html.is_none() && stable.html.is_none() && after_navigation.html.is_none();
    domless_work.release().await?;
    close(&domless_session).await?;
    fixture.shutdown().await?;

    assert!(script_not_sent, "default Session sent arbitrary JavaScript");
    assert!(dom_omitted, "DOM-disabled observations retained HTML");
    assert!(
        epoch_is_truthful,
        "document epoch did not remain stable or advance after navigation"
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn watcher_queue_is_bounded_and_reports_lag() -> Result<(), Box<dyn Error>> {
    if !enabled("watcher_queue_is_bounded_and_reports_lag") {
        return Ok(());
    }

    let fixture = session_fixture::SessionFixture::start().await?;
    let policy = browser_policy(5_000_000)?;
    let bounded_settings = SessionPolicy {
        watch_capacity: 1,
        ..settings(1, 5_000)
    };
    let session = session::new()
        .bind(&policy)
        .configure(bounded_settings)
        .acquire()
        .await?;
    let mut watcher = session.watch();
    let work = session.work().await?;
    work.navigate(&fixture.url("/")).await?;
    work.wait(0).await?;
    let first_watcher_result = timeout(Duration::from_secs(2), watcher.next()).await;
    let lagged =
        matches!(first_watcher_result, Ok(Err(SessionError::WatchLagged(count))) if count > 0);
    work.release().await?;
    close(&session).await?;
    fixture.shutdown().await?;

    assert!(lagged, "a full watcher queue did not report explicit lag");
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn request_and_flow_bind_limits_intersect_with_session_deadlines()
-> Result<(), Box<dyn Error>> {
    if !enabled("request_and_flow_bind_limits_intersect_with_session_deadlines") {
        return Ok(());
    }

    let fixture = session_fixture::SessionFixture::start().await?;
    let session_policy = browser_policy(5_000_000)?;
    let session = session::new()
        .bind(&session_policy)
        .configure(settings(1, 120))
        .acquire()
        .await?;
    let work = session.work().await?;

    // A looser Request policy must still obey the shorter Session deadline.
    let request_policy = browser_policy(2_000_000)?;
    let mut request_watcher = session.watch();
    let request_started = tokio_time::Instant::now();
    let request_result = timeout(
        Duration::from_secs(3),
        request::new(fixture.url("/delay/500"))
            .with_work(&work)
            .bind(&request_policy)
            .send(),
    )
    .await;
    let request_elapsed = request_started.elapsed();
    let request_incomplete = match &request_result {
        Ok(Ok(response)) => {
            response.termination() != ResponseTermination::Completed
                || response
                    .attempts()
                    .any(|attempt| attempt.state() != AttemptState::Completed)
                || response.attempts().any(|attempt| {
                    attempt
                        .documents()
                        .any(|document| !matches!(document.outcome(), DocumentOutcome::Produced(_)))
                })
        }
        Ok(Err(_)) => true,
        Err(_) => false,
    };
    let request_watcher_result = timeout(Duration::from_secs(2), request_watcher.next()).await;
    let request_watcher_not_success = match request_watcher_result {
        Ok(Ok(receipt)) => receipt.status != yosoi_automation_record::OperationStatus::Observed,
        Ok(Err(SessionError::WatchDeadline)) => true,
        _ => false,
    };

    let request_tab_fenced = matches!(
        work.navigate(&fixture.url("/")).await,
        Err(SessionError::Closed)
    );
    work.release().await?;
    close(&session).await?;

    // Test Flow's stricter policy on fresh control, since timed-out Request control is fenced.
    let flow_session = session::new()
        .bind(&session_policy)
        .configure(settings(1, 1_000))
        .acquire()
        .await?;
    let flow_work = flow_session.work().await?;
    let mut flow_policy = browser_policy(50_000)?;
    // Flow action bounds are explicit and independent of Request acquisition bounds.
    flow_policy.default_action_timeout_ms = 50;
    let delayed_flow = Flow::new([Step::Navigate {
        url: fixture.url("/delay/500"),
    }]);
    let flow_started = tokio_time::Instant::now();
    let flow_result = timeout(
        Duration::from_secs(3),
        delayed_flow
            .bind(&flow_policy)
            .with_lease(&flow_work)
            .invoke(),
    )
    .await;
    let flow_elapsed = flow_started.elapsed();
    let flow_not_completed =
        matches!(flow_result, Ok(Ok(outcome)) if outcome.terminal != FlowTermination::Completed);

    flow_work.release().await?;
    close(&flow_session).await?;
    fixture.shutdown().await?;

    assert!(
        request_incomplete,
        "Request exceeded the stricter Session deadline"
    );
    assert!(
        request_elapsed < Duration::from_millis(400),
        "Request did not return within the bounded operation/collector margin: {request_elapsed:?}"
    );
    assert!(
        request_watcher_not_success,
        "a partial or failed browser Request was reported as successful to its watcher"
    );
    assert!(flow_not_completed, "Flow ignored its stricter bound policy");
    assert!(
        flow_elapsed < Duration::from_millis(400),
        "Flow did not respect its bounded action margin: {flow_elapsed:?}"
    );
    assert!(
        request_tab_fenced,
        "timed-out Request control remained available for new work"
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn incomplete_browser_request_is_not_reported_as_observed() -> Result<(), Box<dyn Error>> {
    if !enabled("incomplete_browser_request_is_not_reported_as_observed") {
        return Ok(());
    }

    let fixture = session_fixture::SessionFixture::start().await?;
    let session_policy = browser_policy(5_000_000)?;
    let session = session::new()
        .bind(&session_policy)
        .configure(settings(1, 1_000))
        .acquire()
        .await?;
    let work = session.work().await?;
    let mut limited_request_policy = browser_policy(5_000_000)?;
    limited_request_policy.request.browser.dom_utf8_bytes = AddressableByteLimit::try_from(32_u64)?;
    let mut watcher = session.watch();
    let response_result = timeout(
        Duration::from_secs(5),
        request::new(fixture.url("/"))
            .with_work(&work)
            .bind(&limited_request_policy)
            .send(),
    )
    .await;

    let response_incomplete = match &response_result {
        Ok(Ok(response)) => response.attempts().any(|attempt| {
            attempt.documents().any(|document| {
                document.requested() == DocumentRequest::RenderedDom
                    && !matches!(document.outcome(), DocumentOutcome::Produced(_))
            })
        }),
        Ok(Err(_)) => true,
        Err(_) => false,
    };
    let watcher_result = timeout(Duration::from_secs(5), watcher.next()).await;
    let watcher_not_success = match watcher_result {
        Ok(Ok(receipt)) => receipt.status != yosoi_automation_record::OperationStatus::Observed,
        Ok(Err(SessionError::WatchDeadline)) => true,
        _ => false,
    };

    work.release().await?;
    close(&session).await?;
    fixture.shutdown().await?;

    assert!(
        response_incomplete,
        "the bounded Request unexpectedly produced a complete DOM"
    );
    assert!(
        watcher_not_success,
        "watcher treated an incomplete browser Request as observed"
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn closing_an_additional_tab_revokes_only_its_held_work() -> Result<(), Box<dyn Error>> {
    if !enabled("closing_an_additional_tab_revokes_only_its_held_work") {
        return Ok(());
    }

    let fixture = session_fixture::SessionFixture::start().await?;
    let policy = browser_policy(5_000_000)?;
    let session = session::new()
        .bind(&policy)
        .configure(settings(2, 5_000))
        .acquire()
        .await?;
    let initial = session.work().await?;
    initial.navigate(&fixture.url("/seed")).await?;

    let additional_tab = session.new_tab().await?;
    let additional = additional_tab.work().await?;
    additional.navigate(&fixture.url("/check")).await?;
    additional_tab.close().await?;

    let closed_work_rejected = additional.observe().await.is_err();
    let initial_receipt = initial.navigate(&fixture.url("/check")).await?;
    let initial_observation = initial.observe().await?;
    let initial_work_usable = initial_receipt.status
        == yosoi_automation_record::OperationStatus::Observed
        && initial_observation
            .html
            .as_deref()
            .is_some_and(|html| html.contains("shared-context"));

    additional.release().await?;
    initial.release().await?;
    close(&session).await?;
    fixture.shutdown().await?;

    assert!(
        closed_work_rejected,
        "Work held on a closed additional tab remained usable"
    );
    assert!(
        initial_work_usable,
        "closing an additional tab invalidated the initial Session tab"
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn action_receipt_is_unknown_when_dom_evidence_exceeds_its_bound()
-> Result<(), Box<dyn Error>> {
    if !enabled("action_receipt_is_unknown_when_dom_evidence_exceeds_its_bound") {
        return Ok(());
    }

    let fixture = session_fixture::SessionFixture::start().await?;
    let policy = browser_policy(5_000_000)?;
    let bounded_settings = SessionPolicy {
        maximum_observation_bytes: 32,
        ..settings(1, 5_000)
    };
    let session = session::new()
        .bind(&policy)
        .configure(bounded_settings)
        .acquire()
        .await?;
    let work = session.work().await?;
    let receipt = work.navigate(&fixture.url("/")).await?;
    let evidence_unavailable = receipt.observation.is_none();
    work.release().await?;
    close(&session).await?;
    fixture.shutdown().await?;

    assert_eq!(
        receipt.status,
        yosoi_automation_record::OperationStatus::Unknown,
        "an action with incomplete DOM evidence was reported as observed"
    );
    assert!(
        evidence_unavailable,
        "the bounded receipt unexpectedly retained incomplete DOM evidence"
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn json_unsupported_javascript_result_is_not_observed_as_null() -> Result<(), Box<dyn Error>>
{
    if !enabled("json_unsupported_javascript_result_is_not_observed_as_null") {
        return Ok(());
    }

    let fixture = session_fixture::SessionFixture::start().await?;
    let policy = browser_policy(5_000_000)?;
    let javascript_settings = allow_javascript(settings(1, 5_000));
    let session = session::new()
        .bind(&policy)
        .configure(javascript_settings)
        .acquire()
        .await?;
    let work = session.work().await?;
    work.navigate(&fixture.url("/")).await?;
    let receipt = work.evaluate("1n").await?;
    work.release().await?;
    close(&session).await?;
    fixture.shutdown().await?;

    assert_eq!(
        receipt.status,
        yosoi_automation_record::OperationStatus::Unknown,
        "a JavaScript BigInt without a JSON representation was reported as observed"
    );
    assert_ne!(
        receipt.result,
        Some(serde_json::Value::Null),
        "an unsupported JavaScript result was collapsed into JSON null"
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn targeted_evaluation_rejects_stale_missing_and_unsupported_targets_before_dispatch()
-> Result<(), Box<dyn Error>> {
    if !enabled("targeted_evaluation_rejects_stale_missing_and_unsupported_targets_before_dispatch")
    {
        return Ok(());
    }

    let fixture = session_fixture::SessionFixture::start().await?;
    let policy = browser_policy(5_000_000)?;
    let javascript_settings = allow_javascript(settings(1, 5_000));
    let session = session::new()
        .bind(&policy)
        .configure(javascript_settings)
        .acquire()
        .await?;
    let work = session.work().await?;
    work.navigate(&fixture.url("/")).await?;
    let observation = work.observe().await?;
    let source = "globalThis.__yosoi_target_probe = 'ran'; 'ran'";

    let stale_target = session::JsTarget {
        frame: session::JsFrame::Main,
        world: session::JsWorld::Main,
        expected_document_epoch: Some(observation.document_epoch.saturating_add(1)),
    };
    let stale_result = work.evaluate_targeted(&stale_target, source).await;
    let missing_frame_target = session::JsTarget {
        frame: session::JsFrame::UrlContains("no-such-frame".to_owned()),
        world: session::JsWorld::Main,
        expected_document_epoch: None,
    };
    let missing_frame_result = work.evaluate_targeted(&missing_frame_target, source).await;
    let isolated_world_target = session::JsTarget {
        frame: session::JsFrame::Main,
        world: session::JsWorld::Isolated,
        expected_document_epoch: None,
    };
    let isolated_world_result = work.evaluate_targeted(&isolated_world_target, source).await;
    let probe = work
        .evaluate("typeof globalThis.__yosoi_target_probe")
        .await?;
    let script_was_not_dispatched =
        probe.result == Some(serde_json::Value::String("undefined".to_owned()));

    work.release().await?;
    close(&session).await?;
    fixture.shutdown().await?;

    assert!(
        matches!(stale_result, Err(SessionError::InvalidInput)),
        "targeted evaluation accepted a stale document epoch"
    );
    assert!(
        matches!(missing_frame_result, Err(SessionError::InvalidInput)),
        "targeted evaluation dispatched into a missing frame"
    );
    assert!(
        matches!(isolated_world_result, Err(SessionError::Unsupported(_))),
        "unsupported isolated-world evaluation was not rejected explicitly"
    );
    assert!(
        script_was_not_dispatched,
        "a rejected targeted evaluation still ran its JavaScript source"
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn process_browser_limit_bounds_waiting_acquisitions() -> Result<(), Box<dyn Error>> {
    if !enabled("process_browser_limit_bounds_waiting_acquisitions") {
        return Ok(());
    }

    let policy = browser_policy(5_000_000)?;
    let first = session::new()
        .bind(&policy)
        .configure(settings(1, 5_000))
        .acquire()
        .await?;
    let second = session::new()
        .bind(&policy)
        .configure(settings(1, 5_000))
        .acquire()
        .await?;

    let cancellation = CancellationToken::new();
    let mut third = Box::pin(
        session::new()
            .bind(&policy)
            .configure(settings(1, 5_000))
            .acquire_cancellable(&cancellation),
    );
    let (early_third_result, third_waited_for_capacity) = tokio::select! {
        biased;
        result = &mut third => {
            (Some(result), false)
        },
        () = tokio_task::yield_now() => (None, true),
    };
    cancellation.cancel();
    let third_result = match early_third_result {
        Some(result) => result,
        None => timeout(Duration::from_secs(2), third)
            .await
            .map_err(|_| io::Error::other("cancelled queued Session did not wake"))?,
    };
    let third_cancelled = matches!(&third_result, Err(SessionError::Cancelled));
    if let Ok(third_session) = third_result {
        let _ = close(&third_session).await;
    }
    close(&first).await?;
    close(&second).await?;

    assert!(
        third_waited_for_capacity,
        "a third browser Session bypassed the process-wide capacity limit"
    );
    assert!(
        third_cancelled,
        "a queued Session did not wake on cancellation"
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn targeted_evaluation_reads_a_uniquely_selected_srcdoc_frame() -> Result<(), Box<dyn Error>>
{
    if !enabled("targeted_evaluation_reads_a_uniquely_selected_srcdoc_frame") {
        return Ok(());
    }

    let fixture = session_fixture::SessionFixture::start().await?;
    let policy = browser_policy(5_000_000)?;
    let javascript_settings = allow_javascript(settings(1, 5_000));
    let session = session::new()
        .bind(&policy)
        .configure(javascript_settings)
        .acquire()
        .await?;
    let work = session.work().await?;
    work.navigate(&fixture.url("/")).await?;

    let created = work
        .evaluate(
            "(()=>{const frame=document.createElement('iframe');frame.srcdoc='<p id=\"inside\">frame</p>';document.body.append(frame);return 'created'})()",
        )
        .await?;
    let target = session::JsTarget {
        frame: session::JsFrame::UrlContains("about:srcdoc".to_owned()),
        world: session::JsWorld::Main,
        expected_document_epoch: None,
    };
    let evaluated = work
        .evaluate_targeted(&target, "document.getElementById('inside')?.textContent")
        .await?;

    work.release().await?;
    close(&session).await?;
    fixture.shutdown().await?;

    assert_eq!(
        created.status,
        yosoi_automation_record::OperationStatus::Observed,
        "creating the srcdoc frame did not produce an observed action receipt"
    );
    assert_eq!(
        created.result,
        Some(serde_json::Value::String("created".to_owned())),
        "the srcdoc frame creation script did not complete"
    );
    assert_eq!(
        evaluated.status,
        yosoi_automation_record::OperationStatus::Observed,
        "evaluation in the uniquely selected srcdoc frame was not observed"
    );
    assert_eq!(
        evaluated.result,
        Some(serde_json::Value::String("frame".to_owned())),
        "targeted evaluation did not read the iframe document"
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn same_tab_work_waiters_are_bounded_and_abandoned_waits_release_capacity()
-> Result<(), Box<dyn Error>> {
    if !enabled("same_tab_work_waiters_are_bounded_and_abandoned_waits_release_capacity") {
        return Ok(());
    }

    use std::future::Future;

    let policy = browser_policy(5_000_000)?;
    let session = session::new()
        .bind(&policy)
        .configure(settings(1, 5_000))
        .acquire()
        .await?;
    let held_work = session.work().await?;
    let mut waiters = Vec::with_capacity(32);
    for _ in 0..32 {
        waiters.push(Box::pin(session.work()));
    }

    let mut context = std::task::Context::from_waker(std_task::Waker::noop());
    let all_waiters_pending = waiters
        .iter_mut()
        .all(|waiter| matches!(waiter.as_mut().poll(&mut context), std_task::Poll::Pending));

    let mut overflow = Box::pin(session.work());
    let overflow_rejected = matches!(
        overflow.as_mut().poll(&mut context),
        std_task::Poll::Ready(Err(SessionError::Admission))
    );
    drop(overflow);

    drop(waiters.pop());
    let mut replacement = Box::pin(session.work());
    let replacement_waited_for_held_tab = matches!(
        replacement.as_mut().poll(&mut context),
        std_task::Poll::Pending
    );
    drop(replacement);
    drop(waiters);

    held_work.release().await?;
    let recovered_work = session.work().await?;
    recovered_work.release().await?;
    close(&session).await?;

    assert!(
        all_waiters_pending,
        "one of the 32 permitted same-tab Work waiters completed unexpectedly"
    );
    assert!(
        overflow_rejected,
        "a 33rd same-tab Work waiter was admitted instead of rejected immediately"
    );
    assert!(
        replacement_waited_for_held_tab,
        "dropping a queued Work future did not release its waiter reservation"
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn javascript_result_errors_are_truthful_and_unresolved_dispatch_fences_one_tab()
-> Result<(), Box<dyn Error>> {
    if !enabled("javascript_result_errors_are_truthful_and_unresolved_dispatch_fences_one_tab") {
        return Ok(());
    }

    let fixture = session_fixture::SessionFixture::start().await?;
    let policy = browser_policy(5_000_000)?;
    let javascript_settings = allow_javascript(SessionPolicy {
        maximum_result_bytes: 64,
        ..settings(2, 1_000)
    });
    let session = session::new()
        .bind(&policy)
        .configure(javascript_settings)
        .acquire()
        .await?;
    let work = session.work().await?;
    work.navigate(&fixture.url("/")).await?;
    let additional_tab = session.new_tab().await?;
    let additional_work = additional_tab.work().await?;
    additional_work.navigate(&fixture.url("/")).await?;

    let oversized = work.evaluate("'x'.repeat(1024)").await?;
    let thrown = work
        .evaluate("throw new Error('distinct-provider-marker')")
        .await?;
    let pending = work
        .evaluate(
            "(()=>{document.body.dataset.dispatchFenceProbe='mutated';return new Promise(()=>{})})()",
        )
        .await?;
    let subsequent_same_work = work.evaluate("'must-not-run'").await;
    let new_work_on_fenced_tab = session.work().await;
    let additional_tab_receipt = additional_work
        .evaluate("'additional-tab-still-usable'")
        .await?;

    let oversized_error_has_limit = oversized
        .error
        .as_deref()
        .is_some_and(|error| error.contains("64"));
    let thrown_error_preserves_reason = thrown
        .error
        .as_deref()
        .is_some_and(|error| error.contains("distinct-provider-marker"));
    let same_work_fenced = matches!(subsequent_same_work, Err(SessionError::Closed));
    let same_tab_acquisition_rejected = new_work_on_fenced_tab.is_err();
    let additional_tab_usable = additional_tab_receipt.status
        == yosoi_automation_record::OperationStatus::Observed
        && additional_tab_receipt.result
            == Some(serde_json::Value::String(
                "additional-tab-still-usable".to_owned(),
            ));

    // Keep both Work handles alive until explicit Session close resolves the fenced dispatch.
    close(&session).await?;
    work.release().await?;
    additional_work.release().await?;
    fixture.shutdown().await?;

    assert_eq!(
        oversized.status,
        yosoi_automation_record::OperationStatus::Unknown,
        "a JavaScript result over the configured byte limit was reported as observed"
    );
    assert!(
        oversized_error_has_limit,
        "the oversized-result receipt did not name its configured 64-byte limit"
    );
    assert_eq!(
        thrown.status,
        yosoi_automation_record::OperationStatus::Unknown,
        "a JavaScript exception was reported as observed"
    );
    assert!(
        thrown_error_preserves_reason,
        "the JavaScript exception receipt lost its provider error reason: {:?}",
        thrown.error
    );
    assert_eq!(
        pending.status,
        yosoi_automation_record::OperationStatus::Unknown,
        "an unresolved JavaScript promise was reported as observed"
    );
    assert!(
        same_work_fenced,
        "a subsequent command was allowed on a tab with unresolved dispatch"
    );
    assert!(
        same_tab_acquisition_rejected,
        "a new Work lease was granted for a tab with unresolved dispatch"
    );
    assert!(
        additional_tab_usable,
        "fencing an unresolved dispatch disabled another tab in the same Session"
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn watchers_receive_session_wide_receipts_for_two_tabs_and_close_independently()
-> Result<(), Box<dyn Error>> {
    if !enabled("watchers_receive_session_wide_receipts_for_two_tabs_and_close_independently") {
        return Ok(());
    }

    let fixture = session_fixture::SessionFixture::start().await?;
    let policy = browser_policy(5_000_000)?;
    let session = session::new()
        .bind(&policy)
        .configure(settings(2, 5_000))
        .acquire()
        .await?;
    let initial_work = session.work().await?;
    let additional_tab = session.new_tab().await?;
    let additional_work = additional_tab.work().await?;
    let mut first_watcher = session.watch();
    let mut second_watcher = session.watch();

    let initial_receipt = initial_work.navigate(&fixture.url("/?tab=one")).await?;
    let additional_receipt = additional_work.navigate(&fixture.url("/?tab=two")).await?;
    let first_events = [first_watcher.next().await?, first_watcher.next().await?];
    let second_events = [second_watcher.next().await?, second_watcher.next().await?];

    let event_matches_receipt =
        |events: &[std_sync::Arc<yosoi_automation_record::OperationReceipt>],
         expected: &yosoi_automation_record::OperationReceipt| {
            events.iter().any(|event| {
                event.id == expected.id
                    && event.observation.as_ref().is_some_and(|observed| {
                        expected
                            .observation
                            .as_ref()
                            .is_some_and(|expected_observation| {
                                observed.tab_id == expected_observation.tab_id
                            })
                    })
            })
        };
    let first_watcher_saw_both = event_matches_receipt(&first_events, &initial_receipt)
        && event_matches_receipt(&first_events, &additional_receipt);
    let second_watcher_saw_both = event_matches_receipt(&second_events, &initial_receipt)
        && event_matches_receipt(&second_events, &additional_receipt);
    let tabs_were_distinct = matches!(
        (
            initial_receipt
                .observation
                .as_ref()
                .map(|observation| observation.tab_id.as_str()),
            additional_receipt
                .observation
                .as_ref()
                .map(|observation| observation.tab_id.as_str()),
        ),
        (Some(initial), Some(additional)) if initial != additional
    );

    first_watcher.close();
    let later_receipt = initial_work.navigate(&fixture.url("/?tab=three")).await?;
    let later_event = second_watcher.next().await?;
    let second_watcher_survived_close = later_event.id == later_receipt.id
        && later_event.observation.as_ref().is_some_and(|observed| {
            later_receipt
                .observation
                .as_ref()
                .is_some_and(|expected| observed.tab_id == expected.tab_id)
        });

    second_watcher.close();
    initial_work.release().await?;
    additional_work.release().await?;
    close(&session).await?;
    fixture.shutdown().await?;

    assert!(
        tabs_were_distinct,
        "the additional Work did not use a distinct tab"
    );
    assert!(
        first_watcher_saw_both,
        "the first watcher missed a tab's navigation receipt or tab identity"
    );
    assert!(
        second_watcher_saw_both,
        "the second watcher missed a tab's navigation receipt or tab identity"
    );
    assert!(
        second_watcher_survived_close,
        "closing one watcher disabled receipt delivery to the other"
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn dropping_a_dispatched_work_request_fences_its_tab_until_session_close()
-> Result<(), Box<dyn Error>> {
    if !enabled("dropping_a_dispatched_work_request_fences_its_tab_until_session_close") {
        return Ok(());
    }

    use tokio::{
        io::{AsyncReadExt, AsyncWriteExt},
        net::TcpListener,
        sync::oneshot,
    };

    let policy = browser_policy(5_000_000)?;
    let session = session::new()
        .bind(&policy)
        .configure(settings(1, 3_000))
        .acquire()
        .await?;
    let work = session.work().await?;

    let listener = TcpListener::bind((std_net::Ipv4Addr::LOCALHOST, 0)).await?;
    let address = listener.local_addr()?;
    let (request_seen_tx, request_seen_rx) = oneshot::channel();
    let (allow_response_tx, allow_response_rx) = oneshot::channel();
    let mut server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await?;
        let mut headers = Vec::with_capacity(2_048);
        loop {
            let mut buffer = [0_u8; 1_024];
            let read = stream.read(&mut buffer).await?;
            if read == 0 {
                return Err(io::Error::other(
                    "browser connection closed before sending request headers",
                ));
            }
            let chunk = buffer
                .get(..read)
                .ok_or_else(|| io::Error::other("loopback read exceeded its buffer"))?;
            headers.extend_from_slice(chunk);
            if headers.windows(4).any(|window| window == b"\r\n\r\n") {
                break;
            }
            if headers.len() > 8_192 {
                return Err(io::Error::other("loopback request headers exceeded 8 KiB"));
            }
        }
        let request_line = String::from_utf8_lossy(&headers)
            .lines()
            .next()
            .map(str::to_owned)
            .ok_or_else(|| io::Error::other("loopback request had no request line"))?;
        let _ = request_seen_tx.send(request_line);
        let _ = allow_response_rx.await;
        let body = "<!doctype html><html><body><main><p>held response</p></main></body></html>";
        let response = format!(
            "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
            body.len()
        );
        let _ = stream.write_all(response.as_bytes()).await;
        Ok::<(), io::Error>(())
    });

    let url = format!("http://{address}/hold");
    let bound_request = request::new(url.clone()).with_work(&work);
    let mut send_future = Box::pin(bound_request.send());
    let request_line = timeout(Duration::from_secs(3), async {
        tokio::select! {
            biased;
            line = request_seen_rx => line.ok(),
            _result = &mut send_future => None,
        }
    })
    .await
    .ok()
    .flatten();
    drop(send_future);
    let dispatched_to_expected_path = request_line
        .as_deref()
        .is_some_and(|line| line.starts_with("GET /hold "));

    let later_navigation = timeout(Duration::from_secs(3), work.navigate(&url)).await;
    let navigate_rejected = matches!(later_navigation, Ok(Err(SessionError::Closed)));
    let replacement_work = timeout(Duration::from_secs(3), session.work()).await;
    let same_tab_work_rejected = matches!(replacement_work, Ok(Err(SessionError::Admission)));

    let session_closed_promptly = matches!(
        timeout(Duration::from_secs(3), session.close()).await,
        Ok(Ok(()))
    );
    work.release().await?;
    if request_line.is_some() {
        let _ = allow_response_tx.send(());
    } else {
        server.abort();
    }
    let server_finished = if matches!(
        timeout(Duration::from_secs(3), &mut server).await,
        Ok(Ok(Ok(())))
    ) {
        true
    } else {
        server.abort();
        let _ = server.await;
        false
    };

    assert!(
        dispatched_to_expected_path,
        "the borrowed Request future was dropped before its loopback HTTP request arrived"
    );
    assert!(
        navigate_rejected,
        "Work::navigate was allowed after dropping a dispatched borrowed Request"
    );
    assert!(
        same_tab_work_rejected,
        "a new Work lease was granted after dropping a dispatched borrowed Request"
    );
    assert!(
        session_closed_promptly,
        "closing the Session did not promptly resolve the dropped Request dispatch"
    );
    assert!(
        server_finished,
        "the held-response loopback server did not finish"
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn empty_browser_document_selection_cannot_report_a_deadline_as_observed()
-> Result<(), Box<dyn Error>> {
    if !enabled("empty_browser_document_selection_cannot_report_a_deadline_as_observed") {
        return Ok(());
    }

    let fixture = session_fixture::SessionFixture::start().await?;
    let session_policy = browser_policy(5_000_000)?;
    let domless_settings = SessionPolicy {
        dom: false,
        ..settings(1, 120)
    };
    let session = session::new()
        .bind(&session_policy)
        .configure(domless_settings)
        .acquire()
        .await?;
    let work = session.work().await?;

    let mut empty_documents_policy = browser_policy(2_000_000)?;
    empty_documents_policy.page = Page::new(vec![
        Acquisition::Browser(BrowserMode::Headless).documents(std_iter::empty::<DocumentRequest>()),
    ])?;
    let mut watcher = session.watch();
    let started = tokio_time::Instant::now();
    let response = timeout(
        Duration::from_secs(3),
        request::new(fixture.url("/delay/500"))
            .with_work(&work)
            .bind(&empty_documents_policy)
            .send(),
    )
    .await
    .map_err(|_| io::Error::other("empty-document browser Request exceeded 3 seconds"))??;
    let elapsed = started.elapsed();
    let receipt = timeout(Duration::from_secs(3), watcher.next())
        .await
        .map_err(|_| io::Error::other("empty-document Request receipt was not published"))??;

    let no_requested_documents = response
        .attempts()
        .all(|attempt| attempt.documents().next().is_none());
    let no_html_retained = receipt
        .observation
        .as_ref()
        .is_none_or(|observation| observation.html.is_none());
    let next_navigation = timeout(Duration::from_secs(3), work.navigate(&fixture.url("/"))).await;
    let fenced_after_deadline = matches!(next_navigation, Ok(Err(SessionError::Closed)));

    work.release().await?;
    close(&session).await?;
    fixture.shutdown().await?;

    assert_eq!(
        receipt.status,
        yosoi_automation_record::OperationStatus::Unknown,
        "an empty-document Request past its deadline was reported as observed"
    );
    assert!(
        no_requested_documents,
        "the exact-empty Browser document policy unexpectedly retained documents"
    );
    assert!(
        no_html_retained,
        "the DOM-disabled Request retained HTML evidence"
    );
    assert!(
        elapsed < Duration::from_millis(400),
        "the bounded Request exceeded its 120 ms Session deadline margin: {elapsed:?}"
    );
    assert!(
        fenced_after_deadline,
        "Work::navigate was allowed after an unsettled empty-document Request"
    );
    Ok(())
}
