//! Shared evidence protocol for web documents and video timelines.
use super::{Budget, Coverage, SurfaceError};
use serde::{Deserialize, Serialize};

macro_rules! identity {
    ($name:ident, $docs:literal) => {
        #[doc = $docs]
        #[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd, Hash, Serialize, Deserialize)]
        #[serde(try_from = "String", into = "String")]
        pub struct $name(String);
        impl $name {
            /// Validates a nonempty opaque identifier of at most 1,024 UTF-8 bytes.
            pub fn new(value: impl Into<String>) -> Result<Self, SurfaceError> {
                let value = value.into();
                if value.is_empty() || value.len() > 1024 || value.chars().any(char::is_control) {
                    return Err(SurfaceError::Invalid(
                        "invalid evidence identifier or token".into(),
                    ));
                }
                Ok(Self(value))
            }
            /// Borrows the producer-issued value; callers must not infer address semantics.
            pub fn as_str(&self) -> &str {
                &self.0
            }
        }
        impl TryFrom<String> for $name {
            type Error = SurfaceError;
            fn try_from(value: String) -> Result<Self, Self::Error> {
                Self::new(value)
            }
        }
        impl From<$name> for String {
            fn from(value: $name) -> Self {
                value.0
            }
        }
    };
}
identity!(
    SourceId,
    "Identity of a source; it does not grant access or control."
);
identity!(
    SurfaceId,
    "Identity of one continuing representation of a source."
);
identity!(
    ObservationId,
    "Identity of one immutable interpretation, separate from live authority."
);
identity!(
    AddressToken,
    "Producer-issued address scoped to one observation; never a universal coordinate."
);
identity!(
    ContinuationToken,
    "Producer-issued read continuation bound to observation, operation and scope."
);

/// A reference shared across representations, without assuming a DOM node or timestamp.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Reference {
    /// Exact immutable evidence against which the address is interpreted.
    pub observation: ObservationId,
    /// Native address hidden behind the representation boundary.
    pub address: AddressToken,
}
/// Which operations a capability may perform on the source.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Access {
    /// Retrieves or derives evidence without changing the observed source.
    Read,
    /// May change an external source and therefore needs separate live authority.
    Control,
}
/// Advertised operation; input semantics belong to its representation.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Capability {
    /// Namespaced, versioned capability name.
    pub id: String,
    /// Whether invoking it can alter the observed source.
    pub access: Access,
    /// Shared actuation domain, absent for read-only capabilities.
    pub control_domain: Option<String>,
    /// Versioned input contract name; this value does not cause schema fetching.
    pub input_schema: String,
}
/// Discovery metadata, not a list of every domain Yosoi might eventually support.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Descriptor {
    /// Continuing representation identity.
    pub id: SurfaceId,
    /// Source represented by this surface.
    pub source: SourceId,
    /// Namespaced interpretation format and version.
    pub representation: String,
    /// Whether the currently bound provider offers any source-changing operations.
    /// This flag is descriptive and never grants action authority.
    pub controllable: bool,
    /// Read and control operations actually available on this surface.
    pub capabilities: Vec<Capability>,
}
/// Immutable evidence metadata; media position is not a wall-clock capture time.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Observation {
    /// Exact interpretation identity used in references.
    pub id: ObservationId,
    /// Continuing surface that produced this observation.
    pub surface: SurfaceId,
    /// What this representation covers, including omissions or sparse sampling.
    pub coverage: Coverage,
}
/// Bounded evidence navigation; adapters may reject operations they do not advertise.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum ReadOperation {
    /// Discover a bounded set of regions.
    Overview,
    /// Retrieve finer structural or temporal regions.
    Expand {
        /// Region to explore within its exact observation.
        reference: Reference,
    },
    /// Retrieve source-backed detail; chunks need not be standalone JSON.
    Inspect {
        /// Exact evidence to inspect.
        reference: Reference,
    },
    /// Literal search when the representation advertises it.
    Search {
        /// Literal query; this is not a universal query language.
        query: String,
    },
    /// Structural parent when the representation supports that relation.
    Parent {
        /// Evidence whose parent is requested.
        reference: Reference,
    },
}
/// One request used unchanged by web and video readers.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReadRequest {
    /// Requested navigation operation.
    pub operation: ReadOperation,
    /// Complete serialized result budget, before an outer transport envelope.
    #[serde(default)]
    pub budget: Budget,
    /// Opaque continuation copied from the preceding result.
    #[serde(default)]
    pub continuation: Option<ContinuationToken>,
}
/// A representation-neutral routing entry; interpretation-specific labels stay strings.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Entry {
    /// Exact address of this evidence.
    pub reference: Reference,
    /// Representation-specific evidence category.
    pub kind: String,
    /// Short routing label, not a generated semantic description.
    pub label: String,
    /// Bounded source-derived preview or timeline description.
    pub preview: String,
    /// Known child count, absent when unavailable.
    pub members: Option<usize>,
}
/// A bounded region or search window.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Page {
    /// Exact interpretation used for all entries.
    pub observation: ObservationId,
    /// Eligible population size, separate from returned entry count.
    pub total: usize,
    /// Position within this particular read population.
    pub offset: usize,
    /// Routing entries in this window.
    pub entries: Vec<Entry>,
    /// Continuation for the same observation and operation.
    pub next: Option<ContinuationToken>,
    /// Coverage of the representation, not a promise that all pixels were decoded.
    pub coverage: Coverage,
}
/// Exact or explicitly normalized evidence chunks.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Inspection {
    /// Exact selected evidence.
    pub reference: Reference,
    /// Format of the content field.
    pub media_type: String,
    /// Complete detail length in UTF-8 bytes.
    pub total_bytes: usize,
    /// Starting UTF-8 byte offset.
    pub offset: usize,
    /// Source-backed content; follow continuations before parsing a complete JSON record.
    pub content: String,
    /// Next chunk of the same inspection.
    pub next: Option<ContinuationToken>,
    /// Observation coverage.
    pub coverage: Coverage,
}
/// Shared read result; no browser handles, image bytes or runtime permits are serialized here.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "kind", content = "data", rename_all = "snake_case")]
pub enum ReadResult {
    /// A bounded routing page.
    Page(Page),
    /// A bounded evidence fragment.
    Inspection(Inspection),
    /// A structural parent, absent at the root.
    Parent(Option<Reference>),
}
/// Common pure reading boundary. Pixel materialization and live effects remain capabilities.
pub trait SurfaceRead: Send + Sync {
    /// Describes the source, representation, and operations actually supported.
    fn descriptor(&self) -> &Descriptor;
    /// Borrows immutable observation metadata.
    fn observation(&self) -> &Observation;
    /// Returns an address of the representation's full scope.
    fn root_reference(&self) -> Reference;
    /// Reads bounded evidence without granting or restoring action authority.
    fn read(&self, request: &ReadRequest) -> Result<ReadResult, SurfaceError>;
}
