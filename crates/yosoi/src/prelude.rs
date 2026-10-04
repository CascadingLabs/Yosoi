//! Common SDK imports. Every item here belongs to a public SDK namespace.
//!
//! Import this module as `ys` when authoring a document, locator plan, request,
//! or Contract. There are no separate namespace-specific SDK preludes.

pub use crate::contracts::{Contract, ContractLocatorError, Currency, Extracted, Money};
pub use crate::documents::{Document, DocumentError, DocumentId, ParseError, ParsedDocument};
pub use crate::locators::{
    LocateOutcome, PinnedLocator, PinnedOutputLocator, Plan, PlanError, QueryError,
    accessibility_state, accessibility_text, accessible_name, css, json_path, json_pointer,
    locator, output, regex, role, text_literal, tree_text_contains, xpath,
};
pub use crate::map::{MapError, MapOutcome, MapRequest};
pub use crate::policy::{Policy, PolicyError};
pub use crate::request::{PageRequest, RequestSendError, Response, WebTarget};
pub use crate::{contracts, documents, locators, map, policy, request};
