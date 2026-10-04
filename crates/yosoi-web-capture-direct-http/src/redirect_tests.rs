#![allow(clippy::unwrap_used, reason = "deterministic local fixtures")]

use std::{error::Error, time::Duration};

use chrono::{DateTime, Utc};
use tokio_util::sync::CancellationToken;

use crate::{CaptureTermination, DirectHttpRedirectPolicy, Observation, RedirectCause};

use super::{
    DirectHttpRedirectErrorKind, DirectHttpRedirectTargetPolicy, DirectHttpTransportErrorKind,
    execute_direct_http_at, execute_direct_http_at_with_redirect_policy,
    redirect_test_assertions::assert_terminal_redirect_failure, tests::spec_with_redirects,
};

fn wall_clock() -> DateTime<Utc> {
    DateTime::from_timestamp(1_700_000_000, 0).unwrap()
}

#[path = "redirect_test_server.rs"]
mod test_server;
use test_server::{server, server_observing_request};

fn follow(url: &str, hops: u32, elapsed: u64) -> crate::ResolvedDirectHttpCaptureSpec {
    spec_with_redirects(
        url,
        DirectHttpRedirectPolicy::follow(crate::RedirectHopLimit::try_from(hops).unwrap()),
        elapsed,
    )
}

#[tokio::test]
async fn observes_zero_redirects_and_final_tuple_origin() {
    let url = server(vec![(
        "HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n",
        Duration::ZERO,
    )])
    .await;
    let pending = execute_direct_http_at(
        follow(&url, 2, 1_000_000),
        &CancellationToken::new(),
        wall_clock(),
    )
    .await
    .unwrap();
    assert!(
        matches!(pending.resolution().redirects(), Observation::Observed(hops) if hops.is_empty())
    );
    assert!(
        matches!(pending.resolution().resource_origin(), Observation::Observed(crate::ObservedWebOrigin::Tuple(origin)) if pending.resolution().final_url().as_observed().unwrap().origin() == *origin)
    );
}

#[tokio::test]
async fn follows_the_five_automatic_redirect_statuses_in_order() {
    let statuses = [301, 302, 303, 307, 308];
    let mut routes = statuses
        .iter()
        .enumerate()
        .map(|(index, status)| {
            let response: &'static str = Box::leak(
                format!(
                    "HTTP/1.1 {status} Redirect\r\nLocation: /hop{}#fragment{}\r\nContent-Length: 0\r\n\r\n",
                    index + 1,
                    index + 1
                )
                .into_boxed_str(),
            );
            (response, Duration::ZERO)
        })
        .collect::<Vec<_>>();
    routes.push((
        "HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n",
        Duration::ZERO,
    ));
    let url = server(routes).await;
    let pending = execute_direct_http_at(
        follow(&url, 5, 2_000_000),
        &CancellationToken::new(),
        wall_clock(),
    )
    .await
    .unwrap();
    let hops = pending.resolution().redirects().as_observed().unwrap();
    assert_eq!(hops.len(), statuses.len());
    for (hop, status) in hops.iter().zip(statuses) {
        assert!(matches!(hop.cause(), RedirectCause::Http(value) if value.get() == status));
        assert!(hop.to().as_str().contains("#fragment"));
    }
}

#[tokio::test]
async fn multiple_choice_and_use_proxy_are_observable_but_not_followed() {
    for status in [300, 305] {
        let response: &'static str = Box::leak(
            format!(
                "HTTP/1.1 {status} Not Followed\r\nLocation: /must-not-request\r\nContent-Length: 0\r\n\r\n"
            )
            .into_boxed_str(),
        );
        let url = server(vec![(response, Duration::ZERO)]).await;
        let pending = execute_direct_http_at(
            follow(&url, 2, 1_000_000),
            &CancellationToken::new(),
            wall_clock(),
        )
        .await
        .unwrap();
        assert_eq!(pending.facts().status(), status);
        assert!(
            matches!(pending.resolution().redirects(), Observation::Observed(hops) if hops.is_empty())
        );
        assert_eq!(
            pending
                .resolution()
                .final_url()
                .as_observed()
                .unwrap()
                .as_str(),
            url
        );
    }
}

#[tokio::test]
async fn resolves_relative_query_and_fragment_references() {
    let url = server(vec![
        ("HTTP/1.1 302 Found\r\nLocation: ../next?signature=REDIRECT_SECRET#observed\r\nContent-Length: 0\r\n\r\n", Duration::ZERO),
        ("HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n", Duration::ZERO),
    ]).await;
    let pending = execute_direct_http_at(
        follow(&url, 2, 1_000_000),
        &CancellationToken::new(),
        wall_clock(),
    )
    .await
    .unwrap();
    assert!(
        pending
            .resolution()
            .final_url()
            .as_observed()
            .unwrap()
            .as_str()
            .ends_with("/next?signature=REDIRECT_SECRET#observed")
    );
    assert!(!format!("{pending:?}").contains("REDIRECT_SECRET"));
}

