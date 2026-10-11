use std::{error::Error, num::NonZeroU32};

use crate::internal::types::{
    ActivityId, ActivityOutcome, ActivityReceipt, CaptureId, CaptureReceipt, OperationId, Producer,
    ProducerId, ProducerVersion,
};
use crate::internal::web_capture::{
    BrowserContextRef, CaptureResolution, CaptureResolutionError, ContextBoundHttpAcquisition,
    CookieSync, DirectHttpAcquisition, DirectHttpTransportProfile, DocumentNavigationAcquisition,
    FetchCredentials, FetchMode, HttpBrowserImpersonationProfile, HttpRedirectStatus,
    HttpSessionUse, NavigationContext, Observation, ObservedWebOrigin, OpaqueOriginId,
    PageContextFetchAcquisition, PageContextRef, RedirectCause, RedirectHop, RequestedWebTarget,
    ResolvedWebUrl, TupleWebOrigin, WebAcquisitionRecord, WebAcquisitionRecordError,
    WebAcquisitionStrategy, WebCaptureRequest, WebUrlParseError,
};
use chrono::{DateTime, Utc};
use serde_json::json;

#[test]
fn requested_and_resolved_url_debug_output_is_redacted() {
    const SECRET: &str = "capture-model-debug-secret";
    let requested =
        RequestedWebTarget::parse(&format!("https://example.test/private?token={SECRET}")).unwrap();
    let resolved = ResolvedWebUrl::parse(requested.as_str()).unwrap();

    for rendered in [format!("{requested:?}"), format!("{resolved:?}")] {
        assert!(!rendered.contains(SECRET));
        assert!(!rendered.contains("example.test"));
        assert!(rendered.contains("<redacted>"));
    }
}

#[test]
fn invalid_targets_fail_before_request_construction() {
    let invalid = [
        "example.com/path",
        "//example.com/path",
        "ftp://example.com/file",
        "file:///tmp/private.html",
        "data:text/html,hello",
        "javascript:alert(1)",
        "mailto:user@example.com",
        "https://user@example.com/",
        "https://%75ser:secret@example.com/",
        "https://user:secret@example.com/",
    ];

    assert!(RequestedWebTarget::parse("http://example.com/").is_ok());
    assert!(RequestedWebTarget::parse("https://example.com/").is_ok());
    for value in invalid {
        assert!(
            RequestedWebTarget::parse(value).is_err(),
            "accepted {value}"
        );
    }

    assert_eq!(
        RequestedWebTarget::parse("ftp://example.com/file"),
        Err(WebUrlParseError::UnsupportedScheme)
    );
    assert_eq!(
        RequestedWebTarget::parse("https://user:secret@example.com/"),
        Err(WebUrlParseError::CredentialsNotAllowed)
    );
    assert!(HttpBrowserImpersonationProfile::new("/tmp/browser-profile").is_err());
}

#[test]
fn target_normalization_preserves_query_order_and_fragment_intent() {
    let target =
        RequestedWebTarget::parse("HTTPS://ExAmPle.Com:443/a/../b?second=2&first=1#Client-State")
            .unwrap();

    assert_eq!(
        target.as_str(),
        "https://example.com/b?second=2&first=1#Client-State"
    );
    assert_eq!(
        serde_json::to_value(&target).unwrap(),
        json!("https://example.com/b?second=2&first=1#Client-State")
    );
    assert_eq!(
        serde_json::from_value::<RequestedWebTarget>(serde_json::to_value(&target).unwrap())
            .unwrap(),
        target
    );
}

#[test]
fn url_fixtures_cover_ports_ipv6_idn_and_percent_encoding() {
    let fixtures = [
        ("http://EXAMPLE.com:80", "http://example.com/"),
        (
            "https://[2001:0DB8:0:0:0:0:0:1]:443/a",
            "https://[2001:db8::1]/a",
        ),
        (
            "https://bücher.example/%7euser?q=%2f",
            "https://xn--bcher-kva.example/%7euser?q=%2f",
        ),
    ];

    for (input, expected) in fixtures {
        let target = RequestedWebTarget::parse(input).unwrap();
        assert_eq!(target.as_str(), expected);
        assert_eq!(
            serde_json::from_value::<RequestedWebTarget>(serde_json::to_value(&target).unwrap())
                .unwrap(),
            target
        );
    }
}

