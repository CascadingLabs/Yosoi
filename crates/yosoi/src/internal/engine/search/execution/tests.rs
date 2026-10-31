#![expect(
    clippy::panic_in_result_fn,
    reason = "assertions intentionally report bounded execution test failures"
)]
use std::{collections::HashMap, error::Error, io, iter, sync::Arc, time::Duration};

use super::provider::should_attempt_bing_recovery;
#[cfg(not(feature = "browser"))]
use crate::internal::engine::search::new as new_search;
use crate::internal::engine::{
    request::execution::AttemptDiagnostic,
    search::{
        ProviderResult, SearchAttemptDiagnostic, SearchIssue, SearchIssueKind, SearchProfileFacts,
    },
};
use crate::internal::policy::Policy;
use crate::internal::policy::policy::{
    AcquisitionKind, ProfileSelectionKind, ProviderDefaultsStatus, search::Provider,
};
use base64::{Engine as _, engine::general_purpose::URL_SAFE_NO_PAD};
use tokio_util::sync::CancellationToken;

use tokio::{
    net::TcpStream,
    sync::{Mutex, mpsc, oneshot},
    task::JoinHandle,
    time::{Instant, timeout},
};

fn synthetic_bing_row(destination: &str, title: &str, snippet: &str) -> String {
    let encoded = URL_SAFE_NO_PAD.encode(destination.as_bytes());
    format!(
        r#"<li class="b_algo"><h2><a href="https://www.bing.com/ck/a?u=a1{encoded}">{title}</a></h2><div class="b_caption"><p class="b_lineclamp2">{snippet}</p></div></li>"#
    )
}

async fn serve_loopback_bodies(
    bodies: Vec<Vec<u8>>,
) -> Result<(String, JoinHandle<Result<(), io::Error>>), Box<dyn Error>> {
    serve_loopback_responses(bodies.into_iter().map(|body| (200, body)).collect()).await
}

async fn serve_loopback_responses(
    responses: Vec<(u16, Vec<u8>)>,
) -> Result<(String, JoinHandle<Result<(), io::Error>>), Box<dyn Error>> {
    use tokio::{io::AsyncReadExt as _, io::AsyncWriteExt as _, net::TcpListener};

    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let address = listener.local_addr()?;
    let server = tokio::spawn(async move {
        for (status, body) in responses {
            let (mut socket, _) = listener.accept().await?;
            let mut header = Vec::new();
            while !header.ends_with(b"\r\n\r\n") {
                if header.len() >= 8_192 {
                    return Err(io::Error::other("fixture request header exceeded bound"));
                }
                header.push(socket.read_u8().await?);
            }
            let reason = match status {
                200 => "OK",
                403 => "Forbidden",
                429 => "Too Many Requests",
                _ => "Synthetic Status",
            };
            let response_head = format!(
                "HTTP/1.1 {status} {reason}\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                body.len()
            );
            socket.write_all(response_head.as_bytes()).await?;
            socket.write_all(&body).await?;
        }
        Ok::<(), io::Error>(())
    });
    Ok((format!("http://{address}"), server))
}

async fn serve_loopback_with_gated_second_response(
    original_body: Vec<u8>,
    recovery_body: Vec<u8>,
) -> Result<
    (
        String,
        oneshot::Receiver<()>,
        oneshot::Sender<()>,
        JoinHandle<Result<(), io::Error>>,
    ),
    Box<dyn Error>,
> {
    use tokio::{io::AsyncReadExt as _, io::AsyncWriteExt as _, net::TcpListener};

    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let address = listener.local_addr()?;
    let (started_tx, started_rx) = oneshot::channel();
    let (release_tx, release_rx) = oneshot::channel();
    let server = tokio::spawn(async move {
        let (mut original_socket, _) = listener.accept().await?;
        read_loopback_headers(&mut original_socket).await?;
        write_loopback_response(&mut original_socket, 200, &original_body).await?;

        let (mut recovery_socket, _) = listener.accept().await?;
        read_loopback_headers(&mut recovery_socket).await?;
        started_tx
            .send(())
            .map_err(|()| io::Error::other("recovery request start observer was dropped"))?;
        release_rx
            .await
            .map_err(|_| io::Error::other("recovery response gate was dropped"))?;
        // Cancellation may close the client socket before the gate opens.
        let _ = write_loopback_response(&mut recovery_socket, 200, &recovery_body).await;
        Ok::<(), io::Error>(())
    });
    Ok((format!("http://{address}"), started_rx, release_tx, server))
}

async fn read_loopback_headers(socket: &mut TcpStream) -> Result<(), io::Error> {
    use tokio::io::AsyncReadExt as _;

    let mut header = Vec::new();
    while !header.ends_with(b"\r\n\r\n") {
        if header.len() >= 8_192 {
            return Err(io::Error::other("fixture request header exceeded bound"));
        }
        header.push(socket.read_u8().await?);
    }
    Ok(())
}