#[tokio::test]
async fn detects_repeated_resources_without_fragments_and_preserves_response() {
    let url = server(vec![
        ("HTTP/1.1 302 Found\r\nLocation: /next#one\r\nContent-Length: 0\r\n\r\n", Duration::ZERO),
        ("HTTP/1.1 301 Found\r\nLocation: /start?signature=INITIAL_SECRET#different\r\nContent-Length: 0\r\n\r\n", Duration::ZERO),
    ]).await;
    let failure = execute_direct_http_at(
        follow(&url, 3, 1_000_000),
        &CancellationToken::new(),
        wall_clock(),
    )
    .await
    .unwrap_err();
    let current = format!("{}/next#one", url.split("/start").next().unwrap());
    assert_terminal_redirect_failure(
        &failure,
        DirectHttpRedirectErrorKind::Loop,
        &current,
        &[(&url, &current)],
        &["INITIAL_SECRET"],
    );
}

#[tokio::test]
async fn hop_limit_is_deterministic_and_preserves_last_response() {
    let url = server(vec![
        (
            "HTTP/1.1 302 Found\r\nLocation: /one\r\nContent-Length: 0\r\n\r\n",
            Duration::ZERO,
        ),
        (
            "HTTP/1.1 307 Found\r\nLocation: /two\r\nContent-Length: 0\r\n\r\n",
            Duration::ZERO,
        ),
    ])
    .await;
    let failure = execute_direct_http_at(
        follow(&url, 1, 1_000_000),
        &CancellationToken::new(),
        wall_clock(),
    )
    .await
    .unwrap_err();
    assert_eq!(
        failure.error().kind(),
        DirectHttpTransportErrorKind::Redirect(DirectHttpRedirectErrorKind::HopLimit)
    );
    assert!(failure.has_unconsumed_response());
    assert_eq!(failure.response_status(), Some(307));
    let resolution = failure.resolution().unwrap();
    let hops = resolution.redirects().as_observed().unwrap();
    assert_eq!(hops.len(), 1);
    assert_eq!(resolution.final_url().as_observed().unwrap(), hops[0].to());
    assert!(
        matches!(failure.lifecycle().termination(), Some(CaptureTermination::Interrupted(evidence)) if evidence.reason().as_str() == "web_capture.direct_http.redirect_policy")
    );
}

#[tokio::test]
async fn classifies_missing_credential_scheme_and_policy_refusal_without_content() {
    for (location, expected) in [
        (None, DirectHttpRedirectErrorKind::MissingLocation),
        (
            Some("http://[::not-an-ipv6-address"),
            DirectHttpRedirectErrorKind::MalformedLocation,
        ),
        (
            Some("http://user:password@example.com/"),
            DirectHttpRedirectErrorKind::CredentialsNotAllowed,
        ),
        (
            Some("file:///private/secret"),
            DirectHttpRedirectErrorKind::UnsupportedScheme,
        ),
    ] {
        let header = location.map_or(String::new(), |value| format!("Location: {value}\r\n"));
        let response = Box::leak(
            format!("HTTP/1.1 302 Found\r\n{header}Content-Length: 0\r\n\r\n").into_boxed_str(),
        );
        let url = server(vec![(response, Duration::ZERO)]).await;
        let failure = execute_direct_http_at(
            follow(&url, 1, 1_000_000),
            &CancellationToken::new(),
            wall_clock(),
        )
        .await
        .unwrap_err();
        assert_eq!(
            failure.error().kind(),
            DirectHttpTransportErrorKind::Redirect(expected)
        );
        assert!(failure.has_unconsumed_response());
        assert_eq!(failure.response_status(), Some(302));
        let resolution = failure.resolution().unwrap();
        assert_eq!(resolution.final_url().as_observed().unwrap().as_str(), url);
        assert_eq!(resolution.redirects().as_observed().unwrap().len(), 0);
        assert!(matches!(
            failure.lifecycle().termination(),
            Some(CaptureTermination::Interrupted(evidence))
                if evidence.reason().as_str() == "web_capture.direct_http.redirect_policy"
        ));
        for rendered in [
            failure.to_string(),
            format!("{failure:?}"),
            format!("{:?}", failure.error()),
        ] {
            assert!(!rendered.contains("password"));
            assert!(!rendered.contains("not-an-ipv6-address"));
            assert!(!rendered.contains("signature=INITIAL_SECRET"));
        }
    }
    let url = server(vec![(
        "HTTP/1.1 302 Found\r\nLocation: http://example.com/secret\r\nContent-Length: 0\r\n\r\n",
        Duration::ZERO,
    )])
    .await;
    let failure = execute_direct_http_at_with_redirect_policy(
        follow(&url, 1, 1_000_000),
        &CancellationToken::new(),
        wall_clock(),
        DirectHttpRedirectTargetPolicy::SameOrigin,
    )
    .await
    .unwrap_err();
    assert_terminal_redirect_failure(
        &failure,
        DirectHttpRedirectErrorKind::TargetRefused,
        &url,
        &[],
        &["INITIAL_SECRET", "example.com/secret"],
    );
}

