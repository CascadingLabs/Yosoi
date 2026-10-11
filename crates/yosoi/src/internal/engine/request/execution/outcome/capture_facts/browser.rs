use crate::internal::policy::policy::DocumentRequest;
use crate::internal::types::CaptureOffset;
use crate::internal::web_capture::{
    BrowserArtifactContext, BrowserDocumentScope, BrowserTerminalKind, CaptureTermination,
    InterruptionInitiator, WebCapture,
};
/// Bounded browser stop offset and a provider-neutral terminal classification.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BrowserTerminalFacts {
    at: CaptureOffset,
    classification: BrowserTerminalClassification,
}

impl BrowserTerminalFacts {
    pub(in crate::internal::engine) const fn from_adapter(
        at: CaptureOffset,
        kind: &BrowserTerminalKind,
    ) -> Self {
        let classification = match kind {
            BrowserTerminalKind::DeadlineReached { .. } => {
                BrowserTerminalClassification::DeadlineReached
            }
            BrowserTerminalKind::SystemInterrupted { .. } => {
                BrowserTerminalClassification::SystemInterrupted
            }
            BrowserTerminalKind::CallerCancelled { .. } => {
                BrowserTerminalClassification::CallerCancelled
            }
            BrowserTerminalKind::ProviderStopped { .. } => {
                BrowserTerminalClassification::ProviderStopped
            }
            BrowserTerminalKind::EventLimitReached => {
                BrowserTerminalClassification::EventLimitReached
            }
            BrowserTerminalKind::ByteLimitReached { .. } => {
                BrowserTerminalClassification::ByteLimitReached
            }
            BrowserTerminalKind::QuietSettled => BrowserTerminalClassification::QuietSettled,
            BrowserTerminalKind::ControllerCompleted => {
                BrowserTerminalClassification::ControllerCompleted
            }
        };
        Self { at, classification }
    }

    pub const fn at(self) -> CaptureOffset {
        self.at
    }
    pub const fn classification(self) -> BrowserTerminalClassification {
        self.classification
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BrowserTerminalClassification {
    DeadlineReached,
    SystemInterrupted,
    CallerCancelled,
    ProviderStopped,
    EventLimitReached,
    ByteLimitReached,
    QuietSettled,
    ControllerCompleted,
}

pub(super) const fn termination_is_caller_cancelled(
    termination: Option<&CaptureTermination>,
) -> bool {
    matches!(
        termination,
        Some(CaptureTermination::Interrupted(evidence))
            if matches!(evidence.initiator(), InterruptionInitiator::Caller)
    )
}

/// Browser frame and capture offset retained beside a browser-derived document.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BrowserDocumentObservation {
    scope: BrowserDocumentScope,
    captured_at: CaptureOffset,
}

impl BrowserDocumentObservation {
    pub const fn scope(self) -> BrowserDocumentScope {
        self.scope
    }
    pub const fn captured_at(self) -> CaptureOffset {
        self.captured_at
    }
}

pub(in crate::internal::engine::request::execution::outcome) fn browser_document_observation(
    capture: &WebCapture,
    requested: DocumentRequest,
) -> Option<BrowserDocumentObservation> {
    let results = capture.artifacts().results();
    let context = match requested {
        DocumentRequest::ResponseDocument => {
            let [artifact] = results.source().artifacts()? else {
                return None;
            };
            artifact.metadata().browser_context().copied()
        }
        DocumentRequest::RenderedDom => {
            let [artifact] = results.rendered_dom().artifacts()? else {
                return None;
            };
            artifact.metadata().browser_context().copied()
        }
        DocumentRequest::AccessibilityTree => {
            let [artifact] = results.accessibility_tree().artifacts()? else {
                return None;
            };
            artifact.metadata().browser_context().copied()
        }
        DocumentRequest::NetworkTree => return None,
    };
    match context? {
        BrowserArtifactContext::DocumentSnapshot { scope, captured_at } => {
            Some(BrowserDocumentObservation { scope, captured_at })
        }
        BrowserArtifactContext::Visual(_) => None,
    }
}