async fn write_loopback_response(
    socket: &mut TcpStream,
    status: u16,
    body: &[u8],
) -> Result<(), io::Error> {
    use tokio::io::AsyncWriteExt as _;

    let reason = match status {
        200 => "OK",
        403 => "Forbidden",
        429 => "Too Many Requests",
        _ => "Synthetic Status",
    };
    let response_head = format!(
        "HTTP/1.1 {status} {reason}\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    );
    socket.write_all(response_head.as_bytes()).await?;
    socket.write_all(body).await
}

fn direct_http_profile(policy: &Policy) -> Result<SearchProfileFacts, Box<dyn Error>> {
    Ok(SearchProfileFacts {
        acquisition: Some(AcquisitionKind::DirectHttp),
        defaults_status: ProviderDefaultsStatus::Exact,
        defaults_version: None,
        effective_request_policy: Some(policy.effective_identity()?),
    })
}

use super::prepare::{is_supported_duckduckgo_acquisition, per_provider_output_quota};
use super::response::{search_attempt_diagnostic, search_failure_for_attempt};
use super::scheduler::{ScheduledJob, SchedulerStopReason, SchedulerTermination, run_scheduler};

async fn run_bing_recovery_fixture(
    recovery_body: Vec<u8>,
) -> Result<ProviderResult, Box<dyn Error>> {
    run_bing_recovery_case(generic_unknown_bing_body(), 200, recovery_body).await
}

async fn run_bing_recovery_case(
    original_body: Vec<u8>,
    recovery_status: u16,
    recovery_body: Vec<u8>,
) -> Result<ProviderResult, Box<dyn Error>> {
    run_bing_recovery_case_with_legacy_failure(original_body, recovery_status, recovery_body, false)
        .await
}

async fn run_bing_recovery_case_with_legacy_failure(
    original_body: Vec<u8>,
    recovery_status: u16,
    recovery_body: Vec<u8>,
    legacy_failure: bool,
) -> Result<ProviderResult, Box<dyn Error>> {
    use crate::internal::engine::{
        request,
        search::{ProviderOutcome, SearchFailure},
    };
    let (base_url, server) =
        serve_loopback_responses(vec![(200, original_body), (recovery_status, recovery_body)])
            .await?;
    let policy = Policy::default();
    let profile = direct_http_profile(&policy)?;
    let query = "history of cotton candy";
    let original_provider_target = super::super::target::provider_target(Provider::Bing, query)?;
    let original_response = request::new(format!("{base_url}/original"))
        .bind(&policy)
        .send()
        .await?;
    let mut result = super::response::provider_result_from_response(
        Provider::Bing,
        &policy,
        &original_provider_target,
        super::response::ProviderResponseLimits {
            results: 5,
            output_bytes: 1_048_576,
            capture_bytes: Some(1_048_576),
        },
        profile,
        &original_response,
    );
    if legacy_failure {
        result.outcome = ProviderOutcome::Failed(SearchFailure::QueryMismatch);
    }
    if !should_attempt_bing_recovery(
        Provider::Bing,
        ProfileSelectionKind::Current,
        &result.outcome,
        query,
        false,
    ) {
        return Err(
            io::Error::other("unknown Current Bing results should consider recovery").into(),
        );
    }
    let recovery_query = super::super::provider::bing::recovery_query(query)
        .ok_or_else(|| io::Error::other("history query should have a bounded candidate rewrite"))?;
    let recovery_provider_target =
        super::super::target::provider_target(Provider::Bing, &recovery_query)?;
    let recovery_request_target = format!("{base_url}/recovery");
    let result = super::provider::execute_bing_recovery(
        result,
        &policy,
        profile,
        &original_provider_target,
        query,
        &recovery_request_target,
        &recovery_provider_target,
        recovery_query,
        5,
        1_048_576,
        true,
        &CancellationToken::new(),
    )
    .await;
    timeout(Duration::from_secs(10), server).await???;
    Ok(result)
}

fn generic_unknown_bing_body() -> Vec<u8> {
    [
        synthetic_bing_row(
            "https://example.org/report-1",
            "Example Report One",
            "A general report summary.",
        ),
        synthetic_bing_row(
            "https://example.org/report-2",
            "Example Report Two",
            "A second general summary.",
        ),
        synthetic_bing_row(
            "https://example.org/report-3",
            "Example Report Three",
            "A third general summary.",
        ),
    ]
    .concat()
    .into_bytes()
}

fn intent_only_bing_body() -> Vec<u8> {
    [
        synthetic_bing_row(
            "https://history.google.com/",
            "Welcome to My Activity",
            "Explore search and browsing activity.",
        ),
        synthetic_bing_row(
            "https://www.history.com/",
            "History Topics",
            "History stories and topics.",
        ),
        synthetic_bing_row(
            "https://en.wikipedia.org/wiki/History",
            "History - Wikipedia",
            "History studies the human past.",
        ),
    ]
    .concat()
    .into_bytes()
}

fn assert_two_attempts_and_captures(
    result: &ProviderResult,
    original_provider_target: &str,
) -> Result<(), Box<dyn Error>> {
    use crate::internal::engine::search::SearchCaptureRetention;

    let attempts = result.attempts();
    let first = attempts
        .first()
        .ok_or_else(|| io::Error::other("initial request attempt is missing"))?;
    let second = attempts
        .get(1)
        .ok_or_else(|| io::Error::other("recovery request attempt is missing"))?;
    if attempts.len() != 2
        || first.request_id == second.request_id
        || first.capture_id == second.capture_id
    {
        return Err(
            io::Error::other("recovery must carry distinct request and capture IDs").into(),
        );
    }
    let captures = result.captures();
    if captures.len() != 2 {
        return Err(
            io::Error::other("both response documents should fit the capture quota").into(),
        );
    }
    for (capture, attempt) in captures.iter().zip([first, second]) {
        if capture.capture_id != attempt.capture_id
            || capture.request_id != attempt.request_id.to_string()
            || capture.original_provider_page_url != original_provider_target
            || attempt.capture_retention != SearchCaptureRetention::Retained
        {
            return Err(
                io::Error::other("recovery provenance or capture retention was lost").into(),
            );
        }
    }
    Ok(())
}

#[test]
fn only_current_bing_unknown_pages_with_clear_topic_loss_are_recovery_candidates()
-> Result<(), Box<dyn Error>> {
    use std::num::NonZeroU16;

    use crate::internal::engine::search::{
        FeatureCoverage, ProviderOutcome, SearchCoverage, SearchFailure, SearchHit, SearchPage,
        SearchResultUrl, WebCoverage,
    };

    let rank = NonZeroU16::MIN;
    let page = SearchPage::new(
        [
            "https://history.google.com/",
            "https://www.history.com/",
            "https://en.wikipedia.org/wiki/History",
        ]
        .into_iter()
        .map(|url| Ok(SearchHit::new(SearchResultUrl::parse(url)?, rank, rank)))
        .collect::<Result<Vec<_>, Box<dyn Error>>>()?,
        Vec::new(),
        SearchCoverage::new(WebCoverage::Partial, FeatureCoverage::NotCollected),
        vec![SearchIssue {
            placement_index: None,
            kind: SearchIssueKind::QueryRelevanceUnknown,
        }],
    );
    let outcome = ProviderOutcome::Results(page);
    assert!(should_attempt_bing_recovery(
        Provider::Bing,
        ProfileSelectionKind::Current,
        &outcome,
        "history of cotton candy",
        false,
    ));
    assert!(!should_attempt_bing_recovery(
        Provider::Bing,
        ProfileSelectionKind::Exact,
        &outcome,
        "history of cotton candy",
        false,
    ));
    assert!(!should_attempt_bing_recovery(
        Provider::Brave,
        ProfileSelectionKind::Current,
        &outcome,
        "history of cotton candy",
        false,
    ));
    assert!(!should_attempt_bing_recovery(
        Provider::Bing,
        ProfileSelectionKind::Current,
        &outcome,
        "history of cotton candy",
        true,
    ));
    for failure in [SearchFailure::RateLimited, SearchFailure::Challenge] {
        assert!(!should_attempt_bing_recovery(
            Provider::Bing,
            ProfileSelectionKind::Current,
            &ProviderOutcome::Failed(failure),
            "history of cotton candy",
            false,
        ));
    }
    assert!(should_attempt_bing_recovery(
        Provider::Bing,
        ProfileSelectionKind::Current,
        &ProviderOutcome::Failed(SearchFailure::QueryMismatch),
        "history of cotton candy",
        false,
    ));

    let rank = NonZeroU16::MIN;
    let cotton_only = SearchPage::new(
        [
            "https://en.wikipedia.org/wiki/Cotton",
            "https://example.org/cotton-fiber",
            "https://cottonon.com/US/",
        ]
        .into_iter()
        .map(|url| Ok(SearchHit::new(SearchResultUrl::parse(url)?, rank, rank)))
        .collect::<Result<Vec<_>, Box<dyn Error>>>()?,
        Vec::new(),
        SearchCoverage::new(WebCoverage::Partial, FeatureCoverage::NotCollected),
        vec![SearchIssue {
            placement_index: None,
            kind: SearchIssueKind::QueryRelevanceUnknown,
        }],
    );
    assert!(!should_attempt_bing_recovery(
        Provider::Bing,
        ProfileSelectionKind::Current,
        &ProviderOutcome::Results(cotton_only),
        "history of cotton candy",
        false,
    ));
    let sparse = SearchPage::new(
        vec![SearchHit::new(
            SearchResultUrl::parse("https://history.google.com/")?,
            rank,
            rank,
        )],
        Vec::new(),
        SearchCoverage::new(WebCoverage::Partial, FeatureCoverage::NotCollected),
        vec![SearchIssue {
            placement_index: None,
            kind: SearchIssueKind::QueryRelevanceUnknown,
        }],
    );
    assert!(!should_attempt_bing_recovery(
        Provider::Bing,
        ProfileSelectionKind::Current,
        &ProviderOutcome::Results(sparse),
        "history of cotton candy",
        false,
    ));
    assert!(!should_attempt_bing_recovery(
        Provider::Bing,
        ProfileSelectionKind::Current,
        &outcome,
        "intitle:\"cotton candy\" history",
        false,
    ));
    Ok(())
}

#[tokio::test]
async fn current_bing_recovery_executes_and_adopts_supported_result() -> Result<(), Box<dyn Error>>
{
    use crate::internal::engine::search::{ProviderOutcome, SearchIssueKind, WebCoverage};

    let recovery_body = [
        synthetic_bing_row(
            "https://example.org/cotton-candy-history",
            "Cotton Candy History",
            "A history of cotton candy and spun sugar.",
        ),
        synthetic_bing_row(
            "https://example.org/cotton-candy-origins",
            "Cotton Candy Origins",
            "The origins of cotton candy.",
        ),
        synthetic_bing_row(
            "https://example.org/cotton-candy-timeline",
            "Cotton Candy Timeline",
            "A timeline for cotton candy.",
        ),
    ]
    .concat()
    .into_bytes();
    let result = run_bing_recovery_fixture(recovery_body).await?;
    assert_eq!(result.recovery_query(), Some("cotton candy history"));
    let ProviderOutcome::Results(page) = result.outcome() else {
        return Err(io::Error::other("supported recovery should return results").into());
    };
    assert_eq!(
        page.hits().first().and_then(|hit| hit.title()),
        Some("Cotton Candy History")
    );
    assert_eq!(page.coverage().web(), WebCoverage::Partial);
    assert!(
        page.issues()
            .iter()
            .any(|issue| issue.kind == SearchIssueKind::QueryRelaxed)
    );
    assert!(
        !page
            .issues()
            .iter()
            .any(|issue| issue.kind == SearchIssueKind::QueryRelevanceUnknown)
    );
    assert_two_attempts_and_captures(
        &result,
        "https://www.bing.com/search?q=history+of+cotton+candy",
    )?;
    Ok(())
}

#[tokio::test]
async fn inconclusive_bing_recovery_keeps_original_partial_results() -> Result<(), Box<dyn Error>> {
    use crate::internal::engine::search::{ProviderOutcome, SearchIssueKind, WebCoverage};

    let recovery_body = [
        synthetic_bing_row(
            "https://en.wikipedia.org/wiki/Cotton",
            "Cotton - Wikipedia",
            "Cotton is a soft fiber.",
        ),
        synthetic_bing_row(
            "https://www.britannica.com/topic/cotton-fibre-and-plant",
            "Cotton Fiber and Plant",
            "Cotton is a plant fiber.",
        ),
        synthetic_bing_row(
            "https://cottonon.com/US/",
            "Cotton On clothing",
            "Shop cotton clothing.",
        ),
    ]
    .concat()
    .into_bytes();
    let result = run_bing_recovery_fixture(recovery_body).await?;
    assert_eq!(result.recovery_query(), Some("cotton candy history"));
    let ProviderOutcome::Results(page) = result.outcome() else {
        return Err(io::Error::other("inconclusive recovery should keep original results").into());
    };
    assert_eq!(
        page.hits().first().and_then(|hit| hit.title()),
        Some("Example Report One")
    );
    assert_eq!(page.coverage().web(), WebCoverage::Partial);
    assert!(
        page.issues()
            .iter()
            .any(|issue| issue.kind == SearchIssueKind::QueryRelevanceUnknown)
    );
    assert!(
        !page
            .issues()
            .iter()
            .any(|issue| issue.kind == SearchIssueKind::QueryRelaxed)
    );
    assert_two_attempts_and_captures(
        &result,
        "https://www.bing.com/search?q=history+of+cotton+candy",
    )?;
    Ok(())
}

#[tokio::test]
async fn recovery_rate_and_challenge_keep_original_results_but_fail_legacy_mismatch()
-> Result<(), Box<dyn Error>> {
    use crate::internal::engine::search::{ProviderOutcome, SearchFailure, SearchIssueKind};

    let blocked_body = b"<html><body>blocked response</body></html>".to_vec();
    for (status, failure) in [
        (429, SearchFailure::RateLimited),
        (403, SearchFailure::Challenge),
    ] {
        let partial =
            run_bing_recovery_case(generic_unknown_bing_body(), status, blocked_body.clone())
                .await?;
        let ProviderOutcome::Results(original_page) = partial.outcome() else {
            return Err(io::Error::other("blocked recovery replaced usable original hits").into());
        };
        assert!(
            original_page
                .issues()
                .iter()
                .any(|issue| issue.kind == SearchIssueKind::QueryRelevanceUnknown)
        );
        assert_eq!(
            partial
                .attempts()
                .get(1)
                .and_then(|attempt| attempt.http_status),
            Some(status)
        );
        assert_two_attempts_and_captures(
            &partial,
            "https://www.bing.com/search?q=history+of+cotton+candy",
        )?;

        let legacy = run_bing_recovery_case_with_legacy_failure(
            intent_only_bing_body(),
            status,
            blocked_body.clone(),
            true,
        )
        .await?;
        assert!(matches!(
            legacy.outcome(),
            ProviderOutcome::Failed(actual) if *actual == failure
        ));
        assert_eq!(
            legacy
                .attempts()
                .get(1)
                .and_then(|attempt| attempt.http_status),
            Some(status)
        );
        assert_two_attempts_and_captures(
            &legacy,
            "https://www.bing.com/search?q=history+of+cotton+candy",
        )?;
    }
    Ok(())
}

#[tokio::test]
async fn cancellation_during_recovery_keeps_original_partial_and_records_attempt()
-> Result<(), Box<dyn Error>> {
    use crate::internal::{
        engine::{
            request,
            search::{ProviderOutcome, SearchIssueKind, WebCoverage},
        },
        policy::Policy,
    };

    let recovery_body = [
        synthetic_bing_row(
            "https://example.org/cotton-candy-history",
            "Cotton Candy History",
            "A history of cotton candy.",
        ),
        synthetic_bing_row(
            "https://example.org/cotton-candy-origins",
            "Cotton Candy Origins",
            "The origins of cotton candy.",
        ),
        synthetic_bing_row(
            "https://example.org/cotton-candy-timeline",
            "Cotton Candy Timeline",
            "A timeline for cotton candy.",
        ),
    ]
    .concat()
    .into_bytes();
    let (base_url, recovery_started, release_recovery, server) =
        serve_loopback_with_gated_second_response(generic_unknown_bing_body(), recovery_body)
            .await?;
    let policy = Policy::default();
    let profile = direct_http_profile(&policy)?;
    let query = "history of cotton candy";
    let original_provider_target = super::super::target::provider_target(Provider::Bing, query)?;
    let original_response = request::new(format!("{base_url}/original"))
        .bind(&policy)
        .send()
        .await?;
    let original = super::response::provider_result_from_response(
        Provider::Bing,
        &policy,
        &original_provider_target,
        super::response::ProviderResponseLimits {
            results: 5,
            output_bytes: 1_048_576,
            capture_bytes: Some(1_048_576),
        },
        profile,
        &original_response,
    );
    let recovery_query = super::super::provider::bing::recovery_query(query)
        .ok_or_else(|| io::Error::other("history query should have a bounded candidate rewrite"))?;
    let recovery_provider_target =
        super::super::target::provider_target(Provider::Bing, &recovery_query)?;
    let recovery_request_target = format!("{base_url}/recovery");
    let cancellation = CancellationToken::new();
    let task_cancellation = cancellation.clone();
    let task = tokio::spawn(async move {
        super::provider::execute_bing_recovery(
            original,
            &policy,
            profile,
            &original_provider_target,
            query,
            &recovery_request_target,
            &recovery_provider_target,
            recovery_query,
            5,
            1_048_576,
            true,
            &task_cancellation,
        )
        .await
    });
    timeout(Duration::from_secs(10), recovery_started)
        .await
        .map_err(|_| io::Error::other("recovery Request did not start"))?
        .map_err(|_| io::Error::other("recovery start notification was dropped"))?;
    cancellation.cancel();
    let result = timeout(Duration::from_secs(10), task)
        .await
        .map_err(|_| io::Error::other("cancelled recovery did not finish"))??;
    release_recovery
        .send(())
        .map_err(|()| io::Error::other("recovery response gate was already closed"))?;
    timeout(Duration::from_secs(10), server)
        .await
        .map_err(|_| io::Error::other("gated response server did not finish"))???;

    assert!(cancellation.is_cancelled());
    assert_eq!(result.recovery_query(), Some("cotton candy history"));
    let ProviderOutcome::Results(page) = result.outcome() else {
        return Err(io::Error::other("cancellation replaced usable original results").into());
    };
    assert_eq!(page.coverage().web(), WebCoverage::Partial);
    assert!(
        page.issues()
            .iter()
            .any(|issue| { issue.kind == SearchIssueKind::QueryRelevanceUnknown })
    );
    assert!(
        !page
            .issues()
            .iter()
            .any(|issue| issue.kind == SearchIssueKind::QueryRelaxed)
    );
    let attempts = result.attempts();
    if attempts.len() != 2
        || attempts.get(1).is_some_and(|attempt| {
            attempt.terminal == super::super::RequestAttemptTerminal::Completed
        })
    {
        return Err(io::Error::other("cancelled recovery attempt status was not retained").into());
    }
    Ok(())
}

#[tokio::test]
async fn loopback_documents_have_bounded_opt_in_replay_evidence() -> Result<(), Box<dyn Error>> {
    use crate::internal::{
        engine::{
            request,
            search::{ProviderOutcome, SearchCaptureRetention, SearchIssueKind},
        },
        policy::Policy,
        web_capture::RequestedWebTarget,
    };
    use tokio::{
        io::{AsyncReadExt as _, AsyncWriteExt as _},
        net::TcpListener,
    };
    let body = include_bytes!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/src/internal/engine/tests/fixtures/search-diagnostics/bing-synthetic-original.html"
    ));
    let listener = TcpListener::bind("127.0.0.1:0").await?;
    let address = listener.local_addr()?;
    let server = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await?;
        let mut header = Vec::new();
        while !header.ends_with(b"\r\n\r\n") {
            if header.len() >= 8_192 {
                return Err(io::Error::other("fixture header exceeded bound"));
            }
            header.push(socket.read_u8().await?);
        }
        let head = format!(
            "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
            body.len()
        );
        socket.write_all(head.as_bytes()).await?;
        socket.write_all(body).await?;
        Ok::<(), io::Error>(())
    });
    let policy = Policy::default();
    let response = request::new(format!("http://{address}/synthetic"))
        .bind(&policy)
        .send()
        .await?;
    server.await??;
    let target =
        RequestedWebTarget::parse("https://www.bing.com/search?q=history+of+photosynthesis")?;
    let profile = super::super::SearchProfileFacts {
        acquisition: Some(AcquisitionKind::DirectHttp),
        defaults_status: ProviderDefaultsStatus::Exact,
        defaults_version: None,
        effective_request_policy: Some(policy.effective_identity()?),
    };
    for (limit, retention, expected_captures) in [
        (None, SearchCaptureRetention::Disabled, 0),
        (
            Some(body.len().saturating_sub(1)),
            SearchCaptureRetention::ByteLimit,
            0,
        ),
        (Some(body.len()), SearchCaptureRetention::Retained, 1),
    ] {
        let result = super::response::provider_result_from_response(
            Provider::Bing,
            &policy,
            &target,
            super::response::ProviderResponseLimits {
                results: 5,
                output_bytes: 1_048_576,
                capture_bytes: limit,
            },
            profile,
            &response,
        );
        let attempt = result.attempts().first().ok_or("missing attempt")?;
        assert_eq!(attempt.capture_retention, retention);
        assert_eq!(attempt.parser_diagnostic, None);
        let ProviderOutcome::Results(page) = result.outcome() else {
            return Err(io::Error::other("uncertain parser result should remain available").into());
        };
        assert!(
            page.issues()
                .iter()
                .any(|issue| { issue.kind == SearchIssueKind::QueryRelevanceUnknown })
        );
        assert_eq!(attempt.document_bytes, Some(u64::try_from(body.len())?));
        assert_eq!(result.captures().len(), expected_captures);
        for capture in result.captures() {
            let replayed = super::super::diagnostics::parse_document(
                capture.provider,
                &capture.document,
                &capture.replay_policy.policy(),
                &capture.provider_page_url,
                capture.replay_policy.result_limit,
                capture.replay_policy.output_limit,
            );
            assert_eq!(capture.observed.decision(), replayed.decision());
        }
    }
    Ok(())
}

