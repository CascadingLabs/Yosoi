//! Public facade for policy-bound acquisition and static document location.
//!
//! Ordinary callers create a named document, describe named outputs in a plan,
//! then locate directly or parse once to reuse the same representation. Page
//! requests prepare ordered acquisitions without performing I/O; capture
//! resolution and projection operate on one prepared attempt. Requests execute
//! through package defaults with `send().await` or through reusable explicit
//! contexts with `send_with(...).await`.
//!
//! A static HTML example:
//!
//! ```rust
//! use std::error::Error;
//! use yosoi::prelude as ys;
//!
//! fn main() -> Result<(), Box<dyn Error>> {
//!     let document =
//!         ys::Document::html("catalog.html", b"<main><h1>Catalog</h1></main>".to_vec())?;
//!     let plan = ys::Plan::new([ys::output("title", ys::css("h1")?.text())?])?;
//!
//!     let located = document.locate(&plan);
//!     let parsed = document.parse()?;
//!     let first = parsed.locate(&plan);
//!     let second = parsed.locate(&plan);
//!     let _ = (located, first, second);
//!     Ok(())
//! }
//! ```

pub(crate) mod browser_document;
mod capture;
mod contract_locator;
mod document;
pub mod map;
pub mod projection;
pub mod request;
pub mod search;
pub use map::{MapError, MapOutcome, MapRequest, RetainedCapture};
mod resolution;
#[path = "policy.rs"]
mod resource_policy;

extern crate self as yosoi;

/// Policy value namespace plus the facade-owned resource-budget bridge.
pub mod policy {
    pub(crate) use crate::resource_policy::resource_budget_for_policy;
    pub use yosoi_policy::policy::*;

    /// Policy authoring vocabulary for constructing complete Yosoi policies.
    pub mod prelude {
        pub use super::Acquisition::{Browser, DirectHttp};
        pub use super::BrowserMode::{Headful, Headless};
        pub use super::{
            AccessibilityNodeLimit, Acquisition, AcquisitionKind, AddressableByteLimit,
            BrowserLimits, BrowserMode, DirectHttpRedirectTargets, DirectHttpRedirects,
            DocumentRequest, DocumentSelectionKind, EffectiveAcquisition, EffectivePage,
            EventLimit, MaximumElapsed, Page, RedirectHopLimit, Request, SourceLimits, Tuning,
            TuningMode,
        };
    }
}

pub use capture::{
    PolicyCapture, PolicyCaptureError, PolicyCaptureExecutionError, PolicyCaptureOutcome,
};
pub use contract_locator::ContractLocatorError;
#[doc(hidden)]
pub use contract_locator::compile_contract_plan;
pub use document::{BoundDocument, Document, ParseError, ParsedDocument};
pub use projection::{
    DocumentOutcome, PartialReason, ProjectedAttempt, ProjectionError, UnavailableReason,
    UnprojectableReason, project_attempt,
};
pub use resolution::{
    AppliedPolicy, AppliedPolicyLimit, BrowserResolutionInputs, DirectHttpResolutionInputs,
    PolicyDecision, PolicyResolutionContext, PolicyResolutionContextKind, PolicyResolutionError,
    PolicyResolver, ResolvedPolicyAttempt, ResolvedPolicySpec,
};
pub use tokio_util::sync::CancellationToken;
pub use yosoi_archive::{
    Archive, ArchiveError, ArchiveRefError, ArchivedDocumentInput, AuthoredDocumentSelection,
    CaptureArchiveRef, ContractRunArchiveRef, ContractRunRecord, ContractRunRecordError,
    ContractSchemaArchiveRef, DocumentArchiveRef, EffectivePolicyIdentityRecord,
    EvaluationRunArchiveRef, EvaluationRunError, EvaluationRunRecord, LocatorRunArchiveRef,
    LocatorRunRecord, LocatorRunRecordError, MAX_ARCHIVED_DOCUMENT_BYTES,
    MAX_CAPTURE_MATERIALIZED_BYTES, MAX_CAPTURE_PAYLOADS, MAX_EVALUATION_DOCUMENTS, PlanArchiveRef,
    PolicyArchiveRef, RequestAttemptDiagnostic, RequestAttemptFailureKind, RequestAttemptOutcome,
    RequestAttemptRecord, RequestBrowserDocumentObservation, RequestDirectHttpRedirectDiagnostic,
    RequestDirectHttpTransportDiagnostic, RequestDocumentOutcome, RequestDocumentPartialReason,
    RequestDocumentRecord, RequestDocumentUnavailableReason, RequestDocumentUnprojectableReason,
    RequestNotStartedReason, RequestRunArchiveRef, RequestRunRecord, RequestRunRecordError,
    RequestRunTermination,
};

