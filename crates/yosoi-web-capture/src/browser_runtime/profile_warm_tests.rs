use std::{
    error::Error,
    io,
    num::{NonZeroU32, NonZeroU64},
    path::Path,
    time::Duration,
};

use super::*;
use crate::{
    BrowserActiveNavigationLimit, BrowserCleanupDeadline, BrowserContextTotalLimit,
    BrowserContextsPerProcessLimit, BrowserEngineProgressCapacity, BrowserNavigationDeadline,
    BrowserNavigationProgressCapacity, BrowserProcessLimit, BrowserProfileLifecycleEvent,
    BrowserProfileLifecycleRecord, BrowserProfileLifecycleState, BrowserProfileOwnerId,
    BrowserProviderEventCapacity, BrowserQueueDepthLimit, BrowserQueueWaitLimit,
    BrowserRecycleThreshold, BrowserTabTotalLimit, BrowserTabsPerSessionLimit, ProfileWarmBounds,
    ProfileWarmPlan, ProfileWarmPlanId, RequestedWebTarget,
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
    sync::mpsc,
    task::JoinHandle,
};

fn limits() -> Result<BrowserExecutionLimits, Box<dyn Error>> {
    Ok(BrowserExecutionLimits::new(
        BrowserProcessLimit::new(NonZeroU32::MIN),
        BrowserContextTotalLimit::new(NonZeroU32::MIN),
        BrowserContextsPerProcessLimit::new(NonZeroU32::MIN),
        BrowserTabTotalLimit::new(NonZeroU32::MIN),
        BrowserTabsPerSessionLimit::new(NonZeroU32::MIN),
        BrowserQueueDepthLimit::new(NonZeroU32::MIN),
        BrowserQueueWaitLimit::new(NonZeroU64::new(10_000).ok_or("queue wait")?),
        BrowserCleanupDeadline::new(NonZeroU64::new(10_000).ok_or("cleanup")?),
        BrowserRecycleThreshold::new(NonZeroU32::MIN),
    )?)
}

fn scheduler_limits() -> BrowserNavigationSchedulerLimits {
    BrowserNavigationSchedulerLimits::new(
        BrowserActiveNavigationLimit::new(NonZeroU32::MIN),
        BrowserQueueDepthLimit::new(NonZeroU32::MIN),
        BrowserNavigationProgressCapacity::new(NonZeroU32::new(16).unwrap_or(NonZeroU32::MIN)),
        BrowserEngineProgressCapacity::new(NonZeroU32::new(16).unwrap_or(NonZeroU32::MIN)),
        BrowserProviderEventCapacity::new(NonZeroU32::new(64).unwrap_or(NonZeroU32::MIN)),
        BrowserNavigationDeadline::new(NonZeroU64::new(10_000).unwrap_or(NonZeroU64::MIN)),
    )
}

fn service(root: &Path) -> Result<ManagedProfileWarmService, Box<dyn Error>> {
    Ok(ManagedProfileWarmService::new(
        provider::ProfileRegistry::new(root.join("profiles")),
        ProfileLifecycleStore::new(root.join("lifecycle"))?,
        Arc::new(BrowserProfileLeaseGenerationRegistry::default()),
        limits()?,
        BrowserExecutionManagerConfig::default(),
        scheduler_limits(),
        Duration::from_secs(60),
    )?)
}

fn plan() -> Result<ProfileWarmPlan, Box<dyn Error>> {
    Ok(ProfileWarmPlan::new(
        vec![RequestedWebTarget::parse("https://warm.example/")?],
        ProfileWarmBounds::new(1, 1_000, 2_000)?,
        BrowserNavigationReadinessCheckpoint::Load,
    )?)
}

struct LoopbackFixture {
    base_url: String,
    requests: mpsc::Receiver<String>,
    cancellation: CancellationToken,
    task: Option<JoinHandle<io::Result<()>>>,
}

