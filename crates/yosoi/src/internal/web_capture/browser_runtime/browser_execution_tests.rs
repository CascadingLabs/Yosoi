#![allow(
    clippy::panic_in_result_fn,
    reason = "test assertions provide clearer manager lifecycle diagnostics"
)]

use crate::internal::types as yosoi_types;

use std::{
    error::Error,
    io,
    num::{NonZeroU32, NonZeroU64},
    sync::Arc,
    time::{Duration, Instant, SystemTime},
};

use tokio::{
    io::AsyncWriteExt,
    net::TcpListener,
    runtime::Builder,
    sync::Notify,
    task::{JoinHandle, spawn_blocking},
    time::timeout,
};

use super::*;

fn nonzero_u32(value: u32) -> Result<NonZeroU32, io::Error> {
    NonZeroU32::new(value).ok_or_else(|| io::Error::other("test limit must be nonzero"))
}

fn nonzero_u64(value: u64) -> Result<NonZeroU64, io::Error> {
    NonZeroU64::new(value).ok_or_else(|| io::Error::other("test limit must be nonzero"))
}

fn seed_available_lifecycle(
    registry: &provider::ProfileRegistry,
    profile_id: &yosoi::BrowserProfileId,
) -> Result<yosoi::ProfileLifecycleStore, Box<dyn Error>> {
    let lifecycle =
        yosoi::ProfileLifecycleStore::new(registry.root().join(".yosoi/profile-lifecycle"))?;
    if lifecycle.record(profile_id)?.is_none() {
        lifecycle.stage_profile(profile_id, SystemTime::now().into())?;
        lifecycle.transition(
            profile_id,
            SystemTime::now().into(),
            yosoi::BrowserProfileLifecycleEvent::ProvisionSucceeded,
        )?;
    }
    Ok(lifecycle)
}

fn limits(
    contexts: u32,
    tabs: u32,
    tabs_per_session: u32,
    queue_depth: u32,
    queue_wait_ms: u64,
    recycle: u32,
) -> Result<yosoi::BrowserExecutionLimits, Box<dyn Error>> {
    limits_with_cleanup(
        contexts,
        tabs,
        tabs_per_session,
        queue_depth,
        queue_wait_ms,
        recycle,
        10_000,
    )
}

#[allow(clippy::too_many_arguments)]
fn limits_with_cleanup(
    contexts: u32,
    tabs: u32,
    tabs_per_session: u32,
    queue_depth: u32,
    queue_wait_ms: u64,
    recycle: u32,
    cleanup_ms: u64,
) -> Result<yosoi::BrowserExecutionLimits, Box<dyn Error>> {
    Ok(yosoi::BrowserExecutionLimits::new(
        yosoi::BrowserProcessLimit::new(NonZeroU32::MIN),
        yosoi::BrowserContextTotalLimit::new(nonzero_u32(contexts)?),
        yosoi::BrowserContextsPerProcessLimit::new(nonzero_u32(contexts)?),
        yosoi::BrowserTabTotalLimit::new(nonzero_u32(tabs)?),
        yosoi::BrowserTabsPerSessionLimit::new(nonzero_u32(tabs_per_session)?),
        yosoi::BrowserQueueDepthLimit::new(nonzero_u32(queue_depth)?),
        yosoi::BrowserQueueWaitLimit::new(nonzero_u64(queue_wait_ms)?),
        yosoi::BrowserCleanupDeadline::new(nonzero_u64(cleanup_ms)?),
        yosoi::BrowserRecycleThreshold::new(nonzero_u32(recycle)?),
    )?)
}

struct Fixture {
    url: String,
    cancellation: CancellationToken,
    task: JoinHandle<Result<(), io::Error>>,
}

impl Fixture {
    async fn start() -> Result<Self, Box<dyn Error>> {
        let listener = TcpListener::bind("127.0.0.1:0").await?;
        let address = listener.local_addr()?;
        let cancellation = CancellationToken::new();
        let server_cancellation = cancellation.clone();
        let task = tokio::spawn(async move {
            loop {
                let accepted = tokio::select! {
                    () = server_cancellation.cancelled() => return Ok(()),
                    result = listener.accept() => result,
                }?;
                let (mut stream, _) = accepted;
                tokio::spawn(async move {
                    let body = b"<!doctype html><title>lease fixture</title>";
                    let response = format!(
                        "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                        body.len()
                    );
                    let _ = stream.write_all(response.as_bytes()).await;
                    let _ = stream.write_all(body).await;
                    let _ = stream.shutdown().await;
                });
            }
        });
        Ok(Self {
            url: format!("http://{address}/"),
            cancellation,
            task,
        })
    }

    async fn close(self) -> Result<(), Box<dyn Error>> {
        self.cancellation.cancel();
        self.task.await??;
        Ok(())
    }
}

async fn wait_for_queue_depth(
    manager: &BrowserExecutionManager,
    expected: u32,
) -> Result<(), BrowserExecutionManagerError> {
    loop {
        let notified = manager.inner.changed.notified();
        tokio::pin!(notified);
        notified.as_mut().enable();
        if manager.snapshot().await?.queued_requests == expected {
            return Ok(());
        }
        notified.await;
    }
}

async fn joined_lease(
    task: JoinHandle<Result<RuntimeBrowserLease, BrowserExecutionManagerError>>,
) -> Result<RuntimeBrowserLease, Box<dyn Error>> {
    Ok(timeout(Duration::from_secs(5), task).await???)
}

async fn wait_for_creation_cleanup(
    manager: &BrowserExecutionManager,
) -> Result<(), BrowserExecutionManagerError> {
    loop {
        let notified = manager.inner.changed.notified();
        tokio::pin!(notified);
        notified.as_mut().enable();
        let state = manager.inner.state.lock().await;
        let cleaned = state.in_flight_creations == 0
            && state.creations.is_empty()
            && state.active_contexts == 0
            && state.active_tabs == 0;
        drop(state);
        if cleaned {
            return Ok(());
        }
        notified.await;
    }
}

async fn wait_for_tab_accounting(
    manager: &BrowserExecutionManager,
    resource: &Arc<LeaseResource>,
    global_tabs: u32,
    session_tabs: u32,
    pending_tabs: usize,
) -> Result<(), BrowserExecutionManagerError> {
    loop {
        let notified = manager.inner.changed.notified();
        tokio::pin!(notified);
        notified.as_mut().enable();
        let lease_state = resource.state.lock().await;
        let session_matches = lease_state.active_tabs == session_tabs
            && lease_state.tab_creations.len() == pending_tabs;
        drop(lease_state);
        if session_matches && manager.snapshot().await?.active_tabs == global_tabs {
            return Ok(());
        }
        notified.await;
    }
}

