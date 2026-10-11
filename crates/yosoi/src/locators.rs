//! Describe named outputs and inspect the evidence found in a document.

pub use crate::internal::documents::{
    AccessibilityCoordinate, AccessibilityStateName, ByteRange, Completeness, CoordinateError,
    DecodedTextCoordinate, DomCoordinate, DomNodeId, ExpandedNamePathSegment, Finding,
    IncompleteEvidence, JsonCoordinate, JsonQuerySyntaxError, LocateFailure, LocateOutcome,
    LocateResult, NamedOutput, NamespaceBinding, NativeCoordinate, NodeReference, OutputId,
    OutputPlan, PinnedLocator, PinnedOutputLocator, Plan, PlanError, ProjectedValue, QueryAtom,
    QueryError, QueryResultShape, QuerySpec, RegionId, RegionLineage, RegionPlan, ResourceLimit,
    TextRange, TreeCoordinate, accessibility_state, accessibility_text, accessible_name, css,
    json_path, json_pointer, output, regex, role, text_literal, tree_text_contains, xpath,
};

/// Constructors for static locators attached to Contract fields and roots.
pub mod locator {
    pub use crate::internal::documents::locator::{css, text_literal};
}