#[tokio::test]
async fn unknown_current_bing_results_execute_one_recovery_request_and_adopt_supported_hits()
-> Result<(), Box<dyn Error>> {
    use crate::internal::engine::search::{ProviderOutcome, SearchIssueKind, WebCoverage};

    let recovery_body = [
        synthetic_bing_row(
            "https://example.org/cotton-candy-history",
            "Cotton Candy History",
            "A history of cotton candy and spun sugar.",
        ),
        synthetic_bing_row(
            "https://example.org/cotton-candy-origins",
            "Cotton Candy Origins",
            "The origins of cotton candy.",
        ),
        synthetic_bing_row(
            "https://example.org/cotton-candy-timeline",
            "Cotton Candy Timeline",
            "A timeline for cotton candy.",
        ),
    ]
    .concat()
    .into_bytes();
    let result = run_bing_recovery_fixture(recovery_body).await?;
    assert_eq!(result.recovery_query(), Some("cotton candy history"));
    let ProviderOutcome::Results(page) = result.outcome() else {
        return Err(io::Error::other("supported recovery should return results").into());
    };
    assert_eq!(
        page.hits().first().and_then(|hit| hit.title()),
        Some("Cotton Candy History")
    );
    assert_eq!(page.coverage().web(), WebCoverage::Partial);
    assert!(
        page.issues()
            .iter()
            .any(|issue| issue.kind == SearchIssueKind::QueryRelaxed)
    );
    assert!(
        !page
            .issues()
            .iter()
            .any(|issue| issue.kind == SearchIssueKind::QueryRelevanceUnknown)
    );
    assert_two_attempts_and_captures(
        &result,
        "https://www.bing.com/search?q=history+of+cotton+candy",
    )?;
    Ok(())
}

