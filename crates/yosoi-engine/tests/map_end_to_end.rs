#![allow(clippy::panic_in_result_fn)]

#[path = "../../yosoi-web-capture-direct-http/tests/support/direct_http_fixture.rs"]
mod fixture;

use std::{error::Error, fmt::Write as _, io, sync::Arc, time::Duration};

use fixture::{
    FixtureService, Protocol, RequestLine, Response as FixtureResponse, ResponseControl,
};
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;
use yosoi_engine::prelude as ys;

type TestResult<T = ()> = Result<T, Box<dyn Error + Send + Sync>>;

const GZIP_SITEMAP: &[u8] = &[
    31, 139, 8, 0, 0, 0, 0, 0, 2, 255, 179, 41, 45, 202, 41, 78, 45, 177, 179, 1, 210, 118, 54, 57,
    249, 201, 118, 250, 233, 85, 153, 5, 186, 249, 121, 57, 149, 54, 250, 32, 190, 141, 62, 88, 74,
    31, 170, 16, 0, 160, 80, 114, 236, 49, 0, 0, 0,
];
const AGGREGATE_GZIP_XML_BYTES: usize = 4_157;
const AGGREGATE_GZIP_SITEMAP: &[u8] = &[
    31, 139, 8, 0, 0, 0, 0, 0, 2, 255, 237, 216, 209, 9, 128, 48, 12, 69, 209, 89, 28, 32, 100,
    129, 144, 101, 164, 72, 33, 180, 82, 91, 81, 167, 23, 197, 41, 228, 158, 207, 251, 54, 120, 54,
    90, 108, 169, 187, 77, 34, 7, 0, 0, 0, 0, 0, 248, 61, 17, 183, 209, 194, 45, 234, 236, 186, 92,
    121, 149, 92, 246, 84, 122, 109, 167, 233, 19, 77, 223, 93, 191, 211, 224, 6, 54, 47, 98, 129,
    61, 16, 0, 0,
];

fn support_miss_routes() -> Vec<(String, FixtureResponse)> {
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

fn add_html_route(routes: &mut Vec<(String, FixtureResponse)>, path: &str, body: &[u8]) {
    routes.push((
        path.to_owned(),
        FixtureResponse::bytes(200, Some("text/html; charset=utf-8"), body),
    ));
}

fn request_paths(requests: &[RequestLine]) -> Vec<String> {
    requests
        .iter()
        .map(|request| request.path.clone())
        .collect()
}

fn requests_for(paths: &[String], expected: &str) -> usize {
    paths
        .iter()
        .filter(|path| path.as_str() == expected)
        .count()
}

fn page_at<'outcome>(
    outcome: &'outcome ys::MapOutcome,
    path: &str,
) -> Option<&'outcome ys::map::PageEntry> {
    outcome.pages().iter().find(|page| page.url.path() == path)
}

fn tree_at<'outcome>(
    outcome: &'outcome ys::MapOutcome,
    path: &str,
) -> Option<&'outcome ys::map::TreeEntry> {
    outcome
        .tree()
        .iter()
        .find(|entry| entry.page.path() == path)
}

fn map_budget(value: u32) -> TestResult<ys::policy::Budget> {
    Ok(ys::policy::Budget::new(value)?)
}

fn missing_page(message: &'static str) -> io::Error {
    io::Error::other(message)
}

#[tokio::test]
async fn ten_root_links_form_a_tree_while_sitemap_entries_stay_metadata_only() -> TestResult {
    let mut routes = support_miss_routes();
    let mut root = String::from("<!doctype html><main>");
    for index in 0..10 {
        write!(root, "<a href=\"/link-{index}\">link {index}</a>")?;
    }
    root.push_str("</main>");
    add_html_route(&mut routes, "/", root.as_bytes());
    routes.push((
        "/sitemap.xml".to_owned(),
        FixtureResponse::bytes(
            200,
            Some("application/xml; charset=utf-8"),
            br#"<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                <url><loc>/metadata-one</loc></url>
                <url><loc>/metadata-two</loc></url>
            </urlset>"#,
        ),
    ));
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    policy.map.limits.max_link_depth = 0;

    let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    assert_eq!(outcome.pages().len(), 13);
    assert_eq!(requests_for(&paths, "/"), 1);
    let root_page =
        page_at(&outcome, "/").ok_or_else(|| missing_page("seed was not inventoried"))?;
    assert_eq!(root_page.exploration, ys::map::Exploration::Inspected);
    let root_tree =
        tree_at(&outcome, "/").ok_or_else(|| missing_page("seed is absent from tree"))?;
    assert_eq!(root_tree.depth, Some(0));
    for index in 0..10 {
        let path = format!("/link-{index}");
        let page =
            page_at(&outcome, &path).ok_or_else(|| missing_page("link was not inventoried"))?;
        assert_eq!(page.minimum_link_depth, Some(1));
        assert!(
            page.observations
                .iter()
                .any(|observation| observation.source == ys::map::DiscoverySource::HtmlLink)
        );
        assert_eq!(
            page.exploration,
            ys::map::Exploration::Skipped(ys::map::SkipReason::Depth)
        );
        assert_eq!(requests_for(&paths, &path), 0);
        let tree =
            tree_at(&outcome, &path).ok_or_else(|| missing_page("link is absent from tree"))?;
        assert_eq!(tree.depth, Some(1));
        assert_eq!(tree.parent.as_ref().map(url::Url::path), Some("/"));
    }
    for path in ["/metadata-one", "/metadata-two"] {
        let page = page_at(&outcome, path)
            .ok_or_else(|| missing_page("sitemap location was not inventoried"))?;
        assert_eq!(page.minimum_link_depth, None);
        assert_eq!(page.exploration, ys::map::Exploration::Inventoried);
        assert!(
            page.observations
                .iter()
                .any(|observation| observation.source == ys::map::DiscoverySource::Sitemap)
        );
        assert_eq!(requests_for(&paths, path), 0);
        let tree =
            tree_at(&outcome, path).ok_or_else(|| missing_page("metadata is absent from tree"))?;
        assert_eq!(tree.depth, None);
        assert!(tree.parent.is_none());
    }
    assert_eq!(outcome.termination(), ys::map::MapTermination::Exhausted);
    Ok(())
}

