#![allow(clippy::panic_in_result_fn)]

use crate::internal::test_support::direct_http_fixture as fixture;

use std::{error::Error, io, sync::Arc, time::Duration};

use crate::internal::engine::prelude as ys;
use crate::internal::map::admission::Rejection;
use fixture::{
    FixtureService, Protocol, RequestLine, Response as FixtureResponse, ResponseControl,
};
use tokio::time::timeout;
use url::Url;

type TestResult = Result<(), Box<dyn Error + Send + Sync>>;

fn support_misses() -> Vec<(String, FixtureResponse)> {
    ["/robots.txt", "/sitemap.xml", "/sitemap_index.xml"]
        .into_iter()
        .map(|path| {
            (
                path.to_owned(),
                FixtureResponse::bytes(404, Some("text/plain; charset=utf-8"), b""),
            )
        })
        .collect()
}

fn set_route(routes: &mut Vec<(String, FixtureResponse)>, path: &str, response: FixtureResponse) {
    if let Some((_, existing)) = routes.iter_mut().find(|(route, _)| route.as_str() == path) {
        *existing = response;
    } else {
        routes.push((path.to_owned(), response));
    }
}

fn set_html_route(routes: &mut Vec<(String, FixtureResponse)>, path: &str, body: &[u8]) {
    set_route(
        routes,
        path,
        FixtureResponse::bytes(200, Some("text/html; charset=utf-8"), body),
    );
}

fn request_count(requests: &[RequestLine], expected: &str) -> usize {
    requests
        .iter()
        .filter(|request| request.path == expected)
        .count()
}

fn page_at<'outcome>(
    outcome: &'outcome ys::MapOutcome,
    path: &str,
) -> Option<&'outcome ys::map::PageEntry> {
    outcome.pages().iter().find(|page| page.url.path() == path)
}

fn missing(message: &'static str) -> io::Error {
    io::Error::other(message)
}

#[tokio::test]
async fn canonical_hints_do_not_become_discovery_or_tree_edges() -> TestResult {
    let mut routes = support_misses();
    set_html_route(
        &mut routes,
        "/",
        br#"<head><link rel="alternate CANONICAL" href="/canonical"></head>
            <main><a href="/alias">alias</a></main>"#,
    );
    set_html_route(
        &mut routes,
        "/alias",
        br#"<head><link rel="canonical" href="/detached"></head><main>alias</main>"#,
    );
    set_html_route(&mut routes, "/canonical", b"<main>canonical</main>");
    if let Some((_, response)) = routes
        .iter_mut()
        .find(|(route, _)| route.as_str() == "/sitemap.xml")
    {
        *response = FixtureResponse::bytes(
            200,
            Some("application/xml; charset=utf-8"),
            br#"<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                <url><loc>/detached</loc></url>
            </urlset>"#,
        );
    }
    let service = FixtureService::start(Protocol::Http, routes).await;
    let seed = Url::parse(&service.url("/"))?;
    let alias = seed.join("/alias")?;
    let canonical_only = seed.join("/canonical")?;
    let detached = seed.join("/detached")?;

    let outcome = ys::map::new(seed.as_str()).send().await?;
    let requests = service.requests().await;
    service.shutdown().await;

    assert_eq!(outcome.pages().len(), 3);
    assert!(page_at(&outcome, "/").is_some());
    assert!(page_at(&outcome, "/alias").is_some());
    assert!(page_at(&outcome, "/canonical").is_none());
    assert_eq!(
        page_at(&outcome, "/detached")
            .ok_or_else(|| missing("sitemap-only page is missing"))?
            .minimum_link_depth,
        None
    );
    assert_eq!(request_count(&requests, "/alias"), 1);
    assert_eq!(request_count(&requests, "/canonical"), 0);
    assert_eq!(request_count(&requests, "/detached"), 0);
    assert!(outcome.relationships().iter().any(|relationship| {
        relationship.kind == ys::map::RelationshipKind::Canonical
            && relationship.from == seed
            && relationship.to == canonical_only
    }));
    assert!(outcome.relationships().iter().any(|relationship| {
        relationship.kind == ys::map::RelationshipKind::Canonical
            && relationship.from == alias
            && relationship.to == detached
    }));
    assert!(outcome.relationships().iter().any(|relationship| {
        relationship.kind == ys::map::RelationshipKind::Link
            && relationship.from == seed
            && relationship.to == alias
    }));
    assert_eq!(outcome.tree().len(), 3);
    assert_eq!(
        outcome
            .tree()
            .iter()
            .find(|entry| entry.page == alias)
            .and_then(|entry| entry.parent.as_ref()),
        Some(&seed)
    );
    let detached_tree = outcome
        .tree()
        .iter()
        .find(|entry| entry.page == detached)
        .ok_or_else(|| missing("sitemap-only tree entry is missing"))?;
    assert_eq!(detached_tree.parent, None);
    assert_eq!(detached_tree.depth, None);
    Ok(())
}