#[tokio::test]
async fn unknown_recovery_retains_original_partial_page_and_both_attempts()
-> Result<(), Box<dyn Error>> {
    use crate::internal::engine::search::{ProviderOutcome, SearchIssueKind, WebCoverage};

    let recovery_body = [
        synthetic_bing_row(
            "https://en.wikipedia.org/wiki/Cotton",
            "Cotton - Wikipedia",
            "Cotton is a soft fiber.",
        ),
        synthetic_bing_row(
            "https://www.britannica.com/topic/cotton-fibre-and-plant",
            "Cotton Fiber and Plant",
            "Cotton is a plant fiber.",
        ),
        synthetic_bing_row(
            "https://cottonon.com/US/",
            "Cotton On clothing",
            "Shop cotton clothing.",
        ),
    ]
    .concat()
    .into_bytes();
    let result = run_bing_recovery_fixture(recovery_body).await?;
    assert_eq!(result.recovery_query(), Some("cotton candy history"));
    let ProviderOutcome::Results(page) = result.outcome() else {
        return Err(
            io::Error::other("inconclusive recovery should retain original results").into(),
        );
    };
    assert_eq!(
        page.hits().first().and_then(|hit| hit.title()),
        Some("Example Report One")
    );
    assert_eq!(page.coverage().web(), WebCoverage::Partial);
    assert!(
        page.issues()
            .iter()
            .any(|issue| issue.kind == SearchIssueKind::QueryRelevanceUnknown)
    );
    assert!(
        !page
            .issues()
            .iter()
            .any(|issue| issue.kind == SearchIssueKind::QueryRelaxed)
    );
    assert_two_attempts_and_captures(
        &result,
        "https://www.bing.com/search?q=history+of+cotton+candy",
    )?;
    Ok(())
}

