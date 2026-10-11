use std::error::Error;

use yosoi::{
    action,
    automation_record::{AutomationRecord, Observation, OperationReceipt, OperationStatus},
    expect,
    flow::{Flow, FlowOutcome, FlowPolicy, FlowTermination, StepOutcome},
    session::{UntilCheck, UntilCheckState, UntilReport, UntilScope, UntilTermination},
};

type TestError = Box<dyn Error + Send + Sync>;

#[cfg(feature = "browser")]
#[path = "support/until_fixture.rs"]
mod until_fixture;

#[test]
fn authored_until_rejects_an_observed_click_receipt_carrying_a_report() -> Result<(), TestError> {
    let report = network_report("click-kind");
    let flow = network_step("click-kind");
    let receipt = OperationReceipt {
        id: "until-outer-click-kind".to_owned(),
        kind: "click".to_owned(),
        status: OperationStatus::Observed,
        result: Some(serde_json::to_value(report)?),
        observation: Some(observation()),
        error: None,
    };
    let outcome = outcome(flow, receipt);

    let record = AutomationRecord::new("wrong-until-kind", Vec::new(), Vec::new())?
        .with_flow_outcome(outcome);
    assert!(
        record.is_err(),
        "an authored Until must use the Until receipt kind"
    );
    Ok(())
}

#[test]
fn satisfied_network_archive_requires_valid_trigger_and_request_timestamps() -> Result<(), TestError>
{
    let positive = network_report("timestamp-positive");
    positive.validate()?;
    assert!(record_with_report(positive, "timestamp-positive").is_ok());

    let mut missing_trigger = network_report("timestamp-missing-trigger");
    set_trigger_timestamp(&mut missing_trigger, None)?;
    assert!(record_with_report(missing_trigger, "timestamp-missing-trigger").is_err());

    let mut zero_trigger = network_report("timestamp-zero-trigger");
    set_trigger_timestamp(&mut zero_trigger, Some(serde_json::json!(0)))?;
    assert!(record_with_report(zero_trigger, "timestamp-zero-trigger").is_err());

    let mut invalid_trigger = network_report("timestamp-invalid-trigger");
    set_trigger_timestamp(
        &mut invalid_trigger,
        Some(serde_json::json!("not-a-timestamp")),
    )?;
    assert!(record_with_report(invalid_trigger, "timestamp-invalid-trigger").is_err());

    let mut missing_request = network_report("timestamp-missing-request");
    set_network_timestamp(&mut missing_request, None)?;
    assert!(record_with_report(missing_request, "timestamp-missing-request").is_err());

    let mut zero_request = network_report("timestamp-zero-request");
    set_network_timestamp(&mut zero_request, Some(serde_json::json!(0)))?;
    assert!(record_with_report(zero_request, "timestamp-zero-request").is_err());

    let mut invalid_request = network_report("timestamp-invalid-request");
    set_network_timestamp(
        &mut invalid_request,
        Some(serde_json::json!("not-a-timestamp")),
    )?;
    assert!(record_with_report(invalid_request, "timestamp-invalid-request").is_err());
    Ok(())
}

#[test]
fn operations_vector_must_match_the_canonical_until_receipt_byte_for_byte() -> Result<(), TestError>
{
    let report = network_report("canonical-payload");
    let flow = network_step("canonical-payload");
    let receipt = until_receipt("canonical-until", &report)?;
    let outcome = outcome(flow, receipt.clone());

    let canonical = AutomationRecord::new(
        "canonical-operation-reference",
        Vec::new(),
        vec![receipt.clone()],
    )?
    .with_flow_outcome(outcome.clone());
    assert!(
        canonical.is_ok(),
        "an exact duplicate reference is canonical"
    );

    let mut conflicting_report = network_report("different-payload");
    conflicting_report
        .checks
        .first_mut()
        .and_then(|check| check.evidence.as_mut())
        .and_then(|evidence| evidence.get_mut("body"))
        .and_then(serde_json::Value::as_object_mut)
        .ok_or("network report has no JSON body")?
        .insert("attempt".to_owned(), serde_json::json!("different-payload"));
    let conflicting = until_receipt("canonical-until", &conflicting_report)?;
    let mismatched = AutomationRecord::new(
        "mismatched-operation-reference",
        Vec::new(),
        vec![conflicting],
    )?
    .with_flow_outcome(outcome);
    assert!(
        mismatched.is_err(),
        "a same-ID operation reference cannot replace the Flow's report"
    );
    Ok(())
}