#[test]
fn process_maintenance_terminals_have_closed_pre_admission_outcomes() {
    assert_eq!(
        BrowserExecutionManagerError::ProcessCloseDeadline.pre_admission_outcome(),
        Some(yosoi::BrowserExecutionPreAdmissionOutcome::ProviderCleanupDeadlineExceeded)
    );
    assert_eq!(
        BrowserExecutionManagerError::ProcessCloseFailed.pre_admission_outcome(),
        Some(yosoi::BrowserExecutionPreAdmissionOutcome::ProviderCleanupFailed)
    );
}

#[tokio::test]
async fn managed_profile_admission_cleanup_and_final_release_are_fenced()
-> Result<(), Box<dyn Error>> {
    let directory = tempfile::tempdir()?;
    let registry = provider::ProfileRegistry::new(directory.path());
    registry.create_profile("runtime-fence", None, Vec::new())?;
    let profile_id = yosoi::BrowserProfileId::new("runtime-fence")?;
    let lifecycle = seed_available_lifecycle(&registry, &profile_id)?;
    let generations = Arc::new(yosoi::BrowserProfileLeaseGenerationRegistry::default());
    let multi_process_limits = yosoi::BrowserExecutionLimits::new(
        yosoi::BrowserProcessLimit::new(nonzero_u32(2)?),
        yosoi::BrowserContextTotalLimit::new(nonzero_u32(1)?),
        yosoi::BrowserContextsPerProcessLimit::new(nonzero_u32(1)?),
        yosoi::BrowserTabTotalLimit::new(nonzero_u32(1)?),
        yosoi::BrowserTabsPerSessionLimit::new(nonzero_u32(1)?),
        yosoi::BrowserQueueDepthLimit::new(nonzero_u32(1)?),
        yosoi::BrowserQueueWaitLimit::new(nonzero_u64(1)?),
        yosoi::BrowserCleanupDeadline::new(nonzero_u64(1)?),
        yosoi::BrowserRecycleThreshold::new(nonzero_u32(1)?),
    )?;
    if !matches!(
        BrowserExecutionManager::new_managed_profile(
            multi_process_limits,
            BrowserExecutionManagerConfig::default(),
            registry.clone(),
            profile_id.clone(),
            lifecycle.clone(),
            Arc::clone(&generations),
            Duration::from_secs(60),
        ),
        Err(BrowserExecutionManagerError::InvalidManagedProfileLimits)
    ) {
        return Err(io::Error::other("managed profile accepted multiple process slots").into());
    }
    let manager = BrowserExecutionManager::new_managed_profile(
        limits(1, 1, 1, 1, 1_000, 10)?,
        BrowserExecutionManagerConfig::default(),
        registry.clone(),
        profile_id.clone(),
        lifecycle.clone(),
        Arc::clone(&generations),
        Duration::from_secs(60),
    )?;
    if !matches!(
        manager.acquire_independent(&CancellationToken::new()).await,
        Err(BrowserExecutionManagerError::ManagedProfileRequiresSessionScope)
    ) {
        return Err(io::Error::other(
            "managed profile accepted an independent disposable-context lease",
        )
        .into());
    }
    let profile = manager
        .inner
        .managed_profile
        .as_ref()
        .ok_or_else(|| io::Error::other("managed profile tenancy was not installed"))?;
    let launch = profile.acquire_before_launch(&manager.inner)?;
    let receipt = manager
        .managed_profile_lease_receipt()
        .ok_or_else(|| io::Error::other("profile receipt was not created"))?;
    if receipt.profile_id().as_str() != "runtime-fence" {
        return Err(io::Error::other("profile receipt has the wrong identity").into());
    }
    if registry.acquire_profile("runtime-fence").is_ok() {
        return Err(io::Error::other("managed profile file lock was not retained").into());
    }
    if profile
        .authorize_admission_at(launch.generation, Instant::now())
        .is_err()
    {
        return Err(io::Error::other("current profile generation was not admitted").into());
    }
    if profile.authorize_admission_at(launch.generation, launch.deadline)
        != Err(BrowserExecutionManagerError::ManagedProfileExpired)
    {
        return Err(io::Error::other("expired profile generation remained admissible").into());
    }
    profile
        .authorize_cleanup(launch.generation)
        .map_err(|error| io::Error::other(format!("authorize cleanup: {error}")))?;

    let stale = generations.next_generation(&profile_id)?;
    if profile
        .authorize_admission_at(stale, Instant::now())
        .is_ok()
        || profile.authorize_cleanup(stale).is_ok()
    {
        return Err(io::Error::other("stale profile generation retained authority").into());
    }
    if profile.close_confirmed(stale).is_ok() {
        return Err(io::Error::other("stale generation released the profile lock").into());
    }
    profile
        .bind_process_generation(launch.generation, 42)
        .map_err(|error| io::Error::other(format!("bind process generation: {error}")))?;
    profile
        .confirm_process_closed(42)
        .map_err(|error| io::Error::other(format!("confirm process close: {error}")))?;
    profile
        .close_confirmed(launch.generation)
        .map_err(|error| io::Error::other(format!("finalize profile close: {error}")))?;
    let terminal = manager
        .managed_profile_terminal_receipt()
        .ok_or_else(|| io::Error::other("confirmed close did not produce a terminal receipt"))?;
    if terminal.outcome() != yosoi::BrowserProfileLeaseTerminalOutcome::Released {
        return Err(io::Error::other("profile terminal receipt was not released").into());
    }
    if lifecycle
        .record(&profile_id)?
        .is_none_or(|record| record.next() != yosoi::BrowserProfileLifecycleState::Available)
    {
        return Err(io::Error::other("confirmed close did not persist Available").into());
    }
    if registry.acquire_profile("runtime-fence").is_err() {
        return Err(io::Error::other("confirmed process close retained the profile lock").into());
    }
    Ok(())
}