#[test]
fn provider_output_limit_is_reported_as_budget_exhausted() -> Result<(), Box<dyn Error>> {
    use crate::internal::{
        engine::Document,
        policy::{Policy, policy::search::Provider},
    };
    let document = Document::html(
        "synthetic-output-limit",
        include_bytes!(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/src/internal/engine/tests/fixtures/search-diagnostics/bing-synthetic-recovery.html"
        ))
        .to_vec(),
    )?;
    let parsed = super::super::parse_document(
        Provider::Bing,
        &document,
        &Policy::default(),
        "https://www.bing.com/search?q=photosynthesis",
        5,
        1,
    );
    assert_eq!(
        parsed.decision().failure,
        Some(super::super::SearchFailure::BudgetExhausted)
    );
    assert_eq!(
        parsed.parser_diagnostic,
        Some(super::super::SearchParserDiagnostic::OutputLimit)
    );
    Ok(())
}

#[test]
fn browser_capture_failure_is_transport_not_provider_markup() {
    let diagnostic = AttemptDiagnostic::BrowserCaptureFailed;
    assert_eq!(
        search_failure_for_attempt(diagnostic),
        super::SearchFailure::TransportFailure
    );
    assert_eq!(
        search_attempt_diagnostic(diagnostic),
        SearchAttemptDiagnostic::BrowserCaptureFailed
    );
}

