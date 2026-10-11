#![cfg(feature = "browser")]
// Assertions fail the harness; Result is used for fixture and task errors.
#![allow(clippy::panic_in_result_fn)]
#![allow(
    clippy::absolute_paths,
    reason = "tests exercise the documented ys::policy namespace"
)]

use std::{
    env, error::Error, ffi::OsString, fs, io, net::Ipv4Addr, num::NonZeroU32, path::Path,
    process::Command, ptr::NonNull, time::Duration,
};

use crate::internal::engine::projection::ProjectedAttemptTransport;
use crate::internal::engine::{
    AcquisitionCapabilityProfile, ArtifactCapability, ArtifactMultiplicity, AttemptDocumentOutcome,
    AttemptOutcome, BrowserArtifactIdentityPlan, BrowserCapabilityStatus,
    BrowserEnvironmentOverrides, BrowserEvidenceAdmissionPolicy, BrowserFamilyCapabilities,
    BrowserHeaderAdmission, BrowserInstrumentationMode, BrowserMainBodyAdmission,
    BrowserNavigationCapabilityProfile, BrowserNavigationPolicy, BrowserOutputSchemas,
    BrowserResolutionInputs, BrowserUrlAdmission, CaptureId, CertifiedBrowserCapabilities,
    DocumentOutcome, NavigationCompletionPolicy, NavigationContext, OperationId,
    PolicyCaptureOutcome, PolicyDecision, PolicyResolutionContext, PolicyResolutionError,
    PolicyResolver, Producer, ReasonCode, RequestExecutor, ResponseTermination, Schema, SchemaId,
    SchemaVersion, SettlementPolicy, WebArtifactCapabilitySet, WebProviderCapabilityProfile,
    prelude as ys, project_attempt,
};
use crate::internal::types::ArtifactAvailability;
use crate::internal::web_capture::{
    AccessibilityTreeArtifact, ArtifactRequest, BrowserCaptureSpecError, BrowserMode,
    BrowserStructuredEvidence, CaptureBundle, CaptureCompleteness, CaptureEnvironment,
    CleanupState, RenderedDomArtifact, SourceArtifact, void_crawl_adapter_producer,
};
use tempfile::tempdir;
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    task::{JoinHandle, spawn_blocking},
    time::timeout,
};
use tokio_util::sync::CancellationToken;

const INLINE_PAGE: &[u8] = br##"<!doctype html>
<meta charset="utf-8">
<main>source-only-marker</main>
<script>
const left = "computed";
const right = "by-script";
document.body.firstElementChild.textContent = left + "-" + right;
</script>
"##;
const MAX_REQUEST_HEADER_BYTES: usize = 16 * 1024;
const ARCHIVE_CHILD_ROLE: &str = "YOSOI_BROWSER_ARCHIVE_CHILD_ROLE";
const ARCHIVE_CHILD_ROOT: &str = "YOSOI_BROWSER_ARCHIVE_CHILD_ROOT";
const ARCHIVE_CHILD_REFERENCE: &str = "YOSOI_BROWSER_ARCHIVE_CHILD_REFERENCE";
const ARCHIVE_CHILD_TARGET: &str = "YOSOI_BROWSER_ARCHIVE_CHILD_TARGET";

type TestResult<T = ()> = Result<T, Box<dyn Error + Send + Sync>>;

struct InlinePageServer {
    url: String,
    cancellation: CancellationToken,
    task: JoinHandle<io::Result<()>>,
}

impl InlinePageServer {
    async fn start() -> TestResult<Self> {
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).await?;
        let address = listener.local_addr()?;
        if !address.ip().is_loopback() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "browser fixture must bind to loopback",
            )
            .into());
        }
        let cancellation = CancellationToken::new();
        let task_cancellation = cancellation.clone();
        let task = tokio::spawn(async move {
            loop {
                let accepted = tokio::select! {
                    () = task_cancellation.cancelled() => break,
                    accepted = listener.accept() => accepted?,
                };
                let (stream, peer) = accepted;
                if !peer.ip().is_loopback() {
                    return Err(io::Error::new(
                        io::ErrorKind::PermissionDenied,
                        "browser fixture rejected a non-loopback peer",
                    ));
                }
                if let Err(error) = serve_inline_page(stream, &task_cancellation).await {
                    // Chrome can cancel speculative requests when a capture closes.
                    // A disconnected client must not terminate the fixture server.
                    if !matches!(
                        error.kind(),
                        io::ErrorKind::BrokenPipe
                            | io::ErrorKind::ConnectionReset
                            | io::ErrorKind::ConnectionAborted
                    ) {
                        return Err(error);
                    }
                }
            }
            Ok(())
        });
        Ok(Self {
            url: format!("http://127.0.0.1:{}/", address.port()),
            cancellation,
            task,
        })
    }

    async fn shutdown(self) -> TestResult {
        self.cancellation.cancel();
        self.task
            .await
            .map_err(|error| io::Error::other(error.to_string()))??;
        Ok(())
    }
}

