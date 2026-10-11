use super::{
    fixture::{FixtureService, Protocol},
    support::*,
};
use crate::internal::direct_http::*;
use crate::internal::types::{ActivityOutcome, ArtifactAvailability};
use chrono::DateTime;
use tokio_util::sync::CancellationToken;

#[tokio::test]
async fn retain_and_report_keeps_source_facts_but_never_fabricates_decoded_output() {
    let service = FixtureService::start(
        Protocol::Http,
        [
            (
                "/unknown".into(),
                response(b"\0\x01\xff", Some("application/octet-stream")),
            ),
            (
                "/unsupported".into(),
                response(b"a,b\n1,2\n", Some("text/csv")),
            ),
            (
                "/strict-json".into(),
                response(b"{\"x\":\xff}", Some("application/json")),
            ),
            (
                "/strict-xml".into(),
                response(
                    b"<?xml version=\"1.0\"?><x>\xff</x>",
                    Some("application/xml"),
                ),
            ),
        ],
    )
    .await;
    for path in ["/unknown", "/unsupported", "/strict-json", "/strict-xml"] {
        let capture = capture_direct_http_at(
            spec(&service.url(path), Options::default()),
            &CancellationToken::new(),
            at(),
        )
        .await
        .unwrap();
        assert!(capture.source_facts().is_some());
        assert!(
            capture
                .bundle()
                .capture()
                .artifacts()
                .results()
                .decoded_source()
                .artifacts()
                .is_none()
        );
        assert_eq!(
            capture.bundle().capture().completeness(),
            CaptureCompleteness::Incomplete
        );
        assert_eq!(
            source(&capture).0.metadata().record().availability(),
            ArtifactAvailability::Retained
        );
    }
    service.shutdown().await;
}

#[tokio::test]
async fn fail_attempt_preserves_evidence_and_publishes_no_bundle() {
    let service = FixtureService::start(
        Protocol::Http,
        [
            (
                "/unknown".into(),
                response(b"\0\x01\xff", Some("application/octet-stream")),
            ),
            ("/unsupported".into(), response(b"csv", Some("text/csv"))),
        ],
    )
    .await;
    for path in ["/unknown", "/unsupported"] {
        let error = capture_direct_http_at(
            spec(
                &service.url(path),
                Options {
                    behavior: UnsupportedSourceFormatBehavior::FailAttempt,
                    ..Options::default()
                },
            ),
            &CancellationToken::new(),
            at(),
        )
        .await
        .unwrap_err();
        let DirectHttpCaptureError::Finalization {
            source: DirectHttpConstructionError::UnsupportedSource { .. },
            evidence,
        } = error
        else {
            panic!("expected unsupported source")
        };
        assert!(evidence.response().is_some());
        assert!(evidence.body().is_some());
        assert!(evidence.source_facts().is_some());
    }
    service.shutdown().await;
}

#[tokio::test]
async fn non_2xx_is_independent_and_network_request_state_is_exact() {
    let mut non_2xx = response(b"missing", Some("text/plain"));
    non_2xx.status = 404;
    non_2xx.reason = "Not Found";
    let service = FixtureService::start(
        Protocol::Http,
        [
            ("/404".into(), non_2xx),
            ("/none".into(), response(b"ok", Some("text/plain"))),
        ],
    )
    .await;
    let requested = capture_direct_http_at(
        spec(&service.url("/404"), Options::default()),
        &CancellationToken::new(),
        at(),
    )
    .await
    .unwrap();
    assert_eq!(requested.response().status(), 404);
    assert!(matches!(
        requested.bundle().capture().artifacts().results().network(),
        ArtifactFamilyResult::Unavailable { .. }
    ));
    assert_eq!(
        requested
            .bundle()
            .capture()
            .acquisition()
            .receipt()
            .receipt()
            .outcome(),
        ActivityOutcome::Succeeded
    );
    let unrequested = capture_direct_http_at(
        spec(
            &service.url("/none"),
            Options {
                network: ArtifactRequest::NotRequested,
                ..Options::default()
            },
        ),
        &CancellationToken::new(),
        at(),
    )
    .await
    .unwrap();
    assert!(
        unrequested
            .bundle()
            .capture()
            .artifacts()
            .results()
            .network()
            .is_not_requested()
    );
    service.shutdown().await;
}

