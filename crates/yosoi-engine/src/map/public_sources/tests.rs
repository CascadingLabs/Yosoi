//! Event-driven provider concurrency and reservation regressions.

#![expect(clippy::panic_in_result_fn, reason = "Assertions report test failures")]

use crate::test_http_fixture as fixture;

use std::{
    error::Error, future::Future, future::poll_fn, io, pin::Pin, sync::Arc, task::Poll,
    time::Duration,
};

use fixture::{
    FixtureService, Protocol, RequestLine, Response as FixtureResponse, ResponseControl,
};
use tokio::time::{Instant, timeout};
use url::Url;
use yosoi_map::admission::Scope;
use yosoi_policy::policy::{Budget as MapBudget, HostScope, PathScope, Subdomains};
use yosoi_web_capture::UserAgent;

use crate::{CancellationToken, Policy, PolicySnapshot, request::execution};

use super::{
    DiscoverySource, Job, LimitReached, MapTermination, PublicProvider, Runner, SourceFailure,
    SourceStatus,
    budget::{AdmissionError, Budget as SourceBudget},
};

type TestResult<T = ()> = Result<T, Box<dyn Error + Send + Sync>>;

fn policy() -> Policy {
    let mut policy = Policy::default();
    policy.map.scope.hosts = HostScope::RegistrableDomain;
    policy.map.scope.paths = PathScope::EntireOrigin;
    policy.map.subdomains = Subdomains::Passive;
    policy
}

fn set_budget(target: &mut MapBudget, value: u32) -> TestResult {
    *target = MapBudget::new(value)?;
    Ok(())
}

fn runner<'a>(policy: &Policy, cancellation: &'a CancellationToken) -> TestResult<Runner<'a>> {
    let seed = Url::parse("https://example.com/")?;
    let scope = Scope::new(&seed, &policy.map)?;
    runner_with_scope(policy, cancellation, seed, scope)
}

fn runner_with_scope<'a>(
    policy: &Policy,
    cancellation: &'a CancellationToken,
    seed: Url,
    scope: Scope,
) -> TestResult<Runner<'a>> {
    let snapshot = PolicySnapshot::from_policy(policy)?;
    let deadline = Instant::now()
        .checked_add(policy.map.limits.maximum_elapsed)
        .ok_or_else(|| io::Error::other("test deadline overflow"))?;
    let user_agent = UserAgent::new("YosoiMap/public-sources-tests")?;
    let executor = execution::direct_http_executor_with_user_agent(user_agent)?;
    Ok(Runner::new(
        seed,
        snapshot,
        scope,
        deadline,
        cancellation,
        executor,
    ))
}

fn job(provider: PublicProvider, url: &str) -> TestResult<Job> {
    Ok(Job {
        provider,
        url: Url::parse(url)?,
    })
}

fn controlled_response(
    status: u16,
    content_type: &str,
    body: &[u8],
    hold_before_head: bool,
) -> (FixtureResponse, Arc<ResponseControl>) {
    let control = Arc::new(ResponseControl {
        hold_before_head,
        ..ResponseControl::default()
    });
    let mut response = FixtureResponse::bytes(status, Some(content_type), body);
    response.control = Some(Arc::clone(&control));
    (response, control)
}

fn paths(requests: &[RequestLine]) -> Vec<String> {
    requests
        .iter()
        .map(|request| request.path.clone())
        .collect()
}

async fn wait_for_event_or_completion<F: Future<Output = ()>>(
    collection: &mut Pin<Box<F>>,
    event: &fixture::Signal,
) -> TestResult {
    tokio::select! {
        () = event.wait() => Ok(()),
        () = collection.as_mut() => Err(io::Error::other("provider collection finished before the fixture event").into()),
    }
}

fn assert_catalog_status(runner: &Runner<'_>, status: &SourceStatus) {
    let expected: Vec<_> = PublicProvider::all()
        .iter()
        .copied()
        .map(super::source)
        .collect();
    assert_eq!(runner.source_outcomes.len(), expected.len());
    for (outcome, expected_source) in runner.source_outcomes.iter().zip(expected) {
        assert_eq!(outcome.source, expected_source);
        assert_eq!(&outcome.status, status);
        assert!(outcome.source_url.is_none());
    }
}