async fn serve_inline_page(
    mut stream: TcpStream,
    cancellation: &CancellationToken,
) -> io::Result<()> {
    let mut request_head = Vec::with_capacity(1_024);
    let mut byte = [0_u8; 1];
    loop {
        if request_head.len() >= MAX_REQUEST_HEADER_BYTES {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "browser fixture request header exceeded its bound",
            ));
        }
        let read = tokio::select! {
            () = cancellation.cancelled() => return Ok(()),
            read = stream.read(&mut byte) => read?,
        };
        if read == 0 {
            return Ok(());
        }
        let Some(value) = byte.first().copied() else {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "browser fixture received an empty byte buffer",
            ));
        };
        request_head.push(value);
        if request_head.ends_with(b"\r\n\r\n") {
            break;
        }
    }

    let response_head = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        INLINE_PAGE.len()
    );
    tokio::select! {
        () = cancellation.cancelled() => return Ok(()),
        result = stream.write_all(response_head.as_bytes()) => result?,
    }
    stream.write_all(INLINE_PAGE).await?;
    stream.shutdown().await
}

#[tokio::test]
async fn inline_page_server_survives_reset_connections() -> TestResult {
    let server = InlinePageServer::start().await?;
    let address = server
        .url
        .trim_start_matches("http://")
        .trim_end_matches('/');
    let mut aborted = TcpStream::connect(address).await?;
    aborted.set_zero_linger()?;
    aborted
        .write_all(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
        .await?;
    drop(aborted);

    let mut next = TcpStream::connect(address).await?;
    next.write_all(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
        .await?;
    let mut response = Vec::new();
    timeout(Duration::from_secs(5), next.read_to_end(&mut response)).await??;
    assert!(response.starts_with(b"HTTP/1.1 200 OK\r\n"));
    assert!(response.ends_with(INLINE_PAGE));
    server.shutdown().await
}

fn test_producer() -> TestResult<Producer> {
    Ok(void_crawl_adapter_producer()?)
}

fn test_operation() -> TestResult<OperationId> {
    Ok(OperationId::new("test.policy-capture.browser")?)
}

fn test_schema(name: &str) -> TestResult<Schema> {
    Ok(Schema::new(
        SchemaId::new(name)?,
        SchemaVersion::new(NonZeroU32::MIN),
    ))
}

fn browser_capabilities(mode: BrowserMode) -> TestResult<CertifiedBrowserCapabilities> {
    // Match the provider and family facts in the existing browser lifecycle fixture.
    let producer = test_producer()?;
    let supported = ArtifactCapability::Supported {
        multiplicity: ArtifactMultiplicity::ExactlyOne,
    };
    let unsupported_storage = ArtifactCapability::Unsupported {
        reason: ReasonCode::new("test.unavailable")?,
    };
    let profile = WebProviderCapabilityProfile::new(
        producer.clone(),
        AcquisitionCapabilityProfile::DocumentNavigation(BrowserNavigationCapabilityProfile::new(
            mode,
        )),
        WebArtifactCapabilitySet::new(
            supported.clone(),
            supported.clone(),
            supported.clone(),
            supported.clone(),
            supported.clone(),
            unsupported_storage,
            supported.clone(),
            supported.clone(),
            supported,
        ),
    )?;
    let unsupported_status = BrowserCapabilityStatus::Unsupported {
        reason: ReasonCode::new("test.unavailable")?,
    };
    Ok(CertifiedBrowserCapabilities::new(
        profile,
        &producer,
        mode,
        BrowserInstrumentationMode::Normal,
        BrowserFamilyCapabilities::new(
            BrowserCapabilityStatus::Supported,
            BrowserCapabilityStatus::Supported,
            BrowserCapabilityStatus::Supported,
            BrowserCapabilityStatus::Supported,
            BrowserCapabilityStatus::Supported,
            unsupported_status,
            BrowserCapabilityStatus::Supported,
            BrowserCapabilityStatus::Supported,
            BrowserCapabilityStatus::Supported,
        ),
    )?)
}

fn browser_context(
    capture_id: CaptureId,
    mode: BrowserMode,
) -> TestResult<PolicyResolutionContext> {
    Ok(PolicyResolutionContext::browser(browser_inputs(
        capture_id, mode,
    )?))
}

fn browser_inputs(capture_id: CaptureId, mode: BrowserMode) -> TestResult<BrowserResolutionInputs> {
    Ok(BrowserResolutionInputs {
        navigation_context: NavigationContext::FreshTopLevel,
        navigation_policy: BrowserNavigationPolicy::new(
            NavigationCompletionPolicy::ControllerCompleted,
        ),
        environment_overrides: BrowserEnvironmentOverrides::default(),
        capabilities: browser_capabilities(mode)?,
        producer: test_producer()?,
        operation: test_operation()?,
        output_schemas: BrowserOutputSchemas::new(
            Some(test_schema("test.policy-capture.source")?),
            Some(test_schema("test.policy-capture.source-representation")?),
            Some(test_schema("test.policy-capture.decoded-source")?),
            Some(test_schema("test.policy-capture.rendered-dom")?),
            Some(test_schema("test.policy-capture.accessibility-tree")?),
            None,
            None,
            None,
            None,
            None,
            None,
        ),
        identity_plan: BrowserArtifactIdentityPlan::sequential(capture_id.activity_id()),
        admission: BrowserEvidenceAdmissionPolicy::new(
            BrowserUrlAdmission::Omit,
            BrowserHeaderAdmission::Omit,
            BrowserMainBodyAdmission::AdmitDecodedRepresentation,
        ),
        settlement: SettlementPolicy::Disabled,
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

fn rendered_dom_artifact(bundle: &CaptureBundle) -> TestResult<&RenderedDomArtifact> {
    bundle
        .capture()
        .artifacts()
        .results()
        .rendered_dom()
        .artifacts()
        .and_then(|artifacts| artifacts.first())
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "DOM artifact is missing").into())
}

fn accessibility_artifact(bundle: &CaptureBundle) -> TestResult<&AccessibilityTreeArtifact> {
    bundle
        .capture()
        .artifacts()
        .results()
        .accessibility_tree()
        .artifacts()
        .and_then(|artifacts| artifacts.first())
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "AX artifact is missing").into())
}

async fn run_browser_capture(mode: BrowserMode) -> TestResult {
    let server = InlinePageServer::start().await?;
    let result = async {
        let mut policy = ys::Policy::default();
        policy.page.acquisitions = vec![ys::policy::Acquisition::Browser(mode).documents([
            ys::policy::DocumentRequest::ResponseDocument,
            ys::policy::DocumentRequest::RenderedDom,
            ys::policy::DocumentRequest::AccessibilityTree,
        ])];
        let prepared = ys::request::new(&server.url).bind(&policy).prepare()?;
        let expected_identity = prepared.effective_policy_identity();
        let prepared_attempt = prepared
            .attempts()
            .first()
            .ok_or_else(|| io::Error::other("prepared browser request has no attempt"))?;
        assert_eq!(
            prepared_attempt.authored_selection(),
            ys::policy::DocumentSelectionKind::Exact
        );
        assert_eq!(
            prepared_attempt.documents(),
            &[
                ys::policy::DocumentRequest::ResponseDocument,
                ys::policy::DocumentRequest::RenderedDom,
                ys::policy::DocumentRequest::AccessibilityTree,
            ]
        );
        let context = browser_context(prepared_attempt.capture_id(), mode)?;
        let attempt = PolicyResolver::resolve(&prepared, prepared_attempt, context)?;
        assert!(
            attempt
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
        for document in prepared_attempt.documents() {
            assert!(
                attempt
                    .applied_policy()
                    .decisions()
                    .iter()
                    .any(|decision| matches!(
                        decision,
                        PolicyDecision::DocumentRequested { document: requested }
                            if requested == document
                    ))
            );
        }
        let cancellation = CancellationToken::new();
        let capture_future = attempt.execute(&cancellation);
        tokio::pin!(capture_future);
        let capture = match timeout(Duration::from_secs(90), &mut capture_future).await {
            Ok(Ok(capture)) => capture,
            Ok(Err(error)) => return Err(error.into()),
            Err(error) => {
                cancellation.cancel();
                let _ = timeout(Duration::from_secs(15), &mut capture_future).await;
                return Err(error.into());
            }
        };

        let capture_debug = format!("{capture:?}");
        assert!(!capture_debug.contains("source-only-marker"));
        assert!(!capture_debug.contains("computed-by-script"));
        assert!(!capture_debug.contains(&server.url));
        assert_eq!(capture.applied_policy().identity(), expected_identity);
        assert_eq!(capture.browser_cleanup(), Some(CleanupState::Complete));
        assert_eq!(capture.browser_status(), Some(200));
        assert!(matches!(
            capture.outcome(),
            PolicyCaptureOutcome::Browser {
                cleanup: CleanupState::Complete,
                ..
            }
        ));
        let bundle = capture.bundle();
        let web = bundle.capture();
        assert_eq!(web.completeness(), CaptureCompleteness::Complete);
        assert!(web.browser_execution().is_none());
        assert!(matches!(
            web.environment(),
            CaptureEnvironment::Browser(environment)
                if environment.mode().as_known() == Some(&mode)
        ));
        assert_eq!(
            web.artifacts().requests().source(),
            ArtifactRequest::Required
        );
        assert_eq!(
            web.artifacts().requests().rendered_dom(),
            ArtifactRequest::Required
        );
        assert_eq!(
            web.artifacts().requests().accessibility_tree(),
            ArtifactRequest::Required
        );

        let source = source_artifact(bundle)?;
        let dom = rendered_dom_artifact(bundle)?;
        let accessibility = accessibility_artifact(bundle)?;
        let decoded = web
            .artifacts()
            .results()
            .decoded_source()
            .artifacts()
            .and_then(|artifacts| artifacts.first())
            .ok_or_else(|| io::Error::other("decoded browser source is missing"))?;
        let decoded_payload = bundle
            .payload(decoded.reference().into())
            .ok_or_else(|| io::Error::other("decoded browser source payload is missing"))?;
        let decoded_payload_start = NonNull::from(
            decoded_payload
                .first()
                .ok_or_else(|| io::Error::other("decoded browser source is empty"))?,
        );
        assert_eq!(
            source.metadata().record().availability(),
            ArtifactAvailability::Retained
        );
        assert_eq!(
            dom.metadata().record().availability(),
            ArtifactAvailability::Retained
        );
        assert_eq!(
            accessibility.metadata().record().availability(),
            ArtifactAvailability::Retained
        );
        let source_bytes = bundle.payload(source.reference().into()).ok_or_else(|| {
            io::Error::new(io::ErrorKind::InvalidData, "source payload is missing")
        })?;
        let dom_bytes = bundle
            .payload(dom.reference().into())
            .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "DOM payload is missing"))?;
        let accessibility_bytes = bundle
            .payload(accessibility.reference().into())
            .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "AX payload is missing"))?;
        let source_text = std::str::from_utf8(source_bytes)?;
        let dom_text = std::str::from_utf8(dom_bytes)?;
        let structured_evidence: BrowserStructuredEvidence =
            serde_json::from_slice(accessibility_bytes)?;
        let BrowserStructuredEvidence::Accessibility(accessibility_evidence) = structured_evidence
        else {
            return Err(
                io::Error::other("AX artifact did not contain its accessibility envelope").into(),
            );
        };
        let accessibility_text = std::str::from_utf8(&accessibility_evidence.canonical_node_bytes)?;
        assert!(source_text.contains("source-only-marker"));
        assert!(!source_text.contains("computed-by-script"));
        assert!(dom_text.contains("computed-by-script"));
        assert!(accessibility_text.contains("computed-by-script"));

        let projected = project_attempt(capture, &prepared, prepared_attempt)?;
        assert_eq!(projected.capture_id(), prepared_attempt.capture_id());
        assert_eq!(projected.policy_snapshot().policy(), &policy);
        assert_eq!(
            projected
                .capture()
                .acquisition()
                .request()
                .target()
                .as_str(),
            server.url
        );
        assert_eq!(projected.browser_cleanup(), Some(CleanupState::Complete));
        assert_eq!(projected.browser_status(), Some(200));
        assert!(matches!(
            projected.transport(),
            ProjectedAttemptTransport::Browser {
                cleanup: CleanupState::Complete,
                ..
            }
        ));
        let [response, rendered_dom, accessibility] = projected.documents() else {
            return Err(io::Error::other(
                "browser projection returned an unexpected document count",
            )
            .into());
        };
        let response_document = response
            .document()
            .ok_or_else(|| io::Error::other("browser response did not normalize"))?;
        assert_eq!(response_document.class(), ys::DocumentClass::SourceHtml);
        assert_eq!(
            NonNull::from(
                response_document
                    .bytes()
                    .first()
                    .ok_or_else(|| io::Error::other("browser response document is empty"))?
            ),
            decoded_payload_start
        );
        assert_eq!(
            rendered_dom
                .document()
                .ok_or_else(|| io::Error::other("rendered DOM did not normalize"))?
                .class(),
            ys::DocumentClass::RenderedDom
        );
        assert_eq!(
            accessibility
                .document()
                .ok_or_else(|| io::Error::other("accessibility tree did not normalize"))?
                .class(),
            ys::DocumentClass::AccessibilityTree
        );
        let projected_debug = format!("{projected:?}");
        assert!(!projected_debug.contains("computed-by-script"));
        assert!(!projected_debug.contains(&server.url));
        Ok::<(), Box<dyn Error + Send + Sync>>(())
    }
    .await;
    server.shutdown().await?;
    result
}

