// Assertions fail the harness; Result is used for fixture and task errors.
#![allow(clippy::panic_in_result_fn)]
#![allow(
    clippy::absolute_paths,
    reason = "tests exercise the documented ys::policy namespace"
)]

#[path = "../../yosoi-web-capture-direct-http/tests/support/direct_http_fixture.rs"]
mod fixture;

use std::{error::Error, io, num::NonZeroU32, sync::Arc, time::Duration};

use fixture::{FixtureService, Protocol, Response, ResponseControl};
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;
use yosoi::{
    AcceptedSourceFormat, AcceptedSourceFormats, DirectHttpAcquisition, DirectHttpCapture,
    DirectHttpCaptureError, DirectHttpOutputSchemas, DirectHttpResolutionInputs,
    DirectHttpTransportProfile, HttpSessionUse, OperationId, PolicyCapture, PolicyCaptureError,
    PolicyCaptureExecutionError, PolicyDecision, PolicyResolutionContext, PolicyResolver,
    PreparedAttempt, PreparedPageRequest, ResolvedPolicySpec, Schema, SchemaId, SchemaVersion,
    SourceRetentionPolicy, UnsupportedSourceFormatBehavior, prelude as ys, wreq_adapter_producer,
};
use yosoi_types::ArtifactAvailability;
use yosoi_web_capture::{
    ArtifactRequest, CaptureBundle, CaptureCompleteness, ClassificationExtent, SourceArtifact,
    SourceClassificationOutcome,
};
use yosoi_web_capture_direct_http::{DirectHttpRedirectErrorKind, DirectHttpTransportErrorKind};

type TestResult<T = ()> = Result<T, Box<dyn Error + Send + Sync>>;

fn test_operation() -> TestResult<OperationId> {
    Ok(OperationId::new("test.policy-capture")?)
}

fn test_schema(name: &str) -> TestResult<Schema> {
    Ok(Schema::new(
        SchemaId::new(name)?,
        SchemaVersion::new(NonZeroU32::MIN),
    ))
}

fn request(policy: &ys::Policy, url: &str) -> TestResult<PreparedPageRequest> {
    Ok(ys::request::new(url).bind(policy).prepare()?)
}

fn first_attempt(prepared: &PreparedPageRequest) -> TestResult<&PreparedAttempt> {
    prepared
        .attempts()
        .first()
        .ok_or_else(|| io::Error::other("prepared request has no acquisition attempt").into())
}

fn direct_context() -> TestResult<PolicyResolutionContext> {
    let inputs = DirectHttpResolutionInputs {
        acquisition: DirectHttpAcquisition::new(
            DirectHttpTransportProfile::Standard,
            HttpSessionUse::Isolated,
        ),
        accepted_formats: AcceptedSourceFormats::new([
            AcceptedSourceFormat::Html,
            AcceptedSourceFormat::PlainText,
        ])?,
        unsupported_format: UnsupportedSourceFormatBehavior::RetainAndReport,
        retention: SourceRetentionPolicy::RepresentationAndUnicodeView,
        producer: wreq_adapter_producer()?,
        operation: test_operation()?,
        output_schemas: DirectHttpOutputSchemas::new(
            test_schema("test.policy-capture.source")?,
            test_schema("test.policy-capture.source-representation")?,
            None,
            Some(test_schema("test.policy-capture.unicode-view")?),
        ),
    };
    Ok(PolicyResolutionContext::direct_http(inputs))
}

async fn capture_with_attempt(
    prepared: &PreparedPageRequest,
    attempt: &PreparedAttempt,
    context: PolicyResolutionContext,
    cancellation: &CancellationToken,
) -> TestResult<PolicyCapture> {
    let resolved = PolicyResolver::resolve(prepared, attempt, context)?;
    Ok(resolved.execute(cancellation).await?)
}

fn policy_with_redirects(redirects: ys::policy::DirectHttpRedirects) -> ys::Policy {
    let mut policy = ys::Policy::default();
    policy.request.direct_http_redirects = redirects;
    policy
}

fn direct_capture(capture: &PolicyCapture) -> TestResult<&DirectHttpCapture> {
    capture.direct_http_capture().ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidData,
            "capture did not retain Direct HTTP facts",
        )
        .into()
    })
}

fn source_artifact(bundle: &CaptureBundle) -> TestResult<&SourceArtifact> {
    bundle
        .capture()
        .artifacts()
        .results()
        .source()
        .artifacts()
        .and_then(|artifacts| artifacts.first())
        .ok_or_else(|| {
            io::Error::new(io::ErrorKind::InvalidData, "source artifact is missing").into()
        })
}