#[test]
fn duckduckgo_requires_headless_browser_and_both_documents() {
    use crate::internal::policy::policy::{Acquisition, BrowserMode, DocumentRequest};

    let supported = Acquisition::Browser(BrowserMode::Headless).documents([
        DocumentRequest::ResponseDocument,
        DocumentRequest::RenderedDom,
    ]);
    assert!(is_supported_duckduckgo_acquisition(&supported));

    let source_only =
        Acquisition::Browser(BrowserMode::Headless).documents([DocumentRequest::ResponseDocument]);
    assert!(!is_supported_duckduckgo_acquisition(&source_only));

    let headful = Acquisition::Browser(BrowserMode::Headful).documents([
        DocumentRequest::ResponseDocument,
        DocumentRequest::RenderedDom,
    ]);
    assert!(!is_supported_duckduckgo_acquisition(&headful));
}

#[cfg(not(feature = "browser"))]
#[test]
fn browser_disabled_build_keeps_duckduckgo_in_unsupported_slot() -> Result<(), Box<dyn Error>> {
    use crate::internal::policy::policy::{
        Acquisition, AddressableByteLimit, BrowserMode, DocumentRequest, Page, Request,
        search::{Provider, ProviderRequestProfile, ProviderSelection, Search},
    };
    use crate::internal::policy::{Documents, Policy};

    let acquisition = Acquisition::Browser(BrowserMode::Headless).documents([
        DocumentRequest::ResponseDocument,
        DocumentRequest::RenderedDom,
    ]);
    let profile = ProviderRequestProfile::new(
        Page::new(vec![acquisition])?,
        Request::default(),
        Documents::default(),
    )?;
    let mut search = Search::default();
    search.providers = vec![ProviderSelection::exact(Provider::DuckDuckGo, profile)];
    let policy = Policy {
        search,
        ..Policy::default()
    };
    let prepared = new_search("bounded fixture query")?
        .bind(&policy)
        .prepare()?;
    let route = prepared
        .providers()
        .first()
        .ok_or_else(|| io::Error::other("missing DuckDuckGo route"))?;
    let (result, job) = super::prepare::prepare_provider_job(
        &prepared,
        route,
        AddressableByteLimit::try_from(1_024_u64)?,
        1_024,
        10,
    )?;

    let result = result.ok_or_else(|| io::Error::other("missing provider slot"))?;
    assert!(matches!(
        result.outcome(),
        super::ProviderOutcome::NotStarted(super::SearchUnavailableReason::UnsupportedCapability)
    ));
    assert!(job.is_none());
    Ok(())
}

