use crate::internal::web_capture as yosoi_web_capture;

use std::{
    error::Error,
    fs, io,
    num::{NonZeroU32, NonZeroU64},
    slice,
    sync::Arc,
    time::{Duration, SystemTime},
};

use crate::internal::browser::ProfileRegistry;
use crate::internal::types::ActivityId;
use chrono::{DateTime, Duration as ChronoDuration, Utc};
use tempfile::TempDir;

use crate::internal::web_capture::{
    BrowserCleanupDeadline, BrowserContextTotalLimit, BrowserContextsPerProcessLimit,
    BrowserExecutionManager, BrowserExecutionManagerConfig, BrowserExecutionManagerError,
    BrowserProcessLimit, BrowserProfileCheckpointId, BrowserProfileCheckpointIdentity,
    BrowserProfileChildId, BrowserProfileChildIdentity, BrowserProfileForkFailureReason,
    BrowserProfileForkRequest, BrowserProfileId, BrowserProfileLeaseGenerationRegistry,
    BrowserProfileLifecycleEvent, BrowserProfileLifecycleState, BrowserProfileLineageId,
    BrowserProfileLineageIdentity, BrowserQueueDepthLimit, BrowserQueueWaitLimit,
    BrowserRecycleThreshold, BrowserTabTotalLimit, BrowserTabsPerSessionLimit,
    ProfileLifecycleStore, ResolvedBrowserProfileForkLimits,
};

use super::{
    BrowserProfileChildContractState, BrowserProfileChildContractStore,
    BrowserProfileChildLeaseContract, BrowserProfileForkServiceError, ManagedProfileForkOutcome,
    ManagedProfileForkService, child_contracts_for_request,
};

fn request_for_source(
    source: &super::ManagedProfileForkSourceLease,
    limits: ResolvedBrowserProfileForkLimits,
    expiry_seconds: i64,
) -> Result<BrowserProfileForkRequest, Box<dyn Error>> {
    let checkpoint = BrowserProfileCheckpointIdentity::new(
        BrowserProfileCheckpointId::new(ActivityId::random()),
        source.receipt(),
    );
    let lineage = BrowserProfileLineageIdentity::new(
        BrowserProfileLineageId::new(ActivityId::random()),
        &checkpoint,
    );
    let child = BrowserProfileChildIdentity::new(
        BrowserProfileChildId::new(ActivityId::random()),
        BrowserProfileId::new("fork-child".to_owned())?,
        &lineage,
    );
    let requested_at = *source.receipt().acquired_at();
    let child_expires_at = requested_at
        .checked_add_signed(ChronoDuration::seconds(expiry_seconds))
        .ok_or("child expiry overflowed")?;
    Ok(BrowserProfileForkRequest::new(
        source.receipt().clone(),
        checkpoint,
        lineage,
        vec![child],
        limits,
        requested_at,
        child_expires_at,
    )?)
}

fn setup() -> Result<
    (
        TempDir,
        ProfileRegistry,
        ProfileLifecycleStore,
        ManagedProfileForkService,
    ),
    Box<dyn Error>,
> {
    let temp = tempfile::tempdir()?;
    let registry = ProfileRegistry::new(temp.path());
    registry.create_profile("fork-source", None, vec![])?;
    let lifecycle = ProfileLifecycleStore::new(temp.path().join("lifecycle"))?;
    let source_id = BrowserProfileId::new("fork-source".to_owned())?;
    lifecycle.stage_profile(&source_id, SystemTime::now().into())?;
    lifecycle.transition(
        &source_id,
        SystemTime::now().into(),
        BrowserProfileLifecycleEvent::ProvisionSucceeded,
    )?;
    let generations = Arc::new(BrowserProfileLeaseGenerationRegistry::default());
    let service = ManagedProfileForkService::new(
        registry.clone(),
        lifecycle.clone(),
        generations,
        Duration::from_secs(60),
    )?;
    Ok((temp, registry, lifecycle, service))
}

fn seed_available_lifecycle(
    lifecycle: &ProfileLifecycleStore,
    profile_id: &BrowserProfileId,
) -> Result<(), Box<dyn Error>> {
    if lifecycle.record(profile_id)?.is_none() {
        lifecycle.stage_profile(profile_id, SystemTime::now().into())?;
        lifecycle.transition(
            profile_id,
            SystemTime::now().into(),
            BrowserProfileLifecycleEvent::ProvisionSucceeded,
        )?;
    }
    Ok(())
}

