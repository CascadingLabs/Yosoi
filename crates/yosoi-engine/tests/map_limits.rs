#![allow(clippy::panic_in_result_fn)]

#[path = "../../yosoi-web-capture-direct-http/tests/support/direct_http_fixture.rs"]
mod fixture;

use std::{error::Error, fmt::Write as _, io};

use fixture::{FixtureService, Protocol, RequestLine, Response as FixtureResponse};
use yosoi_engine::prelude as ys;

type TestResult<T = ()> = Result<T, Box<dyn Error + Send + Sync>>;

fn misses() -> Vec<(String, FixtureResponse)> {
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

fn html(routes: &mut Vec<(String, FixtureResponse)>, path: &str, body: &[u8]) {
    routes.push((
        path.to_owned(),
        FixtureResponse::bytes(200, Some("text/html; charset=utf-8"), body),
    ));
}

fn budget(value: u32) -> TestResult<ys::policy::Budget> {
    Ok(ys::policy::Budget::new(value)?)
}

fn page_at<'outcome>(
    outcome: &'outcome ys::MapOutcome,
    path: &str,
) -> Option<&'outcome ys::map::PageEntry> {
    let (expected_path, expected_query) = path
        .split_once('?')
        .map_or((path, None), |(path, query)| (path, Some(query)));
    outcome
        .pages()
        .iter()
        .find(|page| page.url.path() == expected_path && page.url.query() == expected_query)
}

fn request_paths(requests: &[RequestLine]) -> Vec<String> {
    requests
        .iter()
        .map(|request| request.path.clone())
        .collect()
}

fn request_count(paths: &[String], expected: &str) -> usize {
    paths
        .iter()
        .filter(|path| path.as_str() == expected)
        .count()
}

fn missing(message: &'static str) -> io::Error {
    io::Error::other(message)
}

#[tokio::test]
async fn same_host_url_limit_is_independent_and_depth_zero_still_inspects_the_seed() -> TestResult {
    let mut routes = misses();
    html(
        &mut routes,
        "/",
        br#"<a href="/one">one</a><a href="/two">two</a>"#,
    );
    html(&mut routes, "/one", b"<main>one</main>");
    html(&mut routes, "/two", b"<main>two</main>");
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    policy.map.limits.max_hosts = budget(1)?;
    policy.map.limits.max_urls = budget(2)?;
    policy.map.limits.max_link_depth = 0;

    let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    assert_eq!(outcome.hosts().len(), 1);
    assert_eq!(outcome.pages().len(), 2);
    assert!(page_at(&outcome, "/").is_some());
    assert!(page_at(&outcome, "/one").is_some());
    assert!(page_at(&outcome, "/two").is_none());
    let seed = page_at(&outcome, "/").ok_or_else(|| missing("seed is missing"))?;
    assert_eq!(seed.exploration, ys::map::Exploration::Inspected);
    assert_eq!(
        page_at(&outcome, "/one")
            .ok_or_else(|| missing("first child is missing"))?
            .exploration,
        ys::map::Exploration::Skipped(ys::map::SkipReason::Depth)
    );
    assert_eq!(request_count(&paths, "/"), 1);
    assert_eq!(request_count(&paths, "/one"), 0);
    assert_eq!(request_count(&paths, "/two"), 0);
    assert_eq!(
        outcome.termination(),
        ys::map::MapTermination::Limit(ys::map::LimitReached::Urls)
    );
    Ok(())
}

#[tokio::test]
async fn relationship_limit_keeps_discovered_pages_and_bounds_edges() -> TestResult {
    let mut routes = misses();
    html(
        &mut routes,
        "/",
        br#"<a href="/one">one</a><a href="/two">two</a>"#,
    );
    html(&mut routes, "/one", b"<main>one</main>");
    html(&mut routes, "/two", b"<main>two</main>");
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    policy.map.limits.max_link_depth = 0;
    policy.map.limits.max_relationships = budget(1)?;

    let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    assert!(page_at(&outcome, "/").is_some());
    assert!(page_at(&outcome, "/one").is_some());
    assert!(page_at(&outcome, "/two").is_some());
    assert_eq!(outcome.relationships().len(), 1);
    assert_eq!(
        request_count(&paths, "/one") + request_count(&paths, "/two"),
        0
    );
    assert_eq!(
        outcome.termination(),
        ys::map::MapTermination::Limit(ys::map::LimitReached::Relationships)
    );
    Ok(())
}

