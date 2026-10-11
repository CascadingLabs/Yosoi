#![allow(
    clippy::absolute_paths,
    clippy::missing_const_for_fn,
    clippy::semicolon_if_nothing_returned,
    clippy::unwrap_used,
    reason = "integration fixtures use validated constants and compact assertions"
)]

use std::{
    error::Error,
    io::{Read, Write},
    net::TcpListener,
    thread,
    time::Duration,
};

use crate::internal::direct_http::{
    AcceptedSourceFormat, AcceptedSourceFormats, ArtifactRequest, ByteLimit, CaptureDeadline,
    CaptureTermination, DirectHttpAcquisition, DirectHttpContentLimits, DirectHttpOutputSchemas,
    DirectHttpRedirectPolicy, DirectHttpTransportErrorKind, DirectHttpTransportProfile,
    HttpBrowserImpersonationProfile, HttpSessionUse, InterruptionInitiator, ObservationLimits,
    ObservationPolicy, ObservedContentLength, RequestedWebTarget, ResolvedDirectHttpCaptureSpec,
    SettlementPolicy, SourceRetentionPolicy, StructuredWebCaptureError,
    UnsupportedSourceFormatBehavior, UserAgent, WebAcquisitionStrategy, WebArtifactRequestSet,
    WebCaptureErrorContext, WebCaptureRequest, WebCaptureWire, execute_direct_http_at,
};
use crate::internal::types::{Schema, SchemaId, SchemaVersion};
use chrono::{DateTime, Utc};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener as AsyncTcpListener,
    sync::oneshot,
    time::timeout,
};
use tokio_util::sync::CancellationToken;

fn named_schema(name: &str) -> Schema {
    Schema::new(
        SchemaId::new(name).unwrap(),
        SchemaVersion::try_from(1).unwrap(),
    )
}

fn spec(url: &str, timeout_us: u64) -> ResolvedDirectHttpCaptureSpec {
    spec_with(
        url,
        timeout_us,
        DirectHttpTransportProfile::Standard,
        HttpSessionUse::Isolated,
        DirectHttpRedirectPolicy::Disabled,
    )
}

fn spec_with(
    url: &str,
    timeout_us: u64,
    profile: DirectHttpTransportProfile,
    session: HttpSessionUse,
    redirects: DirectHttpRedirectPolicy,
) -> ResolvedDirectHttpCaptureSpec {
    spec_with_user_agent(url, timeout_us, profile, session, redirects, None)
}

fn spec_with_user_agent(
    url: &str,
    timeout_us: u64,
    profile: DirectHttpTransportProfile,
    session: HttpSessionUse,
    redirects: DirectHttpRedirectPolicy,
    user_agent: Option<UserAgent>,
) -> ResolvedDirectHttpCaptureSpec {
    let bytes = std::fs::read(format!(
        "{}/src/internal/direct_http/integration_tests/fixtures/web-capture/complete-v1.json",
        env!("CARGO_MANIFEST_DIR")
    ))
    .unwrap();
    let capture = WebCaptureWire::from_json(&bytes).unwrap();
    let mut direct_http = DirectHttpAcquisition::new(profile, session);
    if let Some(user_agent) = user_agent {
        direct_http = direct_http.with_user_agent(user_agent);
    }
    let request = WebCaptureRequest::new(
        capture.acquisition().request().capture_id(),
        RequestedWebTarget::parse(url).unwrap(),
        WebAcquisitionStrategy::DirectHttp(direct_http),
    );
    let artifacts = WebArtifactRequestSet::new(
        ArtifactRequest::Required,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
        ArtifactRequest::NotRequested,
    );
    let limit = ByteLimit::try_from(1_000_000_u64).unwrap();
    let schema = Schema::new(
        SchemaId::new("com.cascadinglabs.yosoi.web-source").unwrap(),
        SchemaVersion::try_from(1).unwrap(),
    );
    ResolvedDirectHttpCaptureSpec::new(
        request,
        artifacts,
        ObservationPolicy::new(
            ObservationLimits::new(CaptureDeadline::try_from(timeout_us).unwrap(), None, None),
            SettlementPolicy::Disabled,
        ),
        DirectHttpContentLimits::new(limit, limit, limit),
        redirects,
        AcceptedSourceFormats::new([AcceptedSourceFormat::Html]).unwrap(),
        UnsupportedSourceFormatBehavior::RetainAndReport,
        SourceRetentionPolicy::Representation,
        crate::internal::direct_http::wreq_adapter_producer().unwrap(),
        capture
            .acquisition()
            .receipt()
            .receipt()
            .operation()
            .clone(),
        DirectHttpOutputSchemas::new(
            schema,
            named_schema("com.cascadinglabs.yosoi.transport-source-representation"),
            None,
            None,
        ),
    )
    .unwrap()
}