fn manager_limits() -> Result<yosoi_web_capture::BrowserExecutionLimits, Box<dyn Error>> {
    Ok(yosoi_web_capture::BrowserExecutionLimits::new(
        BrowserProcessLimit::new(NonZeroU32::new(1).ok_or("nonzero process limit")?),
        BrowserContextTotalLimit::new(NonZeroU32::new(1).ok_or("nonzero context limit")?),
        BrowserContextsPerProcessLimit::new(
            NonZeroU32::new(1).ok_or("nonzero process context limit")?,
        ),
        BrowserTabTotalLimit::new(NonZeroU32::new(1).ok_or("nonzero tab limit")?),
        BrowserTabsPerSessionLimit::new(NonZeroU32::new(1).ok_or("nonzero session tab limit")?),
        BrowserQueueDepthLimit::new(NonZeroU32::new(1).ok_or("nonzero queue limit")?),
        BrowserQueueWaitLimit::new(NonZeroU64::new(10).ok_or("nonzero queue wait")?),
        BrowserCleanupDeadline::new(NonZeroU64::new(10).ok_or("nonzero cleanup deadline")?),
        BrowserRecycleThreshold::new(NonZeroU32::new(2).ok_or("nonzero recycle threshold")?),
    )?)
}

#[test]
fn fork_uses_quiescent_fenced_source_and_registers_child_contract() -> Result<(), Box<dyn Error>> {
    let (_temp, registry, lifecycle, service) = setup()?;
    let source_path = registry.describe_profile("fork-source")?.profile.path;
    fs::write(source_path.join("Default").join("Cookies"), "cookie")?;
    let source_id = BrowserProfileId::new("fork-source".to_owned())?;
    let source = service.acquire_source(&source_id)?;
    let request = request_for_source(
        &source,
        ResolvedBrowserProfileForkLimits::new(1, 100)?,
        3_600,
    )?;

    let outcome = service.fork(&source, &request)?;
    let ManagedProfileForkOutcome::Completed(receipt) = outcome else {
        return Err(io::Error::other("expected successful profile fork").into());
    };
    assert_eq!(receipt.children().len(), 1);
    assert_eq!(receipt.copied_bytes(), 8);
    let first_child = receipt.children().first().ok_or("fork had no children")?;
    let contract = service.child_contract(first_child.profile_id())?;
    assert!(contract.lease_authorized());
    assert_eq!(contract.identity(), first_child);
    assert_eq!(request.checkpoint().source_generation().get(), 1);
    assert!(registry.acquire_profile("fork-source").is_err());
    assert_eq!(
        lifecycle
            .record(first_child.profile_id())?
            .map(|record| record.next()),
        Some(BrowserProfileLifecycleState::Available)
    );
    drop(source);
    let restarted = ManagedProfileForkService::new(
        registry,
        lifecycle,
        service.generation_registry(),
        Duration::from_secs(60),
    )?;
    assert_eq!(
        restarted.child_contract(first_child.profile_id())?,
        contract
    );
    Ok(())
}

#[test]
fn active_provider_lease_proves_profile_is_not_quiescent() -> Result<(), Box<dyn Error>> {
    let (_temp, registry, _lifecycle, service) = setup()?;
    let active_browser_lease = registry.acquire_profile("fork-source")?;
    let source_id = BrowserProfileId::new("fork-source".to_owned())?;
    assert_eq!(
        service.acquire_source(&source_id).err(),
        Some(BrowserProfileForkServiceError::SourceUnavailable)
    );
    drop(active_browser_lease);
    assert_eq!(
        service
            .generation_registry()
            .next_generation(&source_id)?
            .get(),
        2
    );
    Ok(())
}