fn assert_direct_transport_failure(
    error: &PolicyCaptureError,
    expected: DirectHttpTransportErrorKind,
    policy_identity: ys::EffectivePolicyIdentity,
) -> TestResult {
    assert_eq!(error.applied_policy().identity(), policy_identity);
    let PolicyCaptureExecutionError::DirectHttp(cause) = error.execution_error() else {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "capture did not retain the Direct HTTP transport failure",
        )
        .into());
    };
    let DirectHttpCaptureError::Transport(failure) = cause.as_ref() else {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "capture did not retain a transport-stage failure",
        )
        .into());
    };
    assert_eq!(failure.error().kind(), expected);
    Ok(())
}

#[tokio::test]
async fn default_and_404_responses_publish_bundles_with_response_facts() -> TestResult {
    let not_found_body = b"not-found-response";
    let service = FixtureService::start(
        Protocol::Http,
        [
            (
                "/ok".to_owned(),
                Response::bytes(200, Some("text/plain; charset=utf-8"), b"ordinary-response"),
            ),
            (
                "/not-found".to_owned(),
                Response::bytes(404, Some("text/plain; charset=utf-8"), not_found_body),
            ),
            (
                "/exact".to_owned(),
                Response::bytes(200, Some("text/plain; charset=utf-8"), b"exact-response"),
            ),
        ],
    )
    .await;
    let declaration = ys::Policy::default();
    let expected_identity = declaration.effective_identity()?;

    let ok_url = service.url("/ok");
    let ok_prepared = request(&declaration, &ok_url)?;
    let ok_attempt = first_attempt(&ok_prepared)?;
    assert_eq!(
        ok_attempt.authored_selection(),
        ys::policy::DocumentSelectionKind::Current
    );
    assert_eq!(
        ok_attempt.documents(),
        &[ys::policy::DocumentRequest::ResponseDocument]
    );
    let ok_resolved = PolicyResolver::resolve(&ok_prepared, ok_attempt, direct_context()?)?;
    assert!(
        ok_resolved
            .applied_policy()
            .decisions()
            .iter()
            .any(|decision| matches!(
                decision,
                PolicyDecision::DocumentSelection {
                    selection: ys::policy::DocumentSelectionKind::Current
                }
            ))
    );
    assert!(
        ok_resolved
            .applied_policy()
            .decisions()
            .iter()
            .any(|decision| matches!(
                decision,
                PolicyDecision::DocumentRequested {
                    document: ys::policy::DocumentRequest::ResponseDocument
                }
            ))
    );
    let ok_spec = match ok_resolved.spec() {
        ResolvedPolicySpec::DirectHttp { spec, .. } => spec,
        ResolvedPolicySpec::Browser(_) => {
            return Err(io::Error::other("Direct HTTP resolved to a browser spec").into());
        }
    };
    assert_eq!(ok_spec.artifacts().source(), ArtifactRequest::Required);
    let ok_capture = ok_resolved.execute(&CancellationToken::new()).await?;
    let ok_debug = format!("{ok_capture:?}");
    assert!(!ok_debug.contains("ordinary-response"));
    assert!(!ok_debug.contains(&ok_url));
    let ok_http = direct_capture(&ok_capture)?;
    assert_eq!(ok_capture.applied_policy().identity(), expected_identity);
    assert_eq!(ok_http.response().status(), 200);
    assert_eq!(ok_http.response().requested_url().as_str(), ok_url);
    assert_eq!(ok_http.response().final_url().as_str(), ok_url);
    assert_eq!(
        ok_capture.bundle().capture().completeness(),
        CaptureCompleteness::Complete
    );
    let ok_source = source_artifact(ok_capture.bundle())?;
    assert_eq!(
        ok_source.metadata().record().availability(),
        ArtifactAvailability::Retained
    );
    assert_eq!(
        ok_capture.bundle().payload(ok_source.reference().into()),
        Some(&b"ordinary-response"[..])
    );

    let not_found_url = service.url("/not-found");
    let not_found_prepared = request(&declaration, &not_found_url)?;
    let not_found_attempt = first_attempt(&not_found_prepared)?;
    let not_found = capture_with_attempt(
        &not_found_prepared,
        not_found_attempt,
        direct_context()?,
        &CancellationToken::new(),
    )
    .await?;
    let not_found_http = direct_capture(&not_found)?;
    assert_eq!(not_found_http.response().status(), 404);
    assert_eq!(
        not_found_http.response().requested_url().as_str(),
        not_found_url
    );
    assert_eq!(
        not_found_http.response().final_url().as_str(),
        not_found_url
    );
    let not_found_source = source_artifact(not_found.bundle())?;
    assert_eq!(
        not_found_source.metadata().record().availability(),
        ArtifactAvailability::Retained
    );
    assert_eq!(
        not_found
            .bundle()
            .payload(not_found_source.reference().into()),
        Some(&not_found_body[..])
    );

    let mut exact_policy = ys::Policy::default();
    exact_policy.page.acquisitions = vec![
        ys::policy::Acquisition::DirectHttp
            .documents([ys::policy::DocumentRequest::ResponseDocument]),
    ];
    let exact_url = service.url("/exact");
    let exact_prepared = request(&exact_policy, &exact_url)?;
    let exact_attempt = first_attempt(&exact_prepared)?;
    assert_eq!(
        exact_attempt.authored_selection(),
        ys::policy::DocumentSelectionKind::Exact
    );
    let exact_resolved =
        PolicyResolver::resolve(&exact_prepared, exact_attempt, direct_context()?)?;
    assert!(
        exact_resolved
            .applied_policy()
            .decisions()
            .iter()
            .any(|decision| matches!(
                decision,
                PolicyDecision::DocumentSelection {
                    selection: ys::policy::DocumentSelectionKind::Exact
                }
            ))
    );
    assert!(
        exact_resolved
            .applied_policy()
            .decisions()
            .iter()
            .any(|decision| matches!(
                decision,
                PolicyDecision::DocumentRequested {
                    document: ys::policy::DocumentRequest::ResponseDocument
                }
            ))
    );
    let exact_spec = match exact_resolved.spec() {
        ResolvedPolicySpec::DirectHttp { spec, .. } => spec,
        ResolvedPolicySpec::Browser(_) => {
            return Err(io::Error::other("Exact Direct HTTP resolved to a browser spec").into());
        }
    };
    assert_eq!(exact_spec.artifacts().source(), ArtifactRequest::Required);
    let exact_capture = exact_resolved.execute(&CancellationToken::new()).await?;
    assert_eq!(
        exact_capture.applied_policy().identity(),
        exact_policy.effective_identity()?
    );
    assert_eq!(direct_capture(&exact_capture)?.response().status(), 200);
    let exact_source = source_artifact(exact_capture.bundle())?;
    assert_eq!(
        exact_capture
            .bundle()
            .payload(exact_source.reference().into()),
        Some(&b"exact-response"[..])
    );

    service.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn byte_limited_source_publishes_partial_bundle_and_prefix_evidence() -> TestResult {
    let service = FixtureService::start(
        Protocol::Http,
        [(
            "/large".to_owned(),
            Response::bytes(200, Some("text/plain; charset=utf-8"), b"abcdefgh"),
        )],
    )
    .await;
    let mut policy = ys::Policy::default();
    policy.request.source.representation_bytes = ys::policy::AddressableByteLimit::try_from(3_u64)?;
    let expected_identity = policy.effective_identity()?;
    let prepared = request(&policy, &service.url("/large"))?;
    let attempt = first_attempt(&prepared)?;
    let capture = capture_with_attempt(
        &prepared,
        attempt,
        direct_context()?,
        &CancellationToken::new(),
    )
    .await?;
    let http = direct_capture(&capture)?;
    assert_eq!(capture.applied_policy().identity(), expected_identity);
    assert_eq!(
        capture.bundle().capture().completeness(),
        CaptureCompleteness::Incomplete
    );
    let source = source_artifact(capture.bundle())?;
    assert_eq!(
        source.metadata().record().availability(),
        ArtifactAvailability::Truncated
    );
    assert_eq!(
        capture.bundle().payload(source.reference().into()),
        Some(&b"abc"[..])
    );
    let evidence = http.source_representation_evidence()?;
    assert!(matches!(
        evidence.classification(),
        SourceClassificationOutcome::Classified(classified)
            if classified.extent() == ClassificationExtent::RetainedPrefix
    ));

    service.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn old_prepared_redirect_policy_survives_new_snapshot_and_forwarding_is_observable()
-> TestResult {
    let destination = FixtureService::start(
        Protocol::Http,
        [(
            "/destination".to_owned(),
            Response::bytes(
                200,
                Some("text/plain; charset=utf-8"),
                b"second-port-response",
            ),
        )],
    )
    .await;
    let destination_url = destination.url("/destination");
    let origin = FixtureService::start(
        Protocol::Http,
        [
            (
                "/same-origin".to_owned(),
                Response::redirect(&destination_url),
            ),
            ("/follow".to_owned(), Response::redirect(&destination_url)),
        ],
    )
    .await;

    let mut declaration = policy_with_redirects(ys::policy::DirectHttpRedirects::Follow {
        max_hops: ys::policy::RedirectHopLimit::try_from(3_u32)?,
        targets: ys::policy::DirectHttpRedirectTargets::SameOrigin,
    });
    let same_origin_identity = declaration.effective_identity()?;
    let old_prepared = request(&declaration, &origin.url("/same-origin"))?;
    let old_attempt = PolicyResolver::resolve(
        &old_prepared,
        first_attempt(&old_prepared)?,
        direct_context()?,
    )?;
    assert_eq!(
        old_attempt.applied_policy().identity(),
        same_origin_identity
    );

    declaration.request.direct_http_redirects = ys::policy::DirectHttpRedirects::Follow {
        max_hops: ys::policy::RedirectHopLimit::try_from(3_u32)?,
        targets: ys::policy::DirectHttpRedirectTargets::AllowHttpAndHttps,
    };
    let follow_identity = declaration.effective_identity()?;
    let follow_url = origin.url("/follow");
    let follow_prepared = request(&declaration, &follow_url)?;
    let follow_attempt = PolicyResolver::resolve(
        &follow_prepared,
        first_attempt(&follow_prepared)?,
        direct_context()?,
    )?;
    let Err(blocked) = old_attempt.execute(&CancellationToken::new()).await else {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "same-origin redirect unexpectedly followed a different port",
        )
        .into());
    };
    assert_direct_transport_failure(
        &blocked,
        DirectHttpTransportErrorKind::Redirect(DirectHttpRedirectErrorKind::TargetRefused),
        same_origin_identity,
    )?;
    assert!(destination.requests().await.is_empty());

    let followed = follow_attempt.execute(&CancellationToken::new()).await?;
    let followed_http = direct_capture(&followed)?;
    assert_eq!(followed.applied_policy().identity(), follow_identity);
    assert_eq!(followed_http.response().status(), 200);
    assert_eq!(
        followed_http.response().requested_url().as_str(),
        follow_url
    );
    assert_eq!(
        followed_http.response().final_url().as_str(),
        destination_url
    );
    assert_eq!(
        followed
            .bundle()
            .capture()
            .acquisition()
            .resolution()
            .final_url()
            .as_observed(),
        Some(followed_http.response().final_url())
    );
    let followed_source = source_artifact(followed.bundle())?;
    assert_eq!(
        followed
            .bundle()
            .payload(followed_source.reference().into()),
        Some(&b"second-port-response"[..])
    );
    assert_eq!(destination.requests().await.len(), 1);

    let disabled_declaration = policy_with_redirects(ys::policy::DirectHttpRedirects::Disabled);
    let disabled_identity = disabled_declaration.effective_identity()?;
    let disabled_url = origin.url("/same-origin");
    let disabled_prepared = request(&disabled_declaration, &disabled_url)?;
    let disabled_attempt = PolicyResolver::resolve(
        &disabled_prepared,
        first_attempt(&disabled_prepared)?,
        direct_context()?,
    )?;
    let disabled_capture = disabled_attempt.execute(&CancellationToken::new()).await?;
    let disabled_http = direct_capture(&disabled_capture)?;
    assert_eq!(
        disabled_capture.applied_policy().identity(),
        disabled_identity
    );
    assert_eq!(disabled_http.response().status(), 302);
    assert_eq!(
        disabled_http.response().requested_url().as_str(),
        disabled_url
    );
    assert_eq!(disabled_http.response().final_url().as_str(), disabled_url);
    assert_eq!(destination.requests().await.len(), 1);

    origin.shutdown().await;
    destination.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn pre_cancel_and_event_driven_inflight_cancel_keep_policy_identity() -> TestResult {
    let mut controlled_response = Response::bytes(
        200,
        Some("text/plain; charset=utf-8"),
        b"response-never-released",
    );
    let control = Arc::new(ResponseControl {
        hold_before_head: true,
        ..ResponseControl::default()
    });
    controlled_response.control = Some(control.clone());
    let service = FixtureService::start(
        Protocol::Http,
        [
            (
                "/pre-cancel".to_owned(),
                Response::bytes(200, Some("text/plain; charset=utf-8"), b"unused"),
            ),
            ("/inflight".to_owned(), controlled_response),
        ],
    )
    .await;
    let declaration = ys::Policy::default();
    let expected_identity = declaration.effective_identity()?;
    let pre_cancelled = CancellationToken::new();
    pre_cancelled.cancel();
    let pre_cancel_prepared = request(&declaration, &service.url("/pre-cancel"))?;
    let pre_attempt = PolicyResolver::resolve(
        &pre_cancel_prepared,
        first_attempt(&pre_cancel_prepared)?,
        direct_context()?,
    )?;
    let Err(pre_error) = pre_attempt.execute(&pre_cancelled).await else {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "pre-cancelled capture unexpectedly succeeded",
        )
        .into());
    };
    let pre_error_debug = format!("{pre_error:?}");
    assert!(!pre_error_debug.contains("pre-cancel"));
    assert_direct_transport_failure(
        &pre_error,
        DirectHttpTransportErrorKind::Cancelled,
        expected_identity,
    )?;
    assert!(service.requests().await.is_empty());

    let in_flight_token = CancellationToken::new();
    let in_flight_prepared = request(&declaration, &service.url("/inflight"))?;
    let in_flight_attempt = PolicyResolver::resolve(
        &in_flight_prepared,
        first_attempt(&in_flight_prepared)?,
        direct_context()?,
    )?;
    let in_flight_capture = in_flight_attempt.execute(&in_flight_token);
    tokio::pin!(in_flight_capture);
    let test_result = async {
        let cancel_after_request = async {
            timeout(Duration::from_secs(10), control.requested.wait()).await?;
            in_flight_token.cancel();
            Ok::<(), tokio::time::error::Elapsed>(())
        };
        // Poll capture while waiting for its request event; an unpolled future
        // cannot produce the very event used to trigger cancellation.
        let (request_event, captured) = tokio::join!(
            cancel_after_request,
            timeout(Duration::from_secs(10), &mut in_flight_capture),
        );
        request_event?;
        let result = captured?;
        let Err(error) = result else {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "cancelled in-flight capture unexpectedly succeeded",
            )
            .into());
        };
        assert_direct_transport_failure(
            &error,
            DirectHttpTransportErrorKind::Cancelled,
            expected_identity,
        )
    }
    .await;
    service.shutdown().await;
    test_result
}