async fn user_agent_fixture() -> Result<
    (
        String,
        oneshot::Receiver<Vec<u8>>,
        tokio::task::JoinHandle<Result<(), std::io::Error>>,
    ),
    std::io::Error,
> {
    let listener = AsyncTcpListener::bind("127.0.0.1:0").await?;
    let address = listener.local_addr()?;
    let (request_sender, request_receiver) = oneshot::channel();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await?;
        let mut request = Vec::new();
        let mut byte = [0_u8; 1];
        loop {
            if stream.read(&mut byte).await? == 0 {
                return Err(std::io::Error::new(
                    std::io::ErrorKind::UnexpectedEof,
                    "HTTP client closed before completing request headers",
                ));
            }
            request.extend_from_slice(&byte);
            if request.ends_with(b"\r\n\r\n") {
                break;
            }
        }
        let _ = request_sender.send(request);
        stream
            .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
            .await?;
        Ok::<(), std::io::Error>(())
    });
    Ok((format!("http://{address}/agent"), request_receiver, server))
}

fn serve(response: &'static [u8], delay: Duration) -> String {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    thread::spawn(move || {
        if let Ok((mut stream, _)) = listener.accept() {
            let mut request = [0_u8; 1024];
            let _ = stream.read(&mut request);
            thread::sleep(delay);
            let _ = stream.write_all(response);
        }
    });
    format!("http://{address}/path?signature=SECRET")
}

fn wall_clock() -> DateTime<Utc> {
    DateTime::from_timestamp(1_700_000_000, 0).unwrap()
}

