//! Web capture behavior for Yosoi.
//!
//! Provider-neutral web-capture foundation contracts and durable behavior.
//!
//! Concrete producers depend on this crate; transport and provider SDK
//! integration remain in producer crates such as `yosoi-web-capture-direct-http`.
//!
//! # Invariants
//!
//! - Dependencies may point inward to `yosoi-types`; `yosoi-types` must never
//!   depend on this crate.
//! - Shared vocabulary moves to `yosoi-types` only when an immediate consumer
//!   needs it.
//! - Capture abstractions are introduced only alongside behavior that uses
//!   them.

mod acquisition;
mod acquisition_finalization;
mod aggregate;
mod artifact;
mod attempt_boundary;
mod bounded_acquisition;
mod browser_adapter;
mod browser_artifact;
mod browser_challenge;
mod browser_evidence;
mod browser_execution;
mod browser_finalization;
#[cfg(feature = "browser")]
mod browser_runtime;
pub use browser_artifact::{
    BrowserArtifactIdentityPlan, BrowserArtifactIdentityPlanError, BrowserDecodedSource,
    BrowserSourceRepresentation, BrowserSourceRepresentationError, StagedBrowserArtifactEnvelope,
    StagedBrowserArtifactEnvelopeError, canonical_browser_source_representation,
};
pub use browser_challenge::{
    BROWSER_CHALLENGE_BODY_PREFIX_LIMIT, BROWSER_CHALLENGE_CORPUS_VERSION,
    BROWSER_CHALLENGE_DETECTOR_VERSION, BrowserChallengeEvidenceTier, BrowserChallengeFact,
    BrowserChallengeSignalSource, BrowserChallengeState, BrowserChallengeSupportingFact,
    BrowserResponseBodySignals, BrowserResponseSignalCompleteness, BrowserResponseSignalScope,
    BrowserResponseSignalUnavailableReason, BrowserResponseSignals, classify_browser_challenge,
};
pub use browser_evidence::{
    BrowserAccessibilityCaptureMode, BrowserAccessibilityEvidence,
    BrowserAccessibilityIgnoredNodes, BrowserAccessibilitySchema, BrowserArtifactContext,
    BrowserByteAccounting, BrowserConsoleLevel, BrowserDocumentEpoch, BrowserDocumentScope,
    BrowserExtraInfoEvidence, BrowserFrameId, BrowserLayoutFact, BrowserLayoutRect,
    BrowserMainDocumentFact, BrowserObservationFact, BrowserObservationKind, BrowserRedirectFact,
    BrowserResourceAccounting, BrowserResourceAccountingError, BrowserResourceFact,
    BrowserResourceId, BrowserResourceOutcome, BrowserRuntimeDiagnosticFact,
    BrowserRuntimeDiagnosticKind, BrowserRuntimeValueType, BrowserStructuredEvidence,
    BrowserVisualFact, BrowserVisualFormat, BrowserVisualLayoutCorrelation,
};
pub use browser_execution::{
    BrowserActiveNavigationLimit, BrowserCleanupDeadline, BrowserContextCleanupDisposition,
    BrowserContextLease, BrowserContextLeaseId, BrowserContextTotalLimit,
    BrowserContextsPerProcessLimit, BrowserEngineProgressCapacity, BrowserExecutionAccountingPhase,
    BrowserExecutionAccountingReceipt, BrowserExecutionAdmissionReceipt,
    BrowserExecutionCleanupReceipt, BrowserExecutionId, BrowserExecutionLease,
    BrowserExecutionLimits, BrowserExecutionLimitsError, BrowserExecutionManagerId,
    BrowserExecutionPreAdmissionOutcome, BrowserExecutionReceipt, BrowserExecutionReceiptError,
    BrowserExecutionScope, BrowserExecutionTerminalReason, BrowserExecutionTerminalReceipt,
    BrowserNavigationDeadline, BrowserNavigationFailure, BrowserNavigationOutcome,
    BrowserNavigationProgressAccounting, BrowserNavigationProgressCapacity,
    BrowserNavigationProgressKind, BrowserNavigationProgressReceipt,
    BrowserNavigationReadinessCheckpoint, BrowserNavigationRequest, BrowserNavigationRequestId,
    BrowserNavigationSchedulerId, BrowserNavigationSchedulerLimits,
    BrowserNavigationSchedulingError, BrowserNavigationTerminalReceipt,
    BrowserProcessCleanupDisposition, BrowserProcessGeneration, BrowserProcessLimit,
    BrowserProcessSlotId, BrowserProcessSlotLease, BrowserProfileCheckpointId,
    BrowserProfileCheckpointIdentity, BrowserProfileChildId, BrowserProfileChildIdentity,
    BrowserProfileForkError, BrowserProfileForkFailureFacts, BrowserProfileForkFailureReason,
    BrowserProfileForkFailureReceipt, BrowserProfileForkReceipt, BrowserProfileForkRequest,
    BrowserProfileForkSuccessFacts, BrowserProfileId, BrowserProfileLeaseError,
    BrowserProfileLeaseGeneration, BrowserProfileLeaseGenerationRegistry, BrowserProfileLeaseId,
    BrowserProfileLeaseReceipt, BrowserProfileLeaseScope, BrowserProfileLeaseTerminalOutcome,
    BrowserProfileLeaseTerminalReceipt, BrowserProfileLifecycleError, BrowserProfileLifecycleEvent,
    BrowserProfileLifecycleReason, BrowserProfileLifecycleRecord, BrowserProfileLifecycleSource,
    BrowserProfileLifecycleState, BrowserProfileLineageId, BrowserProfileLineageIdentity,
    BrowserProfileOwnerId, BrowserProfilePoolSnapshot, BrowserProfilePoolSnapshotEntry,
    BrowserProfileQuarantineReason, BrowserProviderEventCapacity, BrowserQueueDepthLimit,
    BrowserQueueWaitLimit, BrowserRecycleThreshold, BrowserSessionLease, BrowserSessionLeaseId,
    BrowserTabLease, BrowserTabLeaseId, BrowserTabTotalLimit, BrowserTabsPerSessionLimit,
    MAX_BROWSER_PROFILE_FORK_CHILDREN, MAX_BROWSER_PROFILE_POOL_SNAPSHOT_ENTRIES,
    MAX_PROFILE_WARM_NAVIGATION_MILLISECONDS, MAX_PROFILE_WARM_OVERALL_MILLISECONDS,
    MAX_PROFILE_WARM_TARGETS, NewProfileSpec, ProfileLifecycleStore, ProfileLifecycleStoreError,
    ProfileWarmBounds, ProfileWarmPlan, ProfileWarmPlanError, ProfileWarmPlanId,
    ProfileWarmProcessCleanup, ProfileWarmProfileDisposition, ProfileWarmReceiptError,
    ProfileWarmStep, ProfileWarmStepId, ProfileWarmStepNumber, ProfileWarmStepOutcome,
    ProfileWarmStepReceipt, ProfileWarmTerminalReason, ProfileWarmTerminalReceipt,
    ResolvedBrowserProfileForkLimits, classify_abandoned_on_startup,
    reduce_browser_profile_lifecycle,
};
pub use browser_finalization::{
    BrowserFinalizationError, BrowserFinalizationInput, finalize_browser_capture,
};
#[cfg(feature = "browser")]
pub use browser_runtime::capture as browser_capture;
#[cfg(feature = "browser")]
pub use browser_runtime::{
    BrowserExecutionManager, BrowserExecutionManagerConfig, BrowserExecutionManagerError,
    BrowserExecutionManagerSnapshot, BrowserNavigationCommand, BrowserNavigationHandle,
    BrowserNavigationScheduler, BrowserNavigationSchedulerError,
    BrowserNavigationSchedulerSnapshot, BrowserProfileChildLeaseContract,
    BrowserProfileForkServiceError, BrowserTabInstrumentationState, ManagedProfileForkOutcome,
    ManagedProfileForkService, ManagedProfileForkSourceLease, ManagedProfileWarmService,
    ProfileWarmServiceError, RuntimeBrowserLease, RuntimeBrowserTabLease, VoidCrawlAdapterError,
    VoidCrawlAdapterErrorCategory, VoidCrawlAdapterProducerError, capture_attempt,
    capture_attempt_managed, void_crawl_adapter_producer,
};
mod browser_spec;
mod bundle;
mod capture;
mod environment;
mod error;
mod lifecycle_events;
mod observation;
mod source;
mod source_input;
mod target;
mod wire;

