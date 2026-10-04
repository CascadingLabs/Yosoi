//! Regressions for page work that redirects into or fails before probe dispatch.

#![allow(clippy::panic_in_result_fn)]

use crate::test_http_fixture as fixture;

use std::{error::Error, io};

use fixture::{FixtureService, Protocol, RequestLine, Response as FixtureResponse};
use tokio::time::Instant;
use url::Url;
use yosoi_map::admission::Scope;
use yosoi_policy::policy::Budget;
use yosoi_web_capture::UserAgent;

use crate::{CancellationToken, Policy, PolicySnapshot, request::execution};

use super::{
    DiscoverySource, Exploration, PageTask, Runner, SkipReason, SourceFailure, SourceStatus,
};

type TestResult<T = ()> = Result<T, Box<dyn Error + Send + Sync>>;

fn support_routes() -> Vec<(String, FixtureResponse)> {
    ["/robots.txt", "/sitemap.xml", "/sitemap_index.xml"]
        .into_iter()
        .map(|path| {
            (
                path.to_owned(),
                FixtureResponse::bytes(404, Some("text/plain"), b"missing"),
            )
        })
        .collect()
}

fn runner<'a>(
    policy: &Policy,
    cancellation: &'a CancellationToken,
    seed: Url,
) -> TestResult<Runner<'a>> {
    let snapshot = PolicySnapshot::from_policy(policy)?;
    let scope = Scope::new(&seed, &policy.map)?;
    let deadline = Instant::now()
        .checked_add(policy.map.limits.maximum_elapsed)
        .ok_or_else(|| io::Error::other("page concurrency test deadline overflow"))?;
    let user_agent = UserAgent::new("YosoiMap/page-concurrency-tests")?;
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

fn request_paths(requests: &[RequestLine]) -> Vec<String> {
    requests
        .iter()
        .map(|request| request.path.clone())
        .collect()
}

#[tokio::test]
async fn redirected_probe_reuses_the_completed_non_html_page_and_keeps_provenance() -> TestResult {
    let mut policy = Policy::default();
    policy.map.limits.max_concurrency = Budget::new(1)?;
    let mut routes = support_routes();
    routes.push(("/".to_owned(), FixtureResponse::redirect("/target")));
    routes.push((
        "/target".to_owned(),
        FixtureResponse::bytes(404, Some("text/plain"), b"not found"),
    ));
    let service = FixtureService::start(Protocol::Http, routes).await;
    let root = Url::parse(&service.url("/"))?;
    let target = Url::parse(&service.url("/target"))?;
    let cancellation = CancellationToken::new();
    let mut runner = runner(&policy, &cancellation, root.clone())?;

    assert!(runner.page(root, Some(0), DiscoverySource::Seed, None));
    assert!(runner.probes.insert(target.clone()));
    runner.queue.push_back(PageTask {
        url: target.clone(),
        depth: 0,
        probe: true,
    });

    runner.explore_pages().await;

    let requests = service.requests().await;
    service.shutdown().await;

    assert_eq!(
        request_paths(&requests)
            .iter()
            .filter(|path| path.as_str() == "/target")
            .count(),
        1
    );
    assert!(!runner.probes.contains(&target));
    let target_page = runner
        .pages
        .get(&target)
        .ok_or_else(|| io::Error::other("redirected target page was not retained"))?;
    assert!(target_page.observations.iter().any(|observation| {
        observation.source == DiscoverySource::PassiveCertificate
            && observation.source_url.is_none()
    }));
    assert_eq!(
        target_page.exploration,
        Exploration::Failed(SourceFailure::HttpStatus(404))
    );
    Ok(())
}

#[tokio::test]
async fn rejected_long_probe_does_not_block_a_later_valid_probe() -> TestResult {
    let mut policy = Policy::default();
    policy.map.limits.max_concurrency = Budget::new(1)?;
    policy.map.limits.max_url_bytes = Budget::new(80)?;
    let mut routes = support_routes();
    routes.push((
        "/".to_owned(),
        FixtureResponse::bytes(
            200,
            Some("text/html; charset=utf-8"),
            b"<html><body>root</body></html>",
        ),
    ));
    routes.push((
        "/later".to_owned(),
        FixtureResponse::bytes(404, Some("text/plain"), b"not found"),
    ));
    let service = FixtureService::start(Protocol::Http, routes).await;
    let root = Url::parse(&service.url("/"))?;
    let long_path = format!("/{}", "x".repeat(128));
    let rejected = Url::parse(&service.url(&long_path))?;
    let later = Url::parse(&service.url("/later"))?;
    assert!(root.as_str().len() < 80);
    assert!(later.as_str().len() < 80);
    assert!(rejected.as_str().len() > 80);

    let cancellation = CancellationToken::new();
    let mut runner = runner(&policy, &cancellation, root.clone())?;
    assert!(runner.page(root, Some(0), DiscoverySource::Seed, None));
    for url in [&rejected, &later] {
        assert!(runner.probes.insert(url.clone()));
        runner.queue.push_back(PageTask {
            url: url.clone(),
            depth: 0,
            probe: true,
        });
    }

    runner.explore_pages().await;

    let requests = service.requests().await;
    service.shutdown().await;

    let paths = request_paths(&requests);
    assert_eq!(
        paths
            .iter()
            .filter(|path| path.as_str() == "/later")
            .count(),
        1
    );
    assert!(!paths.iter().any(|path| path == &long_path));
    assert!(!runner.probes.contains(&rejected));
    assert!(!runner.probes.contains(&later));
    assert_eq!(runner.queue.len(), 0);
    assert_eq!(runner.termination, None);
    assert!(runner.source_outcomes.iter().any(|outcome| {
        outcome.source_url.as_ref() == Some(&rejected)
            && outcome.source == DiscoverySource::HtmlLink
            && outcome.status == SourceStatus::Failed(SourceFailure::RedirectRejected)
    }));
    let later_page = runner
        .pages
        .get(&later)
        .ok_or_else(|| io::Error::other("later valid probe page was not retained"))?;
    assert!(later_page.observations.iter().any(|observation| {
        observation.source == DiscoverySource::PassiveCertificate
            && observation.source_url.is_none()
    }));
    Ok(())
}

