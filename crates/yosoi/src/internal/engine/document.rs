use std::fmt;

use crate::internal::documents::{
    Document as EngineDocument, DocumentClass, DocumentEpoch, DocumentError, DocumentId,
    DocumentParseError as EngineDocumentParseError, DocumentProfile, LocateFailure, LocateOutcome,
    ParsedDocument as EngineParsedDocument, Plan, ResourceBudget, ResourceLimit,
};
use crate::internal::policy::Policy;
use thiserror::Error;

use crate::internal::engine::resource_policy::{document_tuning, resource_budget_for_policy};

/// A facade parsing error, including invalid operation-owned resource policy.
#[derive(Debug, Error)]
pub enum ParseError {
    #[error("document policy has an invalid {limit:?} limit")]
    InvalidResourcePolicy { limit: ResourceLimit },
    #[error(transparent)]
    Document(#[from] EngineDocumentParseError),
}

/// An immutable document with an explicit representation.
///
/// Bytes move into the document. DOM and accessibility-tree documents require
/// the epoch of the browser document that produced their canonical bytes.
#[derive(Clone, Eq, PartialEq)]
pub struct Document {
    inner: EngineDocument,
}

impl fmt::Debug for Document {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("Document")
            .field("id", self.id())
            .field("class", &self.class())
            .field("byte_len", &self.byte_len())
            .field("bytes", &"<redacted>")
            .finish()
    }
}

impl Document {
    /// Creates an immutable source HTML document.
    pub fn html(id: impl Into<String>, bytes: impl Into<Vec<u8>>) -> Result<Self, DocumentError> {
        EngineDocument::html(id, bytes).map(Self::from_inner)
    }

    /// Creates an immutable source XML document.
    pub fn xml(id: impl Into<String>, bytes: impl Into<Vec<u8>>) -> Result<Self, DocumentError> {
        EngineDocument::xml(id, bytes).map(Self::from_inner)
    }

    /// Creates an immutable source JSON document.
    pub fn json(id: impl Into<String>, bytes: impl Into<Vec<u8>>) -> Result<Self, DocumentError> {
        EngineDocument::json(id, bytes).map(Self::from_inner)
    }

    /// Creates an immutable decoded-text document.
    pub fn text(id: impl Into<String>, bytes: impl Into<Vec<u8>>) -> Result<Self, DocumentError> {
        EngineDocument::text(id, bytes).map(Self::from_inner)
    }

    /// Creates an immutable rendered-DOM document tied to one document epoch.
    pub fn rendered_dom(
        id: impl Into<String>,
        epoch: DocumentEpoch,
        bytes: impl Into<Vec<u8>>,
    ) -> Result<Self, DocumentError> {
        EngineDocument::rendered_dom(id, epoch, bytes).map(Self::from_inner)
    }

    /// Creates an immutable accessibility-tree document tied to one document epoch.
    pub fn accessibility_tree(
        id: impl Into<String>,
        epoch: DocumentEpoch,
        bytes: impl Into<Vec<u8>>,
    ) -> Result<Self, DocumentError> {
        EngineDocument::accessibility_tree(id, epoch, bytes).map(Self::from_inner)
    }

    /// Reconstructs a Document from its validated durable interpretation data.
    ///
    /// Callers must provide the exact archived profile; this method never
    /// substitutes between source, rendered-DOM, or accessibility evidence.
    pub fn from_profile(
        id: DocumentId,
        profile: DocumentProfile,
        bytes: impl Into<Vec<u8>>,
    ) -> Result<Self, DocumentError> {
        EngineDocument::from_profile(id, profile, bytes).map(Self::from_inner)
    }

    /// Borrows the validated owning-domain value accepted by Archive.
    pub const fn archive_value(&self) -> &EngineDocument {
        &self.inner
    }

    /// Restores the SDK facade without copying an archived Document payload.
    pub const fn from_archived(value: EngineDocument) -> Self {
        Self::from_inner(value)
    }

    pub const fn id(&self) -> &DocumentId {
        self.inner.id()
    }

    /// Returns the exact semantic document class.
    pub const fn class(&self) -> DocumentClass {
        self.inner.class()
    }

    /// Returns the exact interpretation profile needed to reconstruct this value.
    pub const fn profile(&self) -> DocumentProfile {
        self.inner.profile()
    }

    /// Borrows the immutable canonical bytes owned by this document.
    pub fn bytes(&self) -> &[u8] {
        self.inner.bytes()
    }

    /// Returns the exact canonical byte length.
    pub const fn byte_len(&self) -> u64 {
        self.inner.byte_len()
    }

    /// Binds this document's next operations to a borrowed policy value.
    pub const fn bind<'document, 'policy>(
        &'document self,
        policy: &'policy Policy,
    ) -> BoundDocument<'document, 'policy> {
        BoundDocument {
            document: self,
            policy,
        }
    }

    /// Parses once with the default policy for repeated location.
    pub fn parse(&self) -> Result<ParsedDocument<'_>, ParseError> {
        self.parse_with_policy(&Policy::default())
    }

    /// Locates with the default policy in one operation.
    pub fn locate(&self, plan: &Plan) -> LocateOutcome {
        self.locate_with_policy(plan, &Policy::default())
    }

    pub(in crate::internal::engine) const fn from_inner(inner: EngineDocument) -> Self {
        Self { inner }
    }

    pub(in crate::internal::engine) fn parse_with_budget(
        &self,
        budget: ResourceBudget,
    ) -> Result<EngineParsedDocument<'_>, EngineDocumentParseError> {
        self.inner.parse_with_budget(budget)
    }

    fn parse_with_policy<'document>(
        &'document self,
        policy: &Policy,
    ) -> Result<ParsedDocument<'document>, ParseError> {
        let budget = resource_budget_for_policy(policy)
            .map_err(|error| ParseError::InvalidResourcePolicy { limit: error.limit })?;
        let inner = self
            .inner
            .parse_with_tuning(budget, document_tuning(policy.tuning))?;
        Ok(ParsedDocument { inner })
    }

    fn locate_with_policy(&self, plan: &Plan, policy: &Policy) -> LocateOutcome {
        match resource_budget_for_policy(policy) {
            Ok(budget) => {
                self.inner
                    .locate_with_tuning(plan, budget, document_tuning(policy.tuning))
            }
            Err(error) => LocateOutcome::Failed {
                failure: LocateFailure::InvalidResourcePolicy { limit: error.limit },
            },
        }
    }
}

/// A parsed document that retains the policy budget used during parsing.
#[derive(Debug)]
pub struct ParsedDocument<'document> {
    inner: EngineParsedDocument<'document>,
}

impl ParsedDocument<'_> {
    pub fn locate(&self, plan: &Plan) -> LocateOutcome {
        self.inner.locate(plan)
    }
}

/// A document view whose parse and locate operations use one borrowed policy.
#[derive(Debug)]
pub struct BoundDocument<'document, 'policy> {
    document: &'document Document,
    policy: &'policy Policy,
}

impl<'document> BoundDocument<'document, '_> {
    pub fn parse(&self) -> Result<ParsedDocument<'document>, ParseError> {
        self.document.parse_with_policy(self.policy)
    }

    pub fn locate(&self, plan: &Plan) -> LocateOutcome {
        self.document.locate_with_policy(plan, self.policy)
    }
}