fn record_with_report(report: UntilReport, attempt: &str) -> Result<AutomationRecord, TestError> {
    let flow = network_step(attempt);
    let receipt = until_receipt("network-until", &report)?;
    Ok(
        AutomationRecord::new("timestamp-report", Vec::new(), Vec::new())?
            .with_flow_outcome(outcome(flow, receipt))?,
    )
}

fn outcome(flow: Flow, receipt: OperationReceipt) -> FlowOutcome {
    FlowOutcome {
        version: 3,
        flow,
        steps: vec![StepOutcome {
            index: 0,
            flow_path: vec![0],
            receipt,
            failure: None,
            cancellation: None,
            cancelled_flow: None,
        }],
        terminal: FlowTermination::Completed,
        continuation_defaults: FlowPolicy::default(),
        stop_reason: None,
        skipped_steps: Vec::new(),
        cleanup: Vec::new(),
        failure_capture: None,
    }
}

fn network_step(attempt: &str) -> Flow {
    Flow::new([action::click("#trigger").until(
        expect::response(network_url(attempt))
            .method("GET")
            .status(200)
            .json("/attempt", attempt),
    )])
}

fn network_url(attempt: &str) -> String {
    format!("http://127.0.0.1/api?attempt={attempt}")
}

fn network_report(attempt: &str) -> UntilReport {
    UntilReport {
        version: 1,
        termination: UntilTermination::Satisfied,
        scope: UntilScope {
            session_id: "session-archive".to_owned(),
            tab_id: "tab-archive".to_owned(),
            document_epoch: 7,
            frame_id: Some("frame-archive".to_owned()),
            loader_id: Some("loader-archive".to_owned()),
        },
        trigger: Some(OperationReceipt {
            id: format!("trigger-{attempt}"),
            kind: "click".to_owned(),
            status: OperationStatus::Observed,
            result: Some(serde_json::json!({
                "value": null,
                "started_at_unix_us": 1_000
            })),
            observation: None,
            error: None,
        }),
        evaluations: 1,
        checks: vec![UntilCheck {
            index: 0,
            source: "network".to_owned(),
            state: UntilCheckState::Satisfied,
            evidence: Some(serde_json::json!({
                "request_id": format!("request-{attempt}"),
                "url": network_url(attempt),
                "method": "GET",
                "status": 200,
                "top_level": true,
                "frame_id": "frame-archive",
                "loader_id": "loader-archive",
                "started_at_unix_us": 1_001,
                "document_epoch": 7,
                "observed_at_unix_ms": 1,
                "body": {"attempt": attempt}
            })),
            error: None,
        }],
        error: None,
    }
}

fn set_trigger_timestamp(
    report: &mut UntilReport,
    value: Option<serde_json::Value>,
) -> Result<(), TestError> {
    let result = report
        .trigger
        .as_mut()
        .and_then(|trigger| trigger.result.as_mut())
        .and_then(serde_json::Value::as_object_mut)
        .ok_or("report has no trigger result")?;
    match value {
        Some(value) => {
            let _ = result.insert("started_at_unix_us".to_owned(), value);
        }
        None => {
            let _ = result.remove("started_at_unix_us");
        }
    }
    Ok(())
}

