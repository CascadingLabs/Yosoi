// Assertions fail the harness; Result is used for fixture/setup failures.
#![allow(clippy::panic_in_result_fn)]
#![allow(
    clippy::absolute_paths,
    reason = "tests exercise the documented ys::policy namespace"
)]

#[path = "../../yosoi-web-capture-direct-http/tests/support/direct_http_fixture.rs"]
mod fixture;

use std::{error::Error, io, num::NonZeroU32};

use fixture::{FixtureService, Protocol, Response};
use tokio_util::sync::CancellationToken;
use yosoi_engine::prelude as ys;
use yosoi_engine::{
    AcceptedSourceFormat, AcceptedSourceFormats, DirectHttpAcquisition, DirectHttpOutputSchemas,
    DirectHttpResolutionInputs, DirectHttpTransportProfile, DocumentOutcome, HttpSessionUse,
    OperationId, PolicyCapture, PolicyDecision, PolicyResolutionContext, PolicyResolver,
    PreparedAttempt, PreparedPageRequest, Producer, ProjectedAttempt, ProjectionError,
    ResolvedPolicyAttempt, Schema, SchemaId, SchemaVersion, SourceRetentionPolicy,
    UnavailableReason, UnprojectableReason, UnsupportedSourceFormatBehavior, project_attempt,
    wreq_adapter_producer,
};
use yosoi_web_capture::{DecodedSourceArtifact, WebArtifactRef};
use yosoi_web_capture_direct_http::XmlSourceProfile;

type TestResult<T = ()> = Result<T, Box<dyn Error + Send + Sync>>;

const BODY_SENTINEL: &str = "cas440-projected-body-sentinel";
const TARGET_SENTINEL: &str = "cas440-projected-target-sentinel";

fn test_schema(name: &str) -> TestResult<Schema> {
    Ok(Schema::new(
        SchemaId::new(name)?,
        SchemaVersion::new(NonZeroU32::MIN),
    ))
}

fn direct_context() -> TestResult<PolicyResolutionContext> {
    let producer: Producer = wreq_adapter_producer()?;
    Ok(PolicyResolutionContext::direct_http(
        DirectHttpResolutionInputs {
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
            producer,
            operation: OperationId::new("test.cas-440.document-projection")?,
            output_schemas: DirectHttpOutputSchemas::new(
                test_schema("test.cas-440.source")?,
                test_schema("test.cas-440.source-representation")?,
                None,
                Some(test_schema("test.cas-440.decoded-source")?),
            ),
        },
    ))
}

fn prepare(policy: &ys::Policy, target: &str) -> TestResult<PreparedPageRequest> {
    Ok(ys::request::new(target).bind(policy).prepare()?)
}

fn first_attempt(prepared: &PreparedPageRequest) -> TestResult<&PreparedAttempt> {
    prepared
        .attempts()
        .first()
        .ok_or_else(|| io::Error::other("prepared request has no attempt").into())
}

fn resolve_direct(
    prepared: &PreparedPageRequest,
    attempt: &PreparedAttempt,
) -> TestResult<ResolvedPolicyAttempt> {
    Ok(PolicyResolver::resolve(
        prepared,
        attempt,
        direct_context()?,
    )?)
}

async fn execute_direct(
    prepared: &PreparedPageRequest,
    attempt: &PreparedAttempt,
) -> TestResult<PolicyCapture> {
    Ok(resolve_direct(prepared, attempt)?
        .execute(&CancellationToken::new())
        .await?)
}

fn first_document(projected: &ProjectedAttempt) -> TestResult<&DocumentOutcome> {
    projected
        .documents()
        .first()
        .ok_or_else(|| io::Error::other("projected attempt has no document outcome").into())
}

