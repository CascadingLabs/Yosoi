use super::*;

/// CAS-354-style short source tenancy that keeps the VoidCrawl file lock held.
/// Constructed only by [`ManagedProfileForkService::acquire_source`].
pub struct ManagedProfileForkSourceLease {
    pub(super) provider_lease: provider::ManagedProfileLease,
    pub(super) fence: BrowserProfileLeaseFence,
    pub(super) lifecycle: ProfileLifecycleStore,
}

impl fmt::Debug for ManagedProfileForkSourceLease {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ManagedProfileForkSourceLease")
            .field("profile_id", self.fence.receipt().profile_id())
            .field("generation", &self.fence.generation())
            .finish_non_exhaustive()
    }
}

impl ManagedProfileForkSourceLease {
    pub const fn receipt(&self) -> &BrowserProfileLeaseReceipt {
        self.fence.receipt()
    }
}

impl Drop for ManagedProfileForkSourceLease {
    fn drop(&mut self) {
        let generation = self.fence.generation();
        let event = if self.fence.expired_at(Instant::now()) {
            BrowserProfileLifecycleEvent::LeaseExpired { generation }
        } else {
            BrowserProfileLifecycleEvent::LeaseReleased { generation }
        };
        let _transition_result = self.lifecycle.transition(
            self.fence.receipt().profile_id(),
            SystemTime::now().into(),
            event,
        );
    }
}