/// Code-independent views of archived Contract outcomes.
pub mod archived {
    pub use yosoi_archive::{
        ArchivedCandidateField as CandidateField, ArchivedContractField as ContractField,
        ArchivedContractFieldValue as ContractFieldValue,
        ArchivedContractOutcome as ContractOutcome,
        ArchivedContractRecordIssue as ContractRecordIssue, ArchivedContractValue as ContractValue,
        ArchivedExtractionDiagnostic as ExtractionDiagnostic,
        ArchivedExtractionFailure as ExtractionFailure, ArchivedExtractionLimit as ExtractionLimit,
        ArchivedFieldIssue as FieldIssue, ArchivedFieldIssueKind as FieldIssueKind,
        ArchivedValidatedContractRecord as ValidatedContractRecord,
        ArchivedValidationCode as ValidationCode, ArchivedValidationFailure as ValidationFailure,
    };
}
pub use yosoi_contract_validation::{
    ArchivedContract, ContractIssues, ContractOutcome, Currency, Extracted, FieldIssue,
    FieldIssueKind, Money, RecordIssue, RuntimeValueIssue, ValidatedRecord, ValidationCode,
    ValidationFailure,
};

/// Implementation details used by Yosoi derive macros.
///
/// This is not an application SDK namespace and has no compatibility promise.
#[doc(hidden)]
pub mod __private {
    pub use yosoi_contract_validation::portable::{
        PortableCandidateField, PortableContractDecodeError, PortableContractField,
        PortableContractFieldShape, PortableContractScalar, PortableValidatedContractRecord,
    };
}
#[doc(hidden)]
pub use yosoi_contract_validation::{
    FieldIssueDraft, RuntimeContractValue, ValidationBudget, ValidationLimits, read_many,
    read_optional, read_required,
};

pub use yosoi_policy::{
    CountLimit, Documents, EffectivePolicy, EffectivePolicyIdentity, Locators, Policy, PolicyError,
    PolicySnapshot, StepLimit, Tuning, TuningMode,
};
pub use yosoi_types::{
    ActivityId, ByteLimitError, CaptureDeadlineError, CaptureId, OperationId, Producer, ProducerId,
    ProducerVersion, ReasonCode, Schema, SchemaId, SchemaVersion,
};
pub use yosoi_web_capture::{
    AcquisitionCapabilityProfile, ArtifactCapability, ArtifactMultiplicity,
    BrowserArtifactIdentityPlan, BrowserAttemptEnvironment, BrowserBoundsError, BrowserBudgetScope,
    BrowserByteBound, BrowserByteDomain, BrowserCapabilityStatus, BrowserContextRef,
    BrowserEnvironmentOverrides, BrowserEvidenceAdmissionPolicy, BrowserFamilyCapabilities,
    BrowserFinalizationError, BrowserFinalizationInput, BrowserHeaderAdmission,
    BrowserInstrumentationMode, BrowserLimitEnforcement, BrowserMainBodyAdmission, BrowserMode,
    BrowserNavigationCapabilityProfile, BrowserNavigationPolicy, BrowserOutputSchemas,
    BrowserProviderBounds, BrowserUrlAdmission, CaptureBundle, CertifiedBrowserCapabilities,
    CleanupState, DocumentNavigationAcquisition, HttpSessionUse, NavigationCompletionPolicy,
    NavigationContext, Observation, ObservationPolicy, RequestedWebTarget, SettlementPolicy,
    TupleWebOrigin, WebAcquisitionStrategy, WebArtifactCapabilitySet, WebArtifactFamily,
    WebArtifactRef, WebArtifactRequestSet, WebCapture, WebProviderCapabilityProfile,
    WebUrlParseError,
};
pub use yosoi_web_capture_direct_http::{
    AcceptedSourceFormat, AcceptedSourceFormats, DirectHttpAcquisition, DirectHttpCapture,
    DirectHttpCaptureError, DirectHttpCaptureEvidence, DirectHttpCaptureSpecError,
    DirectHttpContentLimits, DirectHttpFailure, DirectHttpOutputSchemas, DirectHttpRedirectPolicy,
    DirectHttpRedirectTargetPolicy, DirectHttpResponseFacts, DirectHttpTransportError,
    DirectHttpTransportProfile, RedirectHopLimit, ResolvedDirectHttpCaptureSpec,
    SourceRetentionPolicy, UnsupportedSourceFormatBehavior, wreq_adapter_producer,
};