#[tokio::test]
async fn observation_limit_is_reported_without_exceeding_its_count() -> TestResult {
    let mut routes = misses();
    html(&mut routes, "/", br#"<a href="/child">child</a>"#);
    html(&mut routes, "/child", b"<main>child</main>");
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    policy.map.limits.max_observations = budget(2)?;

    let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
    service.shutdown().await;

    assert!(page_at(&outcome, "/").is_some());
    assert!(outcome.summary().observations <= 2);
    assert_eq!(outcome.summary().observations, 2);
    assert_eq!(
        outcome.termination(),
        ys::map::MapTermination::Limit(ys::map::LimitReached::Observations)
    );
    Ok(())
}

#[tokio::test]
async fn url_byte_limit_also_guards_support_requests_before_dispatch() -> TestResult {
    let service = FixtureService::start(Protocol::Http, misses()).await;
    let seed = service.url("/");
    let mut policy = ys::Policy::default();
    policy.map.robots = ys::policy::Robots::Respect;
    policy.map.limits.max_url_bytes = budget(u32::try_from(seed.len())?)?;

    let outcome = ys::map::new(seed).bind(&policy).send().await?;
    let requests = service.requests().await;
    service.shutdown().await;

    assert_eq!(requests.len(), 0);
    assert!(outcome.support_documents().iter().any(|document| {
        document.kind == ys::map::SupportDocumentKind::Robots
            && document.status
                == ys::map::SourceStatus::Failed(ys::map::SourceFailure::RedirectRejected)
    }));
    assert_eq!(outcome.summary().requests, 0);
    Ok(())
}

#[tokio::test]
async fn inventory_byte_limit_preserves_the_seed_and_bounds_accounting() -> TestResult {
    let mut routes = misses();
    let mut root = String::from("<main>");
    for number in 0..50 {
        write!(root, "<a href=\"/item-{number:02}\">item</a>")?;
    }
    root.push_str("</main>");
    html(&mut routes, "/", root.as_bytes());
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    policy.map.limits.max_link_depth = 0;
    policy.map.limits.max_inventory_bytes = budget(4_096)?;

    let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
    service.shutdown().await;

    assert!(page_at(&outcome, "/").is_some());
    assert!(outcome.summary().inventory_bytes <= 4_096);
    assert_eq!(
        outcome.termination(),
        ys::map::MapTermination::Limit(ys::map::LimitReached::InventoryBytes)
    );
    Ok(())
}

#[tokio::test]
async fn pending_limit_bounds_frontier_while_retaining_discovered_pages() -> TestResult {
    let mut routes = misses();
    html(
        &mut routes,
        "/",
        br#"<a href="/one">one</a><a href="/two">two</a><a href="/three">three</a>"#,
    );
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    policy.map.limits.max_link_depth = 1;
    policy.map.limits.max_pending = budget(1)?;

    let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    for path in ["/one", "/two", "/three"] {
        let page = page_at(&outcome, path)
            .ok_or_else(|| missing("discovered child was dropped from inventory"))?;
        assert_eq!(page.minimum_link_depth, Some(1));
        assert_eq!(request_count(&paths, path), 0);
    }
    assert!(outcome.frontier().len() <= 1);
    assert_eq!(
        outcome.termination(),
        ys::map::MapTermination::Limit(ys::map::LimitReached::Pending)
    );
    Ok(())
}

#[tokio::test]
async fn robots_parser_entry_limit_blocks_pages_and_keeps_a_typed_source_outcome() -> TestResult {
    let mut routes = misses();
    routes.push((
        "/robots.txt".to_owned(),
        FixtureResponse::bytes(
            200,
            Some("text/plain; charset=utf-8"),
            b"User-agent: YosoiMap\nDisallow: /private\n",
        ),
    ));
    html(&mut routes, "/", b"<main>must remain unfetched</main>");
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    policy.map.robots = ys::policy::Robots::Respect;
    policy.map.limits.max_parser_entries = budget(1)?;

    let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    assert_eq!(request_count(&paths, "/robots.txt"), 1);
    assert_eq!(request_count(&paths, "/"), 0);
    let seed = page_at(&outcome, "/").ok_or_else(|| missing("seed was not inventoried"))?;
    assert_eq!(
        seed.exploration,
        ys::map::Exploration::Skipped(ys::map::SkipReason::Robots)
    );
    assert!(outcome.support_documents().iter().any(|document| {
        document.kind == ys::map::SupportDocumentKind::Robots
            && document.status == ys::map::SourceStatus::Failed(ys::map::SourceFailure::Parse)
    }));
    Ok(())
}

#[tokio::test]
async fn sitemap_count_stops_before_dispatching_the_next_document() -> TestResult {
    let mut routes = misses();
    routes.push((
        "/robots.txt".to_owned(),
        FixtureResponse::bytes(
            200,
            Some("text/plain; charset=utf-8"),
            b"User-agent: YosoiMap\nSitemap: /index.xml\n",
        ),
    ));
    routes.push((
        "/index.xml".to_owned(),
        FixtureResponse::bytes(
            200,
            Some("application/xml; charset=utf-8"),
            br#"<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                <sitemap><loc>/nested.xml</loc></sitemap>
            </sitemapindex>"#,
        ),
    ));
    routes.push((
        "/nested.xml".to_owned(),
        FixtureResponse::bytes(200, Some("application/xml; charset=utf-8"), b"<urlset/>"),
    ));
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    policy.map.limits.max_sitemaps = budget(1)?;

    let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    assert_eq!(request_count(&paths, "/index.xml"), 1);
    assert_eq!(request_count(&paths, "/nested.xml"), 0);
    assert_eq!(request_count(&paths, "/"), 0);
    assert_eq!(
        outcome.termination(),
        ys::map::MapTermination::Limit(ys::map::LimitReached::Sitemaps)
    );
    Ok(())
}

#[tokio::test]
async fn sitemap_index_depth_does_not_fetch_deeper_indexes() -> TestResult {
    let mut routes = misses();
    routes.push((
        "/robots.txt".to_owned(),
        FixtureResponse::bytes(
            200,
            Some("text/plain; charset=utf-8"),
            b"User-agent: YosoiMap\nSitemap: /index-one.xml\n",
        ),
    ));
    for (path, child) in [
        ("/index-one.xml", "/index-two.xml"),
        ("/index-two.xml", "/index-three.xml"),
        ("/index-three.xml", "/index-four.xml"),
    ] {
        let body = format!(
            "<sitemapindex xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\"><sitemap><loc>{child}</loc></sitemap></sitemapindex>"
        );
        routes.push((
            path.to_owned(),
            FixtureResponse::bytes(200, Some("application/xml; charset=utf-8"), body.as_bytes()),
        ));
    }
    html(&mut routes, "/", b"<main>seed</main>");
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    policy.map.limits.max_sitemap_depth = 1;

    let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    for path in ["/index-one.xml", "/index-two.xml"] {
        assert_eq!(request_count(&paths, path), 1);
    }
    assert_eq!(request_count(&paths, "/index-three.xml"), 0);
    assert_eq!(request_count(&paths, "/"), 1);
    assert_eq!(outcome.termination(), ys::map::MapTermination::Exhausted);
    Ok(())
}

#[tokio::test]
async fn malicious_base_cannot_expand_seed_host_scope() -> TestResult {
    let mut routes = misses();
    let service = FixtureService::start(Protocol::Http, misses()).await;
    let outside = service.url("/outside").replace("localhost", "127.0.0.1");
    let body = format!("<base href=\"{outside}\"><a href=\"/outside\">outside</a>");
    html(&mut routes, "/", body.as_bytes());
    html(&mut routes, "/outside", b"<main>outside</main>");
    let map_service = FixtureService::start(Protocol::Http, routes).await;

    let outcome = ys::map::new(map_service.url("/")).send().await?;
    let paths = request_paths(&map_service.requests().await);
    map_service.shutdown().await;
    let outside_requests = service.requests().await;
    service.shutdown().await;

    assert!(page_at(&outcome, "/").is_some());
    assert!(page_at(&outcome, "/outside").is_none());
    assert!(
        !outside_requests
            .iter()
            .any(|request| request.path == "/outside")
    );
    assert_eq!(request_count(&paths, "/outside"), 0);
    Ok(())
}

#[tokio::test]
async fn cross_host_redirect_is_rejected_before_the_target_request() -> TestResult {
    let outside = FixtureService::start(
        Protocol::Http,
        vec![(
            "/outside".to_owned(),
            FixtureResponse::bytes(
                200,
                Some("text/html; charset=utf-8"),
                b"<main>outside</main>",
            ),
        )],
    )
    .await;
    let mut routes = misses();
    html(&mut routes, "/", br#"<a href="/escape">escape</a>"#);
    let outside_url = outside.url("/outside").replace("localhost", "127.0.0.1");
    routes.push((
        "/escape".to_owned(),
        FixtureResponse::redirect(&outside_url),
    ));
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    policy.request.direct_http_redirects = ys::DirectHttpRedirects::Follow {
        max_hops: ys::RedirectHopLimit::try_from(2)?,
        targets: ys::DirectHttpRedirectTargets::AllowHttpAndHttps,
    };

    let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;
    let outside_requests = outside.requests().await;
    outside.shutdown().await;

    assert_eq!(request_count(&paths, "/escape"), 1);
    assert_eq!(
        page_at(&outcome, "/escape")
            .ok_or_else(|| missing("redirect source was not inventoried"))?
            .exploration,
        ys::map::Exploration::Failed(ys::map::SourceFailure::RedirectRejected)
    );
    assert_eq!(outside_requests.len(), 0);
    Ok(())
}

#[tokio::test]
async fn canonical_url_identity_keeps_trailing_slash_query_order_and_case() -> TestResult {
    let mut routes = misses();
    html(
        &mut routes,
        "/",
        br#"<a href="/Case">case</a><a href="/case">lower</a>
            <a href="/topic">plain</a><a href="/topic/">slash</a>
            <a href="/query?a=1&b=2">ordered</a><a href="/query?b=2&a=1">reversed</a>"#,
    );
    for path in [
        "/Case",
        "/case",
        "/topic",
        "/topic/",
        "/query?a=1&b=2",
        "/query?b=2&a=1",
    ] {
        html(&mut routes, path, b"<main>page</main>");
    }
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    policy.map.limits.max_link_depth = 1;

    let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    for path in [
        "/Case",
        "/case",
        "/topic",
        "/topic/",
        "/query?a=1&b=2",
        "/query?b=2&a=1",
    ] {
        assert!(page_at(&outcome, path).is_some(), "{path}");
        assert_eq!(request_count(&paths, path), 1, "{path}");
    }
    assert_eq!(outcome.pages().len(), 7);
    Ok(())
}

#[tokio::test]
async fn retention_byte_limit_omits_capture_without_losing_inspection() -> TestResult {
    let mut routes = misses();
    html(
        &mut routes,
        "/",
        b"<main>a response larger than one byte</main>",
    );
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    policy.map.documents = ys::policy::DiscoveryDocuments::RetainWithinBudget;
    policy.map.limits.max_retained_document_bytes = budget(1)?;

    let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
    service.shutdown().await;

    assert_eq!(outcome.captures().len(), 0);
    assert_eq!(outcome.summary().retained_document_bytes, 0);
    assert_eq!(
        page_at(&outcome, "/")
            .ok_or_else(|| missing("seed disappeared after retention limit"))?
            .exploration,
        ys::map::Exploration::Inspected
    );
    assert!(outcome.sources().iter().any(|source| {
        source.status == ys::map::SourceStatus::Failed(ys::map::SourceFailure::RetentionLimit)
    }));
    Ok(())
}

#[tokio::test]
async fn disabled_page_exploration_still_inventories_the_seed_host() -> TestResult {
    let service = FixtureService::start(Protocol::Http, misses()).await;
    let mut policy = ys::Policy::default();
    policy.map.pages = ys::policy::PageDiscovery::Disabled;

    let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
    let requests = service.requests().await;
    service.shutdown().await;

    assert_eq!(outcome.hosts().len(), 1);
    assert_eq!(
        outcome
            .hosts()
            .first()
            .ok_or_else(|| missing("seed host is missing"))?
            .host,
        "localhost"
    );
    assert_eq!(outcome.pages().len(), 0);
    assert_eq!(requests.len(), 0);
    assert_eq!(outcome.termination(), ys::map::MapTermination::Exhausted);
    Ok(())
}
