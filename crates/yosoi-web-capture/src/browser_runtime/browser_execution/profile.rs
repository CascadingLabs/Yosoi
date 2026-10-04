use std::{
    mem,
    path::PathBuf,
    sync::{Arc, Mutex},
    time::{Duration, Instant, SystemTime},
};

use chrono::{DateTime, Utc};
use provider::managed_profile::ManagedProfileLeaseRelease;
use void_crawl_core as provider;

use crate as yosoi;
use crate::browser_execution::{
    BrowserProfileLeaseFence, BrowserProfileLifecycleEvent, BrowserProfileLifecycleState,
    ProfileLifecycleStore, ProfileLifecycleStoreError,
};
use crate::browser_runtime::profile_fork::{
    BrowserProfileChildContractStore, BrowserProfileChildContractStoreError,
};

use super::BrowserExecutionManagerError;

mod launch;
mod ownership;
mod release;

/// One Yosoi-owned fenced tenancy of one VoidCrawl managed profile.
/// Filesystem paths and registry lock handles stay private to this runtime.
pub struct ManagedProfileTenancy {
    registry: provider::ProfileRegistry,
    profile_id: yosoi::BrowserProfileId,
    owner_id: yosoi::BrowserProfileOwnerId,
    generations: Arc<yosoi::BrowserProfileLeaseGenerationRegistry>,
    lifecycle: ProfileLifecycleStore,
    lease_duration: Duration,
    child_contract_store: BrowserProfileChildContractStore,
    child_expires_at: Option<DateTime<Utc>>,
    state: Mutex<ManagedProfileState>,
}

enum ManagedProfileState {
    Unleased,
    Staged {
        registry_lease: Option<provider::ManagedProfileLease>,
    },
    Held {
        registry_lease: provider::ManagedProfileLease,
        fence: BrowserProfileLeaseFence,
        process_generation: Option<u64>,
        lifecycle_leased: bool,
        ownership_uncertain: bool,
    },
    Terminal {
        receipt: Option<yosoi::BrowserProfileLeaseTerminalReceipt>,
        staging_release: Option<ManagedProfileLeaseRelease>,
    },
}

pub(super) struct ManagedProfileLaunch {
    pub(super) user_data_dir: PathBuf,
    pub(super) generation: yosoi::BrowserProfileLeaseGeneration,
    pub(super) deadline: Instant,
}

impl ManagedProfileTenancy {
    pub(super) fn new(
        registry: provider::ProfileRegistry,
        profile_id: yosoi::BrowserProfileId,
        lifecycle: ProfileLifecycleStore,
        generations: Arc<yosoi::BrowserProfileLeaseGenerationRegistry>,
        lease_duration: Duration,
    ) -> Result<Self, BrowserExecutionManagerError> {
        if lease_duration.is_zero() {
            return Err(BrowserExecutionManagerError::InvalidManagedProfileLeaseDuration);
        }
        let mut record = lifecycle
            .record(&profile_id)
            .map_err(|_| BrowserExecutionManagerError::ManagedProfileUnavailable)?
            .ok_or(BrowserExecutionManagerError::ManagedProfileUnavailable)?;
        if matches!(record.next(), BrowserProfileLifecycleState::Leased { .. }) {
            let live_lease_probe = registry
                .acquire_profile(profile_id.as_str())
                .map_err(|_| BrowserExecutionManagerError::ManagedProfileUnavailable)?;
            drop(live_lease_probe);
            record = lifecycle
                .classify_profile_abandoned_on_startup(&profile_id, SystemTime::now().into())
                .map_err(|_| BrowserExecutionManagerError::ManagedProfileUnavailable)?
                .ok_or(BrowserExecutionManagerError::ManagedProfileUnavailable)?;
        }
        if record.next() != BrowserProfileLifecycleState::Available {
            return Err(BrowserExecutionManagerError::ManagedProfileUnavailable);
        }
        let child_contract_store =
            BrowserProfileChildContractStore::for_registry_root(registry.root());
        let now: DateTime<Utc> = SystemTime::now().into();
        let child_expires_at = child_contract_store
            .authorize_profile(&profile_id, &now)
            .map_err(map_child_contract_error)?;
        Ok(Self {
            registry,
            profile_id,
            owner_id: yosoi::BrowserProfileOwnerId::random(),
            generations,
            lifecycle,
            lease_duration,
            child_contract_store,
            child_expires_at,
            state: Mutex::new(ManagedProfileState::Unleased),
        })
    }

