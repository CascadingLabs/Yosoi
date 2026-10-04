use serde::{Deserialize, Serialize};

use super::super::{BrowserNavigationRequestId, BrowserNavigationSchedulerId, BrowserTabLease};
use super::BrowserNavigationReadinessCheckpoint;

/// Provider-neutral scheduling request for a navigation already associated
/// with a Yosoi-owned tab lease.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserNavigationRequest {
    scheduler: BrowserNavigationSchedulerId,
    request: BrowserNavigationRequestId,
    tab: BrowserTabLease,
    readiness: BrowserNavigationReadinessCheckpoint,
}

impl BrowserNavigationRequest {
    pub const fn new(
        scheduler: BrowserNavigationSchedulerId,
        request: BrowserNavigationRequestId,
        tab: BrowserTabLease,
        readiness: BrowserNavigationReadinessCheckpoint,
    ) -> Self {
        Self {
            scheduler,
            request,
            tab,
            readiness,
        }
    }

    pub const fn scheduler(&self) -> BrowserNavigationSchedulerId {
        self.scheduler
    }

    pub const fn request(&self) -> BrowserNavigationRequestId {
        self.request
    }

    pub const fn tab(&self) -> &BrowserTabLease {
        &self.tab
    }

    pub const fn readiness(&self) -> BrowserNavigationReadinessCheckpoint {
        self.readiness
    }
}