#[tokio::test]
async fn sdk_browser_capture_headless_finalizes_policy_evidence_and_cleanup() -> TestResult {
    run_browser_capture(BrowserMode::Headless).await
}

#[tokio::test]
async fn sdk_browser_capture_headful_finalizes_policy_evidence_and_cleanup() -> TestResult {
    run_browser_capture(BrowserMode::Headful).await
}

#[tokio::test]
async fn request_executor_runs_headless_and_headful_in_policy_order() -> TestResult {
    let server = InlinePageServer::start().await?;
    let result = async {
        let mut policy = ys::Policy::default();
        policy.page.acquisitions = vec![
            ys::policy::Acquisition::Browser(BrowserMode::Headless)
                .documents([ys::policy::DocumentRequest::RenderedDom]),
            ys::policy::Acquisition::Browser(BrowserMode::Headful)
                .documents([ys::policy::DocumentRequest::AccessibilityTree]),
        ];
        let executor = RequestExecutor::new()
            .with_browser(
                BrowserMode::Headless,
                browser_inputs(CaptureId::random(), BrowserMode::Headless)?,
            )
            .with_browser(
                BrowserMode::Headful,
                browser_inputs(CaptureId::random(), BrowserMode::Headful)?,
            );
        let cancellation = CancellationToken::new();
        let request = ys::request::new(&server.url).bind(&policy);
        let send = request.send_with(&executor, &cancellation);
        let response = timeout(Duration::from_secs(180), send).await??;

        assert_eq!(response.termination(), ResponseTermination::Completed);
        let [headless, headful] = response.attempts() else {
            return Err(io::Error::other("request response lost browser attempts").into());
        };
        assert!(matches!(headless, AttemptOutcome::Completed(_)));
        assert!(matches!(headful, AttemptOutcome::Completed(_)));
        assert_eq!(
            headless.acquisition(),
            ys::policy::AcquisitionKind::Browser {
                mode: BrowserMode::Headless
            }
        );
        assert_eq!(
            headful.acquisition(),
            ys::policy::AcquisitionKind::Browser {
                mode: BrowserMode::Headful
            }
        );
        let headless_result = headless
            .result()
            .ok_or_else(|| io::Error::other("headless attempt did not complete"))?;
        let headful_result = headful
            .result()
            .ok_or_else(|| io::Error::other("headful attempt did not complete"))?;
        let [dom] = headless_result.documents() else {
            return Err(io::Error::other("headless DOM outcome is missing").into());
        };
        let [accessibility] = headful_result.documents() else {
            return Err(io::Error::other("headful AX outcome is missing").into());
        };
        assert_eq!(
            dom.outcome()
                .document()
                .ok_or_else(|| io::Error::other("headless DOM did not normalize"))?
                .class(),
            ys::DocumentClass::RenderedDom
        );
        assert!(dom.browser_observation().is_some());
        assert_eq!(
            accessibility
                .outcome()
                .document()
                .ok_or_else(|| io::Error::other("headful AX did not normalize"))?
                .class(),
            ys::DocumentClass::AccessibilityTree
        );
        assert!(accessibility.browser_observation().is_some());
        Ok::<(), Box<dyn Error + Send + Sync>>(())
    }
    .await;
    server.shutdown().await?;
    result
}