    pub(super) fn new_staged(
        registry: provider::ProfileRegistry,
        profile_id: yosoi::BrowserProfileId,
        owner_id: yosoi::BrowserProfileOwnerId,
        lifecycle: ProfileLifecycleStore,
        generations: Arc<yosoi::BrowserProfileLeaseGenerationRegistry>,
        lease_duration: Duration,
        registry_lease: provider::ManagedProfileLease,
    ) -> Result<Self, BrowserExecutionManagerError> {
        if lease_duration.is_zero() {
            return Err(BrowserExecutionManagerError::InvalidManagedProfileLeaseDuration);
        }
        if registry_lease.id() != profile_id.as_str() {
            return Err(BrowserExecutionManagerError::ManagedProfileUnavailable);
        }
        let record = lifecycle
            .record(&profile_id)
            .map_err(|_| BrowserExecutionManagerError::ManagedProfileUnavailable)?
            .ok_or(BrowserExecutionManagerError::ManagedProfileUnavailable)?;
        if record.next() != BrowserProfileLifecycleState::Staged {
            return Err(BrowserExecutionManagerError::ManagedProfileUnavailable);
        }
        let child_contract_store =
            BrowserProfileChildContractStore::for_registry_root(registry.root());
        let now: DateTime<Utc> = SystemTime::now().into();
        let child_expires_at = child_contract_store
            .authorize_profile(&profile_id, &now)
            .map_err(map_child_contract_error)?;
        Ok(Self {
            registry,
            profile_id,
            owner_id,
            generations,
            lifecycle,
            lease_duration,
            child_contract_store,
            child_expires_at,
            state: Mutex::new(ManagedProfileState::Staged {
                registry_lease: Some(registry_lease),
            }),
        })
    }

    pub(super) fn authorize_admission(
        &self,
        generation: yosoi::BrowserProfileLeaseGeneration,
    ) -> Result<(), BrowserExecutionManagerError> {
        self.authorize_admission_at(generation, Instant::now())
    }

    pub(super) fn authorize_admission_at(
        &self,
        generation: yosoi::BrowserProfileLeaseGeneration,
        now: Instant,
    ) -> Result<(), BrowserExecutionManagerError> {
        if self.child_expires_at.is_some_and(|expires_at| {
            let wall_now: DateTime<Utc> = SystemTime::now().into();
            wall_now >= expires_at
        }) {
            return Err(BrowserExecutionManagerError::ManagedProfileChildExpired);
        }
        let state = self
            .state
            .lock()
            .map_err(|_| BrowserExecutionManagerError::InternalInvariant)?;
        match &*state {
            ManagedProfileState::Held {
                fence,
                ownership_uncertain: false,
                ..
            } => fence
                .authorize(generation, now)
                .map_err(|error| match error {
                    yosoi::BrowserProfileLeaseError::Expired => {
                        BrowserExecutionManagerError::ManagedProfileExpired
                    }
                    _ => BrowserExecutionManagerError::ManagedProfileOwnershipUncertain,
                }),
            ManagedProfileState::Held { .. } => {
                Err(BrowserExecutionManagerError::ManagedProfileOwnershipUncertain)
            }
            ManagedProfileState::Unleased | ManagedProfileState::Staged { .. } => {
                Err(BrowserExecutionManagerError::ManagedProfileUnavailable)
            }
            ManagedProfileState::Terminal { .. } => {
                Err(BrowserExecutionManagerError::ManagerClosing)
            }
        }
    }