#[tokio::test]
async fn concurrent_prepared_direct_http_requests_get_fresh_capture_ids() -> TestResult {
    let service = FixtureService::start(
        Protocol::Http,
        [
            (
                "/one".to_owned(),
                Response::bytes(200, Some("text/plain; charset=utf-8"), b"one"),
            ),
            (
                "/two".to_owned(),
                Response::bytes(200, Some("text/plain; charset=utf-8"), b"two"),
            ),
            (
                "/again".to_owned(),
                Response::bytes(200, Some("text/plain; charset=utf-8"), b"again"),
            ),
        ],
    )
    .await;
    let declaration = ys::Policy::default();
    let expected_identity = declaration.effective_identity()?;
    let one_cancellation = CancellationToken::new();
    let two_cancellation = CancellationToken::new();
    let one_prepared = request(&declaration, &service.url("/one"))?;
    let one_attempt = PolicyResolver::resolve(
        &one_prepared,
        first_attempt(&one_prepared)?,
        direct_context()?,
    )?;
    let two_prepared = request(&declaration, &service.url("/two"))?;
    let two_attempt = PolicyResolver::resolve(
        &two_prepared,
        first_attempt(&two_prepared)?,
        direct_context()?,
    )?;
    let (one_result, two_result) = tokio::join!(
        one_attempt.execute(&one_cancellation),
        two_attempt.execute(&two_cancellation)
    );
    let one = one_result?;
    let two = two_result?;
    let one_id = one.bundle().capture().id();
    let two_id = two.bundle().capture().id();
    assert_ne!(one_id, two_id);
    assert_eq!(one.applied_policy().identity(), expected_identity);
    assert_eq!(two.applied_policy().identity(), expected_identity);

    let repeated_prepared = request(&declaration, &service.url("/again"))?;
    let repeated = capture_with_attempt(
        &repeated_prepared,
        first_attempt(&repeated_prepared)?,
        direct_context()?,
        &CancellationToken::new(),
    )
    .await?;
    assert_ne!(one_id, repeated.bundle().capture().id());
    assert_ne!(two_id, repeated.bundle().capture().id());
    assert_eq!(repeated.applied_policy().identity(), expected_identity);

    let requests = service.requests().await;
    assert!(requests.iter().any(|request| request.path == "/one"));
    assert!(requests.iter().any(|request| request.path == "/two"));
    assert!(requests.iter().any(|request| request.path == "/again"));
    service.shutdown().await;
    Ok(())
}