fn assert_no_provider_requests(runner: &Runner<'_>) {
    assert_eq!(runner.summary.requests, 0);
    assert_eq!(runner.request_trace.len(), 0);
}

#[tokio::test]
async fn provider_pool_holds_its_cap_until_a_response_finishes() -> TestResult {
    let mut policy = policy();
    set_budget(&mut policy.map.limits.max_concurrency, 2)?;
    set_budget(&mut policy.map.limits.max_pending, 2)?;
    let cancellation = CancellationToken::new();
    let mut runner = runner(&policy, &cancellation)?;

    let (response_a, control_a) = controlled_response(
        200,
        "application/json",
        br#"[{"name_value":"a.example.com"}]"#,
        true,
    );
    let (response_b, control_b) = controlled_response(
        200,
        "application/json",
        br#"[{"name_value":"b.example.com"}]"#,
        true,
    );
    let (response_c, control_c) = controlled_response(
        200,
        "application/json",
        br#"[{"name_value":"c.example.com"}]"#,
        true,
    );
    let service = FixtureService::start(
        Protocol::Http,
        [
            ("/a".to_owned(), response_a),
            ("/b".to_owned(), response_b),
            ("/c".to_owned(), response_c),
        ],
    )
    .await;
    let jobs = vec![
        job(PublicProvider::CrtSh, &service.url("/a"))?,
        job(PublicProvider::CrtSh, &service.url("/b"))?,
        job(PublicProvider::CrtSh, &service.url("/c"))?,
    ];
    let mut collection = Box::pin(runner.collect_sources(jobs));

    wait_for_event_or_completion(&mut collection, &control_a.requested).await?;
    wait_for_event_or_completion(&mut collection, &control_b.requested).await?;
    let before_release = service.requests().await;
    let cap_held = before_release.len() == 2;

    control_a.allow_head.signal();
    wait_for_event_or_completion(&mut collection, &control_c.requested).await?;
    control_b.allow_head.signal();
    control_c.allow_head.signal();
    collection.await;

    let peak = runner.summary.provider_concurrency_peak;
    let request_paths = paths(&service.requests().await);
    service.shutdown().await;

    assert!(
        cap_held,
        "a third source request started while two responses were held"
    );
    assert_eq!(peak, 2);
    assert_eq!(request_paths.len(), 3);
    assert_eq!(runner.summary.requests, 3);
    Ok(())
}

#[tokio::test]
async fn response_reservations_release_unused_capacity_and_charge_exact_bytes() -> TestResult {
    let budget = SourceBudget::new(3, 10, 8, 4_096);
    let cancellation = CancellationToken::new();
    let url = Url::parse("http://localhost:8080/provider")?;
    let deadline = Instant::now() + Duration::from_secs(10);

    let first = budget
        .reserve(&url, &cancellation, deadline)
        .await
        .map_err(|_| io::Error::other("first response reservation was rejected"))?;
    assert_eq!(first.cap, 8);

    let mut waiting = Box::pin(budget.reserve(&url, &cancellation, deadline));
    let remained_pending = poll_fn(|context| match waiting.as_mut().poll(context) {
        Poll::Pending => Poll::Ready(true),
        Poll::Ready(_) => Poll::Ready(false),
    })
    .await;
    assert!(
        remained_pending,
        "a second reservation exceeded the aggregate byte cap"
    );

    budget.complete(first, Some(200), 3).await;
    let second = waiting
        .await
        .map_err(|_| io::Error::other("released response capacity was not reusable"))?;
    assert_eq!(second.cap, 7);
    budget.complete(second, Some(200), 50).await;

    assert!(matches!(
        budget.reserve(&url, &cancellation, deadline).await,
        Err(AdmissionError::Limit(LimitReached::TotalResponseBytes))
    ));
    let consumption = budget.consumption().await;
    assert_eq!(consumption.traces.len(), 2);
    assert_eq!(consumption.charged, 10);
    let inventory_per_request = u64::try_from(url.as_str().len())
        .unwrap_or(u64::MAX)
        .saturating_add(96);
    assert_eq!(
        consumption.inventory,
        inventory_per_request.saturating_mul(2)
    );
    assert_eq!(consumption.peak, 1);
    assert_eq!(consumption.traces[0].charged_response_bytes, 3);
    assert_eq!(consumption.traces[1].charged_response_bytes, 7);
    Ok(())
}

