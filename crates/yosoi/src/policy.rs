//! Configure the limits and acquisition choices used by SDK operations.

pub use crate::internal::engine::{Policy, PolicyError, PolicySnapshot};
pub use crate::internal::policy::EffectivePolicyIdentity;
pub use crate::internal::policy::policy::{
    AccessibilityNodeLimit, Acquisition, AcquisitionKind, AddressableByteLimit, BrowserLimits,
    BrowserMode, Budget, Continuation, CountLimit, DirectHttpRedirectTargets, DirectHttpRedirects,
    DiscoveryDocuments, DocumentRequest, DocumentSelectionKind, Documents, EventLimit, Filters,
    FlowPolicy, HostScope, IpFamily, Limits, Locators, Map, MaximumElapsed, Network, Page,
    PageDiscovery, PathScope, RedirectHopLimit, Request, ResourceLimit, Robots, Scope,
    SourceLimits, StepLimit, StopScope, Subdomains, Tuning, TuningMode,
};
pub use search::{
    ProfileSelection, ProviderDefaultsStatus, ProviderDefaultsVersion, ProviderRequestProfile,
    ProviderSelection,
};

/// Regex-group traffic constraints backed by a runtime-bound Registry.
pub mod respectfulness {
    pub use crate::internal::policy::policy::respectfulness::{
        Cooldown, Group, RateBudget, Respectfulness, Retry, Unmatched,
    };
    pub use crate::internal::respectfulness::{Event, EventKind, LimitReason, RespectfulnessError};
}

/// Provider selection and bounded Search configuration.
pub mod search {
    pub use crate::internal::policy::policy::search::{
        EffectiveProviderRoute, EffectiveSearch, ProfileSelection, ProfileSelectionKind, Provider,
        ProviderDefaultsStatus, ProviderDefaultsVersion, ProviderRequestProfile, ProviderSelection,
        Search,
    };
}