#[test]
fn global_byte_budget_is_divided_without_exceeding_total() -> Result<(), Box<dyn Error>> {
    let quota = per_provider_output_quota(10, 3)?;
    assert_eq!(quota, 3);
    assert!(quota.checked_mul(3).is_some_and(|retained| retained <= 10));
    assert!(per_provider_output_quota(2, 3).is_err());
    Ok(())
}

#[tokio::test]
async fn completion_order_does_not_change_response_slots() -> Result<(), Box<dyn Error>> {
    let (started_tx, mut started_rx) = mpsc::unbounded_channel();
    let (mut release_tx, release_rx) = release_gates(3);
    let gates = Arc::new(Mutex::new(release_rx));
    let worker = {
        let gates = Arc::clone(&gates);
        move |job: usize, cancellation: CancellationToken| {
            let gates = Arc::clone(&gates);
            let started_tx = started_tx.clone();
            async move {
                let _ = started_tx.send(job);
                let receiver = gates.lock().await.remove(&job);
                if let Some(receiver) = receiver {
                    tokio::select! {
                        () = cancellation.cancelled() => job,
                        _ = receiver => job,
                    }
                } else {
                    job
                }
            }
        }
    };
    let jobs = (0..3)
        .map(|slot| ScheduledJob {
            slot,
            uses_browser: false,
            payload: slot,
        })
        .collect();
    let slots = iter::repeat_with(|| None).take(3).collect();
    let cancellation = CancellationToken::new();
    let deadline = Instant::now()
        .checked_add(Duration::from_secs(20))
        .ok_or_else(|| io::Error::other("test deadline overflow"))?;
    let scheduler_cancellation = cancellation.clone();
    let scheduler = tokio::spawn(async move {
        run_scheduler(jobs, slots, 2, 1, deadline, &scheduler_cancellation, worker).await
    });

    let first = started_rx
        .recv()
        .await
        .ok_or_else(|| io::Error::other("first task did not start"))?;
    let second = started_rx
        .recv()
        .await
        .ok_or_else(|| io::Error::other("second task did not start"))?;
    release_job(&mut release_tx, second)?;
    let third = started_rx
        .recv()
        .await
        .ok_or_else(|| io::Error::other("queued task did not start after a slot freed"))?;
    assert_eq!(third, 2);
    release_job(&mut release_tx, third)?;
    release_job(&mut release_tx, first)?;

    let scheduled = scheduler
        .await
        .map_err(|_| io::Error::other("scheduler task failed"))?;
    assert_eq!(scheduled.termination, SchedulerTermination::Completed);
    assert_eq!(scheduled.slots, vec![Some(0), Some(1), Some(2)]);
    Ok(())
}

#[tokio::test]
async fn cancellation_keeps_queued_slot_and_drains_active_task() -> Result<(), Box<dyn Error>> {
    let (started_tx, mut started_rx) = mpsc::unbounded_channel();
    let worker = move |job: usize, cancellation: CancellationToken| {
        let started_tx = started_tx.clone();
        async move {
            let _ = started_tx.send(job);
            cancellation.cancelled().await;
            job + 10
        }
    };
    let jobs = (0..2)
        .map(|slot| ScheduledJob {
            slot,
            uses_browser: false,
            payload: slot,
        })
        .collect();
    let slots = iter::repeat_with(|| None).take(2).collect();
    let cancellation = CancellationToken::new();
    let deadline = Instant::now()
        .checked_add(Duration::from_secs(20))
        .ok_or_else(|| io::Error::other("test deadline overflow"))?;
    let scheduler_cancellation = cancellation.clone();
    let scheduler = tokio::spawn(async move {
        run_scheduler(jobs, slots, 1, 1, deadline, &scheduler_cancellation, worker).await
    });
    let started = started_rx
        .recv()
        .await
        .ok_or_else(|| io::Error::other("active task did not start"))?;
    assert_eq!(started, 0);
    cancellation.cancel();
    let scheduled = scheduler
        .await
        .map_err(|_| io::Error::other("scheduler task failed"))?;
    assert_eq!(scheduled.termination, SchedulerTermination::Cancelled);
    assert_eq!(scheduled.slots, vec![Some(10), None]);
    assert_eq!(
        scheduled.not_started.get(1).copied().flatten(),
        Some(SchedulerStopReason::Cancelled)
    );
    Ok(())
}

