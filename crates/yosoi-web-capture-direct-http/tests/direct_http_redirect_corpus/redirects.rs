use crate::{
    fixture::{FixtureService, Protocol, Response, ResponseControl},
    support::*,
};
use std::{error::Error, sync::Arc};
use tokio_util::sync::CancellationToken;
use yosoi_web_capture_direct_http::*;

#[allow(clippy::option_if_let_else, clippy::single_match_else)]
fn redirect(status: u16, location: Option<&str>) -> Response {
    match location {
        Some(location) => {
            let mut response = Response::redirect(location);
            response.status = status;
            response.reason = match status {
                301 => "Moved Permanently",
                302 => "Found",
                303 => "See Other",
                307 => "Temporary Redirect",
                308 => "Permanent Redirect",
                _ => "Fixture",
            };
            response
        }
        None => {
            let mut response = Response::bytes(status, None, b"");
            response.reason = "Found";
            response
        }
    }
}
fn assert_redirect_failure(
    error: DirectHttpCaptureError,
    kind: DirectHttpRedirectErrorKind,
    hops: usize,
    secret: &str,
) {
    let failure = transport(error);
    assert_eq!(
        failure.error().kind(),
        DirectHttpTransportErrorKind::Redirect(kind)
    );
    assert_eq!(
        failure.error().category(),
        WebCaptureErrorCategory::InvalidInput
    );
    let expected_code = match kind {
        DirectHttpRedirectErrorKind::MissingLocation => {
            "web_capture.direct_http.redirect_location_missing"
        }
        DirectHttpRedirectErrorKind::MalformedLocation => {
            "web_capture.direct_http.redirect_location_malformed"
        }
        DirectHttpRedirectErrorKind::CredentialsNotAllowed => {
            "web_capture.direct_http.redirect_credentials"
        }
        DirectHttpRedirectErrorKind::UnsupportedScheme => "web_capture.direct_http.redirect_scheme",
        DirectHttpRedirectErrorKind::TargetRefused => "web_capture.direct_http.redirect_refused",
        DirectHttpRedirectErrorKind::Loop => "web_capture.direct_http.redirect_loop",
        DirectHttpRedirectErrorKind::HopLimit => "web_capture.direct_http.redirect_hop_limit",
    };
    assert_eq!(failure.error().code().as_str(), expected_code);
    assert_ne!(failure.error().to_string(), "");
    assert!(failure.has_unconsumed_response());
    assert_eq!(
        failure
            .resolution()
            .unwrap()
            .redirects()
            .as_observed()
            .unwrap()
            .len(),
        hops
    );
    assert!(
        matches!(failure.lifecycle().termination(), Some(CaptureTermination::Interrupted(value)) if value.reason().as_str() == "web_capture.direct_http.redirect_policy")
    );
    for rendered in [
        failure.to_string(),
        format!("{failure:?}"),
        format!("{:?}", failure.error()),
    ] {
        assert!(!rendered.contains(secret));
    }
    let (response, resolution, _spec, lifecycle, primary, secondary) = failure.into_parts();
    assert!(response.is_some());
    assert!(resolution.is_some());
    assert!(lifecycle.termination().is_some());
    assert_eq!(primary.kind(), DirectHttpTransportErrorKind::Redirect(kind));
    assert!(secondary.is_none());
    let mut source = primary.source();
    while let Some(value) = source {
        assert!(!format!("{value} {value:?}").contains(secret));
        source = value.source();
    }
}

#[tokio::test]
async fn disabled_and_non_follow_statuses_are_final_captures() {
    let service = FixtureService::start(
        Protocol::Http,
        [
            ("/disabled".into(), redirect(302, Some("/unused"))),
            ("/300".into(), redirect(300, Some("/unused"))),
            ("/305".into(), redirect(305, Some("/unused"))),
        ],
    )
    .await;
    let disabled = capture(
        spec(
            &service.url("/disabled"),
            DirectHttpRedirectPolicy::Disabled,
            1_000_000,
        ),
        &CancellationToken::new(),
    )
    .await
    .unwrap();
    assert_success(&disabled, 302, &service.url("/disabled"), 0, b"");
    for status in [300, 305] {
        let url = service.url(&format!("/{status}"));
        let value = capture(follow(&url, 2, 1_000_000), &CancellationToken::new())
            .await
            .unwrap();
        assert_success(&value, status, &url, 0, b"");
    }
    service.shutdown().await;
}

