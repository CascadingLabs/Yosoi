#[path = "../../yosoi-web-capture-direct-http/tests/support/direct_http_fixture.rs"]
mod fixture;

use std::{error::Error, fs, io, str};

use fixture::{FixtureService, Protocol, Response as FixtureResponse};
use tempfile::tempdir;
use tokio_util::sync::CancellationToken;
use yosoi_engine::prelude as ys;
use yosoi_engine::{
    RequestAttemptOutcome, RequestDocumentOutcome, RequestNotStartedReason, RequestRunTermination,
};

type TestResult<T = ()> = Result<T, Box<dyn Error + Send + Sync>>;

#[tokio::test]
async fn archived_direct_http_request_reopens_policy_run_and_capture() -> TestResult {
    const PATH_SENTINEL: &str = "cas460-archive-path-sentinel";
    const QUERY_SENTINEL: &str = "cas460-query-sentinel";
    let route = format!("/{PATH_SENTINEL}?token={QUERY_SENTINEL}");
    let service = FixtureService::start(
        Protocol::Http,
        [(
            route.clone(),
            FixtureResponse::bytes(
                200,
                Some("text/html; charset=utf-8"),
                b"<!doctype html><main>archived request</main>",
            ),
        )],
    )
    .await;
    let temporary = tempdir()?;
    let archive = ys::Archive::open(temporary.path().join(".yosoi")).await?;

    let archived_result = ys::request::new(service.url(&route))
        .send_archived(&archive)
        .await;
    let requests = service.requests().await;
    service.shutdown().await;
    let archived = archived_result?;
    if requests.len() != 1 {
        return Err(
            io::Error::other("archived request did not perform exactly one request").into(),
        );
    }

    let _: ys::Policy = archive.read(archived.policy_ref()).await?;
    let run: ys::RequestRunRecord = archive.read(archived.request_run_ref()).await?;
    if run.request_id() != archived.response().request_id().activity_id() {
        return Err(io::Error::other("RequestRun identity differs from the response").into());
    }
    let attempt = run
        .attempts()
        .first()
        .ok_or_else(|| io::Error::other("RequestRun is missing its Direct HTTP attempt"))?;
    let RequestAttemptOutcome::Completed {
        capture,
        response_status,
        documents,
    } = attempt.outcome()
    else {
        return Err(io::Error::other("archived Direct HTTP attempt did not complete").into());
    };
    if *response_status != Some(200) || documents.len() != 1 {
        return Err(io::Error::other("completed attempt lost response or Document facts").into());
    }
    let document_outcome = documents
        .first()
        .ok_or_else(|| io::Error::other("completed attempt omitted its Document outcome"))?;
    let RequestDocumentOutcome::Produced { document } = document_outcome.outcome() else {
        return Err(io::Error::other("response Document was not archived as produced").into());
    };
    let reopened_document = ys::Document::from_archived(archive.read(document.document()).await?);
    if reopened_document.class() != ys::DocumentClass::SourceHtml
        || !str::from_utf8(reopened_document.bytes())?.contains("archived request")
    {
        return Err(io::Error::other("archived Document changed across reopen").into());
    }
    let document = documents
        .first()
        .ok_or_else(|| io::Error::other("completed attempt lost its requested document"))?;
    if document.requested() != ys::policy::DocumentRequest::ResponseDocument {
        return Err(io::Error::other("completed attempt reordered its requested document").into());
    }
    if capture.capture_id() != attempt.capture_id() {
        return Err(io::Error::other("completed attempt references another CaptureId").into());
    }
    let reopened_capture: ys::CaptureBundle = archive.read(capture).await?;
    if reopened_capture.capture().id() != attempt.capture_id() {
        return Err(io::Error::other("Capture reference reopened another capture").into());
    }

    let serialized = serde_json::to_string(&run)?;
    if serialized.contains(PATH_SENTINEL) || serialized.contains(QUERY_SENTINEL) {
        return Err(io::Error::other("RequestRun retained target path or query data").into());
    }
    if !serialized.contains(run.target_origin().as_str()) {
        return Err(io::Error::other("RequestRun omitted its origin-only target").into());
    }
    Ok(())
}

#[tokio::test]
async fn pre_cancelled_archived_request_writes_policy_and_run_without_capture_or_io() -> TestResult
{
    let service = FixtureService::start(
        Protocol::Http,
        [(
            "/unused".to_owned(),
            FixtureResponse::bytes(200, Some("text/plain"), b"unused"),
        )],
    )
    .await;
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let archive = ys::Archive::open(&root).await?;
    let cancellation = CancellationToken::new();
    cancellation.cancel();

    let archived_result = ys::request::new(service.url("/unused"))
        .send_archived_cancellable(&archive, &cancellation)
        .await;
    let requests = service.requests().await;
    service.shutdown().await;
    let archived = archived_result?;
    if !requests.is_empty() {
        return Err(io::Error::other("pre-cancelled archived request performed I/O").into());
    }

    let _: ys::Policy = archive.read(archived.policy_ref()).await?;
    let run: ys::RequestRunRecord = archive.read(archived.request_run_ref()).await?;
    if run.termination() != RequestRunTermination::Cancelled {
        return Err(io::Error::other("pre-cancelled RequestRun lost cancellation").into());
    }
    let attempt = run
        .attempts()
        .first()
        .ok_or_else(|| io::Error::other("pre-cancelled RequestRun is missing its attempt"))?;
    if !matches!(
        attempt.outcome(),
        RequestAttemptOutcome::NotStarted {
            reason: RequestNotStartedReason::Cancelled
        }
    ) {
        return Err(
            io::Error::other("pre-cancelled attempt was not archived as NotStarted").into(),
        );
    }
    if root.join("archive/v1/records/capture").exists() {
        return Err(io::Error::other("pre-cancelled request published a Capture record").into());
    }
    Ok(())
}

#[tokio::test]
async fn document_publication_failure_returns_committed_policy_and_capture() -> TestResult {
    let service = FixtureService::start(
        Protocol::Http,
        [(
            "/document-failure".to_owned(),
            FixtureResponse::bytes(
                200,
                Some("text/html; charset=utf-8"),
                b"<!doctype html><main>committed capture</main>",
            ),
        )],
    )
    .await;
    let temporary = tempdir()?;
    let archive = ys::Archive::open(temporary.path().join(".yosoi")).await?;
    fs::write(archive.format_root().join("documents"), b"block-directory")?;

    let result = ys::request::new(service.url("/document-failure"))
        .send_archived(&archive)
        .await;
    let request_count = service.requests().await.len();
    service.shutdown().await;
    let ys::ArchivedRequestError::DocumentPublication { progress, .. } =
        result.err().ok_or_else(|| {
            io::Error::other("Document publication failure unexpectedly returned success")
        })?
    else {
        return Err(io::Error::other("Document failure returned another error variant").into());
    };
    if request_count != 1 || progress.captures().len() != 1 {
        return Err(io::Error::other("publication progress lost the committed Capture").into());
    }
    let _: ys::Policy = archive.read(progress.policy_ref()).await?;
    let capture_progress = progress
        .captures()
        .first()
        .ok_or_else(|| io::Error::other("publication progress omitted its Capture"))?;
    let _: ys::CaptureBundle = archive.read(capture_progress.capture_ref()).await?;
    if !capture_progress.document_refs().is_empty() {
        return Err(io::Error::other("failed Document was reported as committed").into());
    }
    Ok(())
}
