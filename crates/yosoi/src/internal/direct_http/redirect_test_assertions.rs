use std::error::Error;

use crate::internal::direct_http::{
    CaptureTermination, DirectHttpFailure, InterruptionInitiator, StructuredWebCaptureError,
    WebCaptureErrorContext,
};

use super::{DirectHttpRedirectErrorKind, DirectHttpTransportErrorKind};

pub(super) fn assert_terminal_redirect_failure(
    failure: &DirectHttpFailure,
    kind: DirectHttpRedirectErrorKind,
    current: &str,
    expected_hops: &[(&str, &str)],
    secrets: &[&str],
) {
    assert_eq!(
        failure.error().kind(),
        DirectHttpTransportErrorKind::Redirect(kind)
    );
    assert!(failure.has_unconsumed_response());
    let resolution = failure.resolution().unwrap();
    let hops = resolution.redirects().as_observed().unwrap();
    assert_eq!(hops.len(), expected_hops.len());
    for (hop, (from, to)) in hops.iter().zip(expected_hops) {
        assert_eq!(hop.from().as_str(), *from);
        assert_eq!(hop.to().as_str(), *to);
    }
    assert_eq!(
        resolution.final_url().as_observed().unwrap().as_str(),
        current
    );
    assert!(matches!(
        failure.lifecycle().termination(),
        Some(CaptureTermination::Interrupted(evidence))
            if evidence.initiator() == InterruptionInitiator::Provider
                && evidence.reason().as_str() == "web_capture.direct_http.redirect_policy"
    ));

    let summary = super::DirectHttpTransportError::redirect(kind)
        .at(WebCaptureErrorContext::new("acquisition.direct_http"))
        .summary();
    let structured = serde_json::to_string(&summary).unwrap();
    let rendered = [failure.to_string(), format!("{failure:?}"), structured];
    for secret in secrets {
        assert!(rendered.iter().all(|value| !value.contains(secret)));
    }
    let mut source = failure.source();
    while let Some(error) = source {
        let display = error.to_string();
        let debug = format!("{error:?}");
        for secret in secrets {
            assert!(!display.contains(secret));
            assert!(!debug.contains(secret));
        }
        source = error.source();
    }
}
