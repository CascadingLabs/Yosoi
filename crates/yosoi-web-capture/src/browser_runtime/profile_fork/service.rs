#[allow(
    clippy::wildcard_imports,
    reason = "private split module shares its facade's implementation context"
)]
use super::*;

mod fork;

/// Provider-backed fork service. It does not launch Chromium, manage browser
/// pools, or issue child leases.
///
/// Child contracts are stored under the provider registry root and are consumed
/// by the existing CAS-354 leasing path.
#[derive(Clone)]
pub struct ManagedProfileForkService {
    registry: provider::ProfileRegistry,
    lifecycle: ProfileLifecycleStore,
    generations: Arc<BrowserProfileLeaseGenerationRegistry>,
    source_lease_duration: Duration,
    child_contract_store: BrowserProfileChildContractStore,
}

impl fmt::Debug for ManagedProfileForkService {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ManagedProfileForkService")
            .finish_non_exhaustive()
    }
}

impl ManagedProfileForkService {
    pub fn new(
        registry: provider::ProfileRegistry,
        lifecycle: ProfileLifecycleStore,
        generations: Arc<BrowserProfileLeaseGenerationRegistry>,
        source_lease_duration: Duration,
    ) -> Result<Self, BrowserProfileForkServiceError> {
        if source_lease_duration.is_zero() {
            return Err(BrowserProfileForkServiceError::InvalidSourceLeaseDuration);
        }
        let child_contract_store =
            BrowserProfileChildContractStore::for_registry_root(registry.root());
        child_contract_store
            .validate_on_open()
            .map_err(super::facts::map_contract_store_error)?;
        Ok(Self {
            registry,
            lifecycle,
            generations,
            source_lease_duration,
            child_contract_store,
        })
    }

    /// Takes a CAS-354 generation/fence and VoidCrawl profile lock without
    /// starting a browser. A busy result means another managed browser still
    /// owns the profile, so its live data is never copied.
    pub fn acquire_source(
        &self,
        profile_id: &BrowserProfileId,
    ) -> Result<ManagedProfileForkSourceLease, BrowserProfileForkServiceError> {
        let lifecycle_record = self
            .lifecycle
            .record(profile_id)
            .map_err(|_| BrowserProfileForkServiceError::LifecycleStoreUnavailable)?
            .ok_or(BrowserProfileForkServiceError::SourceUnavailable)?;
        if let BrowserProfileLifecycleState::Leased { .. } = lifecycle_record.next() {
            let live_lease_probe = self
                .registry
                .acquire_profile(profile_id.as_str())
                .map_err(|_| BrowserProfileForkServiceError::SourceUnavailable)?;
            drop(live_lease_probe);
            self.lifecycle
                .classify_profile_abandoned_on_startup(profile_id, SystemTime::now().into())
                .map_err(|_| BrowserProfileForkServiceError::LifecycleStoreUnavailable)?;
            return Err(BrowserProfileForkServiceError::SourceUnavailable);
        }
        if lifecycle_record.next() != BrowserProfileLifecycleState::Available {
            return Err(BrowserProfileForkServiceError::SourceUnavailable);
        }

        let generation = self
            .generations
            .next_generation_after(profile_id, lifecycle_record.latest_generation())
            .map_err(|_| BrowserProfileForkServiceError::GenerationUnavailable)?;
        self.lifecycle
            .transition(
                profile_id,
                SystemTime::now().into(),
                BrowserProfileLifecycleEvent::LeaseAcquired { generation },
            )
            .map_err(|_| BrowserProfileForkServiceError::LifecycleStoreUnavailable)?;
        let provider_lease = match self.registry.acquire_profile(profile_id.as_str()) {
            Ok(lease) if lease.id() == profile_id.as_str() => lease,
            Ok(_) | Err(_) => {
                self.release_unlaunched_source(generation, profile_id)?;
                return Err(BrowserProfileForkServiceError::SourceUnavailable);
            }
        };
        let monotonic_now = Instant::now();
        let wall_now: DateTime<Utc> = SystemTime::now().into();
        let fence = match BrowserProfileLeaseFence::start(
            profile_id.clone(),
            BrowserProfileLeaseId::random(),
            BrowserProfileOwnerId::random(),
            generation,
            Arc::clone(&self.generations),
            self.source_lease_duration,
            monotonic_now,
            wall_now,
        ) {
            Ok(fence) => fence,
            Err(error) => {
                drop(provider_lease);
                self.release_unlaunched_source(generation, profile_id)?;
                return Err(super::facts::map_lease_error(error));
            }
        };

        Ok(ManagedProfileForkSourceLease {
            provider_lease,
            fence,
            lifecycle: self.lifecycle.clone(),
        })
    }

    /// Loads and authorizes a persisted child contract using the current wall
    /// clock. This remains valid after service reconstruction or process restart.
    pub fn child_contract(
        &self,
        profile_id: &BrowserProfileId,
    ) -> Result<BrowserProfileChildLeaseContract, BrowserProfileForkServiceError> {
        let now: DateTime<Utc> = SystemTime::now().into();
        self.child_contract_store
            .committed_contract(profile_id, &now)
            .map_err(super::facts::map_contract_store_error)
    }

    /// Shares the CAS-354 generation authority with managers created for
    /// registered child contracts.
    pub fn generation_registry(&self) -> Arc<BrowserProfileLeaseGenerationRegistry> {
        Arc::clone(&self.generations)
    }

    fn release_unlaunched_source(
        &self,
        generation: crate::BrowserProfileLeaseGeneration,
        profile_id: &BrowserProfileId,
    ) -> Result<(), BrowserProfileForkServiceError> {
        self.lifecycle
            .transition(
                profile_id,
                SystemTime::now().into(),
                BrowserProfileLifecycleEvent::LeaseReleased { generation },
            )
            .map(|_| ())
            .map_err(|_| BrowserProfileForkServiceError::LifecycleStoreUnavailable)
    }
}
