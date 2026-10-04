//! Immutable canonical static rendered-DOM documents.
//!
//! The v1 light-DOM model contains one document tree. It excludes shadow-root
//! contents, iframe subdocuments, pseudo-elements, and flattened/composed trees.
//! Descendant text is normalized from DOM text nodes, including script and style
//! data; it does not claim layout visibility or rendered paint order.

#[path = "rendered_dom_evaluation.rs"]
mod evaluation;
#[path = "rendered_dom_index.rs"]
mod index;
#[path = "rendered_dom_parsing.rs"]
mod parsing;
#[path = "rendered_dom_types.rs"]
mod types;
#[path = "rendered_dom_validation.rs"]
mod validation;
#[path = "rendered_dom_wire.rs"]
mod wire;

pub use parsing::RenderedDomParseError;
pub use types::{RENDERED_DOM_SCHEMA_V1, RENDERED_DOM_TREE_MODEL, RenderedDomDocument};

pub fn parse_failure(error: &RenderedDomParseError) -> crate::LocateFailure {
    parsing::parse_failure(error)
}