fn set_network_timestamp(
    report: &mut UntilReport,
    value: Option<serde_json::Value>,
) -> Result<(), TestError> {
    let evidence = report
        .checks
        .first_mut()
        .and_then(|check| check.evidence.as_mut())
        .and_then(serde_json::Value::as_object_mut)
        .ok_or("report has no network evidence")?;
    match value {
        Some(value) => {
            let _ = evidence.insert("started_at_unix_us".to_owned(), value);
        }
        None => {
            let _ = evidence.remove("started_at_unix_us");
        }
    }
    Ok(())
}

fn until_receipt(id: &str, report: &UntilReport) -> Result<OperationReceipt, TestError> {
    Ok(OperationReceipt {
        id: id.to_owned(),
        kind: "until".to_owned(),
        status: OperationStatus::Observed,
        result: Some(serde_json::to_value(report)?),
        observation: Some(observation()),
        error: None,
    })
}

fn observation() -> Observation {
    Observation {
        id: "observation-archive".to_owned(),
        session_id: "session-archive".to_owned(),
        tab_id: "tab-archive".to_owned(),
        document_epoch: 7,
        html: None,
        url: Some("http://127.0.0.1/until".to_owned()),
        screenshot: None,
    }
}

#[cfg(feature = "browser")]
mod browser_cleanup {
    use std::{env, error::Error, io, time::Duration};

    use tokio::time::timeout;
    use tokio_util::sync::CancellationToken;
    use yosoi::{
        action, expect,
        flow::{self, FlowOutcome, FlowTermination},
        session::{self, ExecutionPool, SessionPolicy, UntilReport, UntilTermination},
    };

    type TestError = Box<dyn Error + Send + Sync>;

