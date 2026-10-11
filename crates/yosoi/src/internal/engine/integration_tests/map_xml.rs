#![allow(clippy::panic_in_result_fn)]

use crate::internal::test_support::direct_http_fixture as fixture;

use std::{error::Error, io};

use crate::internal::engine::prelude as ys;
use fixture::{FixtureService, Protocol, RequestLine, Response as FixtureResponse};

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

fn page_at<'outcome>(
    outcome: &'outcome ys::MapOutcome,
    path: &str,
    query: Option<&str>,
) -> Option<&'outcome ys::map::PageEntry> {
    outcome
        .pages()
        .iter()
        .find(|page| page.url.path() == path && page.url.query() == query)
}

fn missing(message: &'static str) -> io::Error {
    io::Error::other(message)
}

#[tokio::test]
async fn rss_text_and_namespaced_atom_hrefs_resolve_xml_base_and_preserve_queries() -> TestResult {
    let mut routes = misses();
    routes.push((
        "/feeds/".to_owned(),
        FixtureResponse::bytes(
            200,
            Some("application/rss+xml; charset=utf-8"),
            br#"<rss xmlns:atom="http://www.w3.org/2005/Atom">
                <channel xml:base="posts/">
                    <item><link>read?title=Well%20being&amp;utm_source=rss</link></item>
                    <atom:link href="atom?utm_campaign=launch&amp;q=indoor%20air" rel="alternate"/>
                    <item><link>../../../outside</link></item>
                    <item><link>https://attacker.invalid/escape</link></item>
                    <item><link>   </link></item>
                </channel>
            </rss>"#,
        ),
    ));
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    policy.map.limits.max_link_depth = 0;

    let outcome = ys::map::new(service.url("/feeds/"))
        .bind(&policy)
        .send()
        .await?;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    let rss = page_at(
        &outcome,
        "/feeds/posts/read",
        Some("title=Well%20being&utm_source=rss"),
    )
    .ok_or_else(|| missing("RSS text link was not inventoried"))?;
    let atom = page_at(
        &outcome,
        "/feeds/posts/atom",
        Some("utm_campaign=launch&q=indoor%20air"),
    )
    .ok_or_else(|| missing("namespaced Atom href was not inventoried"))?;
    for page in [rss, atom] {
        assert_eq!(page.minimum_link_depth, Some(1));
        assert_eq!(
            page.exploration,
            ys::map::Exploration::Skipped(ys::map::SkipReason::Depth)
        );
        assert!(
            page.observations
                .iter()
                .any(|observation| { observation.source == ys::map::DiscoverySource::XmlLink })
        );
        let mut target = page.url.path().to_owned();
        if let Some(query) = page.url.query() {
            target.push('?');
            target.push_str(query);
        }
        assert_eq!(request_count(&paths, &target), 0);
    }
    assert!(page_at(&outcome, "/outside", None).is_none());
    assert!(outcome.omissions().iter().any(|omission| {
        omission.reason == ys::map::OmissionReason::Admission(ys::map::Rejection::HostScope)
    }));
    assert!(outcome.omissions().iter().any(|omission| {
        omission.reason == ys::map::OmissionReason::Admission(ys::map::Rejection::PathScope)
    }));
    Ok(())
}

#[tokio::test]
async fn well_formed_xml_without_links_is_a_completed_empty_result() -> TestResult {
    let mut routes = misses();
    routes.push((
        "/empty.xml".to_owned(),
        FixtureResponse::bytes(200, Some("application/xml"), b"<rss><channel/></rss>"),
    ));
    let service = FixtureService::start(Protocol::Http, routes).await;

    let outcome = ys::map::new(service.url("/empty.xml")).send().await?;
    service.shutdown().await;

    assert_eq!(
        page_at(&outcome, "/empty.xml", None)
            .ok_or_else(|| missing("empty XML seed is missing"))?
            .exploration,
        ys::map::Exploration::Inspected
    );
    assert!(outcome.sources().iter().any(|source| {
        source.source == ys::map::DiscoverySource::XmlLink
            && source.status == ys::map::SourceStatus::Completed
    }));
    assert_eq!(outcome.pages().len(), 1);
    Ok(())
}