#[tokio::test]
async fn bound_send_uses_standard_contexts_for_mixed_current_and_exact_acquisitions() -> TestResult
{
    let server = InlinePageServer::start().await?;
    let result = async {
        let mut policy = ys::Policy::default();
        policy.page.acquisitions = vec![
            ys::policy::Acquisition::DirectHttp,
            ys::policy::Acquisition::Browser(BrowserMode::Headless),
            ys::policy::Acquisition::Browser(BrowserMode::Headful)
                .documents([ys::policy::DocumentRequest::RenderedDom]),
        ];
        let request = ys::request::new(&server.url).bind(&policy);
        let response = timeout(Duration::from_secs(180), request.send()).await??;

        assert_eq!(response.termination(), ResponseTermination::Completed);
        let [direct, headless, headful] = response.attempts() else {
            return Err(io::Error::other("standard send lost a mixed acquisition").into());
        };
        assert!(matches!(direct, AttemptOutcome::Completed(_)));
        assert!(matches!(headless, AttemptOutcome::Completed(_)));
        assert!(matches!(headful, AttemptOutcome::Completed(_)));
        assert_ne!(direct.capture_id(), headless.capture_id());
        assert_ne!(direct.capture_id(), headful.capture_id());
        assert_ne!(headless.capture_id(), headful.capture_id());
        assert_eq!(direct.status(), Some(200));

        let direct_result = direct
            .result()
            .ok_or_else(|| io::Error::other("standard Direct HTTP attempt did not complete"))?;
        let headless_result = headless
            .result()
            .ok_or_else(|| io::Error::other("standard headless attempt did not complete"))?;
        let headful_result = headful
            .result()
            .ok_or_else(|| io::Error::other("standard headful attempt did not complete"))?;
        for (outcome, result) in [
            (direct, direct_result),
            (headless, headless_result),
            (headful, headful_result),
        ] {
            assert_eq!(
                result.capture_facts().terminal_receipt().id(),
                outcome.capture_id()
            );
        }
        assert_eq!(
            direct_result.authored_selection(),
            ys::policy::DocumentSelectionKind::Current
        );
        assert_eq!(
            headless_result.authored_selection(),
            ys::policy::DocumentSelectionKind::Current
        );
        assert_eq!(
            headful_result.authored_selection(),
            ys::policy::DocumentSelectionKind::Exact
        );
        assert_eq!(
            headless_result.acquisition(),
            ys::policy::AcquisitionKind::Browser {
                mode: BrowserMode::Headless
            }
        );
        assert_eq!(
            headful_result.acquisition(),
            ys::policy::AcquisitionKind::Browser {
                mode: BrowserMode::Headful
            }
        );
        assert_eq!(
            headless_result
                .documents()
                .first()
                .map(AttemptDocumentOutcome::requested),
            Some(ys::policy::DocumentRequest::ResponseDocument)
        );
        assert!(
            headless_result
                .documents()
                .first()
                .and_then(AttemptDocumentOutcome::browser_observation)
                .is_some()
        );
        assert_eq!(
            headful_result
                .documents()
                .first()
                .map(AttemptDocumentOutcome::requested),
            Some(ys::policy::DocumentRequest::RenderedDom)
        );
        let headless_document = headless_result
            .documents()
            .first()
            .and_then(|document| document.outcome().document())
            .ok_or_else(|| io::Error::other("standard current browser document is missing"))?;
        let headful_document = headful_result
            .documents()
            .first()
            .and_then(|document| document.outcome().document())
            .ok_or_else(|| io::Error::other("standard exact browser document is missing"))?;
        assert_eq!(headless_document.class(), ys::DocumentClass::SourceHtml);
        assert_eq!(headful_document.class(), ys::DocumentClass::RenderedDom);
        Ok::<(), Box<dyn Error + Send + Sync>>(())
    }
    .await;
    server.shutdown().await?;
    result
}

