use std::collections::BTreeMap;

use yosoi_documents::ResourceBudget;
use yosoi_policy::policy::DocumentRequest;
use yosoi_types::{ArtifactAvailability, LossExtent};
use yosoi_web_capture::{
    ArtifactByteExtent, ArtifactFamilyResult, BrowserAccessibilityCaptureMode,
    BrowserArtifactContext, BrowserStructuredEvidence, WebArtifactFamily, WebArtifactMetadata,
    WebArtifactRef, WebCapture,
};

use crate::{Policy, browser_document, policy::resource_budget_for_policy};

use super::{
    DocumentOutcome, PartialReason, ProjectionError, UnavailableReason, UnprojectableReason,
    browser_response::project_browser_response_document,
};

pub(super) fn project_browser_documents(
    capture: &WebCapture,
    requested: &[DocumentRequest],
    policy: &Policy,
    payloads: &mut BTreeMap<WebArtifactRef, Vec<u8>>,
) -> Result<Vec<DocumentOutcome>, ProjectionError> {
    let needs_document_budget = requested.iter().any(|document| {
        matches!(
            document,
            DocumentRequest::RenderedDom | DocumentRequest::AccessibilityTree
        )
    });
    let budget = if needs_document_budget {
        Some(
            resource_budget_for_policy(policy)
                .map_err(|_| ProjectionError::InvalidResourceBudget)?,
        )
    } else {
        None
    };

    requested
        .iter()
        .map(|document| match document {
            DocumentRequest::ResponseDocument => {
                Ok(project_browser_response_document(capture, payloads))
            }
            DocumentRequest::RenderedDom => project_rendered_dom(
                capture,
                budget
                    .as_ref()
                    .ok_or(ProjectionError::InvalidResourceBudget)?,
                payloads,
            ),
            DocumentRequest::AccessibilityTree => project_accessibility_tree(
                capture,
                budget
                    .as_ref()
                    .ok_or(ProjectionError::InvalidResourceBudget)?,
                payloads,
            ),
            DocumentRequest::NetworkTree => Ok(DocumentOutcome::Unprojectable {
                reason: UnprojectableReason::NetworkTreeSchemaUnavailable,
            }),
        })
        .collect()
}

fn project_rendered_dom(
    capture: &WebCapture,
    budget: &ResourceBudget,
    payloads: &mut BTreeMap<WebArtifactRef, Vec<u8>>,
) -> Result<DocumentOutcome, ProjectionError> {
    let family = WebArtifactFamily::RenderedDom;
    let result = capture.artifacts().results().rendered_dom();
    let (artifacts, family_partial) = match result {
        ArtifactFamilyResult::Complete { artifacts } => (artifacts.as_slice(), false),
        ArtifactFamilyResult::Partial { artifacts, .. } => (artifacts.as_slice(), true),
        other => return Ok(non_payload_outcome(other, family)),
    };
    let [artifact] = artifacts else {
        return Err(ProjectionError::ArtifactCountMismatch { family });
    };
    let reference: WebArtifactRef = artifact.reference().into();
    let mut reasons = Vec::new();
    if !rendered_dom_can_materialize(family_partial) {
        reasons.push(PartialReason::RenderedDomFamilyPartial);
    }
    if artifact_is_truncated(artifact.metadata()) {
        push_reason(
            &mut reasons,
            PartialReason::BrowserArtifactTruncated { family },
        );
        return Ok(DocumentOutcome::Partial {
            document: None,
            artifact: Some(reference),
            reasons,
        });
    }
    if family_partial {
        return Ok(DocumentOutcome::Partial {
            document: None,
            artifact: Some(reference),
            reasons,
        });
    }
    if !artifact_is_retained_complete(artifact.metadata()) {
        return Ok(DocumentOutcome::Unavailable {
            reason: UnavailableReason::CaptureArtifactNotRetained { family },
        });
    }
    let Some(payload) = payloads.remove(&reference) else {
        return Ok(DocumentOutcome::Unavailable {
            reason: UnavailableReason::CaptureArtifactPayloadUnavailable { family },
        });
    };
    let epoch = match artifact.metadata().browser_context() {
        Some(BrowserArtifactContext::DocumentSnapshot { scope, .. }) => scope.epoch.0,
        Some(BrowserArtifactContext::Visual(_)) | None => {
            return Ok(DocumentOutcome::Unprojectable {
                reason: UnprojectableReason::BrowserDocumentEpochUnavailable,
            });
        }
    };
    let Ok(document) = browser_document::dom::normalize_rendered_dom(
        document_id(reference),
        epoch,
        payload,
        *budget,
    ) else {
        return Ok(DocumentOutcome::Unprojectable {
            reason: UnprojectableReason::BrowserDocumentNormalizationFailed,
        });
    };
    if reasons.is_empty() {
        Ok(DocumentOutcome::Produced {
            document,
            artifact: reference,
        })
    } else {
        Ok(DocumentOutcome::Partial {
            document: Some(document),
            artifact: Some(reference),
            reasons,
        })
    }
}