#[tokio::test]
async fn terminal_inventory_denial_rejects_later_shorter_reservations() -> TestResult {
    let short_url = Url::parse("http://localhost/provider")?;
    let long_url = Url::parse(&format!("http://localhost/{}", "x".repeat(256)))?;
    let inventory_cap = u64::try_from(short_url.as_str().len())
        .unwrap_or(u64::MAX)
        .saturating_add(96);
    let budget = SourceBudget::new(5, 1_024, 512, inventory_cap);
    let cancellation = CancellationToken::new();
    let deadline = Instant::now() + Duration::from_secs(10);

    assert!(matches!(
        budget.reserve(&long_url, &cancellation, deadline).await,
        Err(AdmissionError::Limit(LimitReached::InventoryBytes))
    ));
    assert!(matches!(
        budget.reserve(&short_url, &cancellation, deadline).await,
        Err(AdmissionError::Limit(LimitReached::InventoryBytes))
    ));
    let consumption = budget.consumption().await;
    assert_eq!(consumption.traces.len(), 0);
    assert_eq!(consumption.inventory, 0);
    assert_eq!(consumption.limit, Some(LimitReached::InventoryBytes));
    Ok(())
}

#[tokio::test]
async fn cancelled_or_expired_provider_parsing_returns_no_names() -> TestResult {
    let bytes = br#"[{"name_value":"a.example.com"}]"#;
    let cancelled = CancellationToken::new();
    cancelled.cancel();
    let future_deadline = Instant::now() + Duration::from_secs(10);
    assert!(matches!(
        super::parse_response(
            PublicProvider::CrtSh,
            bytes,
            10,
            &cancelled,
            future_deadline,
        ),
        Err(super::transport::Failure::ParsingStopped)
    ));

    let active = CancellationToken::new();
    let expired_deadline = Instant::now() - Duration::from_secs(1);
    assert!(matches!(
        super::parse_response(PublicProvider::CrtSh, bytes, 10, &active, expired_deadline,),
        Err(super::transport::Failure::ParsingStopped)
    ));
    Ok(())
}

#[tokio::test]
async fn redirect_hops_share_the_request_limit() -> TestResult {
    let mut policy = policy();
    set_budget(&mut policy.map.limits.max_requests, 1)?;
    let cancellation = CancellationToken::new();
    let mut runner = runner(&policy, &cancellation)?;
    let redirect = FixtureResponse::redirect("/after");
    let (after, _) = controlled_response(
        200,
        "application/json",
        br#"[{"name_value":"after.example.com"}]"#,
        false,
    );
    let service = FixtureService::start(
        Protocol::Http,
        [
            ("/redirect".to_owned(), redirect),
            ("/after".to_owned(), after),
        ],
    )
    .await;

    runner
        .collect_sources(vec![job(PublicProvider::CrtSh, &service.url("/redirect"))?])
        .await;

    let request_paths = paths(&service.requests().await);
    service.shutdown().await;

    assert_eq!(request_paths, vec!["/redirect".to_owned()]);
    assert_eq!(runner.summary.requests, 1);
    assert_eq!(runner.request_trace.len(), 1);
    assert_eq!(runner.request_trace[0].status, Some(302));
    assert_eq!(
        runner.termination,
        Some(MapTermination::Limit(LimitReached::Requests))
    );
    assert_eq!(
        runner
            .source_outcomes
            .first()
            .map(|outcome| &outcome.status),
        Some(&SourceStatus::NotStarted)
    );
    Ok(())
}

#[tokio::test]
async fn passive_inventory_keeps_valid_names_after_out_of_scope_entries() -> TestResult {
    let policy = policy();
    let cancellation = CancellationToken::new();
    let mut runner = runner(&policy, &cancellation)?;
    let (response, _) = controlled_response(
        200,
        "application/json",
        br#"[{"name_value":"outside.invalid"},{"name_value":"valid.example.com"}]"#,
        false,
    );
    let service = FixtureService::start(Protocol::Http, [("/crt".to_owned(), response)]).await;

    runner
        .collect_sources(vec![job(PublicProvider::CrtSh, &service.url("/crt"))?])
        .await;

    let request_paths = paths(&service.requests().await);
    service.shutdown().await;

    assert_eq!(request_paths, vec!["/crt".to_owned()]);
    assert_eq!(runner.termination, None);
    assert_eq!(runner.source_outcomes[0].status, SourceStatus::Completed);
    assert!(!runner.hosts.contains_key("outside.invalid"));
    assert!(runner.hosts.contains_key("valid.example.com"));
    assert_eq!(runner.hosts.len(), 1);
    Ok(())
}