#[tokio::test]
async fn cross_host_canonical_hint_is_normalized_without_scope_or_fetch() -> TestResult {
    let mut canonical = Url::parse("http://127.0.0.2:1/external-canonical")?;
    canonical.set_query(Some("view=canonical"));
    canonical.set_fragment(Some("discard-this-fragment"));
    let mut expected_canonical = canonical.clone();
    expected_canonical.set_fragment(None);
    let body = format!("<link rel=\"canonical\" href=\"{}\">", canonical.as_str());

    let mut routes = support_misses();
    set_html_route(&mut routes, "/", body.as_bytes());
    let service = FixtureService::start(Protocol::Http, routes).await;
    let seed = Url::parse(&service.url("/"))?;
    let outcome = ys::map::new(seed.as_str()).send().await?;
    let requests = service.requests().await;
    service.shutdown().await;

    assert_eq!(outcome.pages().len(), 1);
    assert_eq!(page_at(&outcome, "/").map(|page| &page.url), Some(&seed));
    assert!(outcome.relationships().iter().any(|relationship| {
        relationship.kind == ys::map::RelationshipKind::Canonical
            && relationship.from == seed
            && relationship.to == expected_canonical
    }));
    assert_eq!(outcome.summary().requests, 4);
    assert!(
        requests
            .iter()
            .all(|request| request.path != "/external-canonical")
    );
    assert!(
        outcome
            .request_trace()
            .iter()
            .all(|trace| trace.target.host_str() != Some("127.0.0.2"))
    );
    Ok(())
}

#[tokio::test]
async fn off_host_robots_sitemap_is_typed_and_never_dispatched() -> TestResult {
    let external_xml = br#"<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <url><loc>http://127.0.0.1/should-not-be-read</loc></url>
    </urlset>"#;
    let external = FixtureService::start(
        Protocol::Http,
        vec![(
            "/published.xml".to_owned(),
            FixtureResponse::bytes(200, Some("application/xml"), external_xml),
        )],
    )
    .await;
    let mut external_sitemap = Url::parse(&external.url("/published.xml"))?;
    if external_sitemap.set_host(Some("localhost")).is_err() {
        return Err(missing("test off-host sitemap hostname was rejected").into());
    }
    let robots = format!("User-agent: YosoiMap\nSitemap: {external_sitemap}\n");

    let mut routes = support_misses();
    set_route(
        &mut routes,
        "/robots.txt",
        FixtureResponse::bytes(200, Some("text/plain; charset=utf-8"), robots.as_bytes()),
    );
    set_html_route(&mut routes, "/", b"<main>seed</main>");
    let mapped = FixtureService::start(Protocol::Http, routes).await;
    let outcome = ys::map::new(mapped.url("/")).send().await?;
    let external_requests = external.requests().await;
    let mapped_requests = mapped.requests().await;
    external.shutdown().await;
    mapped.shutdown().await;

    assert_eq!(external_requests.len(), 0);
    assert!(
        !mapped_requests
            .iter()
            .any(|request| request.path == "/published.xml")
    );
    assert!(outcome.omissions().iter().any(|omission| {
        omission.reason == ys::map::OmissionReason::Admission(Rejection::OriginScope)
            && omission.count > 0
    }));
    assert!(
        outcome
            .request_trace()
            .iter()
            .all(|trace| trace.target != external_sitemap)
    );
    assert_eq!(outcome.summary().requests, 4);
    assert!(page_at(&outcome, "/").is_some());
    Ok(())
}