#[tokio::test]
async fn gzip_sitemap_media_uses_bounded_raw_response_bytes() -> TestResult {
    let mut routes = support_miss_routes();
    add_html_route(&mut routes, "/", b"<main>seed</main>");
    routes.push((
        "/sitemap.xml".to_owned(),
        FixtureResponse::bytes(200, Some("application/gzip"), GZIP_SITEMAP),
    ));
    let service = FixtureService::start(Protocol::Http, routes).await;

    let outcome = ys::map::new(service.url("/")).send().await?;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    let sitemap_entry = page_at(&outcome, "/gzip-only")
        .ok_or_else(|| missing_page("gzip sitemap location was not inventoried"))?;
    assert!(
        sitemap_entry
            .observations
            .iter()
            .any(|observation| observation.source == ys::map::DiscoverySource::Sitemap)
    );
    assert_eq!(requests_for(&paths, "/gzip-only"), 0);
    assert!(outcome.support_documents().iter().any(|support| {
        support.url.path() == "/sitemap.xml" && support.status == ys::map::SourceStatus::Completed
    }));
    Ok(())
}

#[tokio::test]
async fn aggregate_response_budget_counts_decoded_bytes_from_multiple_gzip_sitemaps() -> TestResult
{
    let robots_body = b"User-agent: YosoiMap\nSitemap: /gzip-one.xml\nSitemap: /gzip-two.xml\n";
    let mut routes = support_miss_routes();
    routes.push((
        "/robots.txt".to_owned(),
        FixtureResponse::bytes(200, Some("text/plain; charset=utf-8"), robots_body),
    ));
    for path in ["/gzip-one.xml", "/gzip-two.xml"] {
        routes.push((
            path.to_owned(),
            FixtureResponse::bytes(200, Some("application/gzip"), AGGREGATE_GZIP_SITEMAP),
        ));
    }
    add_html_route(&mut routes, "/", b"<main>seed</main>");
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    let total_limit = robots_body
        .len()
        .saturating_add(AGGREGATE_GZIP_XML_BYTES)
        .saturating_add(AGGREGATE_GZIP_SITEMAP.len())
        .saturating_add(1);
    policy.map.limits.max_total_response_bytes = map_budget(u32::try_from(total_limit)?)?;

    let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    assert_eq!(requests_for(&paths, "/gzip-one.xml"), 1);
    assert_eq!(requests_for(&paths, "/gzip-two.xml"), 1);
    assert_eq!(requests_for(&paths, "/"), 0);
    assert_eq!(
        outcome.termination(),
        ys::map::MapTermination::Limit(ys::map::LimitReached::TotalResponseBytes)
    );
    assert!(
        outcome.summary().response_bytes
            >= u64::try_from(robots_body.len().saturating_add(AGGREGATE_GZIP_XML_BYTES))?
    );
    assert!(
        outcome.summary().response_bytes <= u64::try_from(total_limit)?,
        "decoded sitemap bytes must stay within the aggregate response cap"
    );
    Ok(())
}