#[tokio::test]
async fn identical_wildcards_keep_both_provider_sources_without_concrete_hosts() -> TestResult {
    let policy = policy();
    let cancellation = CancellationToken::new();
    let mut runner = runner(&policy, &cancellation)?;
    let (crt, _) = controlled_response(
        200,
        "application/json",
        br#"[{"name_value":"*.example.com"}]"#,
        false,
    );
    let (hackertarget, _) =
        controlled_response(200, "text/plain", b"*.example.com,127.0.0.1\n", false);
    let service = FixtureService::start(
        Protocol::Http,
        [("/crt".to_owned(), crt), ("/ht".to_owned(), hackertarget)],
    )
    .await;
    let crt_url = Url::parse(&service.url("/crt"))?;
    let ht_url = Url::parse(&service.url("/ht"))?;

    runner
        .collect_sources(vec![
            job(PublicProvider::CrtSh, crt_url.as_str())?,
            job(PublicProvider::HackerTarget, ht_url.as_str())?,
        ])
        .await;

    let request_paths = paths(&service.requests().await);
    service.shutdown().await;

    assert_eq!(request_paths.len(), 2);
    assert_eq!(runner.hosts.len(), 0);
    assert_eq!(runner.wildcard_names, vec!["*.example.com".to_owned()]);
    let observations = runner
        .wildcard_entries
        .get("*.example.com")
        .ok_or_else(|| io::Error::other("wildcard observations were not retained"))?;
    assert_eq!(observations.len(), 2);
    assert_eq!(observations[0].source, DiscoverySource::PassiveCertificate);
    assert_eq!(observations[0].source_url.as_ref(), Some(&crt_url));
    assert_eq!(
        observations[1].source,
        DiscoverySource::PassiveProvider(PublicProvider::HackerTarget)
    );
    assert_eq!(observations[1].source_url.as_ref(), Some(&ht_url));
    Ok(())
}

#[tokio::test]
async fn request_budget_denials_do_not_consume_provider_rate_quota() -> TestResult {
    let cancellation = CancellationToken::new();
    let url = Url::parse("http://localhost:8080/subdomain-center")?;
    let deadline = Instant::now() + Duration::from_secs(10);
    let no_requests = SourceBudget::new(0, 1_024, 512, 4_096);

    for _ in 0..5 {
        assert!(matches!(
            no_requests
                .reserve_for(
                    &url,
                    &cancellation,
                    deadline,
                    Some(PublicProvider::SubdomainCenter),
                )
                .await,
            Err(AdmissionError::Limit(LimitReached::Requests))
        ));
    }

    let one_request = SourceBudget::new(1, 1_024, 512, 4_096);
    let reservation = one_request
        .reserve_for(
            &url,
            &cancellation,
            deadline,
            Some(PublicProvider::SubdomainCenter),
        )
        .await
        .map_err(|_| io::Error::other("budget-denied calls consumed the provider quota"))?;
    one_request.complete(reservation, Some(200), 0).await;
    Ok(())
}