#[test]
fn requested_target_and_observed_origin_serialize_independently() {
    let target = RequestedWebTarget::parse("https://Example.com:443/path?q=1#fragment").unwrap();
    let origin = target.origin();

    assert_eq!(origin.as_str(), "https://example.com");
    assert_eq!(
        serde_json::to_value(&origin).unwrap(),
        json!("https://example.com")
    );
    assert!(
        "https://example.com/path"
            .parse::<TupleWebOrigin>()
            .is_err()
    );
    assert!("https://EXAMPLE.com".parse::<TupleWebOrigin>().is_err());
}

#[test]
fn concrete_acquisition_strategies_have_distinct_wire_shapes() {
    let capture_id = "123e4567-e89b-42d3-a456-426614174001"
        .parse::<CaptureId>()
        .unwrap();
    let browser_context = BrowserContextRef::new(ActivityId::random(), NonZeroU32::new(1).unwrap());
    let page_context = PageContextRef::new(CaptureId::random(), NonZeroU32::new(1).unwrap());
    let target = RequestedWebTarget::parse("https://example.com/").unwrap();
    let strategies = [
        WebAcquisitionStrategy::DirectHttp(DirectHttpAcquisition::new(
            DirectHttpTransportProfile::BrowserImpersonation(
                HttpBrowserImpersonationProfile::new("safari26").unwrap(),
            ),
            HttpSessionUse::Isolated,
        )),
        WebAcquisitionStrategy::ContextBoundHttp(ContextBoundHttpAcquisition::new(
            browser_context,
            CookieSync::Bidirectional,
        )),
        WebAcquisitionStrategy::PageContextFetch(PageContextFetchAcquisition::new(
            page_context,
            FetchMode::Cors,
            FetchCredentials::SameOrigin,
        )),
        WebAcquisitionStrategy::DocumentNavigation(DocumentNavigationAcquisition::new(
            NavigationContext::TopLevel(browser_context),
        )),
    ];

    for strategy in strategies {
        let request = WebCaptureRequest::new(capture_id, target.clone(), strategy);
        let encoded = serde_json::to_value(&request).unwrap();
        let decoded: WebCaptureRequest = serde_json::from_value(encoded).unwrap();
        assert_eq!(decoded, request);
    }

    let direct = WebCaptureRequest::new(
        capture_id,
        target,
        WebAcquisitionStrategy::DirectHttp(DirectHttpAcquisition::new(
            DirectHttpTransportProfile::BrowserImpersonation(
                HttpBrowserImpersonationProfile::new("safari26").unwrap(),
            ),
            HttpSessionUse::Isolated,
        )),
    );
    assert_eq!(
        serde_json::to_value(direct).unwrap(),
        json!({
            "capture_id": "123e4567-e89b-42d3-a456-426614174001",
            "target": "https://example.com/",
            "strategy": {
                "kind": "direct_http",
                "configuration": {
                    "transport_profile": {
                        "kind": "browser_impersonation",
                        "profile": "safari26"
                    },
                    "session": "isolated"
                }
            }
        })
    );
}

#[test]
fn observed_empty_redirects_are_distinct_from_unobserved_history() {
    let observed: Observation<Vec<RedirectHop>> = Observation::Observed(Vec::new());
    let unobserved: Observation<Vec<RedirectHop>> = Observation::Unobserved;

    assert_eq!(
        serde_json::to_value(observed).unwrap(),
        json!({"status": "observed", "value": []})
    );
    assert_eq!(
        serde_json::to_value(unobserved).unwrap(),
        json!({"status": "unobserved"})
    );
}

#[test]
fn redirect_observations_must_form_a_chain_and_end_at_the_final_url() {
    let first = ResolvedWebUrl::parse("http://example.com/").unwrap();
    let second = ResolvedWebUrl::parse("https://example.com/").unwrap();
    let unrelated = ResolvedWebUrl::parse("https://other.example/").unwrap();
    let final_url = ResolvedWebUrl::parse("https://example.com/final").unwrap();
    let status = HttpRedirectStatus::try_from(301).unwrap();

    let discontinuous = vec![
        RedirectHop::new(first.clone(), second.clone(), RedirectCause::Http(status)),
        RedirectHop::new(unrelated, final_url.clone(), RedirectCause::Script),
    ];
    assert_eq!(
        CaptureResolution::new(
            Observation::Observed(final_url.clone()),
            Observation::Observed(discontinuous),
            Observation::Unobserved,
            Observation::Unobserved,
        ),
        Err(CaptureResolutionError::DiscontinuousRedirects)
    );

    let wrong_final = vec![RedirectHop::new(first, second, RedirectCause::Http(status))];
    assert_eq!(
        CaptureResolution::new(
            Observation::Observed(final_url),
            Observation::Observed(wrong_final),
            Observation::Unobserved,
            Observation::Unobserved,
        ),
        Err(CaptureResolutionError::RedirectFinalUrlMismatch)
    );
    let fragment_chain = vec![
        RedirectHop::new(
            ResolvedWebUrl::parse("https://example.com/start").unwrap(),
            ResolvedWebUrl::parse("https://example.com/middle#client-state").unwrap(),
            RedirectCause::Http(status),
        ),
        RedirectHop::new(
            ResolvedWebUrl::parse("https://example.com/middle").unwrap(),
            ResolvedWebUrl::parse("https://example.com/end#client-state").unwrap(),
            RedirectCause::Script,
        ),
    ];
    assert!(
        CaptureResolution::new(
            Observation::Observed(ResolvedWebUrl::parse("https://example.com/end").unwrap()),
            Observation::Observed(fragment_chain),
            Observation::Unobserved,
            Observation::Unobserved,
        )
        .is_ok()
    );

    assert!(HttpRedirectStatus::try_from(200).is_err());
    assert!(HttpRedirectStatus::try_from(304).is_err());
}

