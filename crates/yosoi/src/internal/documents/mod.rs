//! Static document and portable locator vocabulary.
//!
//! This crate owns the boundary between an immutable document and a compiled
//! locator plan. It deliberately does not know how a document was acquired,
//! archived, queued, or transported. Parsing and locating remain synchronous,
//! static operations with representation-native coordinates and explicit limits.

mod accessibility;
mod decoded_text;
mod document;
mod html;
mod json;
mod limits;
mod locator_declaration;
mod outcome;
mod parsed_document;
mod plan;
mod query;
mod region_membership;
mod rendered_dom;
pub mod xml;

pub use accessibility::{
    AccessibilityCompleteness, AccessibilityParseError, ParsedAccessibilityDocument,
};
pub use decoded_text::{DecodedTextDocument, DecodedTextParseError};
pub use document::{
    Document, DocumentClass, DocumentEpoch, DocumentError, DocumentId, DocumentProfile,
    DocumentProfileError, DocumentRepresentation, DocumentSchemaProfile, SourceFormat,
};
pub use html::{HtmlParseError, HtmlParserProfile, ParsedHtmlDocument};
pub use json::{JsonParseError, JsonQuerySyntaxError, ParsedJsonDocument, parse_json_document};
pub use limits::{ResourceBudget, ResourceBudgetError, ResourceBudgetValues, ResourceLimit};
pub use locator_declaration::{PinnedLocator, PinnedOutputLocator, locator};
pub use outcome::{
    AccessibilityCoordinate, ByteRange, Completeness, CoordinateError, DecodedTextCoordinate,
    DomCoordinate, DomNodeId, ExpandedNamePathSegment, Finding, FindingError, IncompleteEvidence,
    JsonCoordinate, LocateFailure, LocateOutcome, LocateResult, LocateResultError,
    NativeCoordinate, NodeReference, ProjectedValue, RegionLineage, TextRange, TreeCoordinate,
};
pub use parsed_document::{DocumentExecutionTuning, DocumentParseError, ParsedDocument};
pub use plan::{
    NamedOutput, OutputId, OutputPlan, OutputSelection, Plan, PlanError, RegionId, RegionPlan,
    output,
};
pub use query::{
    AccessibilityStateName, NamespaceBinding, QueryAtom, QueryError, QueryResultShape, QuerySpec,
    accessibility_state, accessibility_text, accessible_name, css, json_path, json_pointer, regex,
    role, text_literal, tree_text_contains, xpath,
};
pub use rendered_dom::{
    RENDERED_DOM_SCHEMA_V1, RENDERED_DOM_TREE_MODEL, RenderedDomDocument, RenderedDomParseError,
};
pub use xml::{XmlDocument, XmlError};

pub(in crate::internal::documents) use plan::CompiledOutput;
pub(in crate::internal::documents) use query::Projection;

/// The small public authoring surface used by the SDK facade.
pub mod prelude {
    pub use crate::internal::documents::{
        AccessibilityCompleteness, AccessibilityCoordinate, AccessibilityStateName, ByteRange,
        Completeness, CoordinateError, DecodedTextCoordinate, Document, DocumentClass,
        DocumentEpoch, DocumentError, DocumentId, DocumentParseError, DocumentProfile,
        DocumentRepresentation, DocumentSchemaProfile, DomCoordinate, DomNodeId,
        ExpandedNamePathSegment, Finding, FindingError, IncompleteEvidence, JsonCoordinate,
        JsonQuerySyntaxError, LocateFailure, LocateOutcome, LocateResult, LocateResultError,
        NamedOutput, NamespaceBinding, NativeCoordinate, NodeReference, OutputId, OutputPlan,
        OutputSelection, ParsedDocument, PinnedLocator, PinnedOutputLocator, Plan, PlanError,
        ProjectedValue, QueryAtom, QueryError, QueryResultShape, QuerySpec, RegionId,
        RegionLineage, RegionPlan, ResourceLimit, SourceFormat, TextRange, TreeCoordinate,
        accessibility_state, accessibility_text, accessible_name, css, json_path, json_pointer,
        locator, output, regex, role, text_literal, tree_text_contains, xpath,
    };
}

#[cfg(test)]
mod integration_tests;