#[tokio::test]
async fn request_deadline_before_response_head_is_not_the_map_deadline() -> TestResult {
    let mut routes = support_misses();
    let control = Arc::new(ResponseControl {
        hold_before_head: true,
        ..ResponseControl::default()
    });
    let mut held = FixtureResponse::bytes(
        200,
        Some("text/html; charset=utf-8"),
        b"<main>request deadline</main>",
    );
    held.control = Some(control.clone());
    routes.push(("/".to_owned(), held));
    let service = FixtureService::start(Protocol::Http, routes).await;

    let mut policy = ys::Policy::default();
    policy.map.limits.maximum_elapsed = Duration::from_secs(5);
    policy.request.maximum_elapsed = ys::policy::MaximumElapsed::try_from(500_000)?;
    let seed = service.url("/");
    let task = tokio::spawn(async move { ys::map::new(seed).bind(&policy).send().await });

    timeout(Duration::from_secs(3), control.requested.wait()).await?;
    let result = timeout(Duration::from_secs(3), task).await??;
    let outcome = result?;
    control.allow_head.signal();
    timeout(Duration::from_secs(5), control.connection_finished.wait()).await?;
    let requests = service.requests().await;
    service.shutdown().await;

    assert_eq!(request_count(&requests, "/"), 1);
    assert_eq!(outcome.termination(), ys::map::MapTermination::Exhausted);
    assert_eq!(
        page_at(&outcome, "/")
            .ok_or_else(|| missing("held seed is missing"))?
            .exploration,
        ys::map::Exploration::Failed(ys::map::SourceFailure::IncompleteDocument)
    );
    assert!(outcome.sources().iter().any(|source| {
        source.source == ys::map::DiscoverySource::HtmlLink
            && source.status
                == ys::map::SourceStatus::Failed(ys::map::SourceFailure::IncompleteDocument)
    }));
    Ok(())
}

#[tokio::test]
async fn absolute_map_deadline_cancels_a_held_request_and_preserves_frontier() -> TestResult {
    let mut routes = support_misses();
    set_html_route(
        &mut routes,
        "/",
        br#"<main><a href="/held">held</a><a href="/later">later</a></main>"#,
    );
    set_html_route(&mut routes, "/later", b"<main>later</main>");

    let control = Arc::new(ResponseControl {
        hold_after_chunks: true,
        ..ResponseControl::default()
    });
    let mut held = FixtureResponse::bytes(200, Some("text/html; charset=utf-8"), b"<main>partial");
    held.chunks = vec![b"<main>partial".to_vec()];
    held.raw_headers
        .retain(|header| !header.starts_with(b"Content-Length:"));
    held.raw_headers.push(b"Content-Length: 1024".to_vec());
    held.control = Some(control.clone());
    routes.push(("/held".to_owned(), held));
    let service = FixtureService::start(Protocol::Http, routes).await;

    let mut policy = ys::Policy::default();
    policy.map.limits.max_concurrency = ys::policy::Budget::new(1)?;
    policy.map.limits.maximum_elapsed = Duration::from_millis(500);
    policy.request.maximum_elapsed = ys::policy::MaximumElapsed::try_from(10_000_000)?;
    assert!(policy.request.maximum_elapsed.as_microseconds() > 500_000);
    let seed = service.url("/");
    let task = tokio::spawn(async move { ys::map::new(seed).bind(&policy).send().await });

    timeout(Duration::from_secs(5), control.requested.wait()).await?;
    timeout(Duration::from_secs(5), control.chunk_written.wait()).await?;
    let result = timeout(Duration::from_secs(5), task).await??;
    let outcome = result?;

    // Let the controlled fixture finish its write/close path after the client
    // has cancelled, then wait for its explicit cleanup event.
    control.allow_next_chunk.signal();
    timeout(Duration::from_secs(5), control.connection_finished.wait()).await?;
    let requests = service.requests().await;
    service.shutdown().await;

    assert_eq!(outcome.termination(), ys::map::MapTermination::Deadline);
    assert_eq!(request_count(&requests, "/held"), 1);
    assert_eq!(request_count(&requests, "/later"), 0);
    let held_page = page_at(&outcome, "/held").ok_or_else(|| missing("held page missing"))?;
    let later_page = page_at(&outcome, "/later").ok_or_else(|| missing("later page missing"))?;
    assert_eq!(held_page.exploration, ys::map::Exploration::Pending);
    assert_eq!(later_page.exploration, ys::map::Exploration::Pending);
    assert!(outcome.frontier().iter().any(|entry| {
        entry.page.path() == "/held" && entry.reason == ys::map::PendingReason::OperationStopped
    }));
    assert!(outcome.frontier().iter().any(|entry| {
        entry.page.path() == "/later" && entry.reason == ys::map::PendingReason::OperationStopped
    }));
    assert!(outcome.sources().iter().any(|source| {
        source.source == ys::map::DiscoverySource::HtmlLink
            && source.status == ys::map::SourceStatus::Truncated
    }));
    assert!(!outcome.sources().iter().any(|source| {
        matches!(
            &source.status,
            ys::map::SourceStatus::Failed(ys::map::SourceFailure::Transport)
        )
    }));
    Ok(())
}