fn project_accessibility_tree(
    capture: &WebCapture,
    budget: &ResourceBudget,
    payloads: &mut BTreeMap<WebArtifactRef, Vec<u8>>,
) -> Result<DocumentOutcome, ProjectionError> {
    let family = WebArtifactFamily::AccessibilityTree;
    let result = capture.artifacts().results().accessibility_tree();
    let (artifacts, family_partial) = match result {
        ArtifactFamilyResult::Complete { artifacts } => (artifacts.as_slice(), false),
        ArtifactFamilyResult::Partial { artifacts, .. } => (artifacts.as_slice(), true),
        other => return Ok(non_payload_outcome(other, family)),
    };
    let [artifact] = artifacts else {
        return Err(ProjectionError::ArtifactCountMismatch { family });
    };
    let reference: WebArtifactRef = artifact.reference().into();
    if artifact_is_truncated(artifact.metadata()) {
        let mut reasons = Vec::new();
        if family_partial {
            reasons.push(PartialReason::AccessibilityTreeFamilyPartial);
        }
        push_reason(
            &mut reasons,
            PartialReason::BrowserArtifactTruncated { family },
        );
        return Ok(DocumentOutcome::Partial {
            document: None,
            artifact: Some(reference),
            reasons,
        });
    }
    if !artifact_is_retained_complete(artifact.metadata()) {
        return Ok(DocumentOutcome::Unavailable {
            reason: UnavailableReason::CaptureArtifactNotRetained { family },
        });
    }
    let Some(payload) = payloads.remove(&reference) else {
        return Ok(DocumentOutcome::Unavailable {
            reason: UnavailableReason::CaptureArtifactPayloadUnavailable { family },
        });
    };
    let evidence = match BrowserStructuredEvidence::from_json(&payload) {
        Ok(BrowserStructuredEvidence::Accessibility(evidence)) => evidence,
        Ok(
            BrowserStructuredEvidence::Network { .. }
            | BrowserStructuredEvidence::Layout(_)
            | BrowserStructuredEvidence::RuntimeDiagnostics { .. },
        )
        | Err(_) => {
            return Ok(DocumentOutcome::Unprojectable {
                reason: UnprojectableReason::BrowserDocumentNormalizationFailed,
            });
        }
    };
    let reasons = accessibility_partial_reasons(&evidence, family_partial);
    if !accessibility_can_materialize(family_partial, &reasons) {
        return Ok(DocumentOutcome::Partial {
            document: None,
            artifact: Some(reference),
            reasons,
        });
    }
    let Ok(document) = browser_document::accessibility::normalize_accessibility(
        document_id(reference),
        evidence,
        *budget,
    ) else {
        return Ok(DocumentOutcome::Unprojectable {
            reason: UnprojectableReason::BrowserDocumentNormalizationFailed,
        });
    };
    if reasons.is_empty() {
        Ok(DocumentOutcome::Produced {
            document,
            artifact: reference,
        })
    } else {
        Ok(DocumentOutcome::Partial {
            document: Some(document),
            artifact: Some(reference),
            reasons,
        })
    }
}