#[test]
fn tuple_resource_origin_must_match_the_observed_final_url() {
    let capture = CaptureId::random();
    let request = WebCaptureRequest::new(
        capture,
        RequestedWebTarget::parse("https://example.com/").unwrap(),
        WebAcquisitionStrategy::DirectHttp(DirectHttpAcquisition::new(
            DirectHttpTransportProfile::Standard,
            HttpSessionUse::Isolated,
        )),
    );
    let resolution = CaptureResolution::new(
        Observation::Observed(ResolvedWebUrl::parse("https://example.com/final").unwrap()),
        Observation::Observed(Vec::new()),
        Observation::Observed(ObservedWebOrigin::Tuple(
            RequestedWebTarget::parse("https://other.example/")
                .unwrap()
                .origin(),
        )),
        Observation::Unobserved,
    )
    .unwrap();

    assert_eq!(
        WebAcquisitionRecord::new(request, resolution, successful_receipt(capture).unwrap()),
        Err(WebAcquisitionRecordError::ResourceOriginMismatch)
    );
}

#[test]
fn page_context_resolution_keeps_initiator_and_resource_origins_distinct() {
    let resource_url = ResolvedWebUrl::parse("https://api.example.com/data").unwrap();
    let resource_origin = resource_url.origin();
    let initiator_origin = RequestedWebTarget::parse("https://app.example.com/dashboard")
        .unwrap()
        .origin();
    let resolution = CaptureResolution::new(
        Observation::Observed(resource_url),
        Observation::Observed(Vec::new()),
        Observation::Observed(ObservedWebOrigin::Tuple(resource_origin)),
        Observation::Observed(ObservedWebOrigin::Tuple(initiator_origin)),
    )
    .unwrap();

    assert_ne!(resolution.resource_origin(), resolution.initiator_origin());
}

#[test]
fn aggregate_rejects_foreign_receipts_and_redirects_from_another_target() {
    let capture = CaptureId::random();
    let other_capture = CaptureId::random();
    let browser_context = BrowserContextRef::new(ActivityId::random(), NonZeroU32::new(1).unwrap());
    let request = WebCaptureRequest::new(
        capture,
        RequestedWebTarget::parse("https://example.com/").unwrap(),
        WebAcquisitionStrategy::DocumentNavigation(DocumentNavigationAcquisition::new(
            NavigationContext::TopLevel(browser_context),
        )),
    );
    let no_observations = CaptureResolution::new(
        Observation::Unobserved,
        Observation::Unobserved,
        Observation::Unobserved,
        Observation::Unobserved,
    )
    .unwrap();
    assert_eq!(
        WebAcquisitionRecord::new(
            request.clone(),
            no_observations,
            successful_receipt(other_capture).unwrap(),
        ),
        Err(WebAcquisitionRecordError::ReceiptIdentityMismatch)
    );

    let unrelated = ResolvedWebUrl::parse("https://unrelated.example/").unwrap();
    let final_url = ResolvedWebUrl::parse("https://example.com/final").unwrap();
    let wrong_initial_redirect = CaptureResolution::new(
        Observation::Observed(final_url.clone()),
        Observation::Observed(vec![RedirectHop::new(
            unrelated,
            final_url,
            RedirectCause::Http(HttpRedirectStatus::try_from(302).unwrap()),
        )]),
        Observation::Unobserved,
        Observation::Unobserved,
    )
    .unwrap();
    assert_eq!(
        WebAcquisitionRecord::new(
            request,
            wrong_initial_redirect,
            successful_receipt(capture).unwrap(),
        ),
        Err(WebAcquisitionRecordError::RedirectInitialUrlMismatch)
    );

    let fragment_capture = CaptureId::random();
    let fragment_request = WebCaptureRequest::new(
        fragment_capture,
        RequestedWebTarget::parse("https://example.com/#section").unwrap(),
        WebAcquisitionStrategy::DocumentNavigation(DocumentNavigationAcquisition::new(
            NavigationContext::TopLevel(browser_context),
        )),
    );
    let final_url = ResolvedWebUrl::parse("https://example.com/final").unwrap();
    let fragment_resolution = CaptureResolution::new(
        Observation::Observed(final_url.clone()),
        Observation::Observed(vec![RedirectHop::new(
            ResolvedWebUrl::parse("https://example.com/").unwrap(),
            final_url,
            RedirectCause::Http(HttpRedirectStatus::try_from(302).unwrap()),
        )]),
        Observation::Unobserved,
        Observation::Unobserved,
    )
    .unwrap();
    assert!(
        WebAcquisitionRecord::new(
            fragment_request,
            fragment_resolution,
            successful_receipt(fragment_capture).unwrap(),
        )
        .is_ok()
    );
}