#[tokio::test]
async fn all_follow_statuses_form_one_continuous_chain_and_resolve_references() {
    let statuses = [301, 302, 303, 307, 308];
    let mut routes = Vec::new();
    for (index, status) in statuses.into_iter().enumerate() {
        routes.push((
            format!("/h{index}"),
            redirect(status, Some(&format!("/h{}", index + 1))),
        ));
    }
    routes.push((
        "/h5".into(),
        Response::bytes(200, Some("text/plain"), b"done"),
    ));
    routes.push(("/query".into(), redirect(302, Some("?v=2#fragment"))));
    routes.push((
        "/query?v=2".into(),
        Response::bytes(200, Some("text/plain"), b"query"),
    ));
    routes.push(("/relative/a".into(), redirect(301, Some("../final"))));
    routes.push((
        "/final".into(),
        Response::bytes(200, Some("text/plain"), b"relative"),
    ));
    let service = FixtureService::start(Protocol::Http, routes).await;
    let capture_value = capture(
        follow(&service.url("/h0"), 5, 1_000_000),
        &CancellationToken::new(),
    )
    .await
    .unwrap();
    assert_success(&capture_value, 200, &service.url("/h5"), 5, b"done");
    let hops = capture_value
        .bundle()
        .capture()
        .acquisition()
        .resolution()
        .redirects()
        .as_observed()
        .unwrap();
    for pair in hops.windows(2) {
        assert_eq!(pair[0].to(), pair[1].from());
    }
    let requests = service.requests().await;
    assert_eq!(requests.len(), 6);
    for (index, request) in requests.iter().enumerate() {
        assert_eq!(request.method, "GET");
        assert_eq!(request.path, format!("/h{index}"));
        assert_eq!(request.line, format!("GET /h{index} HTTP/1.1").as_bytes());
    }
    let query = capture(
        follow(&service.url("/query"), 1, 1_000_000),
        &CancellationToken::new(),
    )
    .await
    .unwrap();
    assert_eq!(
        query.response().final_url().as_str(),
        service.url("/query?v=2")
    );
    assert_eq!(
        query
            .bundle()
            .capture()
            .acquisition()
            .resolution()
            .final_url()
            .as_observed()
            .unwrap()
            .as_str(),
        format!("{}#fragment", service.url("/query?v=2"))
    );
    assert_eq!(
        query
            .bundle()
            .capture()
            .acquisition()
            .resolution()
            .redirects()
            .as_observed()
            .unwrap()
            .len(),
        1
    );
    let relative = capture(
        follow(&service.url("/relative/a"), 1, 1_000_000),
        &CancellationToken::new(),
    )
    .await
    .unwrap();
    assert_success(&relative, 200, &service.url("/final"), 1, b"relative");
    service.shutdown().await;
}

#[tokio::test]
async fn absolute_cross_origin_updates_final_url_and_tuple_origin() {
    let second = FixtureService::start(
        Protocol::Http,
        [(
            "/final".into(),
            Response::bytes(200, Some("text/plain"), b"cross"),
        )],
    )
    .await;
    let final_url = second.url("/final");
    let first = FixtureService::start(
        Protocol::Http,
        [("/start".into(), redirect(308, Some(&final_url)))],
    )
    .await;
    let value = capture(
        follow(&first.url("/start"), 1, 1_000_000),
        &CancellationToken::new(),
    )
    .await
    .unwrap();
    assert_success(&value, 200, &final_url, 1, b"cross");
    first.shutdown().await;
    second.shutdown().await;
}

