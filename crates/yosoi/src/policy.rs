//! Configure the limits and acquisition choices used by SDK operations.

pub use crate::internal::engine::{Policy, PolicyError, PolicySnapshot};
pub use crate::internal::policy::EffectivePolicyIdentity;
pub use crate::internal::policy::policy::{
    AccessibilityNodeLimit, Acquisition, AcquisitionKind, AddressableByteLimit, BrowserLimits,
    BrowserMode, Budget, Continuation, CountLimit, DirectHttpRedirectTargets, DirectHttpRedirects,
    DiscoveryDocuments, DocumentRequest, DocumentSelectionKind, Documents, EventLimit,
    EvidenceFailurePolicy, Filters, FlowPolicy, HostScope, IpFamily, Limits, Locators, Map,
    MaximumElapsed, Network, ObserveLimits, ObservePolicy, Page, PageDiscovery, PathScope,
    RecordingMode, RecordingRule, RedirectHopLimit, Request, ResourceLimit, Robots, Scope,
    ScreenshotPolicy, ScreenshotScope, SourceLimits, StepLimit, StopScope, Subdomains, Tuning,
    TuningMode,
};
pub use search::{
    ProfileSelection, ProviderDefaultsStatus, ProviderDefaultsVersion, ProviderRequestProfile,
    ProviderSelection,
};

/// Automatic observation, screenshot, and recording policy vocabulary.
pub mod observe {
    pub use crate::internal::policy::policy::MAX_RECORDING_DURATION_MS;
    pub use crate::internal::policy::policy::{
        EvidenceFailurePolicy, ObserveLimits, ObservePolicy, RecordingMode, RecordingRule,
        ScreenshotPolicy, ScreenshotScope,
    };
}

/// Provider selection and bounded Search configuration.
pub mod search {
    pub use crate::internal::policy::policy::search::{
        EffectiveProviderRoute, EffectiveSearch, ProfileSelection, ProfileSelectionKind, Provider,
        ProviderDefaultsStatus, ProviderDefaultsVersion, ProviderRequestProfile, ProviderSelection,
        Search,
    };
}