#[tokio::test]
async fn partial_dom_does_not_erase_a_complete_accessibility_sibling() -> TestResult {
    let server = InlinePageServer::start().await?;
    let result = async {
        let mut policy = ys::Policy::default();
        policy.page.acquisitions = vec![
            ys::policy::Acquisition::Browser(BrowserMode::Headless).documents([
                ys::policy::DocumentRequest::RenderedDom,
                ys::policy::DocumentRequest::AccessibilityTree,
            ]),
        ];
        policy.request.browser.dom_utf8_bytes = ys::policy::AddressableByteLimit::try_from(8_u64)?;

        let response = ys::request::new(&server.url).bind(&policy).send().await?;
        let attempt = response
            .attempts()
            .first()
            .and_then(AttemptOutcome::result)
            .ok_or_else(|| io::Error::other("browser attempt did not complete"))?;
        let [dom, accessibility] = attempt.documents() else {
            return Err(io::Error::other("browser siblings were not preserved").into());
        };
        assert_eq!(dom.requested(), ys::policy::DocumentRequest::RenderedDom);
        assert!(matches!(dom.outcome(), DocumentOutcome::Partial { .. }));
        assert!(dom.outcome().document().is_none());
        assert_eq!(
            accessibility.requested(),
            ys::policy::DocumentRequest::AccessibilityTree
        );
        assert_eq!(
            accessibility
                .outcome()
                .document()
                .ok_or_else(|| io::Error::other("complete AX sibling was erased"))?
                .class(),
            ys::DocumentClass::AccessibilityTree
        );
        Ok::<(), Box<dyn Error + Send + Sync>>(())
    }
    .await;
    server.shutdown().await?;
    result
}