#[cfg(feature = "browser")]
pub use yosoi_web_capture::VoidCrawlAdapterError;

pub use request::{
    ArchivedCaptureProgress, ArchivedRequestError, ArchivedRequestProgress, ArchivedResponse,
    ArtifactDisposition, ArtifactFamilyDisposition, AttemptCaptureFacts,
    AttemptCaptureFailureFacts, AttemptDiagnostic, AttemptDocumentOutcome, AttemptFailure,
    AttemptFailureKind, AttemptOutcome, AttemptResult, AttemptTransportOutcome, BoundPageRequest,
    BrowserDocumentObservation, BrowserFailureReason, BrowserTerminalClassification,
    BrowserTerminalFacts, NotStartedAttempt, NotStartedReason, PageRequest, PreparedAttempt,
    PreparedPageRequest, RequestExecutor, RequestId, RequestPreparationError, RequestSendError,
    Response, ResponseTermination, StandardExecutionSetupError, WebTarget,
};

pub use yosoi_contracts::{
    CONTRACT_SCHEMA_VERSION, CandidateField, CandidateInput, CandidateView, Cardinality, Contract,
    ContractId, ContractIdentity, ContractSchema, ContractSchemaError, ContractValue, FieldId,
    FieldSchema, RecordScope,
};
/// Derives portable Contract metadata and a model-shaped candidate companion.
///
/// Empty identities are rejected during macro expansion:
///
/// ```compile_fail
/// use yosoi::prelude as ys;
///
/// #[derive(ys::Contract)]
/// #[ys(id = "", description = "Invalid example")]
/// struct Product {
///     #[ys(description = "Product name")]
///     name: String,
/// }
/// ```
///
/// Explicit page/repeated flags are rejected because scope is inferred from root presence:
///
/// ```compile_fail
/// use yosoi::prelude as ys;
///
/// #[derive(ys::Contract)]
/// #[ys(id = "product", description = "Invalid example", page)]
/// struct Product {
///     #[ys(description = "Product name")]
///     name: String,
/// }
/// ```
///
/// ```compile_fail
/// use yosoi::prelude as ys;
///
/// #[derive(ys::Contract)]
/// #[ys(id = "product", description = "Invalid example", repeated)]
/// struct Product {
///     #[ys(description = "Product name")]
///     name: String,
/// }
/// ```
///
/// Located Contracts must pin every field, not a partial plan:
///
/// ```compile_fail
/// use yosoi::prelude as ys;
///
/// #[derive(ys::Contract)]
/// #[ys(id = "product", description = "Invalid partial plan")]
/// struct Product {
///     #[ys(description = "Product name", locator = ys::locator::css("h2").text())]
///     name: String,
///     #[ys(description = "Product price")]
///     price: ys::Money,
/// }
/// ```
///
/// Root and field locators must be static data, not runtime callbacks:
///
/// ```compile_fail
/// use yosoi::prelude as ys;
///
/// fn runtime_root() -> ys::PinnedLocator {
///     ys::locator::css(".product")
/// }
///
/// #[derive(ys::Contract)]
/// #[ys(id = "product", description = "Invalid runtime root", root = runtime_root())]
/// struct Product {
///     #[ys(description = "Product name", locator = ys::locator::css("h2").text())]
///     name: String,
/// }
/// ```
///
/// ```compile_fail
/// use yosoi::prelude as ys;
///
/// fn runtime_field() -> ys::PinnedOutputLocator {
///     ys::locator::css("h2").text()
/// }
///
/// #[derive(ys::Contract)]
/// #[ys(id = "summary", description = "Invalid runtime field")]
/// struct Summary {
///     #[ys(description = "Page title", locator = runtime_field())]
///     title: String,
/// }
/// ```
///
/// Duplicate field identities are rejected:
///
/// ```compile_fail
/// use yosoi::prelude as ys;
///
/// #[derive(ys::Contract)]
/// #[ys(id = "product", description = "Invalid example")]
/// struct Product {
///     #[ys(id = "value", description = "Product name")]
///     name: String,
///     #[ys(id = "value", description = "Product price")]
///     price: String,
/// }
/// ```
///
/// Nested cardinality wrappers are not part of the first Contract slice:
///
/// ```compile_fail
/// use yosoi::prelude as ys;
///
/// #[derive(ys::Contract)]
/// #[ys(id = "product", description = "Invalid example")]
/// struct Product {
///     #[ys(description = "Nested values")]
///     values: Option<Vec<String>>,
/// }
/// ```
///
/// Enums and generic Contracts receive focused derive diagnostics:
///
/// ```compile_fail
/// use yosoi::prelude as ys;
///
/// #[derive(ys::Contract)]
/// #[ys(id = "product", description = "Invalid example")]
/// enum Product {
///     Tea,
/// }
/// ```
///
/// ```compile_fail
/// use yosoi::prelude as ys;
///
/// #[derive(ys::Contract)]
/// #[ys(id = "product", description = "Invalid example")]
/// struct Product<T> {
///     #[ys(description = "Generic value")]
///     value: T,
/// }
/// ```
///
/// Generated candidate metadata names are reserved:
///
/// ```compile_fail
/// use yosoi::prelude as ys;
///
/// #[derive(ys::Contract)]
/// #[ys(id = "product", description = "Invalid example")]
/// struct Product {
///     #[ys(description = "Reserved candidate metadata name")]
///     __document_id: String,
/// }
/// ```
///
/// Duplicate metadata is rejected instead of silently choosing one value:
///
/// ```compile_fail
/// use yosoi::prelude as ys;
///
/// #[derive(ys::Contract)]
/// #[ys(id = "product", id = "other", description = "Invalid example")]
/// struct Product {
///     #[ys(description = "Product name")]
///     name: String,
/// }
/// ```
pub use yosoi_contracts_derive::Contract;
pub use yosoi_documents::{
    DocumentId, DocumentProfile, DocumentRepresentation, DocumentSchemaProfile, LocateOutcome,
    PinnedLocator, PinnedOutputLocator, Plan, RegionLineage, SourceFormat, locator,
};
#[doc(hidden)]
pub use yosoi_extractor::Extracted as ExtractorOutput;
#[doc(hidden)]
pub use yosoi_extractor::ExtractionLimits;
pub use yosoi_extractor::{ExtractionDiagnostic, ExtractionFailure, ExtractionLimit};