#[test]
fn provider_quota_error_maps_to_secret_safe_failure_receipt() -> Result<(), Box<dyn Error>> {
    let (_temp, registry, lifecycle, service) = setup()?;
    let source_path = registry.describe_profile("fork-source")?.profile.path;
    fs::write(source_path.join("Default").join("Cookies"), "12345678")?;
    let source_id = BrowserProfileId::new("fork-source".to_owned())?;
    let source = service.acquire_source(&source_id)?;
    let request = request_for_source(&source, ResolvedBrowserProfileForkLimits::new(1, 9)?, 3_600)?;

    let outcome = service.fork(&source, &request)?;
    let ManagedProfileForkOutcome::Failed(receipt) = outcome else {
        return Err(io::Error::other("expected quota failure").into());
    };
    assert_eq!(
        receipt.facts().reason(),
        BrowserProfileForkFailureReason::AggregateByteQuotaExceeded
    );
    assert!(
        receipt
            .facts()
            .attempted_bytes()
            .is_some_and(|bytes| bytes > 9)
    );
    assert!(receipt.facts().copied_bytes() <= 9);
    assert!(receipt.facts().cleanup_succeeded());
    let encoded = serde_json::to_string(&receipt)?;
    assert!(!encoded.contains("Cookies"));
    assert!(!encoded.contains("cookie"));
    assert!(!encoded.contains("path"));
    assert_eq!(registry.list_profiles()?.len(), 1);
    let child_id = BrowserProfileId::new("fork-child".to_owned())?;
    assert!(matches!(
        lifecycle.record(&child_id)?.map(|record| record.next()),
        Some(BrowserProfileLifecycleState::Quarantined { .. })
    ));
    Ok(())
}

#[test]
fn direct_managed_manager_rejects_persisted_expired_and_quarantined_children()
-> Result<(), Box<dyn Error>> {
    let (_temp, registry, lifecycle, service) = setup()?;
    registry.create_profile("fork-child", None, vec![])?;
    registry.create_profile("fork-quarantined", None, vec![])?;
    let expired_profile_id = BrowserProfileId::new("fork-child".to_owned())?;
    let quarantined_profile_id = BrowserProfileId::new("fork-quarantined".to_owned())?;
    seed_available_lifecycle(&lifecycle, &expired_profile_id)?;
    lifecycle.stage_profile(&quarantined_profile_id, SystemTime::now().into())?;
    lifecycle.transition(
        &quarantined_profile_id,
        SystemTime::now().into(),
        BrowserProfileLifecycleEvent::ProvisionOwnershipUncertain,
    )?;
    let source_id = BrowserProfileId::new("fork-source".to_owned())?;
    let source = service.acquire_source(&source_id)?;
    let request = request_for_source(
        &source,
        ResolvedBrowserProfileForkLimits::new(2, 100)?,
        3_600,
    )?;

    let store = BrowserProfileChildContractStore::for_registry_root(registry.root());
    let mut expired_contracts =
        child_contracts_for_request(&request, BrowserProfileChildContractState::Reserved);
    let mut expired_contract = expired_contracts.pop().ok_or("missing reserved child")?;
    expired_contract.expires_at =
        DateTime::<Utc>::from_timestamp(1, 0).ok_or("invalid expired timestamp")?;
    let expired_identity = expired_contract.identity.clone();
    store.reserve(&[expired_contract])?;
    store.commit(slice::from_ref(&expired_identity))?;

    let quarantined_identity = BrowserProfileChildIdentity::new(
        BrowserProfileChildId::new(ActivityId::random()),
        BrowserProfileId::new("fork-quarantined".to_owned())?,
        request.lineage(),
    );
    let quarantined_contract = BrowserProfileChildLeaseContract {
        identity: quarantined_identity.clone(),
        lineage: request.lineage().clone(),
        expires_at: *request.child_expires_at(),
        state: BrowserProfileChildContractState::Reserved,
    };
    store.reserve(&[quarantined_contract])?;
    drop(source);

    let expired_manager = BrowserExecutionManager::new_managed_profile(
        manager_limits()?,
        BrowserExecutionManagerConfig::default(),
        registry.clone(),
        expired_identity.profile_id().clone(),
        lifecycle.clone(),
        service.generation_registry(),
        Duration::from_secs(30),
    );
    assert!(matches!(
        expired_manager,
        Err(BrowserExecutionManagerError::ManagedProfileChildExpired)
    ));
    assert!(
        registry
            .acquire_profile(expired_identity.profile_id().as_str())
            .is_ok()
    );

    let quarantined_manager = BrowserExecutionManager::new_managed_profile(
        manager_limits()?,
        BrowserExecutionManagerConfig::default(),
        registry.clone(),
        quarantined_identity.profile_id().clone(),
        lifecycle,
        service.generation_registry(),
        Duration::from_secs(30),
    );
    assert!(matches!(
        quarantined_manager,
        Err(BrowserExecutionManagerError::ManagedProfileUnavailable)
    ));
    assert!(
        registry
            .acquire_profile(quarantined_identity.profile_id().as_str())
            .is_ok()
    );
    Ok(())
}