#[tokio::test]
async fn send_with_preserves_the_typed_browser_resolution_error() -> TestResult {
    let mut policy = ys::Policy::default();
    policy.page.acquisitions = vec![ys::policy::Acquisition::Browser(BrowserMode::Headful)];
    let executor = RequestExecutor::new().with_browser(
        BrowserMode::Headful,
        browser_inputs(CaptureId::random(), BrowserMode::Headless)?,
    );
    let cancellation = CancellationToken::new();
    let response = ys::request::new("https://example.test/")
        .bind(&policy)
        .send_with(&executor, &cancellation)
        .await?;

    let failure = response
        .attempts()
        .first()
        .and_then(AttemptOutcome::failure)
        .ok_or_else(|| io::Error::other("browser resolution mismatch did not fail"))?;
    assert!(matches!(
        failure.resolution_error(),
        Some(PolicyResolutionError::BrowserSpec(
            BrowserCaptureSpecError::ModeMismatch
        ))
    ));
    Ok(())
}

#[tokio::test]
async fn archived_browser_request_crosses_process_boundary_with_dom_and_ax() -> TestResult {
    let server = InlinePageServer::start().await?;
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let reference = temporary.path().join("browser-request-run-ref.txt");
    let writer = run_archive_child(
        "internal::engine::integration_tests::policy_capture_browser::subprocess_browser_archive_writer",
        "write",
        &root,
        &reference,
        Some(server.url.clone()),
    )
    .await;
    server.shutdown().await?;
    writer?;
    run_archive_child(
        "internal::engine::integration_tests::policy_capture_browser::subprocess_browser_archive_reader",
        "read",
        &root,
        &reference,
        None,
    )
    .await
}

