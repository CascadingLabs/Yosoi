#![allow(clippy::panic_in_result_fn)]
#[path = "../../yosoi-web-capture-direct-http/tests/support/direct_http_fixture.rs"]
mod fixture;

use fixture::{FixtureService, Protocol, Response as FixtureResponse, ResponseControl};
use std::{error::Error, future::Future, io, pin::Pin, sync::Arc, time::Duration};
use tokio::time::timeout;
use yosoi_engine::prelude as ys;
type TestResult<T = ()> = Result<T, Box<dyn Error + Send + Sync>>;

fn routes(body: &[u8]) -> Vec<(String, FixtureResponse)> {
    let mut routes: Vec<_> = ["/robots.txt", "/sitemap.xml", "/sitemap_index.xml"]
        .into_iter()
        .map(|path| {
            (
                path.to_owned(),
                FixtureResponse::bytes(404, Some("text/plain"), b""),
            )
        })
        .collect();
    routes.push((
        "/".to_owned(),
        FixtureResponse::bytes(200, Some("text/html"), body),
    ));
    routes
}
fn held(body: &[u8]) -> (FixtureResponse, Arc<ResponseControl>) {
    let control = Arc::new(ResponseControl {
        hold_before_head: true,
        ..ResponseControl::default()
    });
    let mut response = FixtureResponse::bytes(200, Some("text/html"), body);
    response.control = Some(Arc::clone(&control));
    (response, control)
}
async fn event<F: Future>(future: &mut Pin<Box<F>>, signal: &fixture::Signal) -> TestResult {
    timeout(Duration::from_secs(5), async {
        tokio::select! {
            () = signal.wait() => Ok(()),
            _ = future.as_mut() => Err(io::Error::other("Map finished before fixture event")),
        }
    })
    .await??;
    Ok(())
}

