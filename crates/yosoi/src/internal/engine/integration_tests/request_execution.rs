#![allow(clippy::panic_in_result_fn)]

use crate::internal::test_support::direct_http_fixture as fixture;

use std::{error::Error, fmt::Write as _, io, num::NonZeroU32, str};

use crate::internal::direct_http::{DirectHttpTransportErrorKind, XmlSourceProfile};
#[cfg(not(feature = "browser"))]
use crate::internal::engine::StandardExecutionSetupError;
use crate::internal::engine::prelude as ys;
use crate::internal::engine::{
    AcceptedSourceFormat, AcceptedSourceFormats, AttemptDiagnostic, AttemptFailureKind,
    AttemptOutcome, AttemptResult, DirectHttpAcquisition, DirectHttpOutputSchemas,
    DirectHttpTransportProfile, HttpSessionUse, NotStartedReason, Observation, OperationId,
    RequestExecutor, Response, ResponseTermination, Schema, SchemaId, SchemaVersion,
    SourceRetentionPolicy, UnsupportedSourceFormatBehavior,
    request::execution::{DirectHttpResolutionInputs, ResolvedWebUrl},
    wreq_adapter_producer,
};
use fixture::{FixtureService, Protocol, Response as FixtureResponse};
use tokio_util::sync::CancellationToken;

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
        operation: OperationId::new("test.cas-404.request-execution")?,
        output_schemas: DirectHttpOutputSchemas::new(
            test_schema("test.cas-404.source")?,
            test_schema("test.cas-404.source-representation")?,
            None,
            Some(test_schema("test.cas-404.unicode-view")?),
        ),
    })
}

async fn send(
    policy: &ys::Policy,
    target: &str,
    executor: &RequestExecutor,
    cancellation: &CancellationToken,
) -> TestResult<Response> {
    Ok(ys::request::new(target)
        .bind(policy)
        .send_with(executor, cancellation)
        .await?)
}

fn attempt(response: &Response, index: usize) -> TestResult<&AttemptOutcome> {
    response
        .attempts()
        .get(index)
        .ok_or_else(|| io::Error::other("request response is missing an attempt outcome").into())
}

fn completed(outcome: &AttemptOutcome) -> TestResult<&AttemptResult> {
    outcome
        .result()
        .ok_or_else(|| io::Error::other("attempt did not complete").into())
}

fn response_document(result: &AttemptResult) -> TestResult<&ys::Document> {
    result
        .documents()
        .first()
        .and_then(|outcome| outcome.outcome().document())
        .ok_or_else(|| io::Error::other("response document was not produced").into())
}

fn mixed_acquisitions() -> Vec<ys::policy::Acquisition> {
    vec![
        ys::policy::Acquisition::DirectHttp,
        ys::policy::Acquisition::Browser(ys::policy::BrowserMode::Headless),
        ys::policy::Acquisition::Browser(ys::policy::BrowserMode::Headful),
    ]
}

async fn unused_service() -> FixtureService {
    FixtureService::start(
        Protocol::Http,
        [(
            "/unused".to_owned(),
            FixtureResponse::bytes(200, None, b"unused"),
        )],
    )
    .await
}

#[tokio::test]
async fn ordinary_send_uses_the_standard_direct_http_adapter() -> TestResult {
    let expected_policy = ys::Policy::default();
    let expected_identity = expected_policy.effective_identity()?;
    let service = FixtureService::start(
        Protocol::Http,
        [(
            "/standard".to_owned(),
            FixtureResponse::bytes(
                200,
                Some("text/html; charset=utf-8"),
                b"<!doctype html><main>standard-send</main>",
            ),
        )],
    )
    .await;

    let response = ys::request::new(service.url("/standard")).send().await;
    let request_count = service.requests().await.len();
    service.shutdown().await;
    let response = response?;
    let outcome = attempt(&response, 0)?;
    assert_eq!(response.policy_snapshot().policy(), &expected_policy);
    assert_eq!(response.policy_snapshot().identity(), expected_identity);
    assert_eq!(
        outcome.authored_selection(),
        ys::policy::DocumentSelectionKind::Current
    );
    assert_eq!(outcome.status(), Some(200));
    let document = response_document(completed(outcome)?)?;
    assert_eq!(document.class(), ys::DocumentClass::SourceHtml);
    assert!(str::from_utf8(document.bytes())?.contains("standard-send"));
    assert_eq!(request_count, 1);
    Ok(())
}

