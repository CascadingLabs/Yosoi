#![allow(clippy::panic_in_result_fn)]

#[path = "../../yosoi-web-capture-direct-http/tests/support/direct_http_fixture.rs"]
mod fixture;

use std::{error::Error, io, num::NonZeroU32, sync::Arc, time::Duration};

use fixture::{FixtureService, Protocol, Response as FixtureResponse, ResponseControl};
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;
use yosoi::prelude as ys;
use yosoi::{
    AcceptedSourceFormat, AcceptedSourceFormats, AttemptDiagnostic, AttemptFailureKind,
    AttemptOutcome, DirectHttpAcquisition, DirectHttpOutputSchemas, DirectHttpTransportProfile,
    HttpSessionUse, NotStartedReason, OperationId, RequestExecutor, Response, ResponseTermination,
    Schema, SchemaId, SchemaVersion, SourceRetentionPolicy, UnsupportedSourceFormatBehavior,
    request::execution::{CaptureTermination, DirectHttpResolutionInputs},
    wreq_adapter_producer,
};
use yosoi_web_capture::InterruptionInitiator;
use yosoi_web_capture_direct_http::{DirectHttpTransportErrorKind, XmlSourceProfile};

type TestResult<T = ()> = Result<T, Box<dyn Error + Send + Sync>>;

fn test_schema(name: &str) -> TestResult<Schema> {
    Ok(Schema::new(
        SchemaId::new(name)?,
        SchemaVersion::new(NonZeroU32::MIN),
    ))
}

fn direct_inputs() -> TestResult<DirectHttpResolutionInputs> {
    Ok(DirectHttpResolutionInputs {
        acquisition: DirectHttpAcquisition::new(
            DirectHttpTransportProfile::Standard,
            HttpSessionUse::Isolated,
        ),
        accepted_formats: AcceptedSourceFormats::new([
            AcceptedSourceFormat::Html,
            AcceptedSourceFormat::Xml(XmlSourceProfile::Generic),
            AcceptedSourceFormat::Xml(XmlSourceProfile::Xhtml),
            AcceptedSourceFormat::Json,
            AcceptedSourceFormat::PlainText,
        ])?,
        unsupported_format: UnsupportedSourceFormatBehavior::RetainAndReport,
        retention: SourceRetentionPolicy::RepresentationAndUnicodeView,
        producer: wreq_adapter_producer()?,
        operation: OperationId::new("test.cas-405.request-execution-cancellation")?,
        output_schemas: DirectHttpOutputSchemas::new(
            test_schema("test.cas-405.source")?,
            test_schema("test.cas-405.source-representation")?,
            None,
            Some(test_schema("test.cas-405.unicode-view")?),
        ),
    })
}

fn attempt(response: &Response, index: usize) -> TestResult<&AttemptOutcome> {
    response
        .attempts()
        .get(index)
        .ok_or_else(|| io::Error::other("request response is missing an attempt outcome").into())
}

