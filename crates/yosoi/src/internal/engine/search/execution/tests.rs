#![expect(
    clippy::panic_in_result_fn,
    reason = "assertions intentionally report bounded execution test failures"
)]
use std::{collections::HashMap, error::Error, io, iter, sync::Arc, time::Duration};

#[cfg(not(feature = "browser"))]
use crate::internal::engine::search::new as new_search;
use crate::internal::engine::{
    request::execution::AttemptDiagnostic, search::SearchAttemptDiagnostic,
};
use crate::internal::policy::policy::ProviderDefaultsStatus;
use tokio_util::sync::CancellationToken;

use tokio::{
    sync::{Mutex, mpsc, oneshot},
    time::Instant,
};

use super::prepare::{is_supported_duckduckgo_acquisition, per_provider_output_quota};
use super::response::{
    search_attempt_diagnostic, search_failure_for_attempt, search_parse_failure,
};
use super::scheduler::{ScheduledJob, SchedulerStopReason, SchedulerTermination, run_scheduler};

#[test]
fn provider_output_limit_is_reported_as_budget_exhausted() {
    assert_eq!(
        search_parse_failure(true),
        super::super::SearchFailure::BudgetExhausted
    );
    assert_eq!(
        search_parse_failure(false),
        super::super::SearchFailure::MalformedResponse
    );
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