#[tokio::test]
async fn passive_catalog_early_exits_report_every_provider_without_requests() -> TestResult {
    let mut disabled_policy = policy();
    disabled_policy.map.subdomains = Subdomains::Disabled;
    let disabled_cancellation = CancellationToken::new();
    disabled_cancellation.cancel();
    let mut disabled_runner = runner(&disabled_policy, &disabled_cancellation)?;
    disabled_runner.passive().await;
    assert_catalog_status(&disabled_runner, &SourceStatus::Disabled);
    assert_eq!(disabled_runner.termination, None);
    assert_no_provider_requests(&disabled_runner);

    let active_policy = policy();
    let mut seed_scope_policy = active_policy.clone();
    seed_scope_policy.map.scope.hosts = HostScope::SeedHost;
    seed_scope_policy.map.subdomains = Subdomains::Disabled;
    let domainless_seed = Url::parse("https://127.0.0.1/")?;
    let domainless_scope = Scope::new(&domainless_seed, &seed_scope_policy.map)?;
    let domainless_cancellation = CancellationToken::new();
    domainless_cancellation.cancel();
    let mut domainless_runner = runner_with_scope(
        &active_policy,
        &domainless_cancellation,
        domainless_seed,
        domainless_scope,
    )?;
    domainless_runner.passive().await;
    assert_catalog_status(&domainless_runner, &SourceStatus::NotStarted);
    assert_eq!(domainless_runner.termination, None);
    assert_no_provider_requests(&domainless_runner);

    let mut limited_policy = policy();
    set_budget(&mut limited_policy.map.limits.max_inventory_bytes, 1)?;
    let limited_cancellation = CancellationToken::new();
    limited_cancellation.cancel();
    let mut limited_runner = runner(&limited_policy, &limited_cancellation)?;
    limited_runner.passive().await;
    assert_catalog_status(&limited_runner, &SourceStatus::NotStarted);
    assert_eq!(
        limited_runner.termination,
        Some(MapTermination::Limit(LimitReached::InventoryBytes))
    );
    assert_eq!(limited_runner.summary.inventory_bytes, 0);
    assert_no_provider_requests(&limited_runner);
    Ok(())
}