#[tokio::test]
async fn replay_is_exact_and_rejects_wrong_length_or_digest() {
    let service = FixtureService::start(
        Protocol::Http,
        [(
            "/source".into(),
            response(b"replay me", Some("text/plain; charset=utf-8")),
        )],
    )
    .await;
    let capture = capture_direct_http_at(
        spec(&service.url("/source"), Options::default()),
        &CancellationToken::new(),
        at(),
    )
    .await
    .unwrap();
    let (artifact, payload) = source(&capture);
    let replay = capture
        .replay_source_facts(&output(&capture, artifact))
        .unwrap();
    assert_eq!(&replay, capture.source_facts().unwrap());
    assert_eq!(
        capture.bundle().payload(artifact.reference().into()),
        Some(payload)
    );
    assert_eq!(
        RetainedSource::from_artifact_payload(artifact, b"short".to_vec()).unwrap_err(),
        RetainedSourceReplayError::SizeMismatch
    );
    let mut mutated = payload.to_vec();
    *mutated.first_mut().unwrap() ^= 1;
    assert_eq!(
        RetainedSource::from_artifact_payload(artifact, mutated).unwrap_err(),
        RetainedSourceReplayError::DigestMismatch
    );
    service.shutdown().await;
}

#[tokio::test]
async fn injected_timestamps_are_exact_and_invalid_orders_publish_no_bundle() {
    let service = FixtureService::start(
        Protocol::Http,
        [
            ("/good".into(), response(b"clock", Some("text/plain"))),
            ("/bad".into(), response(b"clock", Some("text/plain"))),
        ],
    )
    .await;
    let started_at = at();
    let source_generated_at = DateTime::from_timestamp(1_700_000_001, 0).unwrap();
    let decoded_generated_at = DateTime::from_timestamp(1_700_000_002, 0).unwrap();
    let finished_at = DateTime::from_timestamp(1_700_000_003, 0).unwrap();
    let capture = capture_direct_http_with_clock(
        spec(&service.url("/good"), Options::default()),
        &CancellationToken::new(),
        DirectHttpCaptureTimestamps {
            started_at,
            source_generated_at,
            decoded_generated_at,
            finished_at,
        },
    )
    .await
    .unwrap();
    let web = capture.bundle().capture();
    assert_eq!(
        *web.acquisition().receipt().receipt().started_at(),
        started_at
    );
    assert_eq!(
        *web.acquisition().receipt().receipt().finished_at(),
        finished_at
    );
    let source = web
        .artifacts()
        .results()
        .source()
        .artifacts()
        .unwrap()
        .first()
        .unwrap();
    assert_eq!(
        *source.metadata().provenance().generated_at(),
        source_generated_at
    );
    let representation = web
        .artifacts()
        .results()
        .source_representation()
        .artifacts()
        .unwrap()
        .first()
        .unwrap();
    assert_eq!(
        *representation.metadata().provenance().generated_at(),
        decoded_generated_at
    );
    let decoded = web
        .artifacts()
        .results()
        .decoded_source()
        .artifacts()
        .unwrap()
        .first()
        .unwrap();
    assert_eq!(
        *decoded.metadata().provenance().generated_at(),
        decoded_generated_at
    );
    assert_eq!(
        web.acquisition().receipt().receipt().outputs(),
        &[
            source.metadata().record().clone(),
            representation.metadata().record().clone(),
            decoded.metadata().record().clone()
        ]
    );
    let error = capture_direct_http_with_clock(
        spec(&service.url("/bad"), Options::default()),
        &CancellationToken::new(),
        DirectHttpCaptureTimestamps {
            started_at,
            source_generated_at: decoded_generated_at,
            decoded_generated_at: source_generated_at,
            finished_at,
        },
    )
    .await
    .unwrap_err();
    assert!(matches!(
        error,
        DirectHttpCaptureError::Finalization {
            source: DirectHttpConstructionError::Lifecycle(
                LifecycleError::ArtifactTimestampsUnordered
            ),
            ..
        }
    ));
    service.shutdown().await;
}
