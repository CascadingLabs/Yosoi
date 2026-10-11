//! Synchronous, quiescent managed-profile fork service.
//!
//! Acquiring VoidCrawl's profile lease is the quiescence check: CAS-354 holds
//! that same lock from before Chromium launch until confirmed process close.
//! A running managed browser therefore makes `acquire_source` fail busy. The
//! source lock and Yosoi fence stay held through the complete provider copy.

use std::{
    collections::{HashMap, HashSet},
    fmt,
    fs::{self, File, OpenOptions},
    io::{self, Write},
    path::{Path, PathBuf},
    sync::Arc,
    time::{Duration, Instant, SystemTime},
};

use crate::internal::browser as provider;
use chrono::{DateTime, Utc};
use provider::managed_profile::ManagedProfileForkError;
use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use tempfile::NamedTempFile;
use thiserror::Error;

use crate::internal::web_capture::{
    BrowserProfileChildIdentity, BrowserProfileForkError, BrowserProfileForkFailureFacts,
    BrowserProfileForkFailureReason, BrowserProfileForkFailureReceipt, BrowserProfileForkReceipt,
    BrowserProfileForkRequest, BrowserProfileForkSuccessFacts, BrowserProfileId,
    BrowserProfileLeaseError, BrowserProfileLeaseGenerationRegistry, BrowserProfileLeaseId,
    BrowserProfileLineageIdentity, BrowserProfileOwnerId,
};

use crate::internal::web_capture::browser_execution::{
    BrowserProfileLeaseFence, BrowserProfileLifecycleEvent, BrowserProfileLifecycleState,
    ProfileLifecycleStore,
};

mod contract_store;
mod facts;
mod outcome;
mod service;
mod source_lease;

pub use contract_store::{
    BrowserProfileChildContractState, BrowserProfileChildContractStore,
    BrowserProfileChildContractStoreError, BrowserProfileChildLeaseContract,
};
pub use outcome::{BrowserProfileForkServiceError, ManagedProfileForkOutcome};
pub use service::ManagedProfileForkService;
pub use source_lease::ManagedProfileForkSourceLease;

#[cfg(test)]
use facts::child_contracts_for_request;

#[cfg(test)]
#[allow(
    clippy::panic_in_result_fn,
    reason = "test assertions provide clearer fork transaction diagnostics"
)]
#[path = "profile_fork_tests.rs"]
mod tests;

#[cfg(test)]
use crate::internal::web_capture::BrowserProfileLeaseReceipt;
