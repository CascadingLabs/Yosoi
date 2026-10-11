mod browser;
pub(super) use browser::browser_document_observation;
use browser::termination_is_caller_cancelled;
pub use browser::{
    BrowserDocumentObservation, BrowserTerminalClassification, BrowserTerminalFacts,
};
use std::fmt;

use crate::internal::direct_http::DirectHttpTransportErrorKind;
use crate::internal::types::{ByteCount, CaptureId, CaptureReceipt, ReasonCode};
use crate::internal::web_capture::{
    ArtifactFamilyResult, CaptureCompleteness, CaptureObservation, CaptureResolution,
    CaptureTermination, CleanupState, Observation, RedirectHop, ResolvedWebUrl, WebArtifactFamily,
    WebCapture,
};

/// Provider-neutral capture facts retained after document payload projection.
pub struct AttemptCaptureFacts {
    capture_id: CaptureId,
    requested_target: String,
    final_target: Option<ResolvedWebUrl>,
    redirects: Observation<Vec<RedirectHop>>,
    terminal_receipt: CaptureReceipt,
    observation: CaptureObservation,
    completeness: CaptureCompleteness,
    dispositions: Vec<ArtifactFamilyDisposition>,
    response_status: Option<u16>,
    source_bytes: Option<u64>,
}

impl AttemptCaptureFacts {
    pub(in crate::internal::engine) fn from_capture(
        capture: &WebCapture,
        response_status: Option<u16>,
    ) -> Self {
        let acquisition = capture.acquisition();
        let resolution = acquisition.resolution();
        let final_target = match resolution.final_url() {
            Observation::Observed(value) => Some(value.clone()),
            Observation::Unobserved => None,
        };
        let results = capture.artifacts().results();
        let dispositions = vec![
            artifact_disposition(WebArtifactFamily::Source, results.source()),
            artifact_disposition(
                WebArtifactFamily::SourceRepresentation,
                results.source_representation(),
            ),
            artifact_disposition(WebArtifactFamily::DecodedSource, results.decoded_source()),
            artifact_disposition(WebArtifactFamily::RenderedDom, results.rendered_dom()),
            artifact_disposition(
                WebArtifactFamily::AccessibilityTree,
                results.accessibility_tree(),
            ),
            artifact_disposition(WebArtifactFamily::Network, results.network()),
            artifact_disposition(WebArtifactFamily::Cookies, results.cookies()),
            artifact_disposition(WebArtifactFamily::Storage, results.storage()),
            artifact_disposition(WebArtifactFamily::Layout, results.layout()),
            artifact_disposition(WebArtifactFamily::Visual, results.visual()),
            artifact_disposition(
                WebArtifactFamily::RuntimeDiagnostics,
                results.runtime_diagnostics(),
            ),
        ];

        Self {
            capture_id: capture.id(),
            requested_target: acquisition.request().target().as_str().to_owned(),
            final_target,
            redirects: resolution.redirects().clone(),
            terminal_receipt: acquisition.receipt().clone(),
            observation: capture.observation().clone(),
            completeness: capture.completeness(),
            dispositions,
            response_status,
            source_bytes: capture
                .artifacts()
                .results()
                .source()
                .artifacts()
                .and_then(|artifacts| artifacts.first())
                .and_then(|artifact| artifact.metadata().extent().retained_bytes())
                .map(ByteCount::get),
        }
    }

    pub const fn capture_id(&self) -> CaptureId {
        self.capture_id
    }
    pub fn requested_target(&self) -> &str {
        &self.requested_target
    }
    pub const fn final_target(&self) -> Option<&ResolvedWebUrl> {
        self.final_target.as_ref()
    }
    pub const fn redirects(&self) -> &Observation<Vec<RedirectHop>> {
        &self.redirects
    }
    pub const fn terminal_receipt(&self) -> &CaptureReceipt {
        &self.terminal_receipt
    }
    pub const fn observation(&self) -> &CaptureObservation {
        &self.observation
    }
    pub const fn completeness(&self) -> CaptureCompleteness {
        self.completeness
    }
    pub fn artifact_dispositions(&self) -> &[ArtifactFamilyDisposition] {
        &self.dispositions
    }
    /// Exact retained representation extent, independent of document projection.
    pub const fn source_bytes(&self) -> Option<u64> {
        self.source_bytes
    }

    pub const fn response_status(&self) -> Option<u16> {
        self.response_status
    }
    pub(super) const fn observed_cancellation(&self) -> bool {
        termination_is_caller_cancelled(Some(self.observation.termination()))
    }
}

impl fmt::Debug for AttemptCaptureFacts {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("AttemptCaptureFacts")
            .field("capture_id", &self.capture_id)
            .field("requested_target", &"[redacted]")
            .field("has_final_target", &self.final_target.is_some())
            .field("completeness", &self.completeness)
            .field("disposition_count", &self.dispositions.len())
            .finish_non_exhaustive()
    }
}

/// Content-free result state for one artifact family.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactFamilyDisposition {
    family: WebArtifactFamily,
    disposition: ArtifactDisposition,
}