#[test]
fn aggregate_output_cap_keeps_order_and_marks_truncation() -> Result<(), Box<dyn Error>> {
    use std::num::NonZeroU16;

    use super::output::cap_global_output;
    use crate::internal::engine::search::SearchResultUrl;
    use crate::internal::engine::search::{
        FeatureCoverage, ProviderCharge, ProviderIdentity, ProviderOutcome, ProviderResult,
        SearchCoverage, SearchFailure, SearchHit, SearchIssueKind, SearchPage, SearchProfileFacts,
        WebCoverage,
    };
    use crate::internal::policy::policy::search::Provider;

    fn provider_with_urls<const N: usize>(
        provider: Provider,
        urls: [&str; N],
    ) -> Result<ProviderResult, Box<dyn Error>> {
        let mut hits = Vec::with_capacity(N);
        for (index, value) in urls.into_iter().enumerate() {
            let rank_value = u16::try_from(index + 1)?;
            let rank = NonZeroU16::new(rank_value)
                .ok_or_else(|| io::Error::other("test rank must be positive"))?;
            hits.push(SearchHit::new(SearchResultUrl::parse(value)?, rank, rank));
        }
        Ok(ProviderResult {
            identity: ProviderIdentity {
                provider,
                endpoint: None,
                adapter_version: None,
                parser_version: None,
            },
            profile: SearchProfileFacts {
                acquisition: None,
                defaults_status: ProviderDefaultsStatus::Exact,
                defaults_version: None,
                effective_request_policy: None,
            },
            request_id: None,
            recovery_query: None,
            attempts: Vec::new(),
            captures: Vec::new(),
            outcome: ProviderOutcome::Results(SearchPage::new(
                hits,
                Vec::new(),
                SearchCoverage::new(WebCoverage::Complete, FeatureCoverage::NotCollected),
                Vec::new(),
            )),
            charge: ProviderCharge::Unknown,
        })
    }

    let first = provider_with_urls(
        Provider::Brave,
        ["https://a.example/", "https://b.example/"],
    )?;
    let second = provider_with_urls(Provider::Bing, ["https://c.example/"])?;
    let mut providers = vec![first, second];

    cap_global_output(&mut providers, 10, 20);

    let first = providers
        .first()
        .ok_or_else(|| io::Error::other("missing Brave slot"))?;
    let ProviderOutcome::Results(page) = &first.outcome else {
        return Err(io::Error::other("expected a partial Brave page").into());
    };
    assert_eq!(page.hits().len(), 1);
    assert_eq!(page.coverage().web(), WebCoverage::Partial);
    assert_eq!(page.retained_string_bytes(), Some(18));
    assert!(
        page.issues()
            .iter()
            .any(|issue| issue.kind == SearchIssueKind::OutputLimit)
    );

    let second = providers
        .get(1)
        .ok_or_else(|| io::Error::other("missing Bing slot"))?;
    assert!(matches!(
        &second.outcome,
        ProviderOutcome::Failed(SearchFailure::BudgetExhausted)
    ));
    Ok(())
}

fn release_gates(
    count: usize,
) -> (
    HashMap<usize, oneshot::Sender<()>>,
    HashMap<usize, oneshot::Receiver<()>>,
) {
    let mut senders = HashMap::with_capacity(count);
    let mut receivers = HashMap::with_capacity(count);
    for slot in 0..count {
        let (sender, receiver) = oneshot::channel();
        senders.insert(slot, sender);
        receivers.insert(slot, receiver);
    }
    (senders, receivers)
}

fn release_job(
    senders: &mut HashMap<usize, oneshot::Sender<()>>,
    job: usize,
) -> Result<(), Box<dyn Error>> {
    let sender = senders
        .remove(&job)
        .ok_or_else(|| io::Error::other("missing release gate"))?;
    sender
        .send(())
        .map_err(|()| io::Error::other("release receiver was closed"))?;
    Ok(())
}

#[test]
fn precise_browser_diagnostics_survive_search_without_becoming_markup_errors() {
    use crate::internal::engine::BrowserFailureReason;
    for reason in [
        BrowserFailureReason::Launch,
        BrowserFailureReason::Connection,
        BrowserFailureReason::Navigation,
        BrowserFailureReason::Timeout,
        BrowserFailureReason::DisplayUnavailable,
        BrowserFailureReason::EnvironmentMismatch,
        BrowserFailureReason::ProfileUnavailable,
        BrowserFailureReason::Unavailable,
        BrowserFailureReason::CapacityExhausted,
        BrowserFailureReason::Closed,
        BrowserFailureReason::RendererCrashed,
        BrowserFailureReason::UnsupportedConfiguration,
    ] {
        let diagnostic = AttemptDiagnostic::BrowserFailure(reason);
        assert_eq!(
            search_attempt_diagnostic(diagnostic),
            SearchAttemptDiagnostic::BrowserFailure(reason)
        );
        assert_eq!(
            search_failure_for_attempt(diagnostic),
            super::SearchFailure::TransportFailure
        );
    }
}
