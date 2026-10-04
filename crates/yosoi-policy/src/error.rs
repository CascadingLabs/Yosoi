use crate::policy::{AcquisitionKind, DocumentRequest, Provider};
use thiserror::Error;

/// Errors found while constructing or validating policy values.
#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum PolicyError {
    /// A positive document or locator count was given zero.
    #[error("count limit must be greater than zero")]
    ZeroCountLimit,
    /// A positive step, depth, or region count was given zero.
    #[error("step limit must be greater than zero")]
    ZeroStepLimit,
    /// A positive byte bound was given zero.
    #[error("byte limit must be greater than zero")]
    ZeroByteLimit,
    /// A byte bound cannot be represented by this platform's address space.
    #[error("byte limit exceeds the supported platform size")]
    ByteLimitNotAddressable,
    /// A positive event bound was given zero.
    #[error("event limit must be greater than zero")]
    ZeroEventLimit,
    /// An event bound cannot be represented by this platform's address space.
    #[error("event limit exceeds the supported platform size")]
    EventLimitNotAddressable,
    /// A browser resource limit was given zero.
    #[error("browser resource limit must be greater than zero")]
    ZeroResourceLimit,
    /// A browser resource limit is not addressable by this platform.
    #[error("browser resource limit exceeds the supported platform size")]
    ResourceLimitNotAddressable,
    /// An accessibility-node limit was given zero.
    #[error("accessibility-node limit must be greater than zero")]
    ZeroAccessibilityNodeLimit,
    /// An accessibility-node limit is not addressable by this platform.
    #[error("accessibility-node limit exceeds the supported platform size")]
    AccessibilityNodeLimitNotAddressable,
    /// A shared attempt deadline was given zero microseconds.
    #[error("maximum elapsed duration must be greater than zero")]
    ZeroMaximumElapsed,
    /// A redirect bound was given zero transitions.
    #[error("Direct HTTP redirect hop limit must be greater than zero")]
    ZeroRedirectHopLimit,
    /// A Map budget was given zero.
    #[error("Map budgets must be greater than zero")]
    ZeroMapBudget,
    /// The Map duration was given zero.
    #[error("Map maximum elapsed duration must be greater than zero")]
    ZeroMapMaximumElapsed,
    /// A serialized Map duration had an invalid nanosecond component.
    #[error("Map duration nanoseconds must be less than one billion")]
    InvalidMapDuration,
    /// Passive subdomain discovery requires registrable-domain scope.
    #[error("passive subdomain discovery requires registrable-domain host scope")]
    PassiveSubdomainsRequireRegistrableDomain,
    /// One Map filter collection contained more than the supported number of values.
    #[error("Map filter collections may contain at most 128 values each")]
    TooManyMapFilters,
    /// A Map filter string exceeded its supported UTF-8 length.
    #[error("Map filter strings may not exceed 1024 UTF-8 bytes")]
    MapFilterStringTooLong,
    /// An empty path prefix would exclude every URL.
    #[error("Map excluded path prefixes must not be empty")]
    EmptyMapPathPrefix,
    /// More acquisition declarations were supplied than there are supported
    /// acquisition kinds.
    #[error("at most three page acquisitions are permitted")]
    TooManyAcquisitions,
    /// An acquisition kind was declared more than once.
    #[error("page acquisition is duplicated: {0:?}")]
    DuplicateAcquisition(AcquisitionKind),
    /// More document requests were supplied than the supported document set.
    #[error("at most four document requests per acquisition are permitted")]
    TooManyDocuments,
    /// A document request was repeated within one exact acquisition.
    #[error("document request is duplicated within an acquisition: {0:?}")]
    DuplicateDocument(DocumentRequest),
    /// An exact document set bypassed the canonical public constructor order.
    #[error("exact document requests must use canonical policy order")]
    NonCanonicalDocumentOrder,
    /// Direct HTTP can request only a response document.
    #[error("Direct HTTP exact selection supports only ResponseDocument")]
    UnsupportedDirectHttpDocument,
    /// A provider was selected more than once in Search policy order.
    #[error("Search provider is selected more than once: {0:?}")]
    DuplicateSearchProvider(Provider),
    /// Search hit-budget multiplication exceeded the supported integer range.
    #[error("Search result budget arithmetic exceeded its supported range")]
    SearchPlanArithmeticOverflow,
    /// The total-hit bound cannot hold every provider's configured maximum.
    #[error("Search total-hit limit {limit} is below the planned maximum {required}")]
    SearchPlanExceedsTotalResults { required: u32, limit: u32 },
    /// A Search per-provider hit limit was set to zero.
    #[error("Search per-provider result limit must be greater than zero")]
    ZeroSearchPerProviderLimit,
    /// A provider-default version was set to zero.
    #[error("provider-default version must be greater than zero")]
    ZeroProviderDefaultsVersion,
    /// A historical identity cannot describe active Search behavior.
    #[error("legacy effective-policy identity cannot include Search")]
    LegacyIdentityCannotIncludeSearch,
    /// A historical identity cannot describe active Map behavior.
    #[error("legacy effective-policy identity cannot include Map")]
    LegacyIdentityCannotIncludeMap,
    /// Pre-robots Map identity cannot represent active robots enforcement.
    #[error("pre-robots Map identity cannot include robots-rule enforcement")]
    LegacyIdentityCannotIncludeRobots,
    /// An archived effective Search route has an inconsistent resolution state.
    #[error("effective Search route has inconsistent profile or defaults state")]
    InvalidEffectiveSearchRoute,
    /// A stored effective snapshot does not match its recorded identity.
    #[error("effective policy snapshot does not match its archived identity")]
    ArchivedIdentityMismatch,
    /// An archived effective snapshot does not match its authored Policy choices.
    #[error("effective policy snapshot does not match the authored Policy")]
    ArchivedSnapshotMismatch,

    /// Canonical JSON serialization failed.
    #[error("could not serialize policy values: {0}")]
    Serialization(String),
}