    #[tokio::test(flavor = "current_thread")]
    async fn cancellation_settles_the_partial_response_watch_and_tab_remains_reusable()
    -> Result<(), TestError> {
        if env::var("YOSOI_BROWSER_TESTS").as_deref() != Ok("1") {
            eprintln!("SKIPPED: set YOSOI_BROWSER_TESTS=1 for Until browser cleanup acceptance");
            return Ok(());
        }

        let mut fixture = super::until_fixture::UntilFixture::start().await?;
        let pool = ExecutionPool::new(1, 4)?;
        let browser = session::new()
            .configure(SessionPolicy {
                maximum_tabs: 1,
                execution_concurrency: 1,
                mode: if env::var("YOSOI_YIELD_MODE").as_deref() == Ok("headful") {
                    session::BrowserMode::Headful
                } else {
                    session::BrowserMode::Headless
                },
                ..SessionPolicy::default()
            })
            .execution_pool(&pool)
            .acquire()
            .await?;
        let work = browser.work().await?;

        work.navigate(&fixture.url("/until?attempt=cancel-cleanup&stages=1"))
            .await?;
        let cancellation = CancellationToken::new();
        let cancelled_flow = flow::new([action::click("#trigger")
            .until(expect::response(fixture.url("/api?attempt=cancel-cleanup")).status(200))
            .with_cancellation(&cancellation)]);
        let bound = cancelled_flow.with_lease(&work);
        let mut pool_events = pool.subscribe();
        let mut invocation = Box::pin(bound.invoke());

        let trigger = tokio::select! {
            result = invocation.as_mut() => return Err(io::Error::other(format!(
                "invocation completed before its trigger: {:?}", result?.terminal
            )).into()),
            event = timeout(Duration::from_secs(8), fixture.wait_for("/trigger?attempt=cancel-cleanup")) => event??,
        };
        assert_eq!(trigger.method, "GET");
        let pending_response = tokio::select! {
            result = invocation.as_mut() => return Err(io::Error::other(format!(
                "invocation completed before its response request: {:?}", result?.terminal
            )).into()),
            event = timeout(Duration::from_secs(8), fixture.wait_for("/api?attempt=cancel-cleanup")) => event??,
        };
        assert_eq!(pending_response.method, "GET");
        let parked = async {
            loop {
                let snapshot = pool_events.recv().await?;
                if snapshot.parked == 1 && snapshot.active == 0 {
                    return Ok::<(), TestError>(());
                }
            }
        };
        tokio::select! {
            result = invocation.as_mut() => return Err(io::Error::other(format!(
                "invocation completed before parking: {:?}", result?.terminal
            )).into()),
            result = timeout(Duration::from_secs(8), parked) => result??,
        }
        cancellation.cancel();

        let outcome = timeout(Duration::from_secs(8), &mut invocation).await??;
        assert!(
            outcome
                .steps
                .first()
                .is_some_and(|step| step.cancellation.is_some())
        );
        let report = until_report(&outcome)?;
        assert_eq!(report.termination, UntilTermination::Cancelled);
        assert!(
            report.trigger.is_some(),
            "cancellation lost the one-shot trigger"
        );
        assert_eq!(fixture.request_count("/trigger?attempt=cancel-cleanup")?, 1);
        assert_eq!(fixture.request_count("/api?attempt=cancel-cleanup")?, 1);
        drop(invocation);
        drop(bound);
        assert_eq!(pool.snapshot().active, 0);
        assert_eq!(pool.snapshot().parked, 0);
        assert_eq!(pool.snapshot().queued, 0);

        // Complete the page's already-started fetch, then let it finish both
        // separately gated updates before using the same Work again.
        fixture.release("api:cancel-cleanup")?;
        timeout(
            Duration::from_secs(8),
            fixture.wait_for("/gate/dom?attempt=cancel-cleanup"),
        )
        .await??;
        fixture.release("dom:cancel-cleanup")?;
        timeout(
            Duration::from_secs(8),
            fixture.wait_for("/gate/ax?attempt=cancel-cleanup"),
        )
        .await??;
        fixture.release("ax:cancel-cleanup")?;

        // Gate release acknowledges the server, while Until confirms that the
        // page has consumed the response and published its rendered receipt.
        let rendered = flow::new([expect::visible("#receipt").until()]);
        rendered
            .with_lease(&work)
            .invoke()
            .await?
            .require_completed()?;
        let observation = timeout(Duration::from_secs(8), work.observe()).await??;
        let html = observation
            .html
            .as_deref()
            .ok_or("reused tab omitted rendered DOM")?;
        assert!(html.contains("receipt:cancel-cleanup"));

        // A fresh observation watch on this same tab must complete, showing
        // that cleanup did more than fence or abandon the prior watch.
        work.navigate(&fixture.url("/until?attempt=after-cancel&fast=1"))
            .await?;
        let next_flow = flow::new([action::click("#trigger").until(
            expect::response(fixture.url("/api?attempt=after-cancel&fast=1"))
                .status(200)
                .json("/attempt", "after-cancel"),
        )]);
        let next_bound = next_flow.with_lease(&work);
        let next_outcome = timeout(Duration::from_secs(8), next_bound.invoke()).await??;
        assert_eq!(next_outcome.terminal, FlowTermination::Completed);
        let next_report = until_report(&next_outcome)?;
        assert_eq!(next_report.termination, UntilTermination::Satisfied);
        assert_eq!(fixture.request_count("/trigger?attempt=after-cancel")?, 1);
        assert_eq!(pool.snapshot().active, 0);
        assert_eq!(pool.snapshot().parked, 0);
        assert_eq!(pool.snapshot().queued, 0);

        drop(next_bound);
        work.release().await?;
        browser.close().await?;
        fixture.shutdown().await?;
        Ok(())
    }

    fn until_report(outcome: &FlowOutcome) -> Result<UntilReport, TestError> {
        let value = outcome
            .steps
            .first()
            .and_then(|step| step.receipt.result.as_ref())
            .cloned()
            .ok_or_else(|| io::Error::other("Until step omitted its report"))?;
        Ok(serde_json::from_value(value)?)
    }
}