#[tokio::test]
async fn success_retains_unconsumed_response_and_bounded_head() {
    let url = serve(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 5\r\nSet-Cookie: secret=yes\r\n\r\nhello", Duration::ZERO);
    let pending = execute_direct_http_at(
        spec(&url, 2_000_000),
        &CancellationToken::new(),
        wall_clock(),
    )
    .await
    .unwrap();
    assert_eq!(pending.facts().status(), 200);
    assert_eq!(
        pending.facts().content_length(),
        &ObservedContentLength::Value(5)
    );
    let debug = format!("{pending:?}");
    assert!(!debug.contains("SECRET") && !debug.contains("secret=yes"));
    let deadline = pending.deadline();
    let (response, _, _, resolution, lifecycle, _, boundary) = pending.into_parts();
    assert_eq!(
        tokio::time::Instant::from_std(boundary.deadline()),
        deadline
    );
    assert!(resolution.final_url().as_observed().is_some());
    assert!(lifecycle.termination().is_none());
    assert_eq!(response.content_length(), Some(5));
}

#[tokio::test]
async fn production_client_preserves_content_coded_body_bytes() {
    for encoding in ["gzip", "br", "deflate", "zstd"] {
        let body = [0x00, 0xff, 0x1f, 0x8b, 0x42, 0x00];
        let response = format!(
            "HTTP/1.1 200 OK\r\nContent-Encoding: {encoding}\r\nContent-Length: {}\r\n\r\n",
            body.len()
        );
        let mut wire = response.into_bytes();
        wire.extend_from_slice(&body);
        let leaked: &'static [u8] = Box::leak(wire.into_boxed_slice());
        let url = serve(leaked, Duration::ZERO);
        let pending = execute_direct_http_at(
            spec(&url, 2_000_000),
            &CancellationToken::new(),
            wall_clock(),
        )
        .await
        .unwrap();
        let deadline = pending.deadline();
        let (response, _, _, resolution, lifecycle, _, boundary) = pending.into_parts();
        assert_eq!(
            tokio::time::Instant::from_std(boundary.deadline()),
            deadline
        );
        assert!(resolution.final_url().as_observed().is_some());
        assert!(lifecycle.termination().is_none());
        assert_eq!(response.bytes().await.unwrap().as_ref(), body);
    }
}

#[tokio::test]
async fn redirect_is_not_followed_and_location_is_not_exposed() {
    let url = serve(b"HTTP/1.1 302 Found\r\nLocation: https://example.invalid/?token=SECRET\r\nContent-Length: 0\r\n\r\n", Duration::ZERO);
    let pending = execute_direct_http_at(
        spec(&url, 2_000_000),
        &CancellationToken::new(),
        wall_clock(),
    )
    .await
    .unwrap();
    assert_eq!(pending.facts().status(), 302);
    assert!(!format!("{pending:?}").contains("SECRET"));
}

#[tokio::test]
async fn cancellation_stops_and_retains_lifecycle() {
    let token = CancellationToken::new();
    token.cancel();
    let failure = execute_direct_http_at(
        spec("http://127.0.0.1:9/?secret=VALUE", 2_000_000),
        &token,
        wall_clock(),
    )
    .await
    .unwrap_err();
    assert_eq!(
        failure.error().kind(),
        DirectHttpTransportErrorKind::Cancelled
    );
    match failure.lifecycle().termination() {
        Some(CaptureTermination::Interrupted(evidence)) => {
            assert_eq!(evidence.initiator(), InterruptionInitiator::Caller)
        }
        other => panic!("unexpected termination: {other:?}"),
    }
    assert!(!format!("{failure:?}").contains("VALUE"));
}

#[tokio::test]
async fn timeout_stops_at_deadline() {
    let url = serve(
        b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n",
        Duration::from_millis(100),
    );
    let failure =
        execute_direct_http_at(spec(&url, 10_000), &CancellationToken::new(), wall_clock())
            .await
            .unwrap_err();
    assert_eq!(
        failure.error().kind(),
        DirectHttpTransportErrorKind::Timeout
    );
    assert!(matches!(
        failure.lifecycle().termination(),
        Some(CaptureTermination::DeadlineReached { .. })
    ));
}

#[tokio::test]
async fn connection_failure_retains_provider_source_chain() {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    drop(listener);
    let failure = execute_direct_http_at(
        spec(&format!("http://{address}/?token=SECRET"), 500_000),
        &CancellationToken::new(),
        wall_clock(),
    )
    .await
    .unwrap_err();
    assert_eq!(
        failure.error().kind(),
        DirectHttpTransportErrorKind::Connect
    );
    assert!(failure.error().source().is_some());
    let display = failure.to_string();
    let debug = format!("{failure:?}");
    assert!(!display.contains("SECRET") && !debug.contains("SECRET"));
    assert!(
        matches!(failure.lifecycle().termination(), Some(CaptureTermination::Interrupted(e)) if e.initiator() == InterruptionInitiator::Provider)
    );
    let (response, resolution, _spec, lifecycle, error, termination_failure) = failure.into_parts();
    assert!(response.is_none());
    assert!(resolution.is_none());
    assert!(lifecycle.termination().is_some());
    assert!(termination_failure.is_none());
    let summary = error
        .at(WebCaptureErrorContext::new("acquisition.direct_http"))
        .summary();
    let structured = serde_json::to_string(&summary).unwrap();
    assert!(!structured.contains("SECRET"));
}

#[tokio::test]
async fn dns_failure_is_classified_and_redacted() {
    let failure = execute_direct_http_at(
        spec(
            "http://cas-302-does-not-exist.invalid/?token=SECRET",
            2_000_000,
        ),
        &CancellationToken::new(),
        wall_clock(),
    )
    .await
    .unwrap_err();
    assert_eq!(failure.error().kind(), DirectHttpTransportErrorKind::Dns);
    assert_eq!(
        failure.error().code().as_str(),
        "web_capture.direct_http.dns"
    );
    assert!(failure.error().source().is_some());
    assert!(!format!("{failure:?}").contains("SECRET"));
    assert!(failure.lifecycle().termination().is_some());
}

#[tokio::test]
async fn plaintext_on_https_is_a_redacted_connection_failure() {
    let url = serve(b"not tls and token=SECRET", Duration::ZERO).replace("http://", "https://");
    let failure = execute_direct_http_at(
        spec(&url, 2_000_000),
        &CancellationToken::new(),
        wall_clock(),
    )
    .await
    .unwrap_err();
    assert_eq!(
        failure.error().kind(),
        DirectHttpTransportErrorKind::Connect
    );
    assert_eq!(
        failure.error().code().as_str(),
        "web_capture.direct_http.connect"
    );
    assert!(failure.error().source().is_some());
    assert!(!format!("{failure:?}").contains("SECRET"));
    assert!(failure.lifecycle().termination().is_some());
}

#[tokio::test]
async fn malformed_local_protocol_is_classified_and_stopped() {
    let url = serve(b"definitely not HTTP\r\nSECRET", Duration::ZERO);
    let failure = execute_direct_http_at(
        spec(&url, 2_000_000),
        &CancellationToken::new(),
        wall_clock(),
    )
    .await
    .unwrap_err();
    assert_eq!(
        failure.error().kind(),
        DirectHttpTransportErrorKind::Protocol
    );
    assert!(failure.error().source().is_some());
    assert!(failure.lifecycle().termination().is_some());
}

#[tokio::test]
async fn unsupported_profile_and_session_return_typed_stopped_failures() {
    let cases = [
        (
            DirectHttpTransportProfile::BrowserImpersonation(
                HttpBrowserImpersonationProfile::new("safari26").unwrap(),
            ),
            HttpSessionUse::Isolated,
            DirectHttpRedirectPolicy::Disabled,
            DirectHttpTransportErrorKind::UnsupportedProfile,
        ),
        (
            DirectHttpTransportProfile::Standard,
            HttpSessionUse::RuntimeProvided,
            DirectHttpRedirectPolicy::Disabled,
            DirectHttpTransportErrorKind::UnsupportedSession,
        ),
    ];
    for (profile, session, redirects, expected) in cases {
        let failure = execute_direct_http_at(
            spec_with("http://127.0.0.1:9/", 500_000, profile, session, redirects),
            &CancellationToken::new(),
            wall_clock(),
        )
        .await
        .unwrap_err();
        assert_eq!(failure.error().kind(), expected);
        assert!(matches!(
            failure.lifecycle().termination(),
            Some(CaptureTermination::Interrupted(evidence))
                if evidence.initiator() == InterruptionInitiator::Provider
        ));
    }
}

#[tokio::test]
async fn explicit_user_agent_is_sent_and_recorded_as_http_environment() {
    let (url, request, server) = user_agent_fixture().await.unwrap();
    let user_agent = UserAgent::new("YosoiMap/1.0 (+https://example.test/bot)").unwrap();
    let pending = execute_direct_http_at(
        spec_with_user_agent(
            &url,
            2_000_000,
            DirectHttpTransportProfile::Standard,
            HttpSessionUse::Isolated,
            DirectHttpRedirectPolicy::Disabled,
            Some(user_agent.clone()),
        ),
        &CancellationToken::new(),
        wall_clock(),
    )
    .await
    .unwrap();
    let request = timeout(Duration::from_secs(2), request)
        .await
        .unwrap()
        .unwrap();
    server.await.unwrap().unwrap();

    let request = String::from_utf8_lossy(&request).to_ascii_lowercase();
    let expected_header =
        format!("\r\nuser-agent: {}\r\n", user_agent.as_str()).to_ascii_lowercase();
    assert!(request.contains(&expected_header));
    assert_eq!(request.matches("\r\nuser-agent:").count(), 1);
    assert!(matches!(
        pending.identity().environment(),
        crate::internal::direct_http::CaptureEnvironment::Http(environment)
            if environment.user_agent().as_known() == Some(&user_agent)
    ));
}