#[tokio::test]
async fn cancelling_active_direct_http_attempt_preserves_failure_and_stops_later_acquisition()
-> TestResult {
    const TARGET_SECRET: &str = "cas405-cancel-target-secret-7319";
    let route = format!("/active?token={TARGET_SECRET}");
    let control = Arc::new(ResponseControl {
        hold_before_head: true,
        ..ResponseControl::default()
    });
    let mut fixture_response = FixtureResponse::bytes(
        200,
        Some("text/plain; charset=utf-8"),
        b"held response body",
    );
    fixture_response.control = Some(control.clone());
    let service = FixtureService::start(Protocol::Http, [(route.clone(), fixture_response)]).await;

    let target = service.url(&route);
    let mut policy = ys::Policy::default();
    policy.page.acquisitions = vec![
        ys::policy::Acquisition::DirectHttp,
        ys::policy::Acquisition::Browser(ys::BrowserMode::Headless),
    ];
    let expected_policy_snapshot = ys::PolicySnapshot::from_policy(&policy)?;
    let executor = RequestExecutor::new().with_direct_http(direct_inputs()?);
    let task_executor = executor.clone();
    let cancellation = CancellationToken::new();
    let task_cancellation = cancellation.clone();
    let task_target = target.clone();
    let task = tokio::spawn(async move {
        ys::request::new(task_target)
            .bind(&policy)
            .send_with(&task_executor, &task_cancellation)
            .await
    });

    // The fixture emits this durable notification after parsing and logging the
    // request, while still holding the response head. Cancellation is therefore
    // delivered during the first Direct HTTP exchange, not before it starts.
    timeout(Duration::from_secs(10), control.requested.wait()).await?;
    cancellation.cancel();
    let response = task.await??;
    let requests = service.requests().await;
    service.shutdown().await;

    assert_eq!(response.termination(), ResponseTermination::Cancelled);
    assert_eq!(response.attempts().len(), 2);
    assert_eq!(
        response.policy_snapshot(),
        &expected_policy_snapshot,
        "the response must retain the policy snapshot used for planning"
    );

    let first = attempt(&response, 0)?;
    assert_eq!(first.acquisition(), ys::policy::AcquisitionKind::DirectHttp);
    let failure = first
        .failure()
        .ok_or_else(|| io::Error::other("active Direct HTTP attempt was not Failed"))?;
    assert_eq!(failure.kind(), AttemptFailureKind::CaptureExecution);
    assert_eq!(
        failure.diagnostic(),
        AttemptDiagnostic::DirectHttpTransport(DirectHttpTransportErrorKind::Cancelled)
    );
    assert_eq!(first.capture_id(), failure.capture_id());
    assert_eq!(failure.policy_snapshot(), response.policy_snapshot());
    assert_eq!(failure.policy_snapshot(), &expected_policy_snapshot);
    let applied_policy = failure
        .applied_policy()
        .ok_or_else(|| io::Error::other("resolved capture failure lost its applied policy"))?;
    assert_eq!(
        applied_policy.identity(),
        expected_policy_snapshot.identity()
    );
    assert!(
        applied_policy
            .decisions()
            .contains(&ys::PolicyDecision::AcquisitionSelected {
                acquisition: ys::policy::AcquisitionKind::DirectHttp,
            })
    );

    let failure_facts = failure
        .capture_failure_facts()
        .ok_or_else(|| io::Error::other("Direct HTTP failure evidence was not retained"))?;
    assert_eq!(
        failure_facts.transport_failure(),
        Some(DirectHttpTransportErrorKind::Cancelled)
    );
    assert!(matches!(
        failure_facts.termination(),
        Some(CaptureTermination::Interrupted(evidence))
            if evidence.initiator() == InterruptionInitiator::Caller
                && evidence.reason().as_str() == "web_capture.direct_http.cancelled"
    ));

    let second = attempt(&response, 1)?;
    assert_eq!(
        second.acquisition(),
        ys::policy::AcquisitionKind::Browser {
            mode: ys::BrowserMode::Headless,
        }
    );
    let not_started = second
        .not_started()
        .ok_or_else(|| io::Error::other("later browser attempt was started after cancellation"))?;
    assert_eq!(not_started.reason(), NotStartedReason::Cancelled);
    assert_eq!(not_started.planned_capture_id(), second.capture_id());
    assert_eq!(not_started.policy_snapshot(), response.policy_snapshot());

    assert_eq!(
        requests.len(),
        1,
        "cancellation must not cause another HTTP request"
    );
    let request = requests
        .first()
        .ok_or_else(|| io::Error::other("fixture did not observe the active HTTP request"))?;
    assert_eq!(request.method, "GET");
    assert_eq!(request.path, route);

    let debug = format!(
        "{response:?}\n{first:?}\n{failure:?}\n{failure_facts:?}\n{applied_policy:?}\n{executor:?}"
    );
    assert!(!debug.contains(TARGET_SECRET));
    assert!(!debug.contains(&target));
    Ok(())
}

#[tokio::test]
async fn cancelling_the_final_active_attempt_marks_the_response_cancelled() -> TestResult {
    let control = Arc::new(ResponseControl {
        hold_before_head: true,
        ..ResponseControl::default()
    });
    let mut fixture_response = FixtureResponse::bytes(
        200,
        Some("text/plain; charset=utf-8"),
        b"held final response body",
    );
    fixture_response.control = Some(control.clone());
    let service = FixtureService::start(
        Protocol::Http,
        [("/final-active".to_owned(), fixture_response)],
    )
    .await;
    let executor = RequestExecutor::new().with_direct_http(direct_inputs()?);
    let cancellation = CancellationToken::new();
    let task_cancellation = cancellation.clone();
    let target = service.url("/final-active");
    let task = tokio::spawn(async move {
        ys::request::new(target)
            .send_with(&executor, &task_cancellation)
            .await
    });

    timeout(Duration::from_secs(10), control.requested.wait()).await?;
    cancellation.cancel();
    let response = task.await??;
    service.shutdown().await;

    assert_eq!(response.termination(), ResponseTermination::Cancelled);
    let [outcome] = response.attempts() else {
        return Err(io::Error::other("final cancellation lost its attempt").into());
    };
    assert_eq!(
        outcome
            .failure()
            .ok_or_else(|| io::Error::other("final active attempt did not fail"))?
            .diagnostic(),
        AttemptDiagnostic::DirectHttpTransport(DirectHttpTransportErrorKind::Cancelled)
    );
    Ok(())
}