#[tokio::test]
async fn seed_subtree_reaches_deep_about_us_pages_but_excludes_prefix_siblings() -> TestResult {
    let mut routes = support_miss_routes();
    add_html_route(
        &mut routes,
        "/about-us",
        br#"<main><a href="/about-us/team">team</a>
            <a href="/about-us-sibling">sibling</a></main>"#,
    );
    add_html_route(
        &mut routes,
        "/about-us/team",
        br#"<main><a href="/about-us/team/roles">roles</a></main>"#,
    );
    add_html_route(&mut routes, "/about-us/team/roles", b"<main>roles</main>");
    add_html_route(&mut routes, "/about-us-sibling", b"<main>sibling</main>");
    let service = FixtureService::start(Protocol::Http, routes).await;
    let policy = ys::Policy::default();

    let outcome = ys::map::new(service.url("/about-us"))
        .bind(&policy)
        .send()
        .await?;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    assert!(page_at(&outcome, "/about-us").is_some());
    assert!(page_at(&outcome, "/about-us/team").is_some());
    assert!(page_at(&outcome, "/about-us/team/roles").is_some());
    assert!(page_at(&outcome, "/about-us-sibling").is_none());
    assert_eq!(requests_for(&paths, "/about-us/team/roles"), 1);
    assert_eq!(requests_for(&paths, "/about-us-sibling"), 0);
    Ok(())
}

#[tokio::test]
async fn robots_disallow_keeps_a_link_in_inventory_without_dispatching_it() -> TestResult {
    let mut routes = support_miss_routes();
    routes.push((
        "/robots.txt".to_owned(),
        FixtureResponse::bytes(
            200,
            Some("text/plain; charset=utf-8"),
            b"User-agent: YosoiMap\nDisallow: /private\n",
        ),
    ));
    add_html_route(
        &mut routes,
        "/",
        br#"<a href="/private/record">private</a><a href="/public">public</a>"#,
    );
    add_html_route(&mut routes, "/private/record", b"<main>private</main>");
    add_html_route(&mut routes, "/public", b"<main>public</main>");
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    policy.map.robots = ys::policy::Robots::Respect;

    let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    let private = page_at(&outcome, "/private/record")
        .ok_or_else(|| missing_page("robots-disallowed link was not inventoried"))?;
    assert_eq!(
        private.exploration,
        ys::map::Exploration::Skipped(ys::map::SkipReason::Robots)
    );
    assert_eq!(requests_for(&paths, "/private/record"), 0);
    assert_eq!(requests_for(&paths, "/public"), 1);
    Ok(())
}