#[tokio::test]
async fn classified_http_sources_project_to_their_document_classes_and_redact_debug() -> TestResult
{
    let html_path = format!("/html?token={TARGET_SENTINEL}");
    let html_body = format!("<!doctype html><main>{BODY_SENTINEL}</main>");
    let routes = [
        (
            html_path.clone(),
            Response::bytes(200, Some("text/html; charset=utf-8"), html_body.as_bytes()),
        ),
        (
            "/xml".to_owned(),
            Response::bytes(
                200,
                Some("application/xml; charset=utf-8"),
                b"<?xml version=\"1.0\"?><root>xml-body</root>",
            ),
        ),
        (
            "/xhtml".to_owned(),
            Response::bytes(
                200,
                Some("application/xhtml+xml; charset=utf-8"),
                b"<!doctype html><html xmlns=\"http://www.w3.org/1999/xhtml\"><body>xhtml</body></html>",
            ),
        ),
        (
            "/json".to_owned(),
            Response::bytes(
                200,
                Some("application/json; charset=utf-8"),
                b"{\"kind\":\"json\"}",
            ),
        ),
        (
            "/text".to_owned(),
            Response::bytes(200, Some("text/plain; charset=utf-8"), b"plain text"),
        ),
    ];
    let service = FixtureService::start(Protocol::Http, routes).await;
    let cases = [
        (
            html_path.as_str(),
            ys::DocumentClass::SourceHtml,
            &b"<!doctype html><main>cas440-projected-body-sentinel</main>"[..],
        ),
        (
            "/xml",
            ys::DocumentClass::SourceXml,
            &b"<?xml version=\"1.0\"?><root>xml-body</root>"[..],
        ),
        (
            "/xhtml",
            ys::DocumentClass::SourceXml,
            &b"<!doctype html><html xmlns=\"http://www.w3.org/1999/xhtml\"><body>xhtml</body></html>"[..],
        ),
        (
            "/json",
            ys::DocumentClass::SourceJson,
            &b"{\"kind\":\"json\"}"[..],
        ),
        (
            "/text",
            ys::DocumentClass::SourceText,
            &b"plain text"[..],
        ),
    ];

    for (path, expected_class, expected_bytes) in cases {
        let policy = ys::Policy::default();
        let target = service.url(path);
        let prepared = prepare(&policy, &target)?;
        let attempt = first_attempt(&prepared)?;
        let capture = execute_direct(&prepared, attempt).await?;
        let projected = project_attempt(capture, &prepared, attempt)?;

        assert_eq!(projected.capture_id(), attempt.capture_id());
        assert_eq!(
            projected.policy_identity(),
            prepared.effective_policy_identity()
        );
        assert_eq!(
            projected.authored_selection(),
            ys::policy::DocumentSelectionKind::Current
        );
        assert_eq!(projected.policy_snapshot().policy(), &policy);
        assert!(projected.response().is_some());
        assert_eq!(projected.documents().len(), 1);
        let outcome = first_document(&projected)?;
        assert!(matches!(outcome, DocumentOutcome::Produced { .. }));
        let document = outcome
            .document()
            .ok_or_else(|| io::Error::other("complete source did not produce a Document"))?;
        assert_eq!(document.class(), expected_class);
        assert_eq!(document.bytes(), expected_bytes);

        let debug = format!("{projected:?}");
        assert!(!debug.contains(BODY_SENTINEL));
        assert!(!debug.contains(TARGET_SENTINEL));
        assert!(!debug.contains(&target));
    }

    service.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn document_owns_the_existing_decoded_utf8_payload_without_copying() -> TestResult {
    let service = FixtureService::start(
        Protocol::Http,
        [(
            "/windows-1252".to_owned(),
            Response::bytes(
                200,
                Some("text/plain; charset=windows-1252"),
                b"price: \x809",
            ),
        )],
    )
    .await;
    let policy = ys::Policy::default();
    let target = service.url("/windows-1252");
    let prepared = prepare(&policy, &target)?;
    let attempt = first_attempt(&prepared)?;
    let capture = execute_direct(&prepared, attempt).await?;
    let decoded_artifact = capture
        .bundle()
        .capture()
        .artifacts()
        .results()
        .decoded_source()
        .artifacts()
        .and_then(<[DecodedSourceArtifact]>::first)
        .ok_or_else(|| io::Error::other("decoded Source artifact is missing"))?;
    let expected_artifact: WebArtifactRef = decoded_artifact.reference().into();
    let decoded_payload = capture
        .bundle()
        .payload(expected_artifact)
        .ok_or_else(|| io::Error::other("decoded Source payload is missing"))?;
    let decoded_pointer = decoded_payload.as_ptr();
    let decoded_length = decoded_payload.len();
    assert_eq!(decoded_payload, "price: €9".as_bytes());

    let projected = project_attempt(capture, &prepared, attempt)?;
    let outcome = first_document(&projected)?;
    assert!(matches!(outcome, DocumentOutcome::Produced { .. }));
    let document = outcome
        .document()
        .ok_or_else(|| io::Error::other("decoded text did not produce a Document"))?;
    assert_eq!(document.class(), ys::DocumentClass::SourceText);
    assert_eq!(outcome.artifact(), Some(expected_artifact));
    assert_eq!(document.bytes().as_ptr(), decoded_pointer);
    assert_eq!(document.bytes().len(), decoded_length);
    assert_eq!(document.bytes(), "price: €9".as_bytes());

    service.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn truncated_source_is_partial_and_never_published_as_a_complete_document() -> TestResult {
    let service = FixtureService::start(
        Protocol::Http,
        [(
            "/partial".to_owned(),
            Response::bytes(
                200,
                Some("text/plain; charset=utf-8"),
                b"partial-source-body-sentinel",
            ),
        )],
    )
    .await;
    let mut policy = ys::Policy::default();
    policy.request.source.representation_bytes = ys::policy::AddressableByteLimit::try_from(9_u64)?;
    let target = service.url("/partial");
    let prepared = prepare(&policy, &target)?;
    let attempt = first_attempt(&prepared)?;
    let capture = execute_direct(&prepared, attempt).await?;
    assert_eq!(
        capture.bundle().capture().completeness(),
        yosoi_web_capture::CaptureCompleteness::Incomplete
    );

    let projected = project_attempt(capture, &prepared, attempt)?;
    assert_eq!(projected.documents().len(), 1);
    let outcome = first_document(&projected)?;
    assert!(matches!(outcome, DocumentOutcome::Partial { .. }));
    assert!(outcome.document().is_none());
    assert_ne!(outcome.partial_reasons().len(), 0);
    assert!(
        outcome
            .partial_reasons()
            .contains(&yosoi_engine::PartialReason::SourceArtifactTruncated)
    );
    assert!(
        outcome
            .partial_reasons()
            .contains(&yosoi_engine::PartialReason::ClassificationFromRetainedPrefix)
    );
    let debug = format!("{projected:?}");
    assert!(!debug.contains("partial-source-body-sentinel"));
    assert!(!debug.contains(&target));

    service.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn unknown_and_unsupported_source_classifications_are_unprojectable() -> TestResult {
    let service = FixtureService::start(
        Protocol::Http,
        [
            (
                "/unknown".to_owned(),
                Response::bytes(
                    200,
                    None,
                    b"opaque bytes with cas440-projected-body-sentinel and no strong signature",
                ),
            ),
            (
                "/unsupported".to_owned(),
                Response::bytes(200, Some("image/png"), b"\x89PNG\r\n\x1a\nopaque"),
            ),
        ],
    )
    .await;

    for (path, expected_reason) in [("/unknown", "unknown"), ("/unsupported", "unsupported")] {
        let policy = ys::Policy::default();
        let target = service.url(path);
        let prepared = prepare(&policy, &target)?;
        let attempt = first_attempt(&prepared)?;
        let capture = execute_direct(&prepared, attempt).await?;
        let projected = project_attempt(capture, &prepared, attempt)?;
        assert_eq!(projected.documents().len(), 1);
        let outcome = first_document(&projected)?;
        assert!(outcome.document().is_none());
        let expected_outcome = match expected_reason {
            "unknown" => matches!(
                outcome,
                DocumentOutcome::Unprojectable {
                    reason: UnprojectableReason::UnknownSourceFormat { .. },
                }
            ),
            "unsupported" => matches!(
                outcome,
                DocumentOutcome::Unprojectable {
                    reason: UnprojectableReason::UnsupportedSourceFormat,
                }
            ),
            _ => false,
        };
        if !expected_outcome {
            return Err(io::Error::other(format!(
                "{expected_reason} source classification produced an unexpected outcome"
            ))
            .into());
        }
        let debug = format!("{projected:?}");
        assert!(!debug.contains(BODY_SENTINEL));
        assert!(!debug.contains(&target));
    }

    service.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn unavailable_response_body_is_unavailable_not_unprojectable() -> TestResult {
    let mut disconnected = Response::bytes(
        200,
        Some("text/plain; charset=utf-8"),
        b"body-never-written",
    );
    disconnected.close_after_chunks = Some(0);
    let service =
        FixtureService::start(Protocol::Http, [("/unavailable".to_owned(), disconnected)]).await;
    let policy = ys::Policy::default();
    let target = service.url("/unavailable");
    let prepared = prepare(&policy, &target)?;
    let attempt = first_attempt(&prepared)?;
    let capture = execute_direct(&prepared, attempt).await?;
    assert!(
        capture
            .bundle()
            .capture()
            .artifacts()
            .results()
            .source()
            .artifacts()
            .is_none()
    );
    assert!(
        capture
            .direct_http_capture()
            .and_then(|direct| direct.source_facts())
            .is_none()
    );

    let projected = project_attempt(capture, &prepared, attempt)?;
    let outcome = first_document(&projected)?;
    assert!(matches!(
        outcome,
        DocumentOutcome::Unavailable {
            reason: UnavailableReason::SourceArtifactUnavailable,
        }
    ));
    assert!(outcome.document().is_none());
    assert!(!format!("{projected:?}").contains(&target));

    service.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn exact_empty_selection_projects_no_public_document_outcomes() -> TestResult {
    let service = FixtureService::start(
        Protocol::Http,
        [(
            "/empty-selection".to_owned(),
            Response::bytes(200, Some("text/plain; charset=utf-8"), b"internal source"),
        )],
    )
    .await;
    let mut policy = ys::Policy::default();
    policy.page.acquisitions = vec![ys::policy::Acquisition::DirectHttp.documents([])];
    let target = service.url("/empty-selection");
    let prepared = prepare(&policy, &target)?;
    let attempt = first_attempt(&prepared)?;
    assert_eq!(
        attempt.authored_selection(),
        ys::policy::DocumentSelectionKind::Exact
    );
    assert_eq!(attempt.documents().len(), 0);
    let capture = execute_direct(&prepared, attempt).await?;
    let projected = project_attempt(capture, &prepared, attempt)?;

    assert_eq!(projected.capture_id(), attempt.capture_id());
    assert_eq!(
        projected.policy_identity(),
        prepared.effective_policy_identity()
    );
    assert_eq!(
        projected.authored_selection(),
        ys::policy::DocumentSelectionKind::Exact
    );
    assert_eq!(projected.policy_snapshot().policy(), &policy);
    assert_eq!(projected.documents().len(), 0);
    assert!(
        !projected
            .applied_policy()
            .decisions()
            .iter()
            .any(|decision| matches!(decision, PolicyDecision::DocumentRequested { .. }))
    );
    assert_eq!(service.requests().await.len(), 1);

    service.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn projection_rejects_foreign_attempts_and_non_direct_http_attempts() -> TestResult {
    let service = FixtureService::start(
        Protocol::Http,
        [
            (
                "/first".to_owned(),
                Response::bytes(200, Some("text/plain; charset=utf-8"), b"first"),
            ),
            (
                "/second".to_owned(),
                Response::bytes(200, Some("text/plain; charset=utf-8"), b"second"),
            ),
            (
                "/mixed".to_owned(),
                Response::bytes(200, Some("text/plain; charset=utf-8"), b"mixed"),
            ),
        ],
    )
    .await;

    let policy = ys::Policy::default();
    let first_prepared = prepare(&policy, &service.url("/first"))?;
    let first = first_attempt(&first_prepared)?;
    let first_capture = execute_direct(&first_prepared, first).await?;
    let foreign_prepared = prepare(&policy, &service.url("/second"))?;
    let foreign = first_attempt(&foreign_prepared)?;
    let foreign_error = project_attempt(first_capture, &first_prepared, foreign)
        .err()
        .ok_or_else(|| io::Error::other("projection accepted a foreign attempt"))?;
    assert!(matches!(foreign_error, ProjectionError::ForeignAttempt));

    let mut mixed_policy = ys::Policy::default();
    mixed_policy.page.acquisitions = vec![
        ys::policy::Acquisition::DirectHttp,
        ys::policy::Acquisition::Browser(ys::policy::BrowserMode::Headless),
    ];
    let mixed_prepared = prepare(&mixed_policy, &service.url("/mixed"))?;
    let direct = mixed_prepared
        .attempts()
        .first()
        .ok_or_else(|| io::Error::other("Direct HTTP sibling is missing"))?;
    let browser = mixed_prepared
        .attempts()
        .get(1)
        .ok_or_else(|| io::Error::other("browser sibling is missing"))?;
    let direct_capture = execute_direct(&mixed_prepared, direct).await?;
    let non_direct_error = project_attempt(direct_capture, &mixed_prepared, browser)
        .err()
        .ok_or_else(|| io::Error::other("projection accepted a browser attempt"))?;
    assert!(matches!(
        non_direct_error,
        ProjectionError::CaptureOutcomeMismatch
    ));

    service.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn projection_rejects_capture_id_and_policy_identity_mismatches() -> TestResult {
    let service = FixtureService::start(
        Protocol::Http,
        [
            (
                "/capture-id".to_owned(),
                Response::bytes(200, Some("text/plain; charset=utf-8"), b"capture id"),
            ),
            (
                "/policy-id".to_owned(),
                Response::bytes(200, Some("text/plain; charset=utf-8"), b"policy id"),
            ),
        ],
    )
    .await;

    let policy = ys::Policy::default();
    let capture_id_page = ys::request::new(service.url("/capture-id")).bind(&policy);
    let first_prepared = capture_id_page.prepare()?;
    let second_prepared = capture_id_page.prepare()?;
    let first = first_attempt(&first_prepared)?;
    let second = first_attempt(&second_prepared)?;
    assert_eq!(
        first_prepared.effective_policy_identity(),
        second_prepared.effective_policy_identity()
    );
    assert_ne!(first.capture_id(), second.capture_id());
    let capture = execute_direct(&first_prepared, first).await?;
    let error = project_attempt(capture, &second_prepared, second)
        .err()
        .ok_or_else(|| io::Error::other("projection accepted a mismatched capture ID"))?;
    assert!(matches!(error, ProjectionError::CaptureIdMismatch));

    let capture_policy = ys::Policy::default();
    let capture_prepared = prepare(&capture_policy, &service.url("/policy-id"))?;
    let capture_attempt = first_attempt(&capture_prepared)?;
    let capture = execute_direct(&capture_prepared, capture_attempt).await?;
    let mut different_policy = ys::Policy::default();
    different_policy.request.maximum_elapsed =
        ys::policy::MaximumElapsed::try_from(20_000_000_u64)?;
    let mismatched_prepared = prepare(&different_policy, &service.url("/policy-id"))?;
    let mismatched_attempt = first_attempt(&mismatched_prepared)?;
    let error = project_attempt(capture, &mismatched_prepared, mismatched_attempt)
        .err()
        .ok_or_else(|| io::Error::other("projection accepted a mismatched policy identity"))?;
    assert!(matches!(error, ProjectionError::PolicyIdentityMismatch));

    service.shutdown().await;
    Ok(())
}