    /// Expiry permits cleanup only for the generation that acquired this lock.
    pub(super) fn authorize_cleanup(
        &self,
        generation: yosoi::BrowserProfileLeaseGeneration,
    ) -> Result<(), BrowserExecutionManagerError> {
        let state = self
            .state
            .lock()
            .map_err(|_| BrowserExecutionManagerError::InternalInvariant)?;
        match &*state {
            ManagedProfileState::Held { fence, .. } if fence.generation() == generation => Ok(()),
            ManagedProfileState::Terminal {
                receipt: Some(receipt),
                ..
            } if receipt.lease().generation() == generation => Ok(()),
            _ => Err(BrowserExecutionManagerError::ManagedProfileOwnershipUncertain),
        }
    }

    pub(super) fn is_expired_generation(
        &self,
        generation: yosoi::BrowserProfileLeaseGeneration,
        now: Instant,
    ) -> bool {
        let Ok(state) = self.state.lock() else {
            return true;
        };
        matches!(
            &*state,
            ManagedProfileState::Held { fence, .. }
                if fence.generation() == generation && fence.expired_at(now)
        )
    }

    fn release_unlaunched_lifecycle_lease(
        &self,
        generation: yosoi::BrowserProfileLeaseGeneration,
    ) -> Result<(), BrowserExecutionManagerError> {
        if self
            .commit_lifecycle_event(BrowserProfileLifecycleEvent::LeaseReleased { generation })
            .is_ok()
        {
            return Ok(());
        }
        self.commit_lifecycle_event(BrowserProfileLifecycleEvent::LeaseOwnershipUncertain {
            generation,
        })?;
        Err(BrowserExecutionManagerError::ManagedProfileOwnershipUncertain)
    }

    fn lease_duration_for_child(
        &self,
        now: &DateTime<Utc>,
        child_expiry: Option<&DateTime<Utc>>,
    ) -> Result<Duration, BrowserExecutionManagerError> {
        let Some(child_expiry) = child_expiry else {
            return Ok(self.lease_duration);
        };
        let remaining = child_expiry
            .signed_duration_since(*now)
            .to_std()
            .map_err(|_| BrowserExecutionManagerError::ManagedProfileChildExpired)?;
        if remaining.is_zero() {
            return Err(BrowserExecutionManagerError::ManagedProfileChildExpired);
        }
        Ok(self.lease_duration.min(remaining))
    }
}

const fn map_child_contract_error(
    error: BrowserProfileChildContractStoreError,
) -> BrowserExecutionManagerError {
    match error {
        BrowserProfileChildContractStoreError::Expired => {
            BrowserExecutionManagerError::ManagedProfileChildExpired
        }
        BrowserProfileChildContractStoreError::NotCommitted => {
            BrowserExecutionManagerError::ManagedProfileChildNotCommitted
        }
        BrowserProfileChildContractStoreError::Io
        | BrowserProfileChildContractStoreError::InvalidStore
        | BrowserProfileChildContractStoreError::Conflict
        | BrowserProfileChildContractStoreError::ReservationMismatch
        | BrowserProfileChildContractStoreError::NotFound => {
            BrowserExecutionManagerError::ManagedProfileChildContractUnavailable
        }
    }
}

impl Drop for ManagedProfileTenancy {
    fn drop(&mut self) {
        let Ok(state) = self.state.get_mut() else {
            return;
        };
        if let ManagedProfileState::Held {
            registry_lease,
            fence,
            lifecycle_leased,
            ownership_uncertain,
            ..
        } = mem::replace(state, ManagedProfileState::Unleased)
        {
            if !ownership_uncertain {
                let event = if lifecycle_leased {
                    BrowserProfileLifecycleEvent::LeaseOwnershipUncertain {
                        generation: fence.generation(),
                    }
                } else {
                    BrowserProfileLifecycleEvent::ProvisionOwnershipUncertain
                };
                let _transition_result =
                    self.lifecycle
                        .transition(&self.profile_id, SystemTime::now().into(), event);
            }
            // Keep VoidCrawl's advisory profile lock held for the lifetime of
            // this Yosoi process when Chrome close could not be confirmed.
            mem::forget(registry_lease);
        }
    }
}
