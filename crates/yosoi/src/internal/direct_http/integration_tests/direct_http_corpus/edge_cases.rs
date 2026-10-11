use super::common::{at, route, spec};
use super::corpus::CASES;
use super::fixture::{FixtureService, Protocol, Response};
use crate::internal::direct_http::*;
use tokio_util::sync::CancellationToken;

#[tokio::test]
async fn javascript_shell_stays_source_only_without_browser_artifacts() {
    let case = CASES
        .iter()
        .find(|case| case.name == "javascript-shell")
        .unwrap();
    let service = FixtureService::start(Protocol::Http, [route(case)]).await;
    let capture = capture_direct_http_at(
        spec(&service.url("/javascript-shell")),
        &CancellationToken::new(),
        at(),
    )
    .await
    .unwrap();
    let results = capture.bundle().capture().artifacts().results();
    assert!(results.source().artifacts().is_some());
    assert!(results.decoded_source().artifacts().is_some());
    for absent in [
        results.rendered_dom().is_not_requested(),
        results.accessibility_tree().is_not_requested(),
        results.cookies().is_not_requested(),
        results.storage().is_not_requested(),
        results.layout().is_not_requested(),
        results.visual().is_not_requested(),
        results.runtime_diagnostics().is_not_requested(),
    ] {
        assert!(absent);
    }
    assert!(
        !capture
            .identity()
            .capabilities()
            .artifacts()
            .rendered_dom()
            .is_supported()
    );
    assert!(
        !capture
            .identity()
            .capabilities()
            .artifacts()
            .accessibility_tree()
            .is_supported()
    );
    service.shutdown().await;
}

#[tokio::test]
async fn raw_duplicate_and_malformed_content_type_observations_are_not_normalized() {
    let equal = Response {
        raw_headers: vec![
            b"Content-Type: text/plain".to_vec(),
            b"Content-Type: text/plain".to_vec(),
            b"Content-Length: 1".to_vec(),
        ],
        ..Response::bytes(200, None, b"x")
    };
    let conflicting = Response {
        raw_headers: vec![
            b"Content-Type: text/html".to_vec(),
            b"Content-Type: application/json".to_vec(),
            b"Content-Length: 1".to_vec(),
        ],
        ..Response::bytes(200, None, b"x")
    };
    let malformed = Response {
        raw_headers: vec![
            b"Content-Type: \xff".to_vec(),
            b"Content-Length: 1".to_vec(),
        ],
        ..Response::bytes(200, None, b"x")
    };
    let service = FixtureService::start(
        Protocol::Http,
        [
            ("/equal".into(), equal),
            ("/conflict".into(), conflicting),
            ("/malformed".into(), malformed),
        ],
    )
    .await;
    for path in ["/equal", "/conflict"] {
        let capture =
            capture_direct_http_at(spec(&service.url(path)), &CancellationToken::new(), at())
                .await
                .unwrap();
        assert!(matches!(
            capture.response().content_type(),
            ObservedHeaderValue::Duplicate
        ));
    }
    let malformed = capture_direct_http_at(
        spec(&service.url("/malformed")),
        &CancellationToken::new(),
        at(),
    )
    .await
    .unwrap();
    assert!(matches!(
        malformed.response().content_type(),
        ObservedHeaderValue::InvalidEncoding
    ));
    service.shutdown().await;
}
