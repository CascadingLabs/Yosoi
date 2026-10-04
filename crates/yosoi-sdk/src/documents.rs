//! Create immutable documents, then parse or locate using a policy.

use crate::{
    locators::{LocateOutcome, Plan},
    policy::Policy,
};

pub use yosoi::ParseError;
pub use yosoi_documents::{
    AccessibilityCompleteness, DocumentClass, DocumentEpoch, DocumentError, DocumentId,
    DocumentProfile, DocumentRepresentation, DocumentSchemaProfile, SourceFormat,
};

/// An immutable SDK document. Storage and engine handles remain private.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Document {
    inner: yosoi::Document,
}

impl Document {
    /// Creates a source HTML document with an explicit identity.
    pub fn html(id: impl Into<String>, bytes: impl Into<Vec<u8>>) -> Result<Self, DocumentError> {
        yosoi::Document::html(id, bytes).map(|inner| Self { inner })
    }
    /// Creates an XML document.
    pub fn xml(id: impl Into<String>, bytes: impl Into<Vec<u8>>) -> Result<Self, DocumentError> {
        yosoi::Document::xml(id, bytes).map(|inner| Self { inner })
    }
    /// Creates a JSON document.
    pub fn json(id: impl Into<String>, bytes: impl Into<Vec<u8>>) -> Result<Self, DocumentError> {
        yosoi::Document::json(id, bytes).map(|inner| Self { inner })
    }
    /// Creates a decoded text document.
    pub fn text(id: impl Into<String>, bytes: impl Into<Vec<u8>>) -> Result<Self, DocumentError> {
        yosoi::Document::text(id, bytes).map(|inner| Self { inner })
    }
    /// Creates a rendered DOM document bound to its browser document epoch.
    pub fn rendered_dom(
        id: impl Into<String>,
        epoch: DocumentEpoch,
        bytes: impl Into<Vec<u8>>,
    ) -> Result<Self, DocumentError> {
        yosoi::Document::rendered_dom(id, epoch, bytes).map(|inner| Self { inner })
    }
    /// Creates an accessibility-tree document bound to its browser document epoch.
    pub fn accessibility_tree(
        id: impl Into<String>,
        epoch: DocumentEpoch,
        bytes: impl Into<Vec<u8>>,
    ) -> Result<Self, DocumentError> {
        yosoi::Document::accessibility_tree(id, epoch, bytes).map(|inner| Self { inner })
    }
    /// Creates a document with an explicitly chosen representation profile.
    pub fn from_profile(
        id: DocumentId,
        profile: DocumentProfile,
        bytes: impl Into<Vec<u8>>,
    ) -> Result<Self, DocumentError> {
        yosoi::Document::from_profile(id, profile, bytes).map(|inner| Self { inner })
    }
    /// Returns the document identity.
    pub const fn id(&self) -> &DocumentId {
        self.inner.id()
    }
    /// Returns the representation class.
    pub const fn class(&self) -> DocumentClass {
        self.inner.class()
    }
    /// Returns the representation profile.
    pub const fn profile(&self) -> DocumentProfile {
        self.inner.profile()
    }
    /// Returns the immutable document bytes.
    pub fn bytes(&self) -> &[u8] {
        self.inner.bytes()
    }
    /// Returns the number of retained bytes.
    pub const fn byte_len(&self) -> u64 {
        self.inner.byte_len()
    }
    /// Borrows a policy for subsequent parse and locate operations.
    pub const fn bind<'document, 'policy>(
        &'document self,
        policy: &'policy Policy,
    ) -> BoundDocument<'document, 'policy> {
        BoundDocument {
            inner: self.inner.bind(policy),
        }
    }
    /// Parses once so multiple plans can reuse the representation.
    pub fn parse(&self) -> Result<ParsedDocument<'_>, ParseError> {
        self.inner.parse().map(|inner| ParsedDocument { inner })
    }
    /// Evaluates a locator plan using the package's default policy.
    pub fn locate(&self, plan: &Plan) -> LocateOutcome {
        self.inner.locate(plan)
    }
}

/// A reusable parsed representation with its original policy budget.
#[derive(Debug)]
pub struct ParsedDocument<'document> {
    inner: yosoi::ParsedDocument<'document>,
}
impl ParsedDocument<'_> {
    /// Evaluates a locator plan on the retained representation.
    pub fn locate(&self, plan: &Plan) -> LocateOutcome {
        self.inner.locate(plan)
    }
}

/// A borrowed document and policy for bounded SDK operations.
#[derive(Debug)]
pub struct BoundDocument<'document, 'policy> {
    inner: yosoi::BoundDocument<'document, 'policy>,
}
impl<'document> BoundDocument<'document, '_> {
    /// Parses using the bound policy.
    pub fn parse(&self) -> Result<ParsedDocument<'document>, ParseError> {
        self.inner.parse().map(|inner| ParsedDocument { inner })
    }
    /// Evaluates a plan using the bound policy.
    pub fn locate(&self, plan: &Plan) -> LocateOutcome {
        self.inner.locate(plan)
    }
}

/// A borrowed document returned by an SDK request, without an engine handle.
#[derive(Clone, Copy, Debug)]
pub struct DocumentRef<'document> {
    inner: &'document yosoi::Document,
}
impl<'document> DocumentRef<'document> {
    pub(crate) const fn from_internal(inner: &'document yosoi::Document) -> Self {
        Self { inner }
    }
    /// Returns the document identity.
    pub const fn id(self) -> &'document DocumentId {
        self.inner.id()
    }
    /// Returns the representation class.
    pub const fn class(self) -> DocumentClass {
        self.inner.class()
    }
    /// Returns the interpretation profile.
    pub const fn profile(self) -> DocumentProfile {
        self.inner.profile()
    }
    /// Returns the immutable captured bytes without a copy.
    pub fn bytes(self) -> &'document [u8] {
        self.inner.bytes()
    }
    /// Returns the number of retained bytes.
    pub const fn byte_len(self) -> u64 {
        self.inner.byte_len()
    }
    /// Parses once for repeated locator evaluation.
    pub fn parse(self) -> Result<ParsedDocument<'document>, ParseError> {
        self.inner.parse().map(|inner| ParsedDocument { inner })
    }
    /// Evaluates a plan using the default policy.
    pub fn locate(self, plan: &Plan) -> LocateOutcome {
        self.inner.locate(plan)
    }
    /// Binds a borrowed policy to this borrowed document.
    pub const fn bind<'policy>(self, policy: &'policy Policy) -> BoundDocument<'document, 'policy> {
        BoundDocument {
            inner: self.inner.bind(policy),
        }
    }
    /// Retains an owned copy when this document must outlive its response.
    pub fn to_owned(self) -> Document {
        Document {
            inner: self.inner.clone(),
        }
    }
}
