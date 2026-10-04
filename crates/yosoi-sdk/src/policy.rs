//! Configure the limits and acquisition choices used by SDK operations.

pub use yosoi::{Policy, PolicyError, PolicySnapshot};
pub use yosoi_policy::policy::{
    AccessibilityNodeLimit, Acquisition, AcquisitionKind, AddressableByteLimit, BrowserLimits,
    BrowserMode, Budget, CountLimit, DirectHttpRedirectTargets, DirectHttpRedirects,
    DiscoveryDocuments, DocumentRequest, DocumentSelectionKind, Documents, EventLimit, Filters,
    HostScope, Limits, Locators, Map, MaximumElapsed, Page, PageDiscovery, PathScope,
    RedirectHopLimit, Request, Robots, Scope, SourceLimits, StepLimit, Subdomains, Tuning,
    TuningMode,
};