#[tokio::test]
async fn page_requests_overlap_at_one_two_and_four_without_exceeding_the_cap() -> TestResult {
    for cap in [1, 2, 4] {
        let mut routes = routes(br#"<a href="/a">a</a><a href="/b">b</a><a href="/c">c</a><a href="/d">d</a><a href="/e">e</a>"#);
        let mut controls = Vec::new();
        for path in ["/a", "/b", "/c", "/d", "/e"] {
            let (response, control) = held(b"<p>leaf</p>");
            controls.push(control);
            routes.push((path.to_owned(), response));
        }
        let service = FixtureService::start(Protocol::Http, routes).await;
        let mut policy = ys::Policy::default();
        policy.map.limits.max_concurrency = ys::policy::Budget::new(cap)?;
        let cancellation = yosoi_engine::CancellationToken::new();
        let request = ys::map::new(service.url("/"));
        let bound = request.bind(&policy);
        let mut future = Box::pin(bound.send_cancellable(&cancellation));
        for control in controls.iter().take(usize::try_from(cap)?) {
            event(&mut future, &control.requested).await?;
        }
        assert_eq!(service.requests().await.len(), 4 + usize::try_from(cap)?);
        for control in &controls {
            control.allow_head.signal();
        }
        let outcome = timeout(Duration::from_secs(5), future).await??;
        assert_eq!(outcome.summary().page_concurrency_peak, cap);
        assert_eq!(outcome.summary().unused_page_prefetches, 0);
        assert_eq!(outcome.summary().requests, 9);
        assert_eq!(outcome.pages().len(), 6);
        assert_eq!(outcome.termination(), ys::map::MapTermination::Exhausted);
        service.shutdown().await;
    }
    Ok(())
}

#[tokio::test]
async fn cancellation_drains_both_started_pages_and_keeps_the_unstarted_frontier() -> TestResult {
    let mut routes = routes(br#"<a href="/a">a</a><a href="/b">b</a><a href="/c">c</a>"#);
    let (a, control_a) = held(b"<p>a</p>");
    let (b, control_b) = held(b"<p>b</p>");
    routes.extend([("/a".to_owned(), a), ("/b".to_owned(), b)]);
    let service = FixtureService::start(Protocol::Http, routes).await;
    let policy = ys::Policy::default();
    let cancellation = yosoi_engine::CancellationToken::new();
    let request = ys::map::new(service.url("/"));
    let bound = request.bind(&policy);
    let mut future = Box::pin(bound.send_cancellable(&cancellation));
    event(&mut future, &control_a.requested).await?;
    event(&mut future, &control_b.requested).await?;
    cancellation.cancel();
    let outcome = timeout(Duration::from_secs(5), future).await??;
    control_a.allow_head.signal();
    control_b.allow_head.signal();
    timeout(Duration::from_secs(5), control_a.connection_finished.wait()).await?;
    timeout(Duration::from_secs(5), control_b.connection_finished.wait()).await?;
    assert_eq!(service.active_connections(), 0);
    assert!(
        !service
            .requests()
            .await
            .iter()
            .any(|request| request.path == "/c")
    );
    assert_eq!(outcome.termination(), ys::map::MapTermination::Cancelled);
    assert_eq!(outcome.summary().unused_page_prefetches, 2);
    assert_eq!(outcome.frontier().len(), 3);
    service.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn absolute_deadline_cancels_and_drains_a_held_page_batch() -> TestResult {
    let mut routes = routes(br#"<a href="/a">a</a><a href="/b">b</a>"#);
    let (a, control_a) = held(b"<p>a</p>");
    let (b, control_b) = held(b"<p>b</p>");
    routes.extend([("/a".to_owned(), a), ("/b".to_owned(), b)]);
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    policy.map.limits.maximum_elapsed = Duration::from_secs(1);
    let request = ys::map::new(service.url("/"));
    let bound = request.bind(&policy);
    let mut future = Box::pin(bound.send());
    event(&mut future, &control_a.requested).await?;
    event(&mut future, &control_b.requested).await?;
    let outcome = timeout(Duration::from_secs(5), future).await??;
    control_a.allow_head.signal();
    control_b.allow_head.signal();
    timeout(Duration::from_secs(5), control_a.connection_finished.wait()).await?;
    timeout(Duration::from_secs(5), control_b.connection_finished.wait()).await?;
    assert_eq!(outcome.termination(), ys::map::MapTermination::Deadline);
    assert_eq!(service.active_connections(), 0);
    service.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn request_cap_and_small_aggregate_reservations_do_not_overdispatch() -> TestResult {
    for request_cap in [5, 20] {
        let mut routes = routes(br#"<a href="/a">a</a><a href="/b">b</a><a href="/c">c</a>"#);
        for path in ["/a", "/b", "/c"] {
            routes.push((
                path.to_owned(),
                FixtureResponse::bytes(200, Some("text/html"), b"<p>leaf</p>"),
            ));
        }
        let service = FixtureService::start(Protocol::Http, routes).await;
        let mut policy = ys::Policy::default();
        policy.map.limits.max_concurrency = ys::policy::Budget::new(4)?;
        policy.map.limits.max_requests = ys::policy::Budget::new(request_cap)?;
        policy.map.limits.max_response_bytes = ys::policy::Budget::new(128)?;
        policy.map.limits.max_total_response_bytes = ys::policy::Budget::new(200)?;
        let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
        assert!(outcome.summary().response_bytes <= 200);
        assert_eq!(outcome.summary().page_concurrency_peak, 1);
        assert!(outcome.summary().requests <= request_cap);
        assert_eq!(
            service.requests().await.len(),
            usize::try_from(outcome.summary().requests)?
        );
        assert_eq!(
            outcome.termination(),
            if request_cap == 5 {
                ys::map::MapTermination::Limit(ys::map::LimitReached::Requests)
            } else {
                ys::map::MapTermination::Exhausted
            }
        );
        service.shutdown().await;
    }
    Ok(())
}

#[tokio::test]
async fn redirect_targets_are_reused_for_html_binary_failure_and_converging_aliases() -> TestResult
{
    for cap in [1, 2] {
        for (status, media, direct_link) in [
            (200, "text/html", true),
            (200, "application/pdf", true),
            (404, "text/plain", true),
            (200, "application/pdf", false),
            (404, "text/plain", false),
        ] {
            let root = if direct_link {
                br#"<a href="/a">a</a><a href="/target">target</a>"#.as_slice()
            } else {
                br#"<a href="/a">a</a><a href="/b">b</a>"#.as_slice()
            };
            let mut routes = routes(root);
            routes.push(("/a".to_owned(), FixtureResponse::redirect("/target")));
            if !direct_link {
                routes.push(("/b".to_owned(), FixtureResponse::redirect("/target")));
            }
            routes.push((
                "/target".to_owned(),
                FixtureResponse::bytes(status, Some(media), b"<p>target</p>"),
            ));
            let service = FixtureService::start(Protocol::Http, routes).await;
            let mut policy = ys::Policy::default();
            policy.map.limits.max_concurrency = ys::policy::Budget::new(cap)?;
            let outcome = ys::map::new(service.url("/")).bind(&policy).send().await?;
            assert_eq!(
                service
                    .requests()
                    .await
                    .iter()
                    .filter(|request| request.path == "/target")
                    .count(),
                1
            );
            assert_eq!(outcome.summary().requests, if direct_link { 6 } else { 7 });
            assert_eq!(outcome.summary().unused_page_prefetches, 0);
            assert_eq!(outcome.termination(), ys::map::MapTermination::Exhausted);
            service.shutdown().await;
        }
    }
    Ok(())
}

#[tokio::test]
async fn response_race_does_not_choose_the_capped_inventory_and_speculation_is_visible()
-> TestResult {
    let mut routes = routes(br#"<a href="/a">a</a><a href="/b">b</a>"#);
    let (a, control_a) = held(br#"<a href="/aaa">a</a><a href="/aab">a</a><a href="/aac">a</a>"#);
    let control_b = Arc::new(ResponseControl::default());
    let mut b = FixtureResponse::bytes(200, Some("text/html"), br#"<a href="/bbb">b</a>"#);
    b.control = Some(Arc::clone(&control_b));
    routes.extend([("/a".to_owned(), a), ("/b".to_owned(), b)]);
    let service = FixtureService::start(Protocol::Http, routes).await;
    let mut policy = ys::Policy::default();
    policy.map.limits.max_urls = ys::policy::Budget::new(5)?;
    let request = ys::map::new(service.url("/"));
    let bound = request.bind(&policy);
    let mut future = Box::pin(bound.send());
    event(&mut future, &control_b.connection_finished).await?;
    control_a.allow_head.signal();
    let outcome = timeout(Duration::from_secs(5), future).await??;
    assert!(outcome.pages().iter().any(|page| page.url.path() == "/aaa"));
    assert!(!outcome.pages().iter().any(|page| page.url.path() == "/bbb"));
    assert_eq!(outcome.summary().unused_page_prefetches, 1);
    assert_eq!(outcome.summary().requests, 6);
    assert_eq!(
        outcome.termination(),
        ys::map::MapTermination::Limit(ys::map::LimitReached::Urls)
    );
    service.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn redirect_chain_inventories_each_hop_under_one_authored_root() -> TestResult {
    let mut routes = routes(b"");
    routes.retain(|(path, _)| path != "/");
    for (from, to) in [
        ("/", "/first"),
        ("/first", "/second"),
        ("/second", "/target"),
    ] {
        routes.push((from.to_owned(), FixtureResponse::redirect(to)));
    }
    routes.push((
        "/target".to_owned(),
        FixtureResponse::bytes(200, Some("text/html"), b"<p>target</p>"),
    ));
    let service = FixtureService::start(Protocol::Http, routes).await;
    let outcome = ys::map::new(service.url("/")).send().await?;
    assert_eq!(outcome.pages().len(), 4);
    assert_eq!(
        outcome
            .tree()
            .iter()
            .filter(|entry| entry.parent.is_none())
            .count(),
        1
    );
    assert_eq!(outcome.frontier().len(), 0);
    assert_eq!(outcome.summary().requests, 7);
    service.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn redirect_chain_reuses_an_intermediate_prefetched_for_another_page() -> TestResult {
    let mut routes = routes(br#"<a href="/a">a</a><a href="/middle">middle</a>"#);
    routes.push(("/a".to_owned(), FixtureResponse::redirect("/middle")));
    routes.push(("/middle".to_owned(), FixtureResponse::redirect("/target")));
    routes.push((
        "/target".to_owned(),
        FixtureResponse::bytes(200, Some("text/html"), b"<p>target</p>"),
    ));
    let service = FixtureService::start(Protocol::Http, routes).await;
    let outcome = ys::map::new(service.url("/")).send().await?;
    assert_eq!(
        service
            .requests()
            .await
            .iter()
            .filter(|request| request.path == "/middle")
            .count(),
        1
    );
    assert_eq!(outcome.summary().requests, 7);
    assert_eq!(outcome.frontier().len(), 0);
    service.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn redirect_chain_follows_cached_aliases_before_reusing_terminal_state() -> TestResult {
    let mut routes = routes(br#"<a href="/a">a</a><a href="/c">c</a>"#);
    routes.push(("/a".to_owned(), FixtureResponse::redirect("/target")));
    routes.push(("/c".to_owned(), FixtureResponse::redirect("/a")));
    routes.push((
        "/target".to_owned(),
        FixtureResponse::bytes(200, Some("text/html"), br#"<a href="/child">child</a>"#),
    ));
    routes.push((
        "/child".to_owned(),
        FixtureResponse::bytes(200, Some("text/html"), b"<p>child</p>"),
    ));
    let service = FixtureService::start(Protocol::Http, routes).await;
    let outcome = ys::map::new(service.url("/")).send().await?;
    assert_eq!(
        service
            .requests()
            .await
            .iter()
            .filter(|request| request.path == "/a")
            .count(),
        1
    );
    assert!(
        !outcome
            .relationships()
            .iter()
            .any(|edge| edge.kind == ys::map::RelationshipKind::Link
                && edge.from.path() == "/a"
                && edge.to.path() == "/child")
    );
    assert!(
        outcome
            .relationships()
            .iter()
            .any(|edge| edge.kind == ys::map::RelationshipKind::Link
                && edge.from.path() == "/target"
                && edge.to.path() == "/child")
    );
    assert_eq!(outcome.frontier().len(), 0);
    service.shutdown().await;
    Ok(())
}