#[test]
fn manager_restart_quarantines_an_abandoned_lease_and_rejects_it() -> Result<(), Box<dyn Error>> {
    let directory = tempfile::tempdir()?;
    let registry = provider::ProfileRegistry::new(directory.path());
    registry.create_profile("abandoned-lease", None, Vec::new())?;
    let profile_id = yosoi::BrowserProfileId::new("abandoned-lease")?;
    let lifecycle = seed_available_lifecycle(&registry, &profile_id)?;
    let generation = yosoi::BrowserProfileLeaseGeneration::new(nonzero_u64(1)?);
    lifecycle.transition(
        &profile_id,
        SystemTime::now().into(),
        yosoi::BrowserProfileLifecycleEvent::LeaseAcquired { generation },
    )?;

    let result = BrowserExecutionManager::new_managed_profile(
        limits(1, 1, 1, 1, 1_000, 10)?,
        BrowserExecutionManagerConfig::default(),
        registry,
        profile_id.clone(),
        lifecycle.clone(),
        Arc::new(yosoi::BrowserProfileLeaseGenerationRegistry::default()),
        Duration::from_secs(60),
    );

    assert!(matches!(
        result,
        Err(BrowserExecutionManagerError::ManagedProfileUnavailable)
    ));
    assert_eq!(
        lifecycle.record(&profile_id)?.map(|record| record.next()),
        Some(yosoi::BrowserProfileLifecycleState::Quarantined {
            reason: yosoi::BrowserProfileQuarantineReason::StartupLeaseInterrupted,
        })
    );
    Ok(())
}

#[tokio::test]
async fn second_manager_does_not_quarantine_a_live_provider_lease() -> Result<(), Box<dyn Error>> {
    let directory = tempfile::tempdir()?;
    let registry = provider::ProfileRegistry::new(directory.path());
    registry.create_profile("live-lease", None, Vec::new())?;
    let profile_id = yosoi::BrowserProfileId::new("live-lease")?;
    let lifecycle = seed_available_lifecycle(&registry, &profile_id)?;
    let generations = Arc::new(yosoi::BrowserProfileLeaseGenerationRegistry::default());
    let manager = BrowserExecutionManager::new_managed_profile(
        limits(1, 1, 1, 1, 1_000, 10)?,
        BrowserExecutionManagerConfig::default(),
        registry.clone(),
        profile_id.clone(),
        lifecycle.clone(),
        Arc::clone(&generations),
        Duration::from_secs(60),
    )?;
    let profile = manager
        .inner
        .managed_profile
        .as_ref()
        .ok_or_else(|| io::Error::other("managed profile tenancy missing"))?;
    let launch = profile.acquire_before_launch(&manager.inner)?;

    let competing_manager = BrowserExecutionManager::new_managed_profile(
        limits(1, 1, 1, 1, 1_000, 10)?,
        BrowserExecutionManagerConfig::default(),
        registry.clone(),
        profile_id.clone(),
        lifecycle.clone(),
        generations,
        Duration::from_secs(60),
    );
    assert!(matches!(
        competing_manager,
        Err(BrowserExecutionManagerError::ManagedProfileUnavailable)
    ));
    assert!(matches!(
        lifecycle.record(&profile_id)?.map(|record| record.next()),
        Some(yosoi::BrowserProfileLifecycleState::Leased { generation })
            if generation == launch.generation
    ));

    profile.close_confirmed(launch.generation)?;
    assert_eq!(
        lifecycle.record(&profile_id)?.map(|record| record.next()),
        Some(yosoi::BrowserProfileLifecycleState::Available)
    );
    assert!(registry.acquire_profile("live-lease").is_ok());
    Ok(())
}

#[tokio::test]
async fn expired_close_quarantines_and_releases_only_after_persisting() -> Result<(), Box<dyn Error>>
{
    let directory = tempfile::tempdir()?;
    let registry = provider::ProfileRegistry::new(directory.path());
    registry.create_profile("expired-lease", None, Vec::new())?;
    let profile_id = yosoi::BrowserProfileId::new("expired-lease")?;
    let lifecycle = seed_available_lifecycle(&registry, &profile_id)?;
    let manager = BrowserExecutionManager::new_managed_profile(
        limits(1, 1, 1, 1, 1_000, 10)?,
        BrowserExecutionManagerConfig::default(),
        registry.clone(),
        profile_id.clone(),
        lifecycle.clone(),
        Arc::new(yosoi::BrowserProfileLeaseGenerationRegistry::default()),
        Duration::from_secs(60),
    )?;
    let profile = manager
        .inner
        .managed_profile
        .as_ref()
        .ok_or_else(|| io::Error::other("managed profile tenancy missing"))?;
    let launch = profile.acquire_before_launch(&manager.inner)?;

    profile.close_confirmed_at(launch.generation, launch.deadline)?;

    assert_eq!(
        lifecycle.record(&profile_id)?.map(|record| record.next()),
        Some(yosoi::BrowserProfileLifecycleState::Quarantined {
            reason: yosoi::BrowserProfileQuarantineReason::LeaseExpired,
        })
    );
    let terminal = manager
        .managed_profile_terminal_receipt()
        .ok_or_else(|| io::Error::other("expired close did not produce a terminal receipt"))?;
    assert_eq!(
        terminal.outcome(),
        yosoi::BrowserProfileLeaseTerminalOutcome::ExpiredAndReleased
    );
    assert!(terminal.outcome().quarantine_required());
    assert!(registry.acquire_profile("expired-lease").is_ok());
    Ok(())
}

#[tokio::test]
async fn uncertain_cleanup_persists_quarantine_and_blocks_release() -> Result<(), Box<dyn Error>> {
    let directory = tempfile::tempdir()?;
    let registry = provider::ProfileRegistry::new(directory.path());
    registry.create_profile("uncertain-lease", None, Vec::new())?;
    let profile_id = yosoi::BrowserProfileId::new("uncertain-lease")?;
    let lifecycle = seed_available_lifecycle(&registry, &profile_id)?;
    let manager = BrowserExecutionManager::new_managed_profile(
        limits(1, 1, 1, 1, 1_000, 10)?,
        BrowserExecutionManagerConfig::default(),
        registry.clone(),
        profile_id.clone(),
        lifecycle.clone(),
        Arc::new(yosoi::BrowserProfileLeaseGenerationRegistry::default()),
        Duration::from_secs(60),
    )?;
    let profile = manager
        .inner
        .managed_profile
        .as_ref()
        .ok_or_else(|| io::Error::other("managed profile tenancy missing"))?;
    let launch = profile.acquire_before_launch(&manager.inner)?;

    profile.mark_ownership_uncertain()?;

    assert_eq!(
        lifecycle.record(&profile_id)?.map(|record| record.next()),
        Some(yosoi::BrowserProfileLifecycleState::Quarantined {
            reason: yosoi::BrowserProfileQuarantineReason::LeaseOwnershipUncertain,
        })
    );
    assert!(registry.acquire_profile("uncertain-lease").is_err());
    assert!(profile.close_confirmed(launch.generation).is_err());
    assert!(
        profile
            .authorize_admission_at(launch.generation, Instant::now())
            .is_err()
    );
    Ok(())
}