impl ArtifactFamilyDisposition {
    pub const fn family(&self) -> WebArtifactFamily {
        self.family
    }
    pub const fn disposition(&self) -> &ArtifactDisposition {
        &self.disposition
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ArtifactDisposition {
    NotRequested,
    Complete {
        artifact_count: usize,
    },
    Partial {
        artifact_count: usize,
        reason: ReasonCode,
    },
    Failed {
        reason: ReasonCode,
    },
    Unavailable {
        reason: ReasonCode,
    },
    OmittedByPolicy {
        reason: ReasonCode,
    },
    Unsupported {
        reason: ReasonCode,
    },
}

fn artifact_disposition<T>(
    family: WebArtifactFamily,
    result: &ArtifactFamilyResult<T>,
) -> ArtifactFamilyDisposition {
    let disposition = match result {
        ArtifactFamilyResult::NotRequested => ArtifactDisposition::NotRequested,
        ArtifactFamilyResult::Complete { artifacts } => ArtifactDisposition::Complete {
            artifact_count: artifacts.as_slice().len(),
        },
        ArtifactFamilyResult::Partial { artifacts, reason } => ArtifactDisposition::Partial {
            artifact_count: artifacts.as_slice().len(),
            reason: reason.clone(),
        },
        ArtifactFamilyResult::Failed { reason } => ArtifactDisposition::Failed {
            reason: reason.clone(),
        },
        ArtifactFamilyResult::Unavailable { reason } => ArtifactDisposition::Unavailable {
            reason: reason.clone(),
        },
        ArtifactFamilyResult::OmittedByPolicy { reason } => ArtifactDisposition::OmittedByPolicy {
            reason: reason.clone(),
        },
        ArtifactFamilyResult::Unsupported { reason } => ArtifactDisposition::Unsupported {
            reason: reason.clone(),
        },
    };
    ArtifactFamilyDisposition {
        family,
        disposition,
    }
}

/// Capture facts available when an adapter failed before publishing a capture.
pub struct AttemptCaptureFailureFacts {
    final_target: Option<ResolvedWebUrl>,
    redirects: Option<Observation<Vec<RedirectHop>>>,
    termination: Option<CaptureTermination>,
    response_status: Option<u16>,
    transport_failure: Option<DirectHttpTransportErrorKind>,
    browser_terminal: Option<BrowserTerminalFacts>,
    browser_cleanup: Option<CleanupState>,
}

impl AttemptCaptureFailureFacts {
    pub(in crate::internal::engine) fn direct_http(
        resolution: Option<CaptureResolution>,
        termination: Option<CaptureTermination>,
        response_status: Option<u16>,
        transport_failure: Option<DirectHttpTransportErrorKind>,
    ) -> Self {
        let (final_target, redirects) = resolution.map_or((None, None), |resolution| {
            let final_target = match resolution.final_url() {
                Observation::Observed(value) => Some(value.clone()),
                Observation::Unobserved => None,
            };
            (final_target, Some(resolution.redirects().clone()))
        });
        Self {
            final_target,
            redirects,
            termination,
            response_status,
            transport_failure,
            browser_terminal: None,
            browser_cleanup: None,
        }
    }

    pub(in crate::internal::engine) const fn browser(
        termination: Option<CaptureTermination>,
        browser_terminal: BrowserTerminalFacts,
        browser_cleanup: CleanupState,
        response_status: Option<u16>,
    ) -> Self {
        Self {
            final_target: None,
            redirects: None,
            termination,
            response_status,
            transport_failure: None,
            browser_terminal: Some(browser_terminal),
            browser_cleanup: Some(browser_cleanup),
        }
    }

    #[cfg(feature = "browser")]
    pub(in crate::internal::engine) const fn browser_before_finalization(
        cleanup: Option<CleanupState>,
    ) -> Self {
        Self {
            final_target: None,
            redirects: None,
            termination: None,
            response_status: None,
            transport_failure: None,
            browser_terminal: None,
            browser_cleanup: cleanup,
        }
    }

    pub const fn final_target(&self) -> Option<&ResolvedWebUrl> {
        self.final_target.as_ref()
    }
    pub const fn redirects(&self) -> Option<&Observation<Vec<RedirectHop>>> {
        self.redirects.as_ref()
    }
    pub const fn termination(&self) -> Option<&CaptureTermination> {
        self.termination.as_ref()
    }
    pub const fn response_status(&self) -> Option<u16> {
        self.response_status
    }
    pub const fn transport_failure(&self) -> Option<DirectHttpTransportErrorKind> {
        self.transport_failure
    }
    pub const fn browser_terminal(&self) -> Option<&BrowserTerminalFacts> {
        self.browser_terminal.as_ref()
    }
    pub const fn browser_cleanup(&self) -> Option<CleanupState> {
        self.browser_cleanup
    }
    pub(super) const fn observed_cancellation(&self) -> bool {
        matches!(
            self.transport_failure,
            Some(DirectHttpTransportErrorKind::Cancelled)
        ) || termination_is_caller_cancelled(self.termination.as_ref())
            || matches!(
                self.browser_terminal,
                Some(facts) if matches!(facts.classification(), BrowserTerminalClassification::CallerCancelled)
            )
    }
}

impl fmt::Debug for AttemptCaptureFailureFacts {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("AttemptCaptureFailureFacts")
            .field("has_final_target", &self.final_target.is_some())
            .field("has_redirects", &self.redirects.is_some())
            .field("termination", &self.termination)
            .field("response_status", &self.response_status)
            .field("transport_failure", &self.transport_failure)
            .field("browser_terminal", &self.browser_terminal)
            .field("browser_cleanup", &self.browser_cleanup)
            .finish()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::internal::types::CaptureOffset;
    use crate::internal::web_capture::BrowserTerminalKind;

    #[test]
    fn browser_failure_facts_preserve_an_observed_response_status() {
        let terminal = BrowserTerminalFacts::from_adapter(
            CaptureOffset::from_microseconds(7),
            &BrowserTerminalKind::ControllerCompleted,
        );
        let facts =
            AttemptCaptureFailureFacts::browser(None, terminal, CleanupState::Complete, Some(418));

        assert_eq!(facts.response_status(), Some(418));
        assert_eq!(facts.browser_cleanup(), Some(CleanupState::Complete));
    }
}