async fn run_archive_child(
    test_name: &str,
    role: &str,
    root: &Path,
    reference: &Path,
    target: Option<String>,
) -> TestResult {
    let executable = env::current_exe()?;
    let test_name = test_name.to_owned();
    let role = role.to_owned();
    let root = root.to_owned();
    let reference = reference.to_owned();
    let status = spawn_blocking(move || {
        let mut command = Command::new(executable);
        command
            .args(["--ignored", "--exact", &test_name, "--nocapture"])
            .env(ARCHIVE_CHILD_ROLE, role)
            .env(ARCHIVE_CHILD_ROOT, root)
            .env(ARCHIVE_CHILD_REFERENCE, reference);
        if let Some(target) = target {
            command.env(ARCHIVE_CHILD_TARGET, target);
        }
        command.status()
    })
    .await??;
    if !status.success() {
        return Err(io::Error::other(format!("browser Archive child failed with {status}")).into());
    }
    Ok(())
}

#[tokio::test]
#[ignore = "invoked by archived_browser_request_crosses_process_boundary_with_dom_and_ax"]
async fn subprocess_browser_archive_writer() -> TestResult {
    require_archive_role("write")?;
    let root = required_archive_os(ARCHIVE_CHILD_ROOT)?;
    let reference = required_archive_os(ARCHIVE_CHILD_REFERENCE)?;
    let target = env::var(ARCHIVE_CHILD_TARGET)?;
    let archive = ys::Archive::open(root).await?;
    let mut policy = ys::Policy::default();
    policy.page.acquisitions = vec![
        ys::policy::Acquisition::Browser(BrowserMode::Headless).documents([
            ys::policy::DocumentRequest::ResponseDocument,
            ys::policy::DocumentRequest::RenderedDom,
            ys::policy::DocumentRequest::AccessibilityTree,
        ]),
    ];
    let archived = timeout(
        Duration::from_secs(120),
        ys::request::new(target)
            .bind(&policy)
            .send_archived(&archive),
    )
    .await??;
    fs::write(reference, archived.request_run_ref().to_string())?;
    Ok(())
}