#[tokio::test]
async fn cancellation_after_one_hop_retains_exact_partial_resolution() {
    let (url, redirected_request, release_response) = server_observing_request(
        vec![
            ("HTTP/1.1 302 Found\r\nLocation: /next?token=FOLLOWED_SECRET#f\r\nContent-Length: 2000000\r\n\r\nignored", Duration::ZERO),
            ("HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n", Duration::ZERO),
        ],
        "/next?token=",
    )
    .await;
    let cancellation = CancellationToken::new();
    let trigger = cancellation.clone();
    tokio::spawn(async move {
        let _ = redirected_request.await;
        trigger.cancel();
    });
    let failure = execute_direct_http_at(follow(&url, 2, 1_000_000), &cancellation, wall_clock())
        .await
        .unwrap_err();
    let _ = release_response.send(());
    assert_eq!(
        failure.error().kind(),
        DirectHttpTransportErrorKind::Cancelled
    );
    let resolution = failure.resolution().unwrap();
    let hops = resolution.redirects().as_observed().unwrap();
    assert_eq!(hops.len(), 1);
    assert_eq!(resolution.final_url().as_observed().unwrap(), hops[0].to());
    assert!(
        matches!(failure.lifecycle().termination(), Some(CaptureTermination::Interrupted(evidence)) if evidence.reason().as_str() == "web_capture.direct_http.cancelled")
    );
    for rendered in [
        format!("{failure}"),
        format!("{failure:?}"),
        format!("{:?}", failure.error()),
    ] {
        assert!(!rendered.contains("FOLLOWED_SECRET"));
    }
}

#[tokio::test]
async fn provider_failure_after_one_hop_retains_exact_partial_resolution() {
    let url = server(vec![(
        "HTTP/1.1 308 Permanent Redirect\r\nLocation: /closed?token=SOURCE_SECRET\r\nContent-Length: 0\r\n\r\n",
        Duration::ZERO,
    )]).await;
    let failure = execute_direct_http_at(
        follow(&url, 2, 1_000_000),
        &CancellationToken::new(),
        wall_clock(),
    )
    .await
    .unwrap_err();
    let resolution = failure.resolution().unwrap();
    let hops = resolution.redirects().as_observed().unwrap();
    assert_eq!(hops.len(), 1);
    assert_eq!(resolution.final_url().as_observed().unwrap(), hops[0].to());
    assert!(
        matches!(failure.lifecycle().termination(), Some(CaptureTermination::Interrupted(evidence)) if evidence.reason().as_str() == "web_capture.direct_http.provider_failure")
    );
    let mut source = failure.error().source();
    while let Some(error) = source {
        assert!(!format!("{error}").contains("SOURCE_SECRET"));
        assert!(!format!("{error:?}").contains("SOURCE_SECRET"));
        source = error.source();
    }
}

#[tokio::test]
async fn one_overall_deadline_spans_delayed_hops() {
    let url = server(vec![
        (
            "HTTP/1.1 302 Found\r\nLocation: /next\r\nContent-Length: 0\r\n\r\n",
            Duration::from_millis(40),
        ),
        (
            "HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n",
            Duration::from_millis(40),
        ),
    ])
    .await;
    let failure = execute_direct_http_at(
        follow(&url, 2, 70_000),
        &CancellationToken::new(),
        wall_clock(),
    )
    .await
    .unwrap_err();
    assert_eq!(
        failure.error().kind(),
        DirectHttpTransportErrorKind::Timeout
    );
    let resolution = failure.resolution().unwrap();
    assert_eq!(resolution.redirects().as_observed().unwrap().len(), 1);
    assert!(matches!(
        failure.lifecycle().termination(),
        Some(CaptureTermination::DeadlineReached { .. })
    ));
}