pub use acquisition::{
    BrowserContextRef, ContextBoundHttpAcquisition, CookieSync, DirectHttpAcquisition,
    DirectHttpTransportProfile, DocumentNavigationAcquisition, FetchCredentials, FetchMode,
    HttpBrowserImpersonationProfile, HttpBrowserImpersonationProfileError, HttpSessionUse,
    NavigationContext, PageContextFetchAcquisition, PageContextRef, WebAcquisitionStrategy,
    WebCaptureRequest,
};
pub use acquisition_finalization::{
    AcquisitionActivityResult, AcquisitionFinalizationError, AcquisitionFinalizationPlan,
    ArtifactTimestampOrder, finalize_acquisition,
};
pub use aggregate::{CaptureCompleteness, WebCapture, WebCaptureError};
pub use artifact::{
    AccessibilityTreeArtifact, AccessibilityTreeArtifactRef, AcquisitionCapabilityProfile,
    ArtifactByteExtent, ArtifactByteExtentError, ArtifactCapability, ArtifactCollection,
    ArtifactCollectionError, ArtifactFamilyResult, ArtifactMultiplicity, ArtifactRequest,
    ArtifactSensitivity, BrowserNavigationCapabilityProfile, CookieArtifact, CookieArtifactRef,
    DECODED_SOURCE_POLICY_VERSION, DecodedExtent, DecodedSourceArtifact,
    DecodedSourceArtifactError, DecodedSourceArtifactRef, DecodedSourceInterpretation,
    LayoutArtifact, LayoutArtifactRef, MediaType, MediaTypeError, NetworkArtifact,
    NetworkArtifactRef, RenderedDomArtifact, RenderedDomArtifactRef, RuntimeDiagnosticsArtifact,
    RuntimeDiagnosticsArtifactRef, SourceArtifact, SourceArtifactRef, SourceRepresentationArtifact,
    SourceRepresentationArtifactError, SourceRepresentationArtifactRef, StorageArtifact,
    StorageArtifactRef, TruncatedArtifactExtent, VisualArtifact, VisualArtifactRef, WebArtifact,
    WebArtifactCapabilitySet, WebArtifactFamily, WebArtifactManifest, WebArtifactManifestError,
    WebArtifactMetadata, WebArtifactMetadataError, WebArtifactRef, WebArtifactRelationship,
    WebArtifactRequestSet, WebArtifactResults, WebProviderCapabilityProfile,
    WebProviderCapabilityProfileError,
};
pub use attempt_boundary::{AttemptBoundary, AttemptBoundaryError};
pub use bounded_acquisition::{
    AcquisitionObservationError, BoundedAcquisitionError, BoundedAcquisitionLifecycle,
    RetentionCheckpoint,
};
pub use browser_adapter::{
    ArtifactStagingOutcome, BrowserAdapterFacts, BrowserAdapterFactsParts,
    BrowserAdapterOutputError, BrowserAdapterResult, BrowserAdapterResultState,
    BrowserAdapterTerminal, BrowserArtifactMapping, BrowserArtifactStaging, BrowserByteLayer,
    BrowserDiscardedArtifactDescriptor, BrowserMappingError, BrowserProviderStop,
    BrowserSnapshotObservation, BrowserStagingAccounting, BrowserStagingFamily,
    BrowserStagingParts, BrowserStagingSlot, BrowserTerminalCandidate, BrowserTerminalKind,
    BrowserTerminalSignal, CleanupState, LossExtent, StagingOutcomeError, StagingSlotError,
    StagingState, resolve_browser_terminal,
};
pub use browser_spec::{
    BrowserAttemptEnvironment, BrowserBoundsError, BrowserBudgetScope, BrowserByteBound,
    BrowserByteDomain, BrowserCapabilityStatus, BrowserCaptureSpecError, BrowserCertificationError,
    BrowserEnvironmentOverrides, BrowserEvidenceAdmissionPolicy, BrowserFamilyCapabilities,
    BrowserHeaderAdmission, BrowserInstrumentationMode, BrowserLimitEnforcement,
    BrowserMainBodyAdmission, BrowserNavigationPolicy, BrowserOutputSchemas, BrowserProviderBounds,
    BrowserUrlAdmission, CertifiedBrowserCapabilities, FreshBrowserIsolation,
    NavigationCompletionPolicy, ResolvedBrowserCaptureSpec, byte_domain_for,
};
pub use bundle::{CaptureBundle, CaptureBundleBuilder, CaptureBundleError};
pub use capture::{
    CaptureResolution, CaptureResolutionError, HttpRedirectStatus, HttpRedirectStatusError,
    Observation, RedirectCause, RedirectHop, WebAcquisitionRecord, WebAcquisitionRecordError,
};
pub use environment::{
    BrowserCaptureEnvironment, BrowserEnvironmentFingerprintInputs, BrowserMode,
    BrowserRenderingContext, CaptureEnvironment, ColorScheme, DeviceScaleFactor,
    DeviceScaleFactorError, EnvironmentFingerprintInputs, EnvironmentValue, HttpCaptureEnvironment,
    HttpEnvironmentFingerprintInputs, Locale, LocaleError, PreferredLanguages,
    PreferredLanguagesError, ReducedMotion, TimeZone, TimeZoneError, UserAgent, UserAgentError,
    Viewport,
};
pub use error::{
    ContextualWebCaptureError, StructuredWebCaptureError, WebCaptureErrorCategory,
    WebCaptureErrorCode, WebCaptureErrorContext, WebCaptureErrorSummary,
};
pub use lifecycle_events::{
    AdmittedEvent, EventAdmission, LifecycleEvent, LifecycleEventError, LifecycleFinalizationInput,
    LifecycleStop, StagedPayloadError, StagedPayloads,
};
pub use observation::{
    ActivityCount, ByteAccounting, ByteAccountingError, ByteCount, ByteLimit, ByteLimitError,
    CaptureDeadline, CaptureDeadlineError, CaptureDuration, CaptureObservation,
    CaptureObservationError, CaptureOffset, CaptureTermination, ControllerStopReason,
    EventAccounting, EventAccountingError, EventCount, EventLimit, EventLimitError,
    InFlightActivity, InFlightActivityError, InterruptionEvidence, InterruptionInitiator,
    MeasuredCount, ObservationLimits, ObservationPolicy, ObservationWindow, ObservationWindowError,
    QuietPeriod, QuietPeriodError, QuietPeriodPolicy, SettlementEvidence, SettlementEvidenceError,
    SettlementPolicy, SettlementPolicyId, SettlementPolicyIdError, TerminalObservationState,
};
pub use source::{
    CharacterDecodingOutcome, CharsetDeclaration, CharsetIssue, ClassificationBasis,
    ClassificationExtent, ClassifiedSource, DECODED_SOURCE_UTF8_MEDIA_TYPE,
    DeclarationDisagreement, DecodedOutputIdentity, DecodedOutputIdentityError, DecodedSourceView,
    DecodingBasis, DecodingConflict, DecodingErrorCode, DurableCharacterDecoding,
    DurableDecodedView, MediaDeclaration, MediaDeclarationIssue,
    SOURCE_REPRESENTATION_EVIDENCE_MEDIA_TYPE, SOURCE_REPRESENTATION_EVIDENCE_VERSION,
    SelectedEncoding, SourceBindingError, SourceClassificationOutcome, SourceDecoderProducerError,
    SourceFormat, SourceRepresentationEvidence, SourceRepresentationEvidenceError,
    SourceRepresentationFacts, UnknownReason, ValidatedSourceBinding, XmlProfile,
    classify_and_decode, parse_media_declaration, source_decoder_producer,
};
pub use source_input::{
    AcquiredPayloadAccounting, AcquiredPayloadError, AcquiredPayloadOutcome, AcquiredPayloadState,
    BoundedSourceMediaType, MAX_SOURCE_MEDIA_TYPE_BYTES, RetainedSource, RetainedSourceExtent,
    RetainedSourceReplayError, SourceMediaType, SourceMediaTypeTooLong,
};
pub use target::{
    ObservedWebOrigin, OpaqueOriginId, RequestedWebTarget, ResolvedWebUrl, TupleWebOrigin,
    TupleWebOriginParseError, WebUrlParseError,
};
pub use wire::{WEB_CAPTURE_SCHEMA_VERSION, WebCaptureWire, WebCaptureWireError};

#[cfg(test)]
mod integration_tests;
