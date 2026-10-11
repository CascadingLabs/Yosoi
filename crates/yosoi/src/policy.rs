//! Configure the limits and acquisition choices used by SDK operations.

pub use crate::internal::engine::{Policy, PolicyError, PolicySnapshot};
pub use crate::internal::policy::EffectivePolicyIdentity;
pub use crate::internal::policy::policy::{
    AccessibilityNodeLimit, Acquisition, AcquisitionKind, AddressableByteLimit, BrowserLimits,
    BrowserMode, Budget, CountLimit, DirectHttpRedirectTargets, DirectHttpRedirects,
    DiscoveryDocuments, DocumentRequest, DocumentSelectionKind, Documents, EventLimit, Filters,
    HostScope, Limits, Locators, Map, MaximumElapsed, Page, PageDiscovery, PathScope,
    RedirectHopLimit, Request, ResourceLimit, Robots, Scope, SourceLimits, StepLimit, Subdomains,
    Tuning, TuningMode,
};
pub use search::{
    ProfileSelection, ProviderDefaultsStatus, ProviderDefaultsVersion, ProviderRequestProfile,
    ProviderSelection,
};

/// Provider selection and bounded Search configuration.
pub mod search {
    pub use crate::internal::policy::policy::search::{
        EffectiveProviderRoute, EffectiveSearch, ProfileSelection, ProfileSelectionKind, Provider,
        ProviderDefaultsStatus, ProviderDefaultsVersion, ProviderRequestProfile, ProviderSelection,
        Search,
    };
}