#[tokio::test]
async fn default_robots_ignore_fetches_disallowed_seed_and_keeps_sitemap_metadata() -> TestResult {
    let mut routes = support_miss_routes();
    routes.push((
        "/robots.txt".to_owned(),
        FixtureResponse::bytes(
            200,
            Some("text/plain; charset=utf-8"),
            b"User-agent: YosoiMap\nDisallow: /\nSitemap: /listed.xml\n",
        ),
    ));
    routes.push((
        "/listed.xml".to_owned(),
        FixtureResponse::bytes(
            200,
            Some("application/xml; charset=utf-8"),
            br#"<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                <url><loc>/metadata</loc></url>
            </urlset>"#,
        ),
    ));
    add_html_route(&mut routes, "/", br#"<a href="/link">link</a>"#);
    add_html_route(&mut routes, "/link", b"<main>link</main>");
    add_html_route(&mut routes, "/metadata", b"<main>metadata</main>");
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    policy.map.limits.max_link_depth = 0;

    assert_eq!(policy.map.robots, ys::policy::Robots::Ignore);
    let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    let seed = page_at(&outcome, "/").ok_or_else(|| missing_page("seed was not inventoried"))?;
    assert_eq!(seed.exploration, ys::map::Exploration::Inspected);
    assert_eq!(
        page_at(&outcome, "/link")
            .ok_or_else(|| missing_page("linked page was not inventoried"))?
            .exploration,
        ys::map::Exploration::Skipped(ys::map::SkipReason::Depth)
    );
    let metadata = page_at(&outcome, "/metadata")
        .ok_or_else(|| missing_page("sitemap metadata page was not inventoried"))?;
    assert_eq!(metadata.minimum_link_depth, None);
    assert_eq!(metadata.exploration, ys::map::Exploration::Inventoried);
    assert!(
        metadata
            .observations
            .iter()
            .any(|observation| observation.source == ys::map::DiscoverySource::Sitemap)
    );
    assert_eq!(requests_for(&paths, "/robots.txt"), 1);
    assert_eq!(requests_for(&paths, "/listed.xml"), 1);
    assert_eq!(requests_for(&paths, "/"), 1);
    assert_eq!(requests_for(&paths, "/link"), 0);
    assert_eq!(requests_for(&paths, "/metadata"), 0);
    Ok(())
}

#[tokio::test]
async fn manual_redirects_follow_allowed_targets_and_skip_robots_blocked_siblings() -> TestResult {
    let mut routes = support_miss_routes();
    routes.push((
        "/robots.txt".to_owned(),
        FixtureResponse::bytes(
            200,
            Some("text/plain; charset=utf-8"),
            b"User-agent: YosoiMap\nDisallow: /blocked-redirect\n",
        ),
    ));
    add_html_route(
        &mut routes,
        "/",
        br#"<a href="/safe-redirect">safe</a>
            <a href="/blocked-redirect">blocked</a>"#,
    );
    routes.push((
        "/safe-redirect".to_owned(),
        FixtureResponse::redirect("/final"),
    ));
    add_html_route(&mut routes, "/final", b"<main>redirected</main>");
    routes.push((
        "/blocked-redirect".to_owned(),
        FixtureResponse::redirect("/blocked-final"),
    ));
    add_html_route(&mut routes, "/blocked-final", b"<main>forbidden</main>");
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    policy.map.scope.paths = ys::policy::PathScope::EntireOrigin;
    policy.map.robots = ys::policy::Robots::Respect;
    policy.request.direct_http_redirects = ys::DirectHttpRedirects::Follow {
        max_hops: ys::RedirectHopLimit::try_from(3)?,
        targets: ys::DirectHttpRedirectTargets::SameOrigin,
    };

    let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    assert_eq!(requests_for(&paths, "/safe-redirect"), 1);
    assert_eq!(requests_for(&paths, "/final"), 1);
    assert_eq!(requests_for(&paths, "/blocked-redirect"), 0);
    assert_eq!(requests_for(&paths, "/blocked-final"), 0);
    assert!(
        outcome.relationships().iter().any(|relationship| {
            relationship.kind == ys::map::RelationshipKind::Redirect
                && relationship.from.path() == "/safe-redirect"
                && relationship.to.path() == "/final"
        }),
        "the followed transition should remain in the relationship graph"
    );
    assert!(page_at(&outcome, "/final").is_some());
    Ok(())
}

#[tokio::test]
async fn cycles_are_fetched_once_and_multiple_parents_remain_in_the_graph() -> TestResult {
    let mut routes = support_miss_routes();
    add_html_route(
        &mut routes,
        "/",
        br#"<a href="/left">left</a><a href="/right">right</a>"#,
    );
    add_html_route(
        &mut routes,
        "/left",
        br#"<a href="/">cycle</a><a href="/common">common</a>"#,
    );
    add_html_route(&mut routes, "/right", br#"<a href="/common">common</a>"#);
    add_html_route(&mut routes, "/common", b"<main>shared</main>");
    let service = FixtureService::start(Protocol::Http, routes).await;

    let outcome = ys::map::new(service.url("/")).send().await?;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    assert_eq!(requests_for(&paths, "/"), 1);
    assert_eq!(requests_for(&paths, "/left"), 1);
    assert_eq!(requests_for(&paths, "/right"), 1);
    assert_eq!(requests_for(&paths, "/common"), 1);
    assert_eq!(
        outcome
            .relationships()
            .iter()
            .filter(|relationship| {
                relationship.kind == ys::map::RelationshipKind::Link
                    && relationship.to.path() == "/common"
            })
            .count(),
        2
    );
    let root = page_at(&outcome, "/").ok_or_else(|| missing_page("seed was lost"))?;
    assert_eq!(
        root.observations
            .iter()
            .filter(|observation| { observation.source == ys::map::DiscoverySource::HtmlLink })
            .count(),
        1,
        "the cycle should add one incoming edge without refetching the seed"
    );
    let common_tree = tree_at(&outcome, "/common")
        .ok_or_else(|| missing_page("shared page is missing from the tree"))?;
    assert_eq!(common_tree.depth, Some(2));
    Ok(())
}

#[tokio::test]
async fn url_identity_preserves_case_and_query_but_discards_fragments() -> TestResult {
    let mut routes = support_miss_routes();
    add_html_route(
        &mut routes,
        "/",
        br#"<a href="/Case">upper</a><a href="/case">lower</a>
            <a href="/item?x=1">one</a><a href="/item?x=2">two</a>
            <a href="/fragment#first">fragment one</a>
            <a href="/fragment#second">fragment two</a>"#,
    );
    for path in ["/Case", "/case", "/item?x=1", "/item?x=2", "/fragment"] {
        add_html_route(&mut routes, path, b"<main>target</main>");
    }
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    policy.map.limits.max_link_depth = 1;

    let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    assert!(page_at(&outcome, "/Case").is_some());
    assert!(page_at(&outcome, "/case").is_some());
    assert_eq!(
        outcome
            .pages()
            .iter()
            .filter(|page| page.url.path() == "/item")
            .count(),
        2
    );
    assert_eq!(requests_for(&paths, "/fragment"), 1);
    assert_eq!(
        outcome
            .relationships()
            .iter()
            .filter(|relationship| relationship.to.path() == "/fragment")
            .count(),
        1
    );
    for target in ["/Case", "/case", "/item?x=1", "/item?x=2"] {
        assert_eq!(requests_for(&paths, target), 1);
    }
    Ok(())
}

#[tokio::test]
async fn map_filters_exclude_configured_path_prefixes_and_query_keys() -> TestResult {
    let mut routes = support_miss_routes();
    add_html_route(
        &mut routes,
        "/",
        br#"<a href="/keep?x=1">one</a><a href="/keep?x=2">two</a>
            <a href="/keep?tracking=campaign">tracked</a>
            <a href="/private/report">private path</a>"#,
    );
    add_html_route(&mut routes, "/keep?x=1", b"<main>one</main>");
    add_html_route(&mut routes, "/keep?x=2", b"<main>two</main>");
    add_html_route(
        &mut routes,
        "/keep?tracking=campaign",
        b"<main>tracked</main>",
    );
    add_html_route(&mut routes, "/private/report", b"<main>private</main>");
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    policy.map.limits.max_link_depth = 1;
    policy.map.filters.excluded_query_keys = vec!["tracking".to_owned()];
    policy.map.filters.excluded_path_prefixes = vec!["/private".to_owned()];

    let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    assert!(
        outcome
            .pages()
            .iter()
            .any(|page| page.url.as_str().ends_with("/keep?x=1"))
    );
    assert!(
        outcome
            .pages()
            .iter()
            .any(|page| page.url.as_str().ends_with("/keep?x=2"))
    );
    assert!(
        !outcome
            .pages()
            .iter()
            .any(|page| page.url.query() == Some("tracking=campaign"))
    );
    assert!(page_at(&outcome, "/private/report").is_none());
    assert_eq!(requests_for(&paths, "/keep?tracking=campaign"), 0);
    assert_eq!(requests_for(&paths, "/private/report"), 0);
    Ok(())
}

#[tokio::test]
async fn retained_map_response_reuses_its_document_for_locators_without_another_request()
-> TestResult {
    let mut routes = support_miss_routes();
    let html =
        b"<!doctype html><main><h1>Map retained document</h1><a href=\"/child\">child</a></main>";
    add_html_route(&mut routes, "/", html);
    add_html_route(&mut routes, "/child", b"<main>child</main>");
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    policy.map.documents = ys::policy::DiscoveryDocuments::RetainWithinBudget;
    policy.map.limits.max_link_depth = 0;

    let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
    let request_count = service.requests().await.len();
    assert_eq!(outcome.captures().len(), 1);
    let capture = outcome
        .captures()
        .first()
        .ok_or_else(|| missing_page("retained response is missing"))?;
    assert_eq!(capture.url().path(), "/");
    let response_document = capture
        .response()
        .attempts()
        .first()
        .and_then(ys::AttemptOutcome::result)
        .and_then(|result| result.documents().first())
        .and_then(|document| document.outcome().document())
        .ok_or_else(|| missing_page("original Requests response has no Document"))?;
    assert_eq!(response_document.bytes(), html);

    let plan = ys::Plan::new([ys::output("heading", ys::css("h1")?.text())?])?;
    assert!(matches!(
        response_document.bind(&policy).locate(&plan),
        ys::LocateOutcome::Matched { .. }
    ));
    assert_eq!(service.requests().await.len(), request_count);
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;
    assert_eq!(requests_for(&paths, "/"), 1);
    assert_eq!(requests_for(&paths, "/child"), 0);
    Ok(())
}

#[tokio::test]
async fn request_budget_keeps_inventoried_links_when_later_fetches_stop() -> TestResult {
    let mut routes = support_miss_routes();
    add_html_route(
        &mut routes,
        "/",
        br#"<a href="/first">first</a><a href="/second">second</a>"#,
    );
    add_html_route(&mut routes, "/first", b"<main>first</main>");
    add_html_route(&mut routes, "/second", b"<main>second</main>");
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    policy.map.limits.max_requests = map_budget(4)?;

    let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    assert_eq!(outcome.summary().requests, 4);
    assert_eq!(
        outcome.termination(),
        ys::map::MapTermination::Limit(ys::map::LimitReached::Requests)
    );
    assert!(page_at(&outcome, "/").is_some());
    assert!(page_at(&outcome, "/first").is_some());
    assert!(page_at(&outcome, "/second").is_some());
    assert_eq!(requests_for(&paths, "/first"), 0);
    assert_eq!(requests_for(&paths, "/second"), 0);
    assert!(
        outcome
            .frontier()
            .iter()
            .any(|entry| entry.reason == ys::map::PendingReason::OperationStopped)
    );
    Ok(())
}

#[tokio::test]
async fn total_response_byte_budget_preserves_pages_discovered_before_exhaustion() -> TestResult {
    let mut routes = support_miss_routes();
    let root = b"<main><a href=\"/large\">large</a></main>";
    add_html_route(&mut routes, "/", root);
    add_html_route(
        &mut routes,
        "/large",
        b"<main>response larger than the final byte remaining</main>",
    );
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    policy.map.limits.max_total_response_bytes =
        map_budget(u32::try_from(root.len().saturating_add(1))?)?;

    let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    assert!(page_at(&outcome, "/").is_some());
    assert!(page_at(&outcome, "/large").is_some());
    assert_eq!(requests_for(&paths, "/large"), 1);
    assert_eq!(
        outcome.termination(),
        ys::map::MapTermination::Limit(ys::map::LimitReached::TotalResponseBytes)
    );
    assert!(outcome.summary().response_bytes <= u64::try_from(root.len().saturating_add(1))?);
    Ok(())
}

#[tokio::test]
async fn parser_entry_budget_retains_partial_links_and_marks_the_operation_truncated() -> TestResult
{
    let mut routes = support_miss_routes();
    add_html_route(
        &mut routes,
        "/",
        br#"<a href="/one">one</a><a href="/two">two</a>"#,
    );
    add_html_route(&mut routes, "/one", b"<main>one</main>");
    add_html_route(&mut routes, "/two", b"<main>two</main>");
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    policy.map.limits.max_parser_entries = map_budget(1)?;

    let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    assert!(page_at(&outcome, "/").is_some());
    let linked_pages = outcome
        .pages()
        .iter()
        .filter(|page| {
            page.observations
                .iter()
                .any(|observation| observation.source == ys::map::DiscoverySource::HtmlLink)
        })
        .count();
    assert_eq!(linked_pages, 1);
    assert_eq!(
        requests_for(&paths, "/one") + requests_for(&paths, "/two"),
        0
    );
    assert_eq!(
        outcome.termination(),
        ys::map::MapTermination::Limit(ys::map::LimitReached::ParserEntries)
    );
    Ok(())
}

#[tokio::test]
async fn frontier_budget_keeps_all_discovered_children_in_the_result() -> TestResult {
    let mut routes = support_miss_routes();
    add_html_route(
        &mut routes,
        "/",
        br#"<a href="/one">one</a><a href="/two">two</a>"#,
    );
    add_html_route(&mut routes, "/one", b"<main>one</main>");
    add_html_route(&mut routes, "/two", b"<main>two</main>");
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    policy.map.limits.max_pending = map_budget(1)?;

    let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    assert!(page_at(&outcome, "/one").is_some());
    assert!(page_at(&outcome, "/two").is_some());
    for path in ["/one", "/two"] {
        let page = page_at(&outcome, path)
            .ok_or_else(|| missing_page("admitted child identity was not preserved"))?;
        assert_eq!(page.exploration, ys::map::Exploration::Pending);
    }
    assert_eq!(
        outcome
            .frontier()
            .iter()
            .filter(|entry| entry.reason == ys::map::PendingReason::OperationStopped)
            .count(),
        1
    );
    assert!(outcome.summary().omitted >= 1);
    assert_eq!(
        requests_for(&paths, "/one") + requests_for(&paths, "/two"),
        0
    );
    assert_eq!(
        outcome.termination(),
        ys::map::MapTermination::Limit(ys::map::LimitReached::Pending)
    );
    Ok(())
}

#[tokio::test]
async fn malformed_sitemap_is_a_typed_source_failure_and_does_not_erase_the_seed() -> TestResult {
    let mut routes = support_miss_routes();
    routes.push((
        "/sitemap.xml".to_owned(),
        FixtureResponse::bytes(
            200,
            Some("application/xml; charset=utf-8"),
            b"<urlset><url></urlset>",
        ),
    ));
    add_html_route(&mut routes, "/", b"<main>seed survives source error</main>");
    let service = FixtureService::start(Protocol::Http, routes).await;

    let outcome = ys::map::new(service.url("/")).send().await?;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    let sitemap = outcome
        .support_documents()
        .iter()
        .find(|support| support.url.path() == "/sitemap.xml")
        .ok_or_else(|| missing_page("sitemap support outcome is missing"))?;
    assert_eq!(
        sitemap.status,
        ys::map::SourceStatus::Failed(ys::map::SourceFailure::Parse)
    );
    assert!(page_at(&outcome, "/").is_some());
    assert_eq!(requests_for(&paths, "/"), 1);
    Ok(())
}

#[tokio::test]
async fn robots_server_failure_conservatively_prevents_the_seed_request() -> TestResult {
    let mut routes = support_miss_routes();
    routes.push((
        "/robots.txt".to_owned(),
        FixtureResponse::bytes(
            500,
            Some("text/plain; charset=utf-8"),
            b"robots temporarily unavailable",
        ),
    ));
    add_html_route(&mut routes, "/", b"<main>must not be fetched</main>");
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    policy.map.robots = ys::policy::Robots::Respect;

    let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    let seed =
        page_at(&outcome, "/").ok_or_else(|| missing_page("seed URL should be inventoried"))?;
    assert_eq!(
        seed.exploration,
        ys::map::Exploration::Skipped(ys::map::SkipReason::Robots)
    );
    let robots = outcome
        .support_documents()
        .iter()
        .find(|support| support.kind == ys::map::SupportDocumentKind::Robots)
        .ok_or_else(|| missing_page("robots support outcome is missing"))?;
    assert_eq!(
        robots.status,
        ys::map::SourceStatus::Failed(ys::map::SourceFailure::HttpStatus(500))
    );
    assert_eq!(requests_for(&paths, "/robots.txt"), 1);
    assert_eq!(requests_for(&paths, "/"), 0);
    Ok(())
}

#[tokio::test]
async fn empty_successful_robots_response_allows_seed_inspection() -> TestResult {
    let mut routes = support_miss_routes();
    routes.push((
        "/robots.txt".to_owned(),
        FixtureResponse::raw(b"HTTP/1.1 204 No Content\r\n\r\n".to_vec()),
    ));
    add_html_route(
        &mut routes,
        "/",
        b"<main>empty robots means no rules</main>",
    );
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    policy.map.robots = ys::policy::Robots::Respect;

    let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    let seed = page_at(&outcome, "/").ok_or_else(|| missing_page("seed is missing"))?;
    assert_eq!(seed.exploration, ys::map::Exploration::Inspected);
    assert_eq!(requests_for(&paths, "/robots.txt"), 1);
    assert_eq!(requests_for(&paths, "/"), 1);
    assert!(outcome.support_documents().iter().any(|support| {
        support.kind == ys::map::SupportDocumentKind::Robots
            && support.status == ys::map::SourceStatus::Completed
    }));
    Ok(())
}

#[tokio::test]
async fn cancellation_before_work_returns_an_outcome_without_network_requests() -> TestResult {
    let service = FixtureService::start(Protocol::Http, support_miss_routes()).await;
    let cancellation = CancellationToken::new();
    cancellation.cancel();

    let outcome = ys::map::new(service.url("/"))
        .send_cancellable(&cancellation)
        .await?;
    let requests = service.requests().await;
    service.shutdown().await;

    assert_eq!(outcome.termination(), ys::map::MapTermination::Cancelled);
    assert_eq!(requests.len(), 0);
    let seed = page_at(&outcome, "/").ok_or_else(|| missing_page("seed was not inventoried"))?;
    assert_eq!(seed.exploration, ys::map::Exploration::Pending);
    assert!(outcome.frontier().iter().any(|entry| {
        entry.page.path() == "/" && entry.reason == ys::map::PendingReason::OperationStopped
    }));
    for source in [
        ys::map::DiscoverySource::Robots,
        ys::map::DiscoverySource::Sitemap,
    ] {
        assert!(outcome.sources().iter().any(|outcome| {
            outcome.source == source && outcome.status == ys::map::SourceStatus::NotStarted
        }));
    }
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

#[tokio::test]
async fn cancellation_after_a_partial_page_chunk_accounts_available_source_bytes() -> TestResult {
    let mut routes = support_miss_routes();
    let root = br#"<main><a href="/held">held</a></main>"#;
    add_html_route(&mut routes, "/", root);
    let first_chunk = b"<main>first";
    let remaining_body = b" chunk</main>";
    let body = [first_chunk.as_slice(), remaining_body.as_slice()].concat();
    let control = Arc::new(ResponseControl {
        hold_after_chunks: true,
        ..ResponseControl::default()
    });
    let mut response = FixtureResponse::bytes(200, Some("text/html; charset=utf-8"), &body);
    response.chunks = vec![first_chunk.to_vec(), remaining_body.to_vec()];
    response.control = Some(control.clone());
    routes.push(("/held".to_owned(), response));
    let service = FixtureService::start(Protocol::Http, routes).await;
    let cancellation = CancellationToken::new();
    let task_cancellation = cancellation.clone();
    let seed = service.url("/");
    let task = tokio::spawn(async move {
        ys::map::new(seed)
            .send_cancellable(&task_cancellation)
            .await
    });

    timeout(Duration::from_secs(10), control.chunk_written.wait()).await?;
    cancellation.cancel();
    let outcome = task.await??;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    assert_eq!(requests_for(&paths, "/"), 1);
    assert_eq!(requests_for(&paths, "/held"), 1);
    assert_eq!(outcome.termination(), ys::map::MapTermination::Cancelled);
    let root_page =
        page_at(&outcome, "/").ok_or_else(|| missing_page("completed seed is missing"))?;
    assert_eq!(root_page.exploration, ys::map::Exploration::Inspected);
    let interrupted = page_at(&outcome, "/held")
        .ok_or_else(|| missing_page("interrupted seed was not inventoried"))?;
    assert_eq!(interrupted.exploration, ys::map::Exploration::Pending);
    let completed_seed_bytes = u64::try_from(root.len())?;
    assert!(
        outcome.summary().response_bytes >= completed_seed_bytes,
        "the complete root response must remain accounted when a later page is cancelled"
    );
    assert!(
        outcome.summary().response_bytes
            <= completed_seed_bytes.saturating_add(u64::try_from(first_chunk.len())?),
        "the body reader must not charge the not-yet-released second chunk"
    );
    assert!(outcome.frontier().iter().any(|entry| {
        entry.page.path() == "/held" && entry.reason == ys::map::PendingReason::OperationStopped
    }));
    Ok(())
}

#[tokio::test]
async fn cancellation_during_a_held_page_response_stops_the_active_map_request() -> TestResult {
    let mut routes = support_miss_routes();
    let control = Arc::new(ResponseControl {
        hold_before_head: true,
        ..ResponseControl::default()
    });
    let mut response = FixtureResponse::bytes(
        200,
        Some("text/html; charset=utf-8"),
        b"<main>held seed</main>",
    );
    response.control = Some(control.clone());
    routes.push(("/".to_owned(), response));
    let service = FixtureService::start(Protocol::Http, routes).await;
    let cancellation = CancellationToken::new();
    let task_cancellation = cancellation.clone();
    let seed = service.url("/");
    let task = tokio::spawn(async move {
        ys::map::new(seed)
            .send_cancellable(&task_cancellation)
            .await
    });

    timeout(Duration::from_secs(10), control.requested.wait()).await?;
    cancellation.cancel();
    let outcome = task.await??;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    assert_eq!(outcome.termination(), ys::map::MapTermination::Cancelled);
    assert_eq!(requests_for(&paths, "/"), 1);
    let interrupted = page_at(&outcome, "/")
        .ok_or_else(|| missing_page("interrupted seed was not inventoried"))?;
    assert_eq!(interrupted.exploration, ys::map::Exploration::Pending);
    assert!(outcome.frontier().iter().any(|entry| {
        entry.page.path() == "/" && entry.reason == ys::map::PendingReason::OperationStopped
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

#[tokio::test]
async fn per_response_byte_budget_preserves_the_completed_seed_document() -> TestResult {
    let mut routes = support_miss_routes();
    let root = b"<main><a href=\"/large\">large</a></main>";
    add_html_route(&mut routes, "/", root);
    add_html_route(
        &mut routes,
        "/large",
        b"<main>response larger than the per-response budget</main>",
    );
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    let response_limit = u32::try_from(root.len().saturating_add(1))?;
    policy.map.limits.max_response_bytes = map_budget(response_limit)?;

    let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    assert!(page_at(&outcome, "/").is_some());
    assert!(page_at(&outcome, "/large").is_some());
    assert_eq!(requests_for(&paths, "/large"), 1);
    assert_eq!(
        outcome.termination(),
        ys::map::MapTermination::Limit(ys::map::LimitReached::ResponseBytes)
    );
    let completed_seed_bytes = u64::try_from(root.len())?;
    assert!(outcome.summary().response_bytes > completed_seed_bytes);
    assert!(
        outcome.summary().response_bytes
            <= completed_seed_bytes.saturating_add(u64::from(response_limit))
    );
    Ok(())
}

#[tokio::test]
async fn unsupported_binary_page_bytes_count_toward_the_total_response_budget() -> TestResult {
    let mut routes = support_miss_routes();
    let root = b"<main><a href=\"/opaque\">opaque</a></main>";
    let binary = b"\x00\xffopaque-response";
    add_html_route(&mut routes, "/", root);
    routes.push((
        "/opaque".to_owned(),
        FixtureResponse::bytes(200, Some("application/octet-stream"), binary),
    ));
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    policy.map.limits.max_link_depth = 1;

    let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    let opaque = page_at(&outcome, "/opaque")
        .ok_or_else(|| missing_page("unsupported binary page was not inventoried"))?;
    assert_eq!(
        opaque.exploration,
        ys::map::Exploration::Skipped(ys::map::SkipReason::NonHtml)
    );
    assert_eq!(requests_for(&paths, "/opaque"), 1);
    assert_eq!(
        outcome.summary().response_bytes,
        u64::try_from(root.len().saturating_add(binary.len()))?,
        "raw unsupported bytes must be charged even when no Document is produced"
    );
    Ok(())
}

#[tokio::test]
async fn seed_redirect_preserves_the_single_authored_tree_root() -> TestResult {
    let mut routes = support_miss_routes();
    routes.push(("/about".to_owned(), FixtureResponse::redirect("/about/")));
    add_html_route(&mut routes, "/about/", b"<main>About</main>");
    let service = FixtureService::start(Protocol::Http, routes).await;
    let outcome = ys::map::new(service.url("/about")).send().await?;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;
    let target = outcome
        .tree()
        .iter()
        .find(|entry| entry.page.path() == "/about/")
        .ok_or_else(|| missing_page("redirect target missing from tree"))?;
    assert_eq!(target.depth, Some(0));
    assert_eq!(target.parent.as_ref().map(url::Url::path), Some("/about"));
    assert_eq!(requests_for(&paths, "/about/"), 1);
    Ok(())
}