fn accessibility_partial_reasons(
    evidence: &yosoi_web_capture::BrowserAccessibilityEvidence,
    family_partial: bool,
) -> Vec<PartialReason> {
    let mut reasons = Vec::new();
    if family_partial {
        reasons.push(PartialReason::AccessibilityTreeFamilyPartial);
    }
    if evidence.capture_mode == BrowserAccessibilityCaptureMode::DepthLimited {
        push_reason(&mut reasons, PartialReason::AccessibilityDepthLimited);
    }
    match evidence.nodes_lost {
        LossExtent::Known(lost) if lost > 0 => {
            push_reason(&mut reasons, PartialReason::AccessibilityNodeLoss);
        }
        LossExtent::Unknown => {
            push_reason(&mut reasons, PartialReason::AccessibilityNodeLossUnknown);
        }
        LossExtent::Known(_) => {}
    }
    match evidence.bytes.lost {
        LossExtent::Known(lost) if lost > 0 => {
            push_reason(&mut reasons, PartialReason::AccessibilityByteLoss);
        }
        LossExtent::Unknown => {
            push_reason(&mut reasons, PartialReason::AccessibilityByteLossUnknown);
        }
        LossExtent::Known(_) => {}
    }
    reasons
}

fn push_reason(reasons: &mut Vec<PartialReason>, reason: PartialReason) {
    if !reasons.contains(&reason) {
        reasons.push(reason);
    }
}

const fn rendered_dom_can_materialize(family_partial: bool) -> bool {
    // The rendered-DOM v1 wire has no completeness field. A family-level
    // partial result therefore cannot safely expose a locator Document.
    !family_partial
}

fn accessibility_can_materialize(family_partial: bool, reasons: &[PartialReason]) -> bool {
    // Accessibility v1 can safely carry partial/unknown completeness, but a
    // family-level reason not represented by the AX evidence must not be lost.
    !family_partial
        || reasons
            .iter()
            .any(|reason| *reason != PartialReason::AccessibilityTreeFamilyPartial)
}

const fn non_payload_outcome<T>(
    result: &ArtifactFamilyResult<T>,
    family: WebArtifactFamily,
) -> DocumentOutcome {
    match result {
        ArtifactFamilyResult::NotRequested => DocumentOutcome::Unprojectable {
            reason: UnprojectableReason::CaptureArtifactNotRequested { family },
        },
        ArtifactFamilyResult::Failed { .. } => DocumentOutcome::Unavailable {
            reason: UnavailableReason::CaptureArtifactFailed { family },
        },
        ArtifactFamilyResult::Unavailable { .. } => DocumentOutcome::Unavailable {
            reason: UnavailableReason::CaptureArtifactUnavailable { family },
        },
        ArtifactFamilyResult::OmittedByPolicy { .. } => DocumentOutcome::Unavailable {
            reason: UnavailableReason::CaptureArtifactNotRetained { family },
        },
        ArtifactFamilyResult::Unsupported { .. } => DocumentOutcome::Unprojectable {
            reason: UnprojectableReason::CaptureArtifactUnsupported { family },
        },
        ArtifactFamilyResult::Complete { .. } | ArtifactFamilyResult::Partial { .. } => {
            DocumentOutcome::Unavailable {
                reason: UnavailableReason::CaptureArtifactUnavailable { family },
            }
        }
    }
}

const fn artifact_is_retained_complete(metadata: &WebArtifactMetadata) -> bool {
    matches!(
        (metadata.record().availability(), metadata.extent()),
        (
            ArtifactAvailability::Retained,
            ArtifactByteExtent::Complete { .. }
        )
    )
}

const fn artifact_is_truncated(metadata: &WebArtifactMetadata) -> bool {
    matches!(
        (metadata.record().availability(), metadata.extent()),
        (
            ArtifactAvailability::Truncated,
            ArtifactByteExtent::Truncated(_)
        )
    )
}

fn document_id(reference: WebArtifactRef) -> String {
    let untyped = reference.as_untyped();
    format!("{}:{}", untyped.activity_id(), untyped.artifact_id())
}

#[cfg(test)]
#[path = "browser_tests.rs"]
mod tests;