#[tokio::test]
async fn providers_commit_in_catalog_order_and_keep_distinct_provenance() -> TestResult {
    let mut policy = policy();
    set_budget(&mut policy.map.limits.max_concurrency, 4)?;
    let cancellation = CancellationToken::new();
    let mut runner = runner(&policy, &cancellation)?;

    let (crt, crt_control) = controlled_response(
        200,
        "application/json",
        br#"[{"name_value":"a.example.com"},{"name_value":"A.example.com"}]"#,
        true,
    );
    let (hackertarget, ht_control) =
        controlled_response(200, "text/plain", b"a.example.com,127.0.0.1\n", true);
    let (center, center_control) =
        controlled_response(200, "application/json", br#"["A.example.com"]"#, true);
    let (center_challenge, challenge_control) = controlled_response(
        200,
        "text/html",
        b"<!doctype html><html>challenge</html>",
        true,
    );
    let (wayback, wayback_control) = controlled_response(
        200,
        "application/json",
        br#"[["original"],["https://b.example.com/"]]"#,
        true,
    );
    let (wayback_missing, missing_control) =
        controlled_response(404, "text/plain", b"missing", true);
    let service = FixtureService::start(
        Protocol::Http,
        [
            ("/crt".to_owned(), crt),
            ("/ht".to_owned(), hackertarget),
            ("/center".to_owned(), center),
            ("/center-challenge".to_owned(), center_challenge),
            ("/wayback".to_owned(), wayback),
            ("/wayback-missing".to_owned(), wayback_missing),
        ],
    )
    .await;
    let crt_url = Url::parse(&service.url("/crt"))?;
    let ht_url = Url::parse(&service.url("/ht"))?;
    let center_url = Url::parse(&service.url("/center"))?;
    let wayback_url = Url::parse(&service.url("/wayback"))?;
    let jobs = vec![
        job(PublicProvider::CrtSh, crt_url.as_str())?,
        job(PublicProvider::HackerTarget, ht_url.as_str())?,
        job(PublicProvider::SubdomainCenter, center_url.as_str())?,
        job(
            PublicProvider::SubdomainCenter,
            &service.url("/center-challenge"),
        )?,
        job(PublicProvider::WaybackArchive, wayback_url.as_str())?,
        job(
            PublicProvider::WaybackArchive,
            &service.url("/wayback-missing"),
        )?,
    ];
    let mut collection = Box::pin(runner.collect_sources(jobs));

    for control in [
        &crt_control,
        &ht_control,
        &center_control,
        &challenge_control,
    ] {
        wait_for_event_or_completion(&mut collection, &control.requested).await?;
    }

    challenge_control.allow_head.signal();
    wait_for_event_or_completion(&mut collection, &challenge_control.connection_finished).await?;
    wait_for_event_or_completion(&mut collection, &wayback_control.requested).await?;
    wayback_control.allow_head.signal();
    wait_for_event_or_completion(&mut collection, &wayback_control.connection_finished).await?;
    wait_for_event_or_completion(&mut collection, &missing_control.requested).await?;
    missing_control.allow_head.signal();
    wait_for_event_or_completion(&mut collection, &missing_control.connection_finished).await?;

    center_control.allow_head.signal();
    wait_for_event_or_completion(&mut collection, &center_control.connection_finished).await?;
    ht_control.allow_head.signal();
    wait_for_event_or_completion(&mut collection, &ht_control.connection_finished).await?;
    crt_control.allow_head.signal();
    wait_for_event_or_completion(&mut collection, &crt_control.connection_finished).await?;
    collection.await;

    let request_paths = paths(&service.requests().await);
    service.shutdown().await;

    let sources = &runner.source_outcomes;
    assert_eq!(sources.len(), 6);
    assert_eq!(sources[0].source, DiscoverySource::PassiveCertificate);
    assert_eq!(
        sources[1].source,
        DiscoverySource::PassiveProvider(PublicProvider::HackerTarget)
    );
    assert_eq!(
        sources[2].source,
        DiscoverySource::PassiveProvider(PublicProvider::SubdomainCenter)
    );
    assert_eq!(
        sources[3].source,
        DiscoverySource::PassiveProvider(PublicProvider::SubdomainCenter)
    );
    assert_eq!(
        sources[4].source,
        DiscoverySource::PassiveProvider(PublicProvider::WaybackArchive)
    );
    assert_eq!(
        sources[5].source,
        DiscoverySource::PassiveProvider(PublicProvider::WaybackArchive)
    );
    assert_eq!(sources[0].status, SourceStatus::Completed);
    assert_eq!(sources[1].status, SourceStatus::Completed);
    assert_eq!(sources[2].status, SourceStatus::Sampled);
    assert_eq!(
        sources[3].status,
        SourceStatus::Failed(SourceFailure::Parse)
    );
    assert_eq!(sources[4].status, SourceStatus::Completed);
    assert_eq!(
        sources[5].status,
        SourceStatus::Failed(SourceFailure::HttpStatus(404))
    );
    assert_eq!(request_paths.len(), 6);

    let host_a = runner
        .hosts
        .get("a.example.com")
        .ok_or_else(|| io::Error::other("provider host a.example.com was not retained"))?;
    assert_eq!(host_a.observations.len(), 3);
    assert_eq!(
        host_a.observations[0].source,
        DiscoverySource::PassiveCertificate
    );
    assert_eq!(host_a.observations[0].source_url.as_ref(), Some(&crt_url));
    assert_eq!(
        host_a.observations[1].source,
        DiscoverySource::PassiveProvider(PublicProvider::HackerTarget)
    );
    assert_eq!(host_a.observations[1].source_url.as_ref(), Some(&ht_url));
    assert_eq!(
        host_a.observations[2].source,
        DiscoverySource::PassiveProvider(PublicProvider::SubdomainCenter)
    );
    assert_eq!(
        host_a.observations[2].source_url.as_ref(),
        Some(&center_url)
    );

    let host_b = runner
        .hosts
        .get("b.example.com")
        .ok_or_else(|| io::Error::other("Wayback host b.example.com was not retained"))?;
    assert_eq!(host_b.observations.len(), 1);
    assert_eq!(
        host_b.observations[0].source_url.as_ref(),
        Some(&wayback_url)
    );
    Ok(())
}

#[tokio::test]
async fn cancellation_drains_active_work_without_dispatching_queued_jobs() -> TestResult {
    let mut policy = policy();
    set_budget(&mut policy.map.limits.max_concurrency, 1)?;
    let cancellation = CancellationToken::new();
    let mut runner = runner(&policy, &cancellation)?;

    let (kept_response, kept_control) = controlled_response(
        200,
        "application/json",
        br#"[{"name_value":"kept.example.com"}]"#,
        false,
    );
    let (held_response, held_control) =
        controlled_response(200, "text/plain", b"waiting.example.com,127.0.0.1\n", true);
    let (queued_response, _) = controlled_response(
        200,
        "application/json",
        br#"[["original"],["https://queued.example.com/"]]"#,
        false,
    );
    let service = FixtureService::start(
        Protocol::Http,
        [
            ("/kept".to_owned(), kept_response),
            ("/held".to_owned(), held_response),
            ("/queued".to_owned(), queued_response),
        ],
    )
    .await;

    runner
        .collect_sources(vec![job(PublicProvider::CrtSh, &service.url("/kept"))?])
        .await;
    kept_control.connection_finished.wait().await;
    let mut collection = Box::pin(runner.collect_sources(vec![
        job(PublicProvider::HackerTarget, &service.url("/held"))?,
        job(PublicProvider::WaybackArchive, &service.url("/queued"))?,
    ]));
    wait_for_event_or_completion(&mut collection, &held_control.requested).await?;

    cancellation.cancel();
    timeout(Duration::from_secs(2), &mut collection).await?;
    drop(collection);

    let request_paths = paths(&service.requests().await);
    service.shutdown().await;

    assert_eq!(request_paths, vec!["/kept".to_owned(), "/held".to_owned()]);
    assert_eq!(runner.termination, Some(MapTermination::Cancelled));
    assert_eq!(runner.summary.requests, 2);
    assert_eq!(runner.source_outcomes.len(), 3);
    assert_eq!(runner.source_outcomes[0].status, SourceStatus::Completed);
    assert_eq!(runner.source_outcomes[1].status, SourceStatus::NotStarted);
    assert_eq!(runner.source_outcomes[2].status, SourceStatus::NotStarted);
    assert!(runner.hosts.contains_key("kept.example.com"));
    assert!(!runner.hosts.contains_key("waiting.example.com"));
    assert!(!runner.hosts.contains_key("queued.example.com"));
    Ok(())
}

#[tokio::test]
async fn deadline_drains_active_work_and_preserves_finished_provider_results() -> TestResult {
    let mut policy = policy();
    policy.map.limits.maximum_elapsed = Duration::from_secs(1);
    set_budget(&mut policy.map.limits.max_concurrency, 1)?;
    let cancellation = CancellationToken::new();
    let mut runner = runner(&policy, &cancellation)?;

    let (kept_response, kept_control) = controlled_response(
        200,
        "application/json",
        br#"[{"name_value":"deadline-kept.example.com"}]"#,
        false,
    );
    let (held_response, held_control) = controlled_response(
        200,
        "application/json",
        br#"[{"name_value":"deadline-held.example.com"}]"#,
        true,
    );
    let (queued_response, _) = controlled_response(
        200,
        "application/json",
        br#"[{"name_value":"deadline-queued.example.com"}]"#,
        false,
    );
    let service = FixtureService::start(
        Protocol::Http,
        [
            ("/kept".to_owned(), kept_response),
            ("/held".to_owned(), held_response),
            ("/queued".to_owned(), queued_response),
        ],
    )
    .await;
    let mut collection = Box::pin(runner.collect_sources(vec![
        job(PublicProvider::CrtSh, &service.url("/kept"))?,
        job(PublicProvider::HackerTarget, &service.url("/held"))?,
        job(PublicProvider::WaybackArchive, &service.url("/queued"))?,
    ]));
    wait_for_event_or_completion(&mut collection, &kept_control.connection_finished).await?;
    wait_for_event_or_completion(&mut collection, &held_control.requested).await?;
    timeout(Duration::from_secs(3), &mut collection).await?;
    drop(collection);

    let request_paths = paths(&service.requests().await);
    service.shutdown().await;

    assert_eq!(request_paths, vec!["/kept".to_owned(), "/held".to_owned()]);
    assert_eq!(runner.termination, Some(MapTermination::Deadline));
    assert_eq!(runner.summary.requests, 2);
    assert_eq!(runner.source_outcomes.len(), 3);
    assert_eq!(runner.source_outcomes[0].status, SourceStatus::Completed);
    assert_eq!(runner.source_outcomes[1].status, SourceStatus::NotStarted);
    assert_eq!(runner.source_outcomes[2].status, SourceStatus::NotStarted);
    assert!(runner.hosts.contains_key("deadline-kept.example.com"));
    assert!(!runner.hosts.contains_key("deadline-held.example.com"));
    assert!(!runner.hosts.contains_key("deadline-queued.example.com"));
    Ok(())
}