/// Curated authoring, policy, request, capture, and result vocabulary.
pub mod prelude;

#[doc(hidden)]
pub fn extract_contract<T: Contract>(
    located: &yosoi_documents::LocateOutcome,
) -> ExtractorOutput<T> {
    let policy = yosoi_policy::Policy::default();
    let max_matches = policy.locators.max_matches.get();
    let max_regions = u64::from(policy.locators.max_regions.get());
    yosoi_extractor::extract_contract_with_limits(
        located,
        ExtractionLimits {
            max_scanned_regions: max_matches,
            max_scanned_findings: max_matches,
            max_matching_findings: max_matches,
            max_candidates: max_regions,
            max_values_per_field: max_matches,
            max_retained_evidence: max_matches,
            max_diagnostics: max_matches,
        },
    )
}

#[doc(hidden)]
pub fn extract_contract_with_limit<T: Contract>(
    located: &yosoi_documents::LocateOutcome,
    maximum_findings: u64,
) -> ExtractorOutput<T> {
    yosoi_extractor::extract_contract_with_limit(located, maximum_findings)
}

#[doc(hidden)]
pub fn extract_contract_with_limits<T: Contract>(
    located: &yosoi_documents::LocateOutcome,
    limits: ExtractionLimits,
) -> ExtractorOutput<T> {
    yosoi_extractor::extract_contract_with_limits(located, limits)
}

#[cfg(test)]
#[path = "../../yosoi-web-capture-direct-http/tests/support/direct_http_fixture.rs"]
mod test_http_fixture;