impl LoopbackFixture {
    async fn start() -> Result<Self, Box<dyn Error>> {
        let listener = TcpListener::bind("127.0.0.1:0").await?;
        let address = listener.local_addr()?;
        let cancellation = CancellationToken::new();
        let server_cancellation = cancellation.clone();
        let (request_sender, requests) = mpsc::channel(8);
        let task = tokio::spawn(async move {
            loop {
                let (mut stream, _) = tokio::select! {
                    () = server_cancellation.cancelled() => return Ok(()),
                    accepted = listener.accept() => accepted?,
                };
                let mut request = Vec::with_capacity(2_048);
                let mut buffer = [0_u8; 1_024];
                loop {
                    let count = stream.read(&mut buffer).await?;
                    if count == 0 {
                        break;
                    }
                    request.extend_from_slice(&buffer[..count]);
                    if request.windows(4).any(|window| window == b"\r\n\r\n")
                        || request.len() >= 16_384
                    {
                        break;
                    }
                }
                let text = String::from_utf8_lossy(&request);
                let path = text
                    .lines()
                    .next()
                    .and_then(|line| line.split_whitespace().nth(1))
                    .unwrap_or("/");
                if path == "/first" || path == "/second" {
                    request_sender
                        .send(path.to_owned())
                        .await
                        .map_err(|_| io::Error::other("request observer closed"))?;
                }
                let body = b"<html><body>warmed</body></html>";
                let header = format!(
                    "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                    body.len()
                );
                if stream.write_all(header.as_bytes()).await.is_err() {
                    continue;
                }
                if stream.write_all(body).await.is_err() {
                    continue;
                }
                let _ = stream.shutdown().await;
            }
        });
        Ok(Self {
            base_url: format!("http://{address}"),
            requests,
            cancellation,
            task: Some(task),
        })
    }

    async fn shutdown(mut self) -> Result<(), Box<dyn Error>> {
        self.cancellation.cancel();
        let task = self.task.take().ok_or("fixture task missing")?;
        task.await??;
        Ok(())
    }
}

impl Drop for LoopbackFixture {
    fn drop(&mut self) {
        self.cancellation.cancel();
    }
}

#[tokio::test]
async fn pre_cancelled_warmup_returns_without_staging_or_launching() -> Result<(), Box<dyn Error>> {
    let directory = tempfile::tempdir()?;
    let service = service(directory.path())?;
    let profile_id = BrowserProfileId::new("cancelled-warm")?;
    let spec = NewProfileSpec::new(profile_id, BrowserProfileOwnerId::random());
    let cancellation = CancellationToken::new();
    cancellation.cancel();

    let receipt = service.provision(spec, &plan()?, &cancellation).await?;

    assert_eq!(receipt.reason(), ProfileWarmTerminalReason::CallerCancelled);
    assert_eq!(
        receipt.profile_disposition(),
        ProfileWarmProfileDisposition::Removed
    );
    assert!(
        receipt
            .steps()
            .iter()
            .all(|step| { step.outcome() == ProfileWarmStepOutcome::NotAttempted })
    );
    assert!(!directory.path().join("profiles").exists());
    Ok(())
}

#[tokio::test]
async fn lifecycle_stage_conflict_discards_the_unlaunched_provider_profile()
-> Result<(), Box<dyn Error>> {
    let directory = tempfile::tempdir()?;
    let service = service(directory.path())?;
    let profile_id = BrowserProfileId::new("lifecycle-conflict")?;
    let spec = NewProfileSpec::new(profile_id.clone(), BrowserProfileOwnerId::random());
    let lifecycle = ProfileLifecycleStore::new(directory.path().join("lifecycle"))?;
    lifecycle.stage_profile(&profile_id, wall_now())?;
    let available = BrowserProfileLifecycleRecord::from_event(
        wall_now(),
        BrowserProfileLifecycleState::Staged,
        None,
        BrowserProfileLifecycleEvent::ProvisionSucceeded,
    )?;
    lifecycle.commit(&profile_id, &available)?;

    let receipt = service
        .provision(spec, &plan()?, &CancellationToken::new())
        .await?;

    assert_eq!(receipt.reason(), ProfileWarmTerminalReason::StagingFailed);
    assert_eq!(
        receipt.profile_disposition(),
        ProfileWarmProfileDisposition::Removed
    );
    assert!(
        !directory
            .path()
            .join("profiles")
            .join(".staging")
            .join("lifecycle-conflict")
            .exists()
    );
    Ok(())
}

