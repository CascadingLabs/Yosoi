//! Concrete VoidCrawl browser runtime integration for Yosoi.

mod browser_execution;
mod capture;
mod config;
mod conversions;
mod error;
mod identity;
mod overrides;
mod profile_fork;
mod profile_warm;

pub use browser_execution::{
    BrowserExecutionManager, BrowserExecutionManagerConfig, BrowserExecutionManagerError,
    BrowserExecutionManagerSnapshot, BrowserNavigationCommand, BrowserNavigationHandle,
    BrowserNavigationScheduler, BrowserNavigationSchedulerError,
    BrowserNavigationSchedulerSnapshot, BrowserTabInstrumentationState, RuntimeBrowserLease,
    RuntimeBrowserTabLease,
};
pub use capture::{capture, capture_attempt, capture_attempt_managed};
pub use error::{VoidCrawlAdapterError, VoidCrawlAdapterErrorCategory};
pub use identity::{VoidCrawlAdapterProducerError, void_crawl_adapter_producer};
pub use profile_fork::{
    BrowserProfileChildLeaseContract, BrowserProfileForkServiceError, ManagedProfileForkOutcome,
    ManagedProfileForkService, ManagedProfileForkSourceLease,
};
pub use profile_warm::{ManagedProfileWarmService, ProfileWarmServiceError};

#[cfg(test)]
mod tests;