#[tokio::test]
async fn shorter_cached_page_reuses_target_and_requeues_child_at_new_depth() -> TestResult {
    let policy = Policy::default();
    let mut routes = support_routes();
    routes.push((
        "/target".to_owned(),
        FixtureResponse::bytes(
            200,
            Some("text/html; charset=utf-8"),
            b"<html><body><a href=\"/child\">child</a></body></html>",
        ),
    ));
    routes.push((
        "/child".to_owned(),
        FixtureResponse::bytes(200, Some("text/html; charset=utf-8"), b"<html>leaf</html>"),
    ));
    let service = FixtureService::start(Protocol::Http, routes).await;
    let root = Url::parse(&service.url("/"))?;
    let target = Url::parse(&service.url("/target"))?;
    let child = Url::parse(&service.url("/child"))?;
    let cancellation = CancellationToken::new();
    let mut runner = runner(&policy, &cancellation, root)?;

    assert!(runner.page(target.clone(), Some(2), DiscoverySource::HtmlLink, None));
    runner.explore_pages().await;

    let child_before = runner
        .pages
        .get(&child)
        .ok_or_else(|| io::Error::other("depth-limited child was not inventoried"))?;
    assert_eq!(child_before.minimum_link_depth, Some(3));
    assert_eq!(
        child_before.exploration,
        Exploration::Skipped(SkipReason::Depth)
    );
    let first_paths = request_paths(&service.requests().await);
    assert_eq!(
        first_paths
            .iter()
            .filter(|path| path.as_str() == "/target")
            .count(),
        1
    );
    assert!(!first_paths.iter().any(|path| path == "/child"));

    assert!(runner.page(target.clone(), Some(1), DiscoverySource::HtmlLink, None));
    runner.explore_pages().await;

    let all_paths = request_paths(&service.requests().await);
    service.shutdown().await;

    assert_eq!(
        all_paths
            .iter()
            .filter(|path| path.as_str() == "/target")
            .count(),
        1
    );
    assert_eq!(
        all_paths
            .iter()
            .filter(|path| path.as_str() == "/child")
            .count(),
        1
    );
    let target_page = runner
        .pages
        .get(&target)
        .ok_or_else(|| io::Error::other("cached target page was lost"))?;
    assert_eq!(target_page.minimum_link_depth, Some(1));
    assert_eq!(target_page.exploration, Exploration::Inspected);
    let child_page = runner
        .pages
        .get(&child)
        .ok_or_else(|| io::Error::other("child was not requeued at the shorter depth"))?;
    assert_eq!(child_page.minimum_link_depth, Some(2));
    assert_eq!(child_page.exploration, Exploration::Inspected);
    Ok(())
}

#[tokio::test]
async fn shorter_failed_page_keeps_failure_without_a_second_request() -> TestResult {
    let policy = Policy::default();
    let mut routes = support_routes();
    routes.push((
        "/missing".to_owned(),
        FixtureResponse::bytes(404, Some("text/plain"), b"missing"),
    ));
    let service = FixtureService::start(Protocol::Http, routes).await;
    let root = Url::parse(&service.url("/"))?;
    let missing = Url::parse(&service.url("/missing"))?;
    let cancellation = CancellationToken::new();
    let mut runner = runner(&policy, &cancellation, root)?;

    assert!(runner.page(missing.clone(), Some(2), DiscoverySource::HtmlLink, None));
    runner.explore_pages().await;
    assert!(runner.page(missing.clone(), Some(1), DiscoverySource::HtmlLink, None));
    runner.explore_pages().await;

    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    assert_eq!(
        paths
            .iter()
            .filter(|path| path.as_str() == "/missing")
            .count(),
        1
    );
    let page = runner
        .pages
        .get(&missing)
        .ok_or_else(|| io::Error::other("failed page was lost during shorter-path reuse"))?;
    assert_eq!(page.minimum_link_depth, Some(1));
    assert_eq!(
        page.exploration,
        Exploration::Failed(SourceFailure::HttpStatus(404))
    );
    assert_eq!(runner.queue.len(), 0);
    Ok(())
}
