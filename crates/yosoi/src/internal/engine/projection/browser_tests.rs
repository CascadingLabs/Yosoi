use super::{accessibility_can_materialize, rendered_dom_can_materialize};
use crate::internal::engine::projection::PartialReason;

#[test]
fn rendered_dom_withholds_documents_for_family_level_partial_results() {
    assert!(rendered_dom_can_materialize(false));
    assert!(!rendered_dom_can_materialize(true));
}

#[test]
fn accessibility_requires_embedded_incompleteness_for_family_partial_results() {
    assert!(accessibility_can_materialize(false, &[]));
    assert!(!accessibility_can_materialize(
        true,
        &[PartialReason::AccessibilityTreeFamilyPartial]
    ));
    assert!(accessibility_can_materialize(
        true,
        &[
            PartialReason::AccessibilityTreeFamilyPartial,
            PartialReason::AccessibilityNodeLoss,
        ]
    ));
    assert!(accessibility_can_materialize(
        true,
        &[
            PartialReason::AccessibilityTreeFamilyPartial,
            PartialReason::AccessibilityNodeLossUnknown,
        ]
    ));
}