#[test]
fn opaque_origins_cannot_escape_their_capture() {
    let capture = CaptureId::random();
    let other_capture = CaptureId::random();
    let request = WebCaptureRequest::new(
        capture,
        RequestedWebTarget::parse("https://example.com/").unwrap(),
        WebAcquisitionStrategy::DocumentNavigation(DocumentNavigationAcquisition::new(
            NavigationContext::Frame(PageContextRef::new(
                other_capture,
                NonZeroU32::new(1).unwrap(),
            )),
        )),
    );
    let foreign_origin = OpaqueOriginId::new(other_capture, NonZeroU32::new(1).unwrap());
    let resolution = CaptureResolution::new(
        Observation::Observed(ResolvedWebUrl::parse("https://example.com/frame").unwrap()),
        Observation::Unobserved,
        Observation::Observed(ObservedWebOrigin::Opaque(foreign_origin)),
        Observation::Unobserved,
    )
    .unwrap();

    assert_eq!(
        WebAcquisitionRecord::new(request, resolution, successful_receipt(capture).unwrap()),
        Err(WebAcquisitionRecordError::ForeignOpaqueOrigin)
    );
}

#[test]
fn invalid_urls_and_unknown_fields_fail_during_json_deserialization() {
    assert!(
        serde_json::from_value::<RequestedWebTarget>(json!("file:///tmp/private.html")).is_err()
    );

    let request = json!({
        "capture_id": "123e4567-e89b-42d3-a456-426614174001",
        "target": "https://example.com/",
        "strategy": {
            "kind": "page_context_fetch",
            "configuration": {
                "mode": "cors",
                "credentials": "same_origin",
                "cookie": "secret"
            }
        }
    });
    assert!(serde_json::from_value::<WebCaptureRequest>(request).is_err());

    let zero_opaque_origin = json!({
        "capture_id": CaptureId::random().to_string(),
        "local_id": 0
    });
    assert!(serde_json::from_value::<OpaqueOriginId>(zero_opaque_origin).is_err());
}

#[test]
fn serialization_fixture_round_trips_resolution_without_fabrication() {
    let fixture = json!({
        "final_url": {"status": "unobserved"},
        "redirects": {"status": "unobserved"},
        "resource_origin": {"status": "unobserved"},
        "initiator_origin": {"status": "unobserved"}
    });

    let resolution: CaptureResolution = serde_json::from_value(fixture.clone()).unwrap();
    assert_eq!(resolution.final_url(), &Observation::Unobserved);
    assert_eq!(resolution.redirects(), &Observation::Unobserved);
    assert_eq!(serde_json::to_value(resolution).unwrap(), fixture);
}

fn successful_receipt(capture: CaptureId) -> Result<CaptureReceipt, Box<dyn Error>> {
    let timestamp = "2026-09-05T00:00:00Z".parse::<DateTime<Utc>>()?;
    let activity = ActivityReceipt::new(
        capture.activity_id(),
        OperationId::new("com.cascadinglabs.yosoi.web-capture")?,
        Producer::new(
            ProducerId::new("com.cascadinglabs.yosoi.orchestrator")?,
            ProducerVersion::new("0.1.0")?,
        ),
        Vec::new(),
        Vec::new(),
        ActivityOutcome::Succeeded,
        None,
        timestamp,
        timestamp,
    )?;
    Ok(CaptureReceipt::new(capture, activity)?)
}