#[tokio::test]
async fn redirect_rejections_and_exact_hop_boundary_preserve_non_lossy_evidence() {
    for (location, kind, secret) in [
        (
            None,
            DirectHttpRedirectErrorKind::MissingLocation,
            "token=START",
        ),
        (
            Some("http://[bad"),
            DirectHttpRedirectErrorKind::MalformedLocation,
            "bad",
        ),
        (
            Some("http://user:password@localhost/"),
            DirectHttpRedirectErrorKind::CredentialsNotAllowed,
            "password",
        ),
        (
            Some("file:///private/secret"),
            DirectHttpRedirectErrorKind::UnsupportedScheme,
            "private/secret",
        ),
    ] {
        let service = FixtureService::start(
            Protocol::Http,
            [("/start?token=START".into(), redirect(302, location))],
        )
        .await;
        let error = capture(
            follow(&service.url("/start?token=START"), 1, 1_000_000),
            &CancellationToken::new(),
        )
        .await
        .unwrap_err();
        assert_redirect_failure(error, kind, 0, secret);
        service.shutdown().await;
    }
    let service = FixtureService::start(
        Protocol::Http,
        [
            ("/a".into(), redirect(302, Some("/b"))),
            ("/b".into(), redirect(307, Some("/c"))),
            ("/c".into(), Response::bytes(200, Some("text/plain"), b"ok")),
        ],
    )
    .await;
    let exact = capture(
        follow(&service.url("/a"), 2, 1_000_000),
        &CancellationToken::new(),
    )
    .await
    .unwrap();
    assert_success(&exact, 200, &service.url("/c"), 2, b"ok");
    let over = capture(
        follow(&service.url("/a"), 1, 1_000_000),
        &CancellationToken::new(),
    )
    .await
    .unwrap_err();
    assert_redirect_failure(
        over,
        DirectHttpRedirectErrorKind::HopLimit,
        1,
        "never-present",
    );
    service.shutdown().await;
}

#[tokio::test]
async fn fragment_loop_is_rejected_but_changed_query_is_allowed() {
    let service = FixtureService::start(
        Protocol::Http,
        [
            ("/same".into(), redirect(302, Some("/same#other"))),
            ("/q?x=1".into(), redirect(302, Some("?x=2"))),
            (
                "/q?x=2".into(),
                Response::bytes(200, Some("text/plain"), b"changed"),
            ),
        ],
    )
    .await;
    let error = capture(
        follow(&service.url("/same#first"), 1, 1_000_000),
        &CancellationToken::new(),
    )
    .await
    .unwrap_err();
    assert_redirect_failure(error, DirectHttpRedirectErrorKind::Loop, 0, "never-present");
    let changed = capture(
        follow(&service.url("/q?x=1"), 1, 1_000_000),
        &CancellationToken::new(),
    )
    .await
    .unwrap();
    assert_success(&changed, 200, &service.url("/q?x=2"), 1, b"changed");
    service.shutdown().await;
}

#[tokio::test]
async fn one_absolute_deadline_applies_after_a_hop() {
    let second_hop = Arc::new(ResponseControl {
        hold_before_head: true,
        ..ResponseControl::default()
    });
    let slow = FixtureService::start(
        Protocol::Http,
        [
            ("/a".into(), redirect(302, Some("/b"))),
            (
                "/b".into(),
                Response {
                    control: Some(second_hop.clone()),
                    ..Response::bytes(200, Some("text/plain"), b"late")
                },
            ),
        ],
    )
    .await;
    let cancellation = CancellationToken::new();
    let attempt = capture(follow(&slow.url("/a"), 2, 250_000), &cancellation);
    tokio::pin!(attempt);
    tokio::select! {
        result = &mut attempt => panic!("capture ended before requesting the second hop: {result:?}"),
        () = second_hop.requested.wait() => {}
    }
    let failure = transport(attempt.await.unwrap_err());
    assert_eq!(
        failure.error().kind(),
        DirectHttpTransportErrorKind::Timeout
    );
    assert_eq!(
        failure
            .resolution()
            .unwrap()
            .redirects()
            .as_observed()
            .unwrap()
            .len(),
        1
    );
    assert!(matches!(
        failure.lifecycle().termination(),
        Some(CaptureTermination::DeadlineReached { .. })
    ));
    slow.shutdown().await;
}