#[tokio::test]
async fn real_tabs_share_only_session_context_and_cannot_escape_release()
-> Result<(), Box<dyn Error>> {
    let fixture = Fixture::start().await?;
    let manager = BrowserExecutionManager::new(
        limits(2, 3, 2, 2, 2_000, 100)?,
        BrowserExecutionManagerConfig::default(),
    );
    let cancellation = CancellationToken::new();
    let session = manager.acquire_session(&cancellation).await?;
    let initial = session.initial_tab().page().await?;
    if initial.evaluate_js("1 + 1").await? != serde_json::json!(2) {
        return Err(io::Error::other("initial tab is not a real page").into());
    }
    initial.navigate(&fixture.url).await?;
    initial
        .evaluate_js("localStorage.setItem('session_marker', 'shared')")
        .await?;

    let sibling_lease = session.new_tab(&cancellation).await?;
    let sibling = sibling_lease.page().await?;
    sibling.navigate(&fixture.url).await?;
    if sibling
        .evaluate_js("localStorage.getItem('session_marker')")
        .await?
        != serde_json::json!("shared")
    {
        return Err(io::Error::other("session tabs did not share their context").into());
    }
    if !matches!(
        session.new_tab(&cancellation).await,
        Err(BrowserExecutionManagerError::SessionTabCapacity)
    ) {
        return Err(io::Error::other("per-session tab cap was not enforced").into());
    }
    sibling_lease.close().await?;
    sibling_lease.close().await?;
    let replacement_lease = session.new_tab(&cancellation).await?;
    let replacement = replacement_lease.page().await?;
    replacement.navigate(&fixture.url).await?;
    if replacement
        .evaluate_js("localStorage.getItem('session_marker')")
        .await?
        != serde_json::json!("shared")
    {
        return Err(io::Error::other("replacement tab left its session context").into());
    }

    let independent = manager.acquire_independent(&cancellation).await?;
    let unrelated = independent.initial_tab().page().await?;
    unrelated.navigate(&fixture.url).await?;
    if !unrelated
        .evaluate_js("localStorage.getItem('session_marker')")
        .await?
        .is_null()
    {
        return Err(io::Error::other("unrelated contexts shared origin state").into());
    }
    let at_capacity = manager.snapshot().await?;
    if at_capacity.active_contexts != 2 || at_capacity.active_tabs != 3 {
        return Err(io::Error::other("active context/tab accounting was not exact").into());
    }

    independent.release().await?;
    session.release().await?;
    if replacement.evaluate_js("document.title").await.is_ok() {
        return Err(io::Error::other("provider page escaped context release").into());
    }
    if !matches!(
        replacement_lease.page().await,
        Err(BrowserExecutionManagerError::TabReleased)
    ) {
        return Err(io::Error::other("opaque tab stayed usable after release").into());
    }
    let released = manager.snapshot().await?;
    if released.active_contexts != 0 || released.active_tabs != 0 {
        return Err(io::Error::other("release did not return context/tab capacity").into());
    }
    manager.shutdown().await?;
    fixture.close().await?;
    Ok(())
}

#[tokio::test]
async fn aborted_new_tab_after_reservation_returns_exact_capacity() -> Result<(), Box<dyn Error>> {
    let manager = BrowserExecutionManager::new(
        limits(1, 2, 2, 1, 5_000, 100)?,
        BrowserExecutionManagerConfig::default(),
    );
    let session = Arc::new(manager.acquire_session(&CancellationToken::new()).await?);
    let started = Arc::new(Notify::new());
    let proceed = Arc::new(Notify::new());
    manager.inner.state.lock().await.tab_reservation_pause =
        Some((Arc::clone(&started), Arc::clone(&proceed)));

    let task_session = Arc::clone(&session);
    let new_tab =
        tokio::spawn(async move { task_session.new_tab(&CancellationToken::new()).await });
    timeout(Duration::from_secs(5), started.notified()).await?;
    wait_for_tab_accounting(&manager, &session.resource, 2, 2, 1).await?;
    new_tab.abort();
    if !new_tab.await.is_err_and(|error| error.is_cancelled()) {
        return Err(io::Error::other("new_tab caller was not aborted").into());
    }
    proceed.notify_one();
    timeout(
        Duration::from_secs(10),
        wait_for_tab_accounting(&manager, &session.resource, 1, 1, 0),
    )
    .await??;
    let created_page = manager
        .inner
        .state
        .lock()
        .await
        .last_created_tab
        .clone()
        .ok_or_else(|| io::Error::other("reserved provider page was not observed"))?;
    session.release().await?;
    manager.shutdown().await?;
    if created_page.evaluate_js("1").await.is_ok() {
        return Err(io::Error::other("aborted reserved tab escaped provider cleanup").into());
    }
    Ok(())
}

#[tokio::test]
async fn caller_runtime_teardown_after_provider_tab_creation_returns_exact_capacity()
-> Result<(), Box<dyn Error>> {
    let manager = BrowserExecutionManager::new(
        limits(1, 2, 2, 1, 5_000, 100)?,
        BrowserExecutionManagerConfig::default(),
    );
    let session = Arc::new(manager.acquire_session(&CancellationToken::new()).await?);
    let started = Arc::new(Notify::new());
    let proceed = Arc::new(Notify::new());
    manager.inner.state.lock().await.tab_creation_pause =
        Some((Arc::clone(&started), Arc::clone(&proceed)));

    let task_session = Arc::clone(&session);
    let runtime_started = Arc::clone(&started);
    spawn_blocking(move || -> Result<(), io::Error> {
        let runtime = Builder::new_current_thread()
            .enable_all()
            .build()
            .map_err(io::Error::other)?;
        runtime.block_on(async move {
            tokio::spawn(async move {
                let _ = task_session.new_tab(&CancellationToken::new()).await;
            });
            timeout(Duration::from_secs(10), runtime_started.notified())
                .await
                .map_err(io::Error::other)
        })?;
        drop(runtime);
        Ok(())
    })
    .await??;
    wait_for_tab_accounting(&manager, &session.resource, 2, 2, 1).await?;
    let created_page = manager
        .inner
        .state
        .lock()
        .await
        .last_created_tab
        .clone()
        .ok_or_else(|| io::Error::other("created provider page was not observed"))?;
    if created_page.evaluate_js("1").await? != serde_json::json!(1) {
        return Err(io::Error::other("provider creation barrier did not own a live page").into());
    }
    proceed.notify_one();
    timeout(
        Duration::from_secs(10),
        wait_for_tab_accounting(&manager, &session.resource, 1, 1, 0),
    )
    .await??;
    session.release().await?;
    manager.shutdown().await?;
    if created_page.evaluate_js("1").await.is_ok() {
        return Err(io::Error::other("created tab escaped after caller abort").into());
    }
    Ok(())
}