#[tokio::test]
async fn malformed_xml_fails_and_parser_entry_limit_truncates_discovery() -> TestResult {
    let mut routes = misses();
    routes.push((
        "/broken.xml".to_owned(),
        FixtureResponse::bytes(
            200,
            Some("application/rss+xml"),
            b"<rss><channel><item><link>/unfinished</channel></rss>",
        ),
    ));
    routes.push((
        "/many.xml".to_owned(),
        FixtureResponse::bytes(
            200,
            Some("application/atom+xml"),
            br#"<feed xmlns="http://www.w3.org/2005/Atom">
                <link href="one"/><link href="two"/><link href="three"/>
            </feed>"#,
        ),
    ));
    let service = FixtureService::start(Protocol::Http, routes).await;

    let broken = ys::map::new(service.url("/broken.xml")).send().await?;
    let broken_seed = page_at(&broken, "/broken.xml", None)
        .ok_or_else(|| missing("malformed XML seed is missing"))?;
    assert_eq!(
        broken_seed.exploration,
        ys::map::Exploration::Failed(ys::map::SourceFailure::Parse)
    );
    assert!(broken.sources().iter().any(|source| {
        source.source == ys::map::DiscoverySource::XmlLink
            && source.status == ys::map::SourceStatus::Failed(ys::map::SourceFailure::Parse)
    }));

    let mut policy = ys::Policy::default();
    policy.map.scope.paths = ys::policy::PathScope::EntireOrigin;
    policy.map.limits.max_link_depth = 0;
    policy.map.limits.max_parser_entries = ys::policy::Budget::new(2)?;
    let many = ys::map::new(service.url("/many.xml"))
        .bind(&policy)
        .send()
        .await?;
    service.shutdown().await;

    assert_eq!(
        many.termination(),
        ys::map::MapTermination::Limit(ys::map::LimitReached::ParserEntries)
    );
    assert!(
        many.pages()
            .iter()
            .filter(|page| {
                page.observations
                    .iter()
                    .any(|observation| observation.source == ys::map::DiscoverySource::XmlLink)
            })
            .count()
            <= 2
    );
    assert!(many.sources().iter().any(|source| {
        source.source == ys::map::DiscoverySource::XmlLink
            && source.status == ys::map::SourceStatus::Truncated
    }));
    Ok(())
}

#[tokio::test]
async fn xml_node_and_input_byte_limits_are_reported_as_parse_failures() -> TestResult {
    let mut routes = misses();
    routes.push((
        "/feeds/".to_owned(),
        FixtureResponse::bytes(
            200,
            Some("application/xml"),
            b"<rss><channel><item><link>article</link></item></channel></rss>",
        ),
    ));
    let service = FixtureService::start(Protocol::Http, routes).await;

    let mut node_limited_policy = ys::Policy::default();
    node_limited_policy.documents.max_nodes = ys::policy::CountLimit::try_from(1_u64)?;
    let node_limited = ys::map::new(service.url("/feeds/"))
        .bind(&node_limited_policy)
        .send()
        .await?;
    assert_eq!(
        page_at(&node_limited, "/feeds/", None)
            .ok_or_else(|| missing("node-limited XML seed is missing"))?
            .exploration,
        ys::map::Exploration::Failed(ys::map::SourceFailure::Parse)
    );

    let mut byte_limited_policy = ys::Policy::default();
    byte_limited_policy.documents.max_input_bytes =
        ys::policy::AddressableByteLimit::try_from(16_u64)?;
    let byte_limited = ys::map::new(service.url("/feeds/"))
        .bind(&byte_limited_policy)
        .send()
        .await?;

    let mut output_limited_policy = ys::Policy::default();
    output_limited_policy.locators.max_output_bytes =
        ys::policy::AddressableByteLimit::try_from(1_u64)?;
    let output_limited = ys::map::new(service.url("/feeds/"))
        .bind(&output_limited_policy)
        .send()
        .await?;

    let mut work_limited_policy = ys::Policy::default();
    work_limited_policy.locators.max_selector_visits = ys::policy::CountLimit::try_from(1_u64)?;
    let work_limited = ys::map::new(service.url("/feeds/"))
        .bind(&work_limited_policy)
        .send()
        .await?;
    service.shutdown().await;

    assert_eq!(
        page_at(&byte_limited, "/feeds/", None)
            .ok_or_else(|| missing("byte-limited XML seed is missing"))?
            .exploration,
        ys::map::Exploration::Failed(ys::map::SourceFailure::Parse)
    );
    assert_eq!(
        page_at(&output_limited, "/feeds/", None)
            .ok_or_else(|| missing("output-limited XML seed is missing"))?
            .exploration,
        ys::map::Exploration::Failed(ys::map::SourceFailure::Parse)
    );
    assert_eq!(
        page_at(&work_limited, "/feeds/", None)
            .ok_or_else(|| missing("work-limited XML seed is missing"))?
            .exploration,
        ys::map::Exploration::Failed(ys::map::SourceFailure::Parse)
    );
    Ok(())
}

