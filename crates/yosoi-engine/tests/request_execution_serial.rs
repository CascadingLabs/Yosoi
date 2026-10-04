#![cfg(feature = "browser")]
#![allow(clippy::panic_in_result_fn)]

#[path = "../../yosoi-web-capture-direct-http/tests/support/direct_http_fixture.rs"]
mod fixture;

use std::{error::Error, io, sync::Arc, time::Duration};

use fixture::{FixtureService, Protocol, Response as FixtureResponse, ResponseControl};
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;
use yosoi_engine::policy::prelude::{Browser, DirectHttp, Headful, Headless};
use yosoi_engine::prelude as ys;
use yosoi_engine::{
    AttemptDiagnostic, AttemptOutcome, AttemptTransportOutcome, NotStartedReason,
    ResponseTermination,
};
use yosoi_web_capture::{CaptureTermination, InterruptionInitiator};

type TestResult<T = ()> = Result<T, Box<dyn Error + Send + Sync>>;

#[tokio::test]
async fn standard_fan_out_does_not_start_browser_before_direct_http_finishes() -> TestResult {
    let control = Arc::new(ResponseControl {
        hold_before_head: true,
        ..ResponseControl::default()
    });
    let mut fixture_response = FixtureResponse::bytes(
        200,
        Some("text/html; charset=utf-8"),
        b"<!doctype html><main>serial fan-out</main>",
    );
    fixture_response.control = Some(control.clone());
    let service =
        FixtureService::start(Protocol::Http, [("/serial".to_owned(), fixture_response)]).await;

    let mut policy = ys::Policy::default();
    policy.page.acquisitions = vec![DirectHttp, Browser(Headless)];
    let target = service.url("/serial");
    let task = tokio::spawn(async move { ys::request::new(target).bind(&policy).send().await });

    timeout(Duration::from_secs(10), control.requested.wait()).await?;
    assert_eq!(
        service.requests().await.len(),
        1,
        "the browser attempt started while Direct HTTP was still held"
    );
    assert!(
        timeout(Duration::from_secs(2), control.requested.wait())
            .await
            .is_err(),
        "a second acquisition reached the server before Direct HTTP was released"
    );

    // Both acquisitions request the same route. Signals are durable, so one
    // releases the held Direct HTTP response and one is ready for Chromium.
    control.allow_head.signal();
    control.allow_head.signal();
    let response = timeout(Duration::from_secs(180), task)
        .await?
        .map_err(|error| io::Error::other(error.to_string()))??;
    let requests = service.requests().await;
    service.shutdown().await;

    assert_eq!(response.termination(), ResponseTermination::Completed);
    let [direct, browser] = response.attempts() else {
        return Err(io::Error::other("serial response lost an authored attempt").into());
    };
    assert!(matches!(direct, AttemptOutcome::Completed(_)));
    assert!(matches!(browser, AttemptOutcome::Completed(_)));
    assert!(requests.len() >= 2);
    Ok(())
}

#[tokio::test]
async fn standard_browser_cancellation_stops_the_active_attempt_and_skips_headful() -> TestResult {
    let control = Arc::new(ResponseControl {
        hold_before_head: true,
        ..ResponseControl::default()
    });
    let mut fixture_response = FixtureResponse::bytes(
        200,
        Some("text/html; charset=utf-8"),
        b"<!doctype html><main>cancel browser</main>",
    );
    fixture_response.control = Some(control.clone());
    let service = FixtureService::start(
        Protocol::Http,
        [("/cancel-browser".to_owned(), fixture_response)],
    )
    .await;

    let mut policy = ys::Policy::default();
    policy.page.acquisitions = vec![Browser(Headless), Browser(Headful)];
    let cancellation = CancellationToken::new();
    let task_cancellation = cancellation.clone();
    let target = service.url("/cancel-browser");
    let task = tokio::spawn(async move {
        ys::request::new(target)
            .bind(&policy)
            .send_cancellable(&task_cancellation)
            .await
    });

    timeout(Duration::from_secs(30), control.requested.wait()).await?;
    cancellation.cancel();
    let response = timeout(Duration::from_secs(180), task)
        .await?
        .map_err(|error| io::Error::other(error.to_string()))??;
    let requests = service.requests().await;
    service.shutdown().await;

    assert_eq!(response.termination(), ResponseTermination::Cancelled);
    let [headless, headful] = response.attempts() else {
        return Err(io::Error::other("cancelled response lost an authored attempt").into());
    };
    if let Some(result) = headless.result() {
        assert!(matches!(
            result.capture_facts().observation().termination(),
            CaptureTermination::Interrupted(evidence)
                if evidence.initiator() == InterruptionInitiator::Caller
        ));
        assert!(matches!(
            result.transport(),
            AttemptTransportOutcome::Browser {
                cleanup: ys::CleanupState::Complete,
                ..
            }
        ));
    } else {
        let failure = headless
            .failure()
            .ok_or_else(|| io::Error::other("headless cancellation had no outcome"))?;
        assert_eq!(failure.diagnostic(), AttemptDiagnostic::BrowserCancelled);
        if let Some(facts) = failure.capture_failure_facts() {
            assert_ne!(facts.browser_cleanup(), Some(ys::CleanupState::Failed));
        }
    }
    assert_eq!(
        headful
            .not_started()
            .ok_or_else(|| io::Error::other("headful attempt started after cancellation"))?
            .reason(),
        NotStartedReason::Cancelled
    );
    assert_eq!(requests.len(), 1);
    Ok(())
}

#[tokio::test]
async fn browser_response_document_retains_non_success_http_status() -> TestResult {
    let service = FixtureService::start(
        Protocol::Http,
        [(
            "/browser-not-found".to_owned(),
            FixtureResponse::bytes(
                404,
                Some("text/html; charset=utf-8"),
                b"<!doctype html><main>browser 404</main>",
            ),
        )],
    )
    .await;
    let mut policy = ys::Policy::default();
    policy.page.acquisitions = vec![Browser(Headless)];
    let response = ys::request::new(service.url("/browser-not-found"))
        .bind(&policy)
        .send()
        .await?;
    service.shutdown().await;

    let attempt = response
        .attempts()
        .first()
        .ok_or_else(|| io::Error::other("browser response has no attempt"))?;
    assert_eq!(attempt.status(), Some(404));
    let document = attempt
        .result()
        .and_then(|result| result.documents().first())
        .and_then(|outcome| outcome.outcome().document())
        .ok_or_else(|| io::Error::other("browser 404 response document is missing"))?;
    assert_eq!(document.class(), ys::DocumentClass::SourceHtml);
    Ok(())
}