#[tokio::test]
async fn fifo_queue_overflow_cancellation_deadline_release_and_shutdown_are_bounded()
-> Result<(), Box<dyn Error>> {
    let manager = BrowserExecutionManager::new(
        limits(1, 1, 1, 2, 5_000, 100)?,
        BrowserExecutionManagerConfig::default(),
    );
    let cancellation = CancellationToken::new();
    let held = manager.acquire_independent(&cancellation).await?;

    let first_manager = manager.clone();
    let first = tokio::spawn(async move {
        first_manager
            .acquire_independent(&CancellationToken::new())
            .await
    });
    wait_for_queue_depth(&manager, 1).await?;

    let cancelled_token = CancellationToken::new();
    let task_token = cancelled_token.clone();
    let cancelled_manager = manager.clone();
    let cancelled =
        tokio::spawn(async move { cancelled_manager.acquire_independent(&task_token).await });
    wait_for_queue_depth(&manager, 2).await?;

    if !matches!(
        manager.acquire_independent(&CancellationToken::new()).await,
        Err(BrowserExecutionManagerError::QueueFull)
    ) {
        return Err(io::Error::other("queue overflow was not rejected").into());
    }
    cancelled_token.cancel();
    let cancelled_result = timeout(Duration::from_secs(2), cancelled).await??;
    if !matches!(
        cancelled_result,
        Err(BrowserExecutionManagerError::CallerCancelled)
    ) {
        return Err(io::Error::other("queued cancellation had the wrong outcome").into());
    }
    wait_for_queue_depth(&manager, 1).await?;

    let second_manager = manager.clone();
    let second = tokio::spawn(async move {
        second_manager
            .acquire_independent(&CancellationToken::new())
            .await
    });
    wait_for_queue_depth(&manager, 2).await?;

    held.release().await?;
    let first_lease = joined_lease(first).await?;
    let after_first = manager.snapshot().await?;
    if after_first.active_contexts != 1 || after_first.queued_requests != 1 {
        return Err(
            io::Error::other("FIFO admission did not leave the second request queued").into(),
        );
    }
    first_lease.release().await?;
    let second_lease = joined_lease(second).await?;
    second_lease.release().await?;

    let abort_holder = manager.acquire_independent(&cancellation).await?;
    let abandoned_manager = manager.clone();
    let abandoned = tokio::spawn(async move {
        abandoned_manager
            .acquire_independent(&CancellationToken::new())
            .await
    });
    wait_for_queue_depth(&manager, 1).await?;
    abandoned.abort();
    let abandonment = abandoned.await;
    if !abandonment.is_err_and(|error| error.is_cancelled()) {
        return Err(io::Error::other("aborted waiter task did not cancel").into());
    }
    wait_for_queue_depth(&manager, 0).await?;
    abort_holder.release().await?;

    let deadline_manager = BrowserExecutionManager::new(
        limits(1, 1, 1, 1, 50, 100)?,
        BrowserExecutionManagerConfig::default(),
    );
    let deadline_holder = deadline_manager.acquire_independent(&cancellation).await?;
    let deadline_result = timeout(
        Duration::from_secs(2),
        deadline_manager.acquire_independent(&CancellationToken::new()),
    )
    .await?;
    if !matches!(
        deadline_result,
        Err(BrowserExecutionManagerError::QueueWaitDeadline)
    ) {
        return Err(io::Error::other("queue wait did not use its absolute deadline").into());
    }
    deadline_holder.release().await?;
    deadline_manager.shutdown().await?;

    let shutdown_lease = manager.acquire_independent(&cancellation).await?;
    let retained_tab = shutdown_lease.initial_tab().page().await?;
    manager.shutdown().await?;
    manager.shutdown().await?;
    if retained_tab.evaluate_js("1").await.is_ok() {
        return Err(io::Error::other("shutdown left a tab usable").into());
    }
    shutdown_lease.release().await?;
    shutdown_lease.release().await?;
    let closed = manager.snapshot().await?;
    if !closed.closing
        || closed.active_processes != 0
        || closed.active_contexts != 0
        || closed.active_tabs != 0
    {
        return Err(io::Error::other("shutdown did not return all manager capacity").into());
    }
    Ok(())
}

#[tokio::test]
async fn aborted_acquire_after_launch_keeps_manager_ownership_through_cleanup()
-> Result<(), Box<dyn Error>> {
    let manager = BrowserExecutionManager::new(
        limits(1, 1, 1, 1, 5_000, 100)?,
        BrowserExecutionManagerConfig::default(),
    );
    let started = Arc::new(Notify::new());
    let proceed = Arc::new(Notify::new());
    manager.inner.state.lock().await.creation_pause =
        Some((Arc::clone(&started), Arc::clone(&proceed)));
    let acquire_manager = manager.clone();
    let acquire = tokio::spawn(async move {
        acquire_manager
            .acquire_independent(&CancellationToken::new())
            .await
    });
    timeout(Duration::from_secs(5), started.notified()).await?;
    acquire.abort();
    if !acquire.await.is_err_and(|error| error.is_cancelled()) {
        return Err(io::Error::other("acquire caller was not aborted").into());
    }
    proceed.notify_one();
    timeout(Duration::from_secs(10), wait_for_creation_cleanup(&manager)).await??;
    let snapshot = manager.snapshot().await?;
    if snapshot.active_processes != 1 || snapshot.active_contexts != 0 || snapshot.active_tabs != 0
    {
        return Err(io::Error::other("aborted acquire released ownership before cleanup").into());
    }
    manager.shutdown().await?;
    Ok(())
}

#[tokio::test]
async fn aborted_acquire_after_context_keeps_context_owned_through_cleanup()
-> Result<(), Box<dyn Error>> {
    let manager = BrowserExecutionManager::new(
        limits(1, 1, 1, 1, 5_000, 100)?,
        BrowserExecutionManagerConfig::default(),
    );
    let started = Arc::new(Notify::new());
    let proceed = Arc::new(Notify::new());
    manager.inner.state.lock().await.context_creation_pause =
        Some((Arc::clone(&started), Arc::clone(&proceed)));
    let acquire_manager = manager.clone();
    let acquire = tokio::spawn(async move {
        acquire_manager
            .acquire_independent(&CancellationToken::new())
            .await
    });
    timeout(Duration::from_secs(5), started.notified()).await?;
    acquire.abort();
    if !acquire.await.is_err_and(|error| error.is_cancelled()) {
        return Err(io::Error::other("acquire caller was not aborted").into());
    }
    proceed.notify_one();
    timeout(Duration::from_secs(10), wait_for_creation_cleanup(&manager)).await??;
    let snapshot = manager.snapshot().await?;
    if snapshot.active_contexts != 0 || snapshot.active_tabs != 0 {
        return Err(io::Error::other("aborted acquire leaked context capacity").into());
    }
    manager.shutdown().await?;
    Ok(())
}