#[tokio::test]
async fn retained_redirected_xml_feed_is_reused_without_fetching_its_final_url_twice() -> TestResult
{
    let mut routes = misses();
    routes.push((
        "/".to_owned(),
        FixtureResponse::bytes(
            200,
            Some("text/html; charset=utf-8"),
            br#"<a href="/alias">alias</a><a href="/feed.xml">feed</a>"#,
        ),
    ));
    routes.push(("/alias".to_owned(), FixtureResponse::redirect("/feed.xml")));
    routes.push((
        "/feed.xml".to_owned(),
        FixtureResponse::bytes(
            200,
            Some("application/rss+xml"),
            b"<rss><channel><item><link>/story</link></item></channel></rss>",
        ),
    ));
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    policy.map.limits.max_link_depth = 1;
    policy.map.documents = ys::policy::DiscoveryDocuments::RetainWithinBudget;

    let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
    let paths = request_paths(&service.requests().await);
    service.shutdown().await;

    assert_eq!(request_count(&paths, "/alias"), 1);
    assert_eq!(request_count(&paths, "/feed.xml"), 1);
    assert_eq!(
        outcome
            .captures()
            .iter()
            .filter(|capture| capture.url().path() == "/feed.xml")
            .count(),
        1
    );
    let story = page_at(&outcome, "/story", None)
        .ok_or_else(|| missing("XML feed article was not inventoried"))?;
    assert!(
        story
            .observations
            .iter()
            .any(|observation| { observation.source == ys::map::DiscoverySource::XmlLink })
    );
    Ok(())
}

#[tokio::test]
async fn guessed_html_sitemap_is_unavailable_but_declared_html_is_a_real_failure() -> TestResult {
    for declared in [false, true] {
        let robots = if declared {
            b"User-agent: *\nSitemap: /sitemap.xml\n".as_slice()
        } else {
            b"User-agent: *\n".as_slice()
        };
        let routes = vec![
            (
                "/robots.txt".to_owned(),
                FixtureResponse::bytes(200, Some("text/plain"), robots),
            ),
            (
                "/sitemap.xml".to_owned(),
                FixtureResponse::bytes(
                    200,
                    Some("text/html"),
                    b"<html><body>SPA fallback</body></html>",
                ),
            ),
            (
                "/sitemap_index.xml".to_owned(),
                FixtureResponse::bytes(404, Some("text/plain"), b""),
            ),
            (
                "/".to_owned(),
                FixtureResponse::bytes(200, Some("text/html"), b"<main>seed</main>"),
            ),
        ];
        let service = FixtureService::start(Protocol::Http, routes).await;
        let outcome = ys::map::new(service.url("/")).send().await?;
        service.shutdown().await;
        let sitemap = outcome
            .support_documents()
            .iter()
            .find(|source| source.url.path() == "/sitemap.xml")
            .ok_or_else(|| missing("sitemap outcome missing"))?;
        assert_eq!(
            sitemap.status,
            if declared {
                ys::map::SourceStatus::Failed(ys::map::SourceFailure::UnexpectedSitemapContent)
            } else {
                ys::map::SourceStatus::Skipped(ys::map::SourceSkipReason::NotSitemap)
            }
        );
        assert_eq!(
            page_at(&outcome, "/", None)
                .ok_or_else(|| missing("seed missing"))?
                .exploration,
            ys::map::Exploration::Inspected
        );
    }
    Ok(())
}
