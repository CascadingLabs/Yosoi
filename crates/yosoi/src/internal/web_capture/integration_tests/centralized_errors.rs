use std::error::Error;

use crate::internal::types::{ArtifactId, ArtifactRecordError};
use crate::internal::web_capture::{
    CaptureObservationError, CaptureResolutionError, MediaType, RequestedWebTarget,
    StructuredWebCaptureError, TupleWebOrigin, TupleWebOriginParseError, WebCaptureError,
    WebCaptureErrorCategory, WebCaptureErrorContext,
};
use serde_json::json;

#[test]
fn contextual_summary_has_stable_machine_readable_fields() {
    let error = CaptureResolutionError::DiscontinuousRedirects
        .at(WebCaptureErrorContext::new("/resolution/redirects"));
    let encoded = serde_json::to_value(error.summary());

    assert!(encoded.is_ok());
    if let Ok(encoded) = encoded {
        assert_eq!(
            encoded,
            json!({
                "category": "invalid_input",
                "code": "web_capture.resolution.redirects_discontinuous",
                "context": "/resolution/redirects",
                "message": "observed redirect hops must form a continuous chain"
            })
        );
    }
    assert_eq!(
        error.domain_error(),
        &CaptureResolutionError::DiscontinuousRedirects
    );
}

#[test]
fn context_is_static_and_summary_does_not_expose_invalid_input() {
    const SECRET_BEARING_INPUT: &str = "https://user:password@example.com/private?token=secret";
    let error = RequestedWebTarget::parse(SECRET_BEARING_INPUT).err();

    assert!(error.is_some());
    if let Some(error) = error {
        let contextual = error.at(WebCaptureErrorContext::new("/request/target"));
        let encoded = serde_json::to_string(&contextual.summary());

        assert_eq!(
            contextual.code().as_str(),
            "web_capture.url.credentials_not_allowed"
        );
        assert!(encoded.is_ok());
        if let Ok(encoded) = encoded {
            assert!(!encoded.contains("user:password"));
            assert!(!encoded.contains("token=secret"));
            assert!(!encoded.contains("/private"));
        }
    }
}

#[test]
fn unsupported_input_is_distinct_from_invalid_input() {
    let error = RequestedWebTarget::parse("ftp://example.com").err();

    assert!(error.is_some());
    if let Some(error) = error {
        assert_eq!(
            error.category(),
            WebCaptureErrorCategory::UnsupportedCapability
        );
        assert_eq!(error.code().as_str(), "web_capture.url.unsupported_scheme");
    }
}

#[test]
fn contextual_errors_preserve_nested_sources() {
    let error = RequestedWebTarget::parse("not a URL").err();

    assert!(error.is_some());
    if let Some(error) = error {
        let contextual = error.at(WebCaptureErrorContext::new("/request/target"));
        let domain_source = Error::source(&contextual);

        assert!(domain_source.is_some());
        if let Some(domain_source) = domain_source {
            assert_eq!(
                domain_source.to_string(),
                contextual.domain_error().to_string()
            );
            assert!(domain_source.source().is_some());
        }
    }
}

#[test]
fn transparent_url_wrapper_preserves_the_underlying_source() {
    let error = "not a URL".parse::<TupleWebOrigin>().err();

    assert!(error.is_some());
    if let Some(error) = error {
        let contextual = error.at(WebCaptureErrorContext::new("/resolution/resource_origin"));
        let tuple_source = Error::source(&contextual);

        assert!(tuple_source.is_some());
        if let Some(tuple_source) = tuple_source {
            assert!(tuple_source.is::<TupleWebOriginParseError>());
            let underlying_source = tuple_source.source();
            assert!(underlying_source.is_some());
            if let Some(underlying_source) = underlying_source {
                assert!(underlying_source.is::<url::ParseError>());
            }
        }
    }
}

#[test]
fn invalid_limit_and_policy_facts_are_not_runtime_outcomes() {
    for error in [
        CaptureObservationError::SettlementDisabled,
        CaptureObservationError::EventLimitExceeded,
        CaptureObservationError::ByteLimitExceeded,
    ] {
        assert_eq!(error.category(), WebCaptureErrorCategory::InvalidInput);
    }
}

#[test]
fn shared_core_model_errors_use_the_same_registry() {
    let error = ArtifactId::try_from(0).err();

    assert!(error.is_some());
    if let Some(error) = error {
        assert_eq!(error.code().as_str(), "web_capture.artifact.id_zero");
    }

    let error = ArtifactRecordError::MissingDigest;
    assert_eq!(error.code().as_str(), "web_capture.artifact.digest_missing");
    assert_eq!(error.category(), WebCaptureErrorCategory::InvalidInput);

    let error = WebCaptureError::ForeignArtifact;
    assert_eq!(
        error.code().as_str(),
        "web_capture.finalization.artifact_foreign"
    );

    let error = MediaType::new("").err();
    assert!(error.is_some());
    if let Some(error) = error {
        assert_eq!(
            error.code().as_str(),
            "web_capture.artifact.media_type_empty"
        );
    }
}