#[tokio::test]
async fn runtime_shutdown_leaves_creation_owned_for_next_bounded_manager_cleanup()
-> Result<(), Box<dyn Error>> {
    let manager = BrowserExecutionManager::new(
        // Creation remains paused after runtime loss, so it reaches any bounded
        // deadline. Give real Chrome cleanup the normal budget on slower runners.
        limits_with_cleanup(1, 1, 1, 1, 5_000, 100, 10_000)?,
        BrowserExecutionManagerConfig::default(),
    );
    let started = Arc::new(Notify::new());
    let proceed = Arc::new(Notify::new());
    manager.inner.state.lock().await.context_creation_pause = Some((Arc::clone(&started), proceed));
    let runtime_manager = manager.clone();
    spawn_blocking(move || -> Result<(), io::Error> {
        let runtime = Builder::new_multi_thread()
            .enable_all()
            .build()
            .map_err(io::Error::other)?;
        runtime.block_on(async move {
            let acquire_manager = runtime_manager.clone();
            tokio::spawn(async move {
                let _ = acquire_manager
                    .acquire_independent(&CancellationToken::new())
                    .await;
            });
            timeout(Duration::from_secs(10), started.notified())
                .await
                .map_err(io::Error::other)
        })?;
        drop(runtime);
        Ok(())
    })
    .await??;

    let retained = manager.snapshot().await?;
    if retained.active_processes != 1 || retained.active_contexts != 1 || retained.active_tabs != 1
    {
        return Err(io::Error::other("runtime shutdown forgot pending provider ownership").into());
    }
    if !matches!(
        manager.shutdown().await,
        Err(BrowserExecutionManagerError::ContextCleanupDeadline)
    ) {
        return Err(io::Error::other("abandoned creation deadline was not reported").into());
    }
    let after_deadline = manager.snapshot().await?;
    if after_deadline.active_processes > 1
        || after_deadline.active_contexts != 0
        || after_deadline.active_tabs != 0
    {
        return Err(io::Error::other(format!(
            "deadline did not recover context and tab capacity exactly: {after_deadline:?}"
        ))
        .into());
    }
    manager.shutdown().await?;
    let cleaned = manager.snapshot().await?;
    if cleaned.active_processes != 0 || cleaned.active_contexts != 0 || cleaned.active_tabs != 0 {
        return Err(io::Error::other(format!(
            "bounded shutdown retry did not contain abandoned creation: {cleaned:?}"
        ))
        .into());
    }
    Ok(())
}

#[tokio::test]
async fn shutdown_resumes_release_after_executor_loss_and_retries_retained_process()
-> Result<(), Box<dyn Error>> {
    let started = Arc::new(Notify::new());
    let runtime_started = Arc::clone(&started);
    let (manager, lease, page, provider_session) =
        spawn_blocking(move || -> Result<_, io::Error> {
            let runtime = Builder::new_multi_thread()
                .enable_all()
                .build()
                .map_err(io::Error::other)?;
            let owned = runtime.block_on(async move {
                let limits = limits_with_cleanup(1, 1, 1, 1, 5_000, 100, 10_000)
                    .map_err(|error| io::Error::other(error.to_string()))?;
                let manager =
                    BrowserExecutionManager::new(limits, BrowserExecutionManagerConfig::default());
                let lease = Arc::new(
                    manager
                        .acquire_independent(&CancellationToken::new())
                        .await
                        .map_err(io::Error::other)?,
                );
                let page = lease.initial_tab().page().await.map_err(io::Error::other)?;
                let provider_session = manager
                    .inner
                    .state
                    .lock()
                    .await
                    .slots
                    .iter()
                    .find_map(|slot| slot.session.clone())
                    .ok_or_else(|| io::Error::other("provider session is missing"))?;
                let proceed = Arc::new(Notify::new());
                manager.inner.state.lock().await.release_pause =
                    Some((Arc::clone(&runtime_started), proceed));
                let release_lease = Arc::clone(&lease);
                tokio::spawn(async move {
                    let _ = release_lease.release().await;
                });
                timeout(Duration::from_secs(10), runtime_started.notified())
                    .await
                    .map_err(io::Error::other)?;
                Ok::<_, io::Error>((manager, lease, page, provider_session))
            })?;
            drop(runtime);
            Ok(owned)
        })
        .await??;

    let retained = manager.snapshot().await?;
    if retained.active_processes != 1 || retained.active_contexts != 1 || retained.active_tabs != 1
    {
        return Err(io::Error::other("lost release worker forgot manager ownership").into());
    }
    {
        let state = lease.resource.state.lock().await;
        if !state.releasing || state.release_result.is_some() || state.context.is_some() {
            return Err(io::Error::other("release loss was not left restartable").into());
        }
    }
    manager
        .inner
        .state
        .lock()
        .await
        .process_close_outcomes
        .extend([ProcessCloseOutcome::Failed, ProcessCloseOutcome::Failed]);

    let first_shutdown = manager.shutdown().await;
    if !matches!(
        first_shutdown,
        Err(BrowserExecutionManagerError::ProcessCloseFailed)
    ) {
        return Err(io::Error::other(format!(
            "first shutdown did not retain failed process close: {first_shutdown:?}"
        ))
        .into());
    }
    let after_first = manager.snapshot().await?;
    if after_first.active_processes != 1
        || after_first.active_contexts != 0
        || after_first.active_tabs != 0
    {
        return Err(io::Error::other("shutdown resume returned capacity inexactly").into());
    }

    manager.shutdown().await?;
    let closed = manager.snapshot().await?;
    if closed.active_processes != 0 || closed.active_contexts != 0 || closed.active_tabs != 0 {
        return Err(io::Error::other("shutdown retry retained manager capacity").into());
    }
    if provider_session.is_alive() || page.evaluate_js("1").await.is_ok() {
        return Err(
            io::Error::other("shutdown retry left an orphan process or escaped tab").into(),
        );
    }
    lease.release().await?;
    Ok(())
}