#[tokio::test]
#[ignore = "invoked by archived_browser_request_crosses_process_boundary_with_dom_and_ax"]
async fn subprocess_browser_archive_reader() -> TestResult {
    require_archive_role("read")?;
    if env::var_os(ARCHIVE_CHILD_TARGET).is_some() {
        return Err(io::Error::other("offline browser Archive reader received a target").into());
    }
    let archive = ys::Archive::open(required_archive_os(ARCHIVE_CHILD_ROOT)?).await?;
    let reference: ys::RequestRunArchiveRef =
        fs::read_to_string(required_archive_os(ARCHIVE_CHILD_REFERENCE)?)?.parse()?;
    let run: ys::RequestRunRecord = archive.read(&reference).await?;
    let attempt = run
        .attempts()
        .first()
        .ok_or_else(|| io::Error::other("browser RequestRun omitted its attempt"))?;
    let ys::RequestAttemptOutcome::Completed {
        capture, documents, ..
    } = attempt.outcome()
    else {
        return Err(io::Error::other("browser RequestRun did not complete").into());
    };
    let capture: ys::CaptureBundle = archive.read(capture).await?;
    if documents.len() != 3 {
        return Err(io::Error::other("browser RequestRun lost a requested Document").into());
    }
    for record in documents {
        let ys::RequestDocumentOutcome::Produced { document: input } = record.outcome() else {
            return Err(io::Error::other("browser projection was not archived as Produced").into());
        };
        let document = ys::Document::from_archived(archive.read(input.document()).await?);
        let expected = match record.requested() {
            ys::policy::DocumentRequest::ResponseDocument => ys::DocumentClass::SourceHtml,
            ys::policy::DocumentRequest::RenderedDom => ys::DocumentClass::RenderedDom,
            ys::policy::DocumentRequest::AccessibilityTree => ys::DocumentClass::AccessibilityTree,
            ys::policy::DocumentRequest::NetworkTree => {
                return Err(io::Error::other("unexpected NetworkTree Document").into());
            }
        };
        if document.class() != expected {
            return Err(io::Error::other("archived browser Document changed class").into());
        }
        let source_artifact = input
            .source_artifact()
            .ok_or_else(|| io::Error::other("archived browser Document lost provenance"))?;
        let raw = capture
            .payload(source_artifact)
            .ok_or_else(|| io::Error::other("archived browser provenance payload is missing"))?;
        if matches!(
            record.requested(),
            ys::policy::DocumentRequest::RenderedDom
                | ys::policy::DocumentRequest::AccessibilityTree
        ) && document.bytes() == raw
        {
            return Err(io::Error::other(
                "normalized browser Document was replaced by raw artifact bytes",
            )
            .into());
        }
    }
    Ok(())
}

fn require_archive_role(expected: &str) -> TestResult {
    let observed = env::var(ARCHIVE_CHILD_ROLE)?;
    if observed != expected {
        return Err(io::Error::other(format!(
            "expected browser Archive role {expected}, observed {observed}"
        ))
        .into());
    }
    Ok(())
}

fn required_archive_os(name: &str) -> TestResult<OsString> {
    env::var_os(name).ok_or_else(|| {
        io::Error::other(format!("missing browser Archive environment {name}")).into()
    })
}
