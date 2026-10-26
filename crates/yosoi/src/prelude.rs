//! Common SDK imports. Every item here belongs to a public SDK namespace.
//!
//! Import this module as `ys` when authoring a document, locator plan, request,
//! or Contract. There are no separate namespace-specific SDK preludes.

pub use crate::action::AssertionBuilder;
pub use crate::contracts::{Contract, ContractLocatorError, Extracted};
pub use crate::documents::{
    Document, DocumentEpoch, DocumentError, DocumentId, DocumentProfile, ParseError, ParsedDocument,
};
pub use crate::expect::{
    AccessibilityExpectation, AllExpectation, Expectation, JsonMatch, ResponseExpectation,
    UntilExpectation,
};
pub use crate::flow::{BoundFlow, Condition, Flow, FlowInvokeError, Step};
pub use crate::flow::{Continuation, FlowPolicy, StopScope};
pub use crate::flow::{Continuation::*, StopScope::*};
pub use crate::locators::{
    IncompleteEvidence, LocateFailure, LocateOutcome, PinnedLocator, PinnedOutputLocator, Plan,
    PlanError, QueryError, accessibility_state, accessibility_text, accessible_name, css,
    json_path, json_pointer, locator, output, regex, role, text_literal, tree_text_contains, xpath,
};
pub use crate::map::{MapError, MapOutcome, MapRequest};
pub use crate::policy::{Policy, PolicyError};
pub use crate::request::{PageRequest, RequestSendError, Response, WebTarget};
pub use crate::search::{SearchQueryError, SearchRequest, SearchResponse, SearchSendError};
pub use crate::session::{Session, SessionPolicy, Work};
pub use crate::{action, expect, flow, session, view};
pub use crate::{contracts, documents, locators, map, policy, request, search};