#[tokio::test]
async fn manager_maintenance_failure_is_fifo_and_consumed_exactly_once()
-> Result<(), Box<dyn Error>> {
    let manager = BrowserExecutionManager::new(
        limits(1, 1, 1, 2, 5_000, 100)?,
        BrowserExecutionManagerConfig::default(),
    );
    let held = manager
        .acquire_independent(&CancellationToken::new())
        .await?;
    let first_manager = manager.clone();
    let first = tokio::spawn(async move {
        first_manager
            .acquire_independent(&CancellationToken::new())
            .await
    });
    wait_for_queue_depth(&manager, 1).await?;
    let second_manager = manager.clone();
    let second = tokio::spawn(async move {
        second_manager
            .acquire_independent(&CancellationToken::new())
            .await
    });
    wait_for_queue_depth(&manager, 2).await?;
    manager
        .inner
        .state
        .lock()
        .await
        .maintenance_errors
        .push_back(BrowserExecutionManagerError::ProcessCloseFailed);
    held.release().await?;

    let first_result = timeout(Duration::from_secs(5), first).await??;
    if !matches!(
        first_result,
        Err(BrowserExecutionManagerError::ProcessCloseFailed)
    ) {
        return Err(io::Error::other("front ticket did not own maintenance failure").into());
    }
    let second_lease = joined_lease(second).await?;
    second_lease.release().await?;
    manager.shutdown().await?;
    Ok(())
}

#[tokio::test]
async fn terminal_accounting_preserves_concurrent_completions_past_recycle_threshold()
-> Result<(), Box<dyn Error>> {
    let manager = BrowserExecutionManager::new(
        limits(2, 2, 1, 1, 5_000, 1)?,
        BrowserExecutionManagerConfig::default(),
    );
    let first = manager
        .acquire_independent(&CancellationToken::new())
        .await?;
    let second = manager
        .acquire_independent(&CancellationToken::new())
        .await?;
    manager
        .inner
        .state
        .lock()
        .await
        .process_close_outcomes
        .push_back(ProcessCloseOutcome::Failed);
    first.release().await?;
    second.release().await?;

    let accounting = second.terminal_accounting_receipt().await?;
    if accounting.completed_executions_since_recycle() != 2 {
        return Err(io::Error::other("terminal accounting hid a concurrent completion").into());
    }
    manager.shutdown().await?;
    Ok(())
}

#[tokio::test]
async fn terminal_accounting_survives_immediate_process_generation_replacement()
-> Result<(), Box<dyn Error>> {
    let manager = BrowserExecutionManager::new(
        limits(1, 1, 1, 1, 5_000, 1)?,
        BrowserExecutionManagerConfig::default(),
    );
    let first = manager
        .acquire_independent(&CancellationToken::new())
        .await?;
    let next_manager = manager.clone();
    let next = tokio::spawn(async move {
        next_manager
            .acquire_independent(&CancellationToken::new())
            .await
    });
    wait_for_queue_depth(&manager, 1).await?;
    first.release().await?;
    let replacement = joined_lease(next).await?;

    let accounting = first.terminal_accounting_receipt().await?;
    if accounting.phase() != yosoi::BrowserExecutionAccountingPhase::Terminal
        || accounting.active_contexts_in_process() != 0
        || accounting.active_tabs_in_session() != 0
    {
        return Err(
            io::Error::other("terminal accounting rebound to replacement generation").into(),
        );
    }
    replacement.release().await?;
    manager.shutdown().await?;
    Ok(())
}

#[tokio::test]
async fn cleanup_facts_preserve_context_process_deadline_failure_and_round_trip()
-> Result<(), Box<dyn Error>> {
    let cases = [
        (
            yosoi::BrowserContextCleanupDisposition::DeadlineExceeded,
            ProcessCloseOutcome::Completed,
            yosoi::BrowserProcessCleanupDisposition::Completed,
        ),
        (
            yosoi::BrowserContextCleanupDisposition::Failed,
            ProcessCloseOutcome::Completed,
            yosoi::BrowserProcessCleanupDisposition::Completed,
        ),
        (
            yosoi::BrowserContextCleanupDisposition::Completed,
            ProcessCloseOutcome::DeadlineExceeded,
            yosoi::BrowserProcessCleanupDisposition::DeadlineExceeded,
        ),
        (
            yosoi::BrowserContextCleanupDisposition::Completed,
            ProcessCloseOutcome::Failed,
            yosoi::BrowserProcessCleanupDisposition::Failed,
        ),
        (
            yosoi::BrowserContextCleanupDisposition::Failed,
            ProcessCloseOutcome::Failed,
            yosoi::BrowserProcessCleanupDisposition::Failed,
        ),
    ];
    for (context_outcome, process_outcome, expected_process) in cases {
        let manager = BrowserExecutionManager::new(
            limits(1, 1, 1, 1, 5_000, 1)?,
            BrowserExecutionManagerConfig::default(),
        );
        let lease = manager
            .acquire_independent(&CancellationToken::new())
            .await?;
        {
            let mut state = manager.inner.state.lock().await;
            state
                .context_cleanup_dispositions
                .push_back(context_outcome);
            state.process_close_outcomes.push_back(process_outcome);
        }
        let cleanup = lease.release().await?;
        if cleanup.context() != context_outcome || cleanup.process() != expected_process {
            return Err(io::Error::other("cleanup facts collapsed independent outcomes").into());
        }
        let accounting = lease.terminal_accounting_receipt().await?;
        let terminal = yosoi::BrowserExecutionTerminalReceipt::new(
            lease.admission().clone(),
            cleanup,
            yosoi::BrowserExecutionTerminalReason::ProviderFailure,
        )?;
        let receipt = yosoi::BrowserExecutionReceipt::new(
            yosoi_types::CaptureId::random(),
            terminal,
            accounting,
        )?;
        let encoded = serde_json::to_vec(&receipt)?;
        let decoded: yosoi::BrowserExecutionReceipt = serde_json::from_slice(&encoded)?;
        if decoded != receipt {
            return Err(io::Error::other("execution receipt did not round trip").into());
        }
        manager.shutdown().await?;
    }
    Ok(())
}

#[tokio::test]
async fn failed_process_close_retains_ownership_and_retries_without_losing_capacity()
-> Result<(), Box<dyn Error>> {
    let manager = BrowserExecutionManager::new(
        limits(1, 1, 1, 1, 5_000, 1)?,
        BrowserExecutionManagerConfig::default(),
    );
    let lease = manager
        .acquire_independent(&CancellationToken::new())
        .await?;
    let generation = lease.process_generation();
    manager
        .inner
        .state
        .lock()
        .await
        .process_close_outcomes
        .push_back(ProcessCloseOutcome::Failed);

    let cleanup = lease.release().await?;
    if cleanup.context() != yosoi::BrowserContextCleanupDisposition::Completed
        || cleanup.process() != yosoi::BrowserProcessCleanupDisposition::Failed
    {
        return Err(io::Error::other("injected process close failure was not observed").into());
    }
    let retained = manager.snapshot().await?;
    if retained.active_processes != 1 || retained.active_contexts != 0 || retained.active_tabs != 0
    {
        return Err(
            io::Error::other("failed close forgot the retained process or capacity").into(),
        );
    }

    let replacement = manager
        .acquire_independent(&CancellationToken::new())
        .await?;
    if replacement.process_generation() <= generation {
        return Err(
            io::Error::other("retry did not close and replace the retained process").into(),
        );
    }
    replacement.release().await?;
    manager.shutdown().await?;
    Ok(())
}