#[cfg(not(feature = "browser"))]
#[tokio::test]
async fn standard_browser_send_requires_the_browser_feature_before_execution() -> TestResult {
    let service = unused_service().await;
    let mut policy = ys::Policy::default();
    policy.page.acquisitions = vec![
        ys::policy::Acquisition::DirectHttp,
        ys::policy::Acquisition::Browser(ys::BrowserMode::Headless),
    ];

    let error = ys::request::new(service.url("/unused"))
        .bind(&policy)
        .send()
        .await
        .err()
        .ok_or_else(|| io::Error::other("browser send unexpectedly ran without its feature"))?;
    assert!(matches!(
        error,
        ys::RequestSendError::StandardSetup(StandardExecutionSetupError::BrowserFeatureDisabled)
    ));
    assert_eq!(service.requests().await.len(), 0);
    service.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn current_and_equivalent_exact_send_return_the_same_document_and_retain_authorship()
-> TestResult {
    let body = b"<!doctype html><main>equivalent-selection</main>";
    let service = FixtureService::start(
        Protocol::Http,
        [(
            "/selection".to_owned(),
            FixtureResponse::bytes(200, Some("text/html"), body),
        )],
    )
    .await;
    let target = service.url("/selection");

    let current = ys::request::new(&target).send().await?;
    let mut exact_policy = ys::Policy::default();
    exact_policy.page.acquisitions = vec![
        ys::policy::Acquisition::DirectHttp
            .documents([ys::policy::DocumentRequest::ResponseDocument]),
    ];
    let exact = ys::request::new(&target).bind(&exact_policy).send().await?;

    let current_attempt = attempt(&current, 0)?;
    let exact_attempt = attempt(&exact, 0)?;
    assert_eq!(
        current_attempt.authored_selection(),
        ys::policy::DocumentSelectionKind::Current
    );
    assert_eq!(
        exact_attempt.authored_selection(),
        ys::policy::DocumentSelectionKind::Exact
    );
    assert_eq!(
        current.policy_snapshot().identity(),
        exact.policy_snapshot().identity()
    );
    assert_eq!(
        response_document(completed(current_attempt)?)?.bytes(),
        response_document(completed(exact_attempt)?)?.bytes()
    );
    assert_eq!(service.requests().await.len(), 2);
    service.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn empty_acquisition_list_returns_an_empty_completed_response_without_io() -> TestResult {
    let service = unused_service().await;
    let mut policy = ys::Policy::default();
    policy.page.acquisitions.clear();

    let response = send(
        &policy,
        &service.url("/unused"),
        &RequestExecutor::new(),
        &CancellationToken::new(),
    )
    .await?;

    assert_eq!(response.attempts().len(), 0);
    assert_eq!(response.termination(), ResponseTermination::Completed);
    assert_eq!(service.requests().await.len(), 0);
    service.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn pre_cancelled_mixed_attempts_are_ordered_not_started_and_do_no_io() -> TestResult {
    let service = unused_service().await;
    let mut policy = ys::Policy::default();
    policy.page.acquisitions = mixed_acquisitions();
    let cancellation = CancellationToken::new();
    cancellation.cancel();
    let executor = RequestExecutor::new().with_direct_http(direct_inputs()?);

    let response = send(&policy, &service.url("/unused"), &executor, &cancellation).await?;

    assert_eq!(response.termination(), ResponseTermination::Cancelled);
    assert_eq!(response.attempts().len(), policy.page.acquisitions.len());
    for (index, acquisition) in policy.page.acquisitions.iter().enumerate() {
        let outcome = attempt(&response, index)?;
        assert_eq!(outcome.acquisition(), acquisition.kind());
        let not_started = outcome
            .not_started()
            .ok_or_else(|| io::Error::other("cancelled attempt was not marked NotStarted"))?;
        assert_eq!(not_started.reason(), NotStartedReason::Cancelled);
    }
    assert_ne!(
        attempt(&response, 0)?.capture_id(),
        attempt(&response, 1)?.capture_id()
    );
    assert_ne!(
        attempt(&response, 1)?.capture_id(),
        attempt(&response, 2)?.capture_id()
    );
    assert_eq!(service.requests().await.len(), 0);
    service.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn missing_contexts_produce_ordered_typed_failures_with_distinct_ids() -> TestResult {
    let service = unused_service().await;
    let mut policy = ys::Policy::default();
    policy.page.acquisitions = mixed_acquisitions();
    let response = send(
        &policy,
        &service.url("/unused"),
        &RequestExecutor::new(),
        &CancellationToken::new(),
    )
    .await?;

    assert_eq!(response.termination(), ResponseTermination::Completed);
    assert_eq!(response.attempts().len(), policy.page.acquisitions.len());
    for (index, acquisition) in policy.page.acquisitions.iter().enumerate() {
        let outcome = attempt(&response, index)?;
        assert_eq!(outcome.acquisition(), acquisition.kind());
        let failure = outcome
            .failure()
            .ok_or_else(|| io::Error::other("attempt without a context was not Failed"))?;
        assert_eq!(failure.kind(), AttemptFailureKind::MissingExecutionContext);
        assert_eq!(
            failure.diagnostic(),
            AttemptDiagnostic::MissingExecutionContext
        );
    }
    let first_id = attempt(&response, 0)?.capture_id();
    let second_id = attempt(&response, 1)?.capture_id();
    let third_id = attempt(&response, 2)?.capture_id();
    assert_ne!(first_id, second_id);
    assert_ne!(first_id, third_id);
    assert_ne!(second_id, third_id);
    assert_eq!(service.requests().await.len(), 0);
    service.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn direct_http_404_is_a_response_transport_errors_fail_and_redirects_are_observed()
-> TestResult {
    let service = FixtureService::start(
        Protocol::Http,
        [
            (
                "/not-found".to_owned(),
                FixtureResponse::bytes(404, Some("text/plain; charset=utf-8"), b"not found body"),
            ),
            (
                "/malformed".to_owned(),
                FixtureResponse::raw(b"this is not HTTP".to_vec()),
            ),
            (
                "/redirect".to_owned(),
                FixtureResponse::redirect("/destination"),
            ),
            (
                "/destination".to_owned(),
                FixtureResponse::bytes(200, Some("text/plain; charset=utf-8"), b"final body"),
            ),
        ],
    )
    .await;
    let executor = RequestExecutor::new().with_direct_http(direct_inputs()?);
    let default_policy = ys::Policy::default();

    let not_found = send(
        &default_policy,
        &service.url("/not-found"),
        &executor,
        &CancellationToken::new(),
    )
    .await?;
    let not_found_attempt = attempt(&not_found, 0)?;
    let not_found_result = completed(not_found_attempt)?;
    assert_eq!(not_found_attempt.status(), Some(404));
    assert_eq!(
        response_document(not_found_result)?.bytes(),
        b"not found body"
    );

    let malformed = send(
        &default_policy,
        &service.url("/malformed"),
        &executor,
        &CancellationToken::new(),
    )
    .await?;
    let malformed_attempt = attempt(&malformed, 0)?;
    let transport_failure = malformed_attempt
        .failure()
        .ok_or_else(|| io::Error::other("malformed HTTP response did not fail"))?;
    assert_eq!(
        transport_failure.kind(),
        AttemptFailureKind::CaptureExecution
    );
    assert_eq!(
        transport_failure.diagnostic(),
        AttemptDiagnostic::DirectHttpTransport(DirectHttpTransportErrorKind::Protocol)
    );
    assert_eq!(malformed_attempt.status(), None);
    assert!(malformed_attempt.final_target().is_none());
    assert!(malformed_attempt.redirects().is_none());

    let mut redirect_policy = ys::Policy::default();
    redirect_policy.request.direct_http_redirects = ys::policy::DirectHttpRedirects::Follow {
        max_hops: ys::policy::RedirectHopLimit::try_from(3_u32)?,
        targets: ys::policy::DirectHttpRedirectTargets::SameOrigin,
    };
    let redirected = send(
        &redirect_policy,
        &service.url("/redirect"),
        &executor,
        &CancellationToken::new(),
    )
    .await?;
    let redirect_attempt = attempt(&redirected, 0)?;
    let redirect_result = completed(redirect_attempt)?;
    assert_eq!(redirect_attempt.status(), Some(200));
    assert_eq!(
        redirect_result
            .capture_facts()
            .final_target()
            .map(ResolvedWebUrl::as_str),
        Some(service.url("/destination").as_str())
    );
    assert!(matches!(
        redirect_result.capture_facts().redirects(),
        Observation::Observed(hops) if hops.len() == 1
    ));
    assert_eq!(response_document(redirect_result)?.bytes(), b"final body");

    service.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn completed_direct_attempt_is_preserved_when_a_later_sibling_lacks_context() -> TestResult {
    let service = FixtureService::start(
        Protocol::Http,
        [(
            "/first".to_owned(),
            FixtureResponse::bytes(200, Some("text/plain; charset=utf-8"), b"first body"),
        )],
    )
    .await;
    let mut policy = ys::Policy::default();
    policy.page.acquisitions = vec![
        ys::policy::Acquisition::DirectHttp,
        ys::policy::Acquisition::Browser(ys::policy::BrowserMode::Headless),
    ];
    let executor = RequestExecutor::new().with_direct_http(direct_inputs()?);

    let response = send(
        &policy,
        &service.url("/first"),
        &executor,
        &CancellationToken::new(),
    )
    .await?;

    assert_eq!(response.termination(), ResponseTermination::Completed);
    assert_eq!(response.attempts().len(), 2);
    let first = attempt(&response, 0)?;
    assert!(matches!(first, AttemptOutcome::Completed(_)));
    assert_eq!(first.status(), Some(200));
    assert_eq!(response_document(completed(first)?)?.bytes(), b"first body");
    let later = attempt(&response, 1)?;
    assert_eq!(
        later
            .failure()
            .ok_or_else(|| io::Error::other("later attempt outcome was lost"))?
            .kind(),
        AttemptFailureKind::MissingExecutionContext
    );
    assert_eq!(service.requests().await.len(), 1);
    service.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn response_document_classifies_owns_bytes_redacts_debug_and_allows_empty_selection()
-> TestResult {
    const BODY_SECRET: &str = "cas404-request-body-secret-9271";
    const TARGET_SECRET: &str = "cas404-request-target-secret-4186";
    let route = format!("/page?token={TARGET_SECRET}");
    let body = format!("<!doctype html><main>{BODY_SECRET}</main>").into_bytes();
    let service = FixtureService::start(
        Protocol::Http,
        [(
            route.clone(),
            FixtureResponse::bytes(200, Some("text/html; charset=utf-8"), &body),
        )],
    )
    .await;
    let target = service.url(&route);
    let executor = RequestExecutor::new().with_direct_http(direct_inputs()?);
    let response = send(
        &ys::Policy::default(),
        &target,
        &executor,
        &CancellationToken::new(),
    )
    .await?;
    let mut empty_policy = ys::Policy::default();
    empty_policy.page.acquisitions = vec![ys::policy::Acquisition::DirectHttp.documents([])];
    let empty_response = send(&empty_policy, &target, &executor, &CancellationToken::new()).await?;
    assert_eq!(
        completed(attempt(&empty_response, 0)?)?.documents().len(),
        0
    );
    assert_eq!(empty_response.termination(), ResponseTermination::Completed);
    assert_eq!(service.requests().await.len(), 2);
    service.shutdown().await;

    let result = completed(attempt(&response, 0)?)?;
    let document = response_document(result)?;
    assert_eq!(document.class(), ys::DocumentClass::SourceHtml);
    assert_eq!(document.bytes(), body.as_slice());

    let mut debug = format!("{response:?}\n{:?}", attempt(&response, 0)?);
    write!(&mut debug, "\n{result:?}\n{document:?}\n{executor:?}")?;
    let numeric_payload = format!("{body:?}");
    assert!(!debug.contains(BODY_SECRET));
    assert!(!debug.contains(TARGET_SECRET));
    assert!(!debug.contains(&target));
    assert!(!debug.contains(&numeric_payload));
    Ok(())
}
