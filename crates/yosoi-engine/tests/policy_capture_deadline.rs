// Result carries fixture/setup failures; assertions fail the test harness.
#![allow(clippy::panic_in_result_fn)]

#[path = "../../yosoi-web-capture-direct-http/tests/support/direct_http_fixture.rs"]
mod fixture;

use fixture::{FixtureService, Protocol, Response, ResponseControl};
use std::{error::Error, io, num::NonZeroU32, sync::Arc, time::Duration};
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;
use yosoi_engine::policy::MaximumElapsed;
use yosoi_engine::{
    AcceptedSourceFormat, AcceptedSourceFormats, DirectHttpAcquisition, DirectHttpCaptureError,
    DirectHttpOutputSchemas, DirectHttpResolutionInputs, DirectHttpTransportProfile,
    HttpSessionUse, OperationId, Policy, PolicyCaptureExecutionError, PolicyResolutionContext,
    PolicyResolver, Schema, SchemaId, SchemaVersion, SourceRetentionPolicy,
    UnsupportedSourceFormatBehavior, request, wreq_adapter_producer,
};
use yosoi_web_capture_direct_http::DirectHttpTransportErrorKind;

fn schema(name: &str) -> Result<Schema, Box<dyn Error + Send + Sync>> {
    Ok(Schema::new(
        SchemaId::new(name)?,
        SchemaVersion::new(NonZeroU32::MIN),
    ))
}

#[tokio::test]
async fn custom_deadline_bounds_a_held_response_and_retains_policy_identity()
-> Result<(), Box<dyn Error + Send + Sync>> {
    let mut response = Response::bytes(200, Some("text/plain; charset=utf-8"), b"held");
    response.control = Some(Arc::new(ResponseControl {
        hold_before_head: true,
        ..ResponseControl::default()
    }));
    let service = FixtureService::start(Protocol::Http, [("/held".to_owned(), response)]).await;
    let mut policy = Policy::default();
    policy.request.maximum_elapsed = MaximumElapsed::try_from(20_000_u64)?;
    let identity = policy.effective_identity()?;
    let prepared = request::new(service.url("/held")).bind(&policy).prepare()?;
    let context = PolicyResolutionContext::direct_http(DirectHttpResolutionInputs {
        acquisition: DirectHttpAcquisition::new(
            DirectHttpTransportProfile::Standard,
            HttpSessionUse::Isolated,
        ),
        accepted_formats: AcceptedSourceFormats::new([AcceptedSourceFormat::PlainText])?,
        unsupported_format: UnsupportedSourceFormatBehavior::RetainAndReport,
        retention: SourceRetentionPolicy::Representation,
        producer: wreq_adapter_producer()?,
        operation: OperationId::new("test.policy-deadline")?,
        output_schemas: DirectHttpOutputSchemas::new(
            schema("test.deadline.source")?,
            schema("test.deadline.representation")?,
            None,
            None,
        ),
    });
    let attempt = prepared
        .attempts()
        .first()
        .ok_or_else(|| io::Error::other("prepared request has no acquisition attempt"))?;
    let attempt = PolicyResolver::resolve(&prepared, attempt, context)?;
    let cancellation = CancellationToken::new();
    let captured = timeout(Duration::from_secs(10), attempt.execute(&cancellation)).await;
    service.shutdown().await;
    let Err(error) = captured? else {
        return Err(
            io::Error::other("held response unexpectedly completed before its deadline").into(),
        );
    };
    assert_eq!(error.applied_policy().identity(), identity);
    let PolicyCaptureExecutionError::DirectHttp(cause) = error.execution_error() else {
        return Err(io::Error::other("deadline lost its typed HTTP cause").into());
    };
    let DirectHttpCaptureError::Transport(failure) = cause.as_ref() else {
        return Err(
            io::Error::other("deadline did not terminate at the transport boundary").into(),
        );
    };
    assert_eq!(
        failure.error().kind(),
        DirectHttpTransportErrorKind::Timeout
    );
    Ok(())
}