#[tokio::test]
async fn in_flight_creation_timeout_still_tears_down_retained_process_before_retry()
-> Result<(), Box<dyn Error>> {
    let manager = BrowserExecutionManager::new(
        limits_with_cleanup(1, 1, 1, 1, 5_000, 100, 2_000)?,
        BrowserExecutionManagerConfig::default(),
    );
    let started = Arc::new(Notify::new());
    let proceed = Arc::new(Notify::new());
    manager.inner.state.lock().await.creation_pause =
        Some((Arc::clone(&started), Arc::clone(&proceed)));
    let acquire_manager = manager.clone();
    let acquire = tokio::spawn(async move {
        acquire_manager
            .acquire_independent(&CancellationToken::new())
            .await
    });
    timeout(Duration::from_secs(5), started.notified()).await?;

    if !matches!(
        manager.shutdown().await,
        Err(BrowserExecutionManagerError::ContextCleanupDeadline)
    ) {
        return Err(io::Error::other("in-flight creation timeout was not reported").into());
    }
    if manager.snapshot().await?.active_processes != 0 {
        return Err(
            io::Error::other("timeout returned before best-effort process teardown").into(),
        );
    }

    proceed.notify_one();
    let acquire_result = timeout(Duration::from_secs(5), acquire).await??;
    if !matches!(
        acquire_result,
        Err(BrowserExecutionManagerError::ManagerClosing)
    ) {
        return Err(io::Error::other("shutdown creation resolved with the wrong outcome").into());
    }
    manager.shutdown().await?;
    let closed = manager.snapshot().await?;
    if closed.active_processes != 0 || closed.active_contexts != 0 || closed.active_tabs != 0 {
        return Err(io::Error::other("shutdown retry did not recover exact capacity").into());
    }
    Ok(())
}

#[tokio::test]
async fn failed_shutdown_close_is_not_cached_and_last_owner_drop_contains_live_lease()
-> Result<(), Box<dyn Error>> {
    let manager = BrowserExecutionManager::new(
        limits(1, 1, 1, 1, 5_000, 100)?,
        BrowserExecutionManagerConfig::default(),
    );
    let lease = manager
        .acquire_independent(&CancellationToken::new())
        .await?;
    lease.release().await?;
    manager
        .inner
        .state
        .lock()
        .await
        .process_close_outcomes
        .push_back(ProcessCloseOutcome::Failed);
    if !matches!(
        manager.shutdown().await,
        Err(BrowserExecutionManagerError::ProcessCloseFailed)
    ) {
        return Err(io::Error::other("shutdown did not expose process close failure").into());
    }
    if manager.snapshot().await?.active_processes != 1 {
        return Err(io::Error::other("shutdown forgot a process whose close failed").into());
    }
    manager.shutdown().await?;
    if manager.snapshot().await?.active_processes != 0 {
        return Err(io::Error::other("shutdown retry did not recover process capacity").into());
    }

    let drop_manager = BrowserExecutionManager::new(
        limits(1, 1, 1, 1, 5_000, 100)?,
        BrowserExecutionManagerConfig::default(),
    );
    let dropped_lease = drop_manager
        .acquire_independent(&CancellationToken::new())
        .await?;
    let page = dropped_lease.initial_tab().page().await?;
    drop(drop_manager);
    timeout(
        Duration::from_secs(5),
        wait_for_release(&dropped_lease.resource),
    )
    .await??;
    if page.evaluate_js("1").await.is_ok() {
        return Err(io::Error::other("last manager owner drop left its live tab usable").into());
    }
    Ok(())
}

#[tokio::test]
async fn provider_disconnect_is_detected_drained_and_replaced_without_capacity_loss()
-> Result<(), Box<dyn Error>> {
    let manager = BrowserExecutionManager::new(
        limits(1, 1, 1, 1, 5_000, 100)?,
        BrowserExecutionManagerConfig::default(),
    );
    let lease = manager
        .acquire_independent(&CancellationToken::new())
        .await?;
    let generation = lease.process_generation();
    let page = lease.initial_tab().page().await?;
    let session = {
        let state = manager.inner.state.lock().await;
        state
            .slots
            .iter()
            .find_map(|slot| slot.session.clone())
            .ok_or_else(|| io::Error::other("live process session missing"))?
    };
    session
        .close_before(cleanup_deadline(manager.limits()))
        .await?;
    if page.evaluate_js("1").await.is_ok() {
        return Err(io::Error::other("closed provider session left page usable").into());
    }
    let _cleanup = lease.release().await?;
    let drained = manager.snapshot().await?;
    if drained.active_contexts != 0 || drained.active_tabs != 0 {
        return Err(io::Error::other("disconnect did not recover context and tab capacity").into());
    }
    let replacement = manager
        .acquire_independent(&CancellationToken::new())
        .await?;
    if replacement.process_generation() <= generation {
        return Err(io::Error::other("disconnected process generation was reused").into());
    }
    replacement.release().await?;
    manager.shutdown().await?;
    Ok(())
}

#[tokio::test]
async fn poisoned_and_recycled_process_slots_are_replaced_by_generation()
-> Result<(), Box<dyn Error>> {
    let manager = BrowserExecutionManager::new(
        limits(1, 1, 1, 1, 2_000, 1)?,
        BrowserExecutionManagerConfig::default(),
    );
    let cancellation = CancellationToken::new();
    let poisoned = manager.acquire_independent(&cancellation).await?;
    let poisoned_generation = poisoned.process_generation();
    poisoned.poison_process().await?;
    poisoned.release().await?;

    let replacement = manager.acquire_independent(&cancellation).await?;
    if replacement.process_generation() <= poisoned_generation {
        return Err(io::Error::other("poisoned process was not replaced").into());
    }
    let replacement_generation = replacement.process_generation();
    replacement.release().await?;

    let recycled = manager.acquire_independent(&cancellation).await?;
    if recycled.process_generation() <= replacement_generation {
        return Err(io::Error::other("recycle threshold did not replace the process").into());
    }
    let page = recycled.initial_tab().page().await?;
    if page.evaluate_js("6 * 7").await? != serde_json::json!(42) {
        return Err(io::Error::other("replacement process did not own a real tab").into());
    }
    recycled.release().await?;
    manager.shutdown().await?;
    Ok(())
}