#[tokio::test]
async fn lifecycle_publish_failure_returns_unavailable_receipt() -> Result<(), Box<dyn Error>> {
    let directory = tempfile::tempdir()?;
    let registry = provider::ProfileRegistry::new(directory.path().join("profiles"));
    let lifecycle = ProfileLifecycleStore::new(directory.path().join("lifecycle"))?;
    let generations = Arc::new(BrowserProfileLeaseGenerationRegistry::default());
    let service = ManagedProfileWarmService::new(
        registry.clone(),
        lifecycle.clone(),
        Arc::clone(&generations),
        limits()?,
        BrowserExecutionManagerConfig::default(),
        scheduler_limits(),
        Duration::from_secs(60),
    )?;
    lifecycle.fail_after_commits_for_test(1);
    let fixture = LoopbackFixture::start().await?;
    let plan = ProfileWarmPlan::new(
        vec![RequestedWebTarget::parse(&format!(
            "{}/first",
            fixture.base_url
        ))?],
        ProfileWarmBounds::new(1, 10_000, 20_000)?,
        BrowserNavigationReadinessCheckpoint::Load,
    )?;
    let profile_id =
        BrowserProfileId::new(format!("lifecycle-failure-{}", ProfileWarmPlanId::random()))?;
    let spec = NewProfileSpec::new(profile_id.clone(), BrowserProfileOwnerId::random());

    let receipt = service
        .provision(spec, &plan, &CancellationToken::new())
        .await?;
    fixture.shutdown().await?;

    assert_eq!(
        receipt.reason(),
        ProfileWarmTerminalReason::OwnershipUncertain
    );
    assert_eq!(
        receipt.profile_disposition(),
        ProfileWarmProfileDisposition::RetainedUnavailable
    );
    assert!(matches!(
        lifecycle.record(&profile_id)?.map(|record| record.next()),
        Some(BrowserProfileLifecycleState::Quarantined { .. })
    ));
    assert!(
        BrowserExecutionManager::new_managed_profile(
            limits()?,
            BrowserExecutionManagerConfig::default(),
            registry,
            profile_id,
            lifecycle,
            generations,
            Duration::from_secs(60),
        )
        .is_err()
    );
    Ok(())
}

#[tokio::test]
async fn ordered_loopback_plan_publishes_only_after_close() -> Result<(), Box<dyn Error>> {
    let directory = tempfile::tempdir()?;
    let registry = provider::ProfileRegistry::new(directory.path().join("profiles"));
    let lifecycle = ProfileLifecycleStore::new(directory.path().join("lifecycle"))?;
    let service = ManagedProfileWarmService::new(
        registry.clone(),
        lifecycle,
        Arc::new(BrowserProfileLeaseGenerationRegistry::default()),
        limits()?,
        BrowserExecutionManagerConfig::default(),
        scheduler_limits(),
        Duration::from_secs(60),
    )?;
    let mut fixture = LoopbackFixture::start().await?;
    let targets = ["/first", "/second"]
        .into_iter()
        .map(|path| RequestedWebTarget::parse(&format!("{}{path}", fixture.base_url)))
        .collect::<Result<Vec<_>, _>>()?;
    let plan = ProfileWarmPlan::new(
        targets,
        ProfileWarmBounds::new(2, 10_000, 20_000)?,
        BrowserNavigationReadinessCheckpoint::Load,
    )?;
    let profile_id = BrowserProfileId::new(format!("ordered-{}", ProfileWarmPlanId::random()))?;
    let spec = NewProfileSpec::new(profile_id.clone(), BrowserProfileOwnerId::random());

    let receipt = service
        .provision(spec, &plan, &CancellationToken::new())
        .await?;
    assert_eq!(
        receipt.reason(),
        ProfileWarmTerminalReason::Completed,
        "warm receipt: {receipt:?}"
    );
    assert_eq!(
        receipt.profile_disposition(),
        ProfileWarmProfileDisposition::PublishedAvailable
    );
    let first = fixture
        .requests
        .recv()
        .await
        .ok_or("first target was not requested")?;
    let second = fixture
        .requests
        .recv()
        .await
        .ok_or("second target was not requested")?;
    fixture.shutdown().await?;

    assert_eq!(first, "/first");
    assert_eq!(second, "/second");
    assert_eq!(receipt.reason(), ProfileWarmTerminalReason::Completed);
    assert_eq!(
        receipt.process_cleanup(),
        ProfileWarmProcessCleanup::ConfirmedClosed
    );
    assert_eq!(
        receipt.profile_disposition(),
        ProfileWarmProfileDisposition::PublishedAvailable
    );
    assert_eq!(receipt.steps().len(), 2);
    assert_eq!(
        registry.describe_profile(profile_id.as_str())?.status,
        provider::ProfileStatus::Available
    );
    let saved_lifecycle = ProfileLifecycleStore::new(directory.path().join("lifecycle"))?;
    assert_eq!(
        saved_lifecycle
            .load_all()?
            .get(&profile_id)
            .map(BrowserProfileLifecycleRecord::next),
        Some(BrowserProfileLifecycleState::Available)
    );
    Ok(())
}
