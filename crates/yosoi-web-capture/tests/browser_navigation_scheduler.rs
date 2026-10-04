//! Black-box CAS-351 scheduler coverage using event-gated loopback fixtures.
#![allow(clippy::expect_used, clippy::panic, clippy::unwrap_used)]

use std::{
    num::{NonZeroU32, NonZeroU64},
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::Duration,
};

use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    sync::{Notify, oneshot},
    task::JoinHandle,
    time::timeout,
};
use tokio_util::sync::CancellationToken;
use yosoi_web_capture::{
    BrowserActiveNavigationLimit, BrowserCleanupDeadline, BrowserContextTotalLimit,
    BrowserContextsPerProcessLimit, BrowserEngineProgressCapacity, BrowserExecutionLimits,
    BrowserExecutionManager, BrowserExecutionManagerConfig, BrowserNavigationCommand,
    BrowserNavigationDeadline, BrowserNavigationOutcome, BrowserNavigationProgressCapacity,
    BrowserNavigationProgressKind, BrowserNavigationReadinessCheckpoint,
    BrowserNavigationScheduler, BrowserNavigationSchedulerError, BrowserNavigationSchedulerLimits,
    BrowserProcessLimit, BrowserProviderEventCapacity, BrowserQueueDepthLimit,
    BrowserQueueWaitLimit, BrowserRecycleThreshold, BrowserTabTotalLimit,
    BrowserTabsPerSessionLimit, LossExtent, RequestedWebTarget,
};

const TEST_DEADLINE: Duration = Duration::from_secs(10);

struct Gate {
    opened: AtomicBool,
    arrived: AtomicBool,
    arrival: Notify,
    release: Notify,
}

impl Gate {
    fn new() -> Self {
        Self {
            opened: AtomicBool::new(false),
            arrived: AtomicBool::new(false),
            arrival: Notify::new(),
            release: Notify::new(),
        }
    }

    fn arrive(&self) {
        self.arrived.store(true, Ordering::Release);
        self.arrival.notify_waiters();
    }

    async fn wait_for_arrival(&self) {
        while !self.arrived.load(Ordering::Acquire) {
            self.arrival.notified().await;
        }
    }

    fn open(&self) {
        self.opened.store(true, Ordering::Release);
        self.release.notify_waiters();
    }

    fn reset_arrival(&self) {
        self.arrived.store(false, Ordering::Release);
    }

    async fn wait_until_open(&self) {
        while !self.opened.load(Ordering::Acquire) {
            self.release.notified().await;
        }
    }
}

struct Fixture {
    base_url: String,
    slow: Arc<Gate>,
    fast: Arc<Gate>,
    second: Arc<Gate>,
    other_session: Arc<Gate>,
    shutdown: Option<oneshot::Sender<()>>,
    server: JoinHandle<()>,
}

impl Fixture {
    async fn start() -> Self {
        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .expect("bind loopback fixture");
        let address = listener.local_addr().expect("fixture address");
        let slow = Arc::new(Gate::new());
        let fast = Arc::new(Gate::new());
        let second = Arc::new(Gate::new());
        let other_session = Arc::new(Gate::new());
        let (shutdown, mut shutdown_rx) = oneshot::channel();
        let server_gates = [
            Arc::clone(&slow),
            Arc::clone(&fast),
            Arc::clone(&second),
            Arc::clone(&other_session),
        ];
        let server = tokio::spawn(async move {
            loop {
                tokio::select! {
                    _ = &mut shutdown_rx => return,
                    accepted = listener.accept() => match accepted {
                        Ok((stream, _)) => {
                            let gates = server_gates.clone();
                            tokio::spawn(async move { serve(stream, gates).await; });
                        }
                        Err(_) => return,
                    },
                }
            }
        });
        Self {
            base_url: format!("http://{address}"),
            slow,
            fast,
            second,
            other_session,
            shutdown: Some(shutdown),
            server,
        }
    }

    fn target(&self, path: &str) -> RequestedWebTarget {
        RequestedWebTarget::parse(&format!("{}{path}", self.base_url)).expect("fixture target")
    }

    async fn observed(&self, gate: &Gate, label: &str) {
        timeout(TEST_DEADLINE, gate.wait_for_arrival())
            .await
            .unwrap_or_else(|_| panic!("fixture did not observe {label}"));
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        self.slow.open();
        self.fast.open();
        self.second.open();
        self.other_session.open();
        if let Some(shutdown) = self.shutdown.take() {
            let _ = shutdown.send(());
        }
        self.server.abort();
    }
}

async fn serve(mut stream: TcpStream, gates: [Arc<Gate>; 4]) {
    let mut request = [0_u8; 4096];
    let Ok(read) = stream.read(&mut request).await else {
        return;
    };
    let request_text = String::from_utf8_lossy(request.get(..read).unwrap_or(&request));
    let path = request_text
        .split_whitespace()
        .nth(1)
        .unwrap_or("/")
        .split('?')
        .next()
        .unwrap_or("/");
    match path {
        "/slow" => {
            gates[0].arrive();
            gates[0].wait_until_open().await;
        }
        "/fast" => gates[1].arrive(),
        "/second" => gates[2].arrive(),
        "/other-session" => {
            gates[3].arrive();
            gates[3].wait_until_open().await;
        }
        _ => {}
    }
    let body = "<!doctype html><main>fixture</main>";
    let response = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: {}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n{body}",
        body.len()
    );
    let _ = stream.write_all(response.as_bytes()).await;
    let _ = stream.shutdown().await;
}

const fn nz32(value: u32) -> NonZeroU32 {
    NonZeroU32::new(value).expect("positive test limit")
}

fn scheduler(tab_limit: u32, active: u32, queue_depth: u32) -> BrowserNavigationScheduler {
    scheduler_with_progress(tab_limit, active, queue_depth, 16)
}

fn scheduler_with_progress(
    tab_limit: u32,
    active: u32,
    queue_depth: u32,
    progress_capacity: u32,
) -> BrowserNavigationScheduler {
    scheduler_with_policy(tab_limit, active, queue_depth, progress_capacity, 5_000)
}

fn scheduler_with_policy(
    tab_limit: u32,
    active: u32,
    queue_depth: u32,
    progress_capacity: u32,
    queue_wait_ms: u64,
) -> BrowserNavigationScheduler {
    let manager = manager(tab_limit, queue_depth, queue_wait_ms);
    BrowserNavigationScheduler::new(
        manager,
        navigation_limits(active, queue_depth, progress_capacity),
    )
    .expect("valid scheduler")
}

fn manager(tab_limit: u32, queue_depth: u32, queue_wait_ms: u64) -> BrowserExecutionManager {
    let contexts = tab_limit.min(2);
    let execution = BrowserExecutionLimits::new(
        BrowserProcessLimit::new(NonZeroU32::MIN),
        BrowserContextTotalLimit::new(nz32(contexts)),
        BrowserContextsPerProcessLimit::new(nz32(contexts)),
        BrowserTabTotalLimit::new(nz32(tab_limit)),
        BrowserTabsPerSessionLimit::new(nz32(tab_limit)),
        BrowserQueueDepthLimit::new(nz32(queue_depth)),
        BrowserQueueWaitLimit::new(NonZeroU64::new(queue_wait_ms).expect("queue wait")),
        BrowserCleanupDeadline::new(NonZeroU64::new(5_000).expect("cleanup")),
        BrowserRecycleThreshold::new(nz32(100)),
    )
    .expect("valid execution limits");
    BrowserExecutionManager::new(execution, BrowserExecutionManagerConfig::default())
}

const fn navigation_limits(
    active: u32,
    queue_depth: u32,
    progress_capacity: u32,
) -> BrowserNavigationSchedulerLimits {
    BrowserNavigationSchedulerLimits::new(
        BrowserActiveNavigationLimit::new(nz32(active)),
        BrowserQueueDepthLimit::new(nz32(queue_depth)),
        BrowserNavigationProgressCapacity::new(nz32(progress_capacity)),
        BrowserEngineProgressCapacity::new(nz32(16)),
        BrowserProviderEventCapacity::new(nz32(64)),
        BrowserNavigationDeadline::new(NonZeroU64::new(5_000).expect("navigation deadline")),
    )
}

#[tokio::test]
async fn queued_navigation_terminates_at_the_configured_queue_deadline() {
    let fixture = Fixture::start().await;
    let scheduler = scheduler_with_policy(1, 1, 2, 16, 25);
    let cancellation = CancellationToken::new();
    let session = scheduler
        .acquire_session(&cancellation)
        .await
        .expect("session");
    let active = scheduler
        .schedule(
            session.initial_tab(),
            command(
                fixture.target("/slow"),
                BrowserNavigationReadinessCheckpoint::Load,
            ),
            &cancellation,
        )
        .await
        .expect("active navigation");
    fixture.observed(&fixture.slow, "active navigation").await;
    let queued = scheduler
        .schedule(
            session.initial_tab(),
            command(
                fixture.target("/fast"),
                BrowserNavigationReadinessCheckpoint::Load,
            ),
            &cancellation,
        )
        .await
        .expect("queued navigation");
    assert_eq!(
        terminal(queued).await.outcome(),
        BrowserNavigationOutcome::QueueWaitDeadline
    );
    assert_eq!(
        terminal_cancel(active).await.outcome(),
        BrowserNavigationOutcome::CancelledDuringNavigation
    );
    scheduler.shutdown().await.expect("scheduler shutdown");
}

#[tokio::test]
async fn direct_manager_shutdown_drains_active_and_queued_scheduler_jobs() {
    let fixture = Fixture::start().await;
    let manager = manager(1, 2, 5_000);
    let shutdown_manager = manager.clone();
    let scheduler =
        BrowserNavigationScheduler::new(manager, navigation_limits(1, 2, 16)).expect("scheduler");
    let cancellation = CancellationToken::new();
    let session = scheduler
        .acquire_session(&cancellation)
        .await
        .expect("session");
    let active = scheduler
        .schedule(
            session.initial_tab(),
            command(
                fixture.target("/slow"),
                BrowserNavigationReadinessCheckpoint::Load,
            ),
            &cancellation,
        )
        .await
        .expect("active navigation");
    fixture
        .observed(&fixture.slow, "direct shutdown active")
        .await;
    let queued = scheduler
        .schedule(
            session.initial_tab(),
            command(
                fixture.target("/fast"),
                BrowserNavigationReadinessCheckpoint::Load,
            ),
            &cancellation,
        )
        .await
        .expect("queued navigation");
    let (shutdown, active, queued) = tokio::join!(
        shutdown_manager.shutdown(),
        terminal(active),
        terminal(queued)
    );
    shutdown.expect("direct manager shutdown");
    assert_eq!(active.outcome(), BrowserNavigationOutcome::ManagerShutdown);
    assert_eq!(queued.outcome(), BrowserNavigationOutcome::ManagerShutdown);
}

#[tokio::test]
async fn scheduler_attachment_is_unique_and_released_after_drop() {
    let manager = manager(1, 1, 5_000);
    let first = BrowserNavigationScheduler::new(manager.clone(), navigation_limits(1, 1, 16))
        .expect("first scheduler");
    assert!(matches!(
        BrowserNavigationScheduler::new(manager.clone(), navigation_limits(1, 1, 16)),
        Err(BrowserNavigationSchedulerError::SchedulerAlreadyAttached)
    ));
    drop(first);
    let replacement = BrowserNavigationScheduler::new(manager, navigation_limits(1, 1, 16))
        .expect("replacement scheduler");
    replacement.shutdown().await.expect("replacement shutdown");
}

#[tokio::test]
async fn progress_loss_is_bounded_and_reported_without_losing_readiness() {
    let fixture = Fixture::start().await;
    let scheduler = scheduler_with_progress(1, 1, 1, 1);
    let cancellation = CancellationToken::new();
    let session = scheduler
        .acquire_session(&cancellation)
        .await
        .expect("session");
    let handle = scheduler
        .schedule(
            session.initial_tab(),
            command(
                fixture.target("/fast"),
                BrowserNavigationReadinessCheckpoint::Load,
            ),
            &cancellation,
        )
        .await
        .expect("navigation admission");
    let receipt = terminal(handle).await;
    let accounting = receipt.progress();
    assert!(accounting.admitted().get() > accounting.retained().get());
    assert_eq!(accounting.retained().get(), 1);
    assert_eq!(
        accounting.dropped(),
        LossExtent::Known(accounting.admitted().get() - accounting.retained().get())
    );
    assert_eq!(receipt.engine_progress_dropped(), LossExtent::Known(0));
    assert_eq!(receipt.provider_events_dropped(), LossExtent::Known(0));
    assert_eq!(
        receipt.reached_readiness(),
        Some(BrowserNavigationProgressKind::Load)
    );
    scheduler.shutdown().await.expect("scheduler shutdown");
}

const fn command(
    target: RequestedWebTarget,
    readiness: BrowserNavigationReadinessCheckpoint,
) -> BrowserNavigationCommand {
    BrowserNavigationCommand::new(target, readiness)
}

async fn terminal(
    handle: yosoi_web_capture::BrowserNavigationHandle,
) -> yosoi_web_capture::BrowserNavigationTerminalReceipt {
    timeout(TEST_DEADLINE, handle.wait())
        .await
        .expect("navigation terminal deadline")
        .expect("navigation terminal receipt")
}

async fn arbitrary_tab_count(tab_count: u32) {
    let fixture = Fixture::start().await;
    let scheduler = scheduler(tab_count, tab_count, tab_count);
    let cancellation = CancellationToken::new();
    let session = scheduler
        .acquire_session(&cancellation)
        .await
        .expect("session");
    let mut tabs = vec![session.initial_tab().clone()];
    for _ in 1..tab_count {
        tabs.push(session.new_tab(&cancellation).await.expect("dynamic tab"));
    }
    let mut handles = Vec::with_capacity(tabs.len());
    for tab in &tabs {
        handles.push(
            scheduler
                .schedule(
                    tab,
                    command(
                        fixture.target("/fast"),
                        BrowserNavigationReadinessCheckpoint::Load,
                    ),
                    &cancellation,
                )
                .await
                .expect("bounded admission"),
        );
    }
    for (tab, handle) in tabs.iter().zip(&mut handles) {
        let ready = timeout(TEST_DEADLINE, handle.wait_until_ready())
            .await
            .expect("tab readiness deadline")
            .expect("tab readiness receipt");
        assert_eq!(ready.tab(), tab.id());
        assert_eq!(ready.request(), handle.id());
        assert_eq!(ready.kind(), BrowserNavigationProgressKind::Load);
    }
    for handle in handles {
        assert_eq!(
            terminal(handle).await.outcome(),
            BrowserNavigationOutcome::Completed
        );
    }
    scheduler.shutdown().await.expect("scheduler shutdown");
}

#[tokio::test]
async fn runtime_configured_tab_counts_have_no_fixed_scheduler_ceiling() {
    for count in [1, 4, 16] {
        arbitrary_tab_count(count).await;
    }
}

#[tokio::test]
#[ignore = "resource-gated 64-tab browser exercise"]
async fn scheduler_supports_sixty_four_tabs_when_policy_and_ram_allow_it() {
    arbitrary_tab_count(64).await;
}

#[tokio::test]
async fn slow_tab_yields_while_each_tab_remains_serial() {
    let fixture = Fixture::start().await;
    let scheduler = scheduler(2, 2, 4);
    let cancellation = CancellationToken::new();
    let session = scheduler
        .acquire_session(&cancellation)
        .await
        .expect("session");
    let slow_tab = session.initial_tab().clone();
    let fast_tab = session.new_tab(&cancellation).await.expect("second tab");
    let slow = scheduler
        .schedule(
            &slow_tab,
            command(
                fixture.target("/slow"),
                BrowserNavigationReadinessCheckpoint::Load,
            ),
            &cancellation,
        )
        .await
        .expect("slow admission");
    fixture.observed(&fixture.slow, "slow request").await;
    let second = scheduler
        .schedule(
            &slow_tab,
            command(
                fixture.target("/second"),
                BrowserNavigationReadinessCheckpoint::Load,
            ),
            &cancellation,
        )
        .await
        .expect("same-tab queue");
    let fast = scheduler
        .schedule(
            &fast_tab,
            command(
                fixture.target("/fast"),
                BrowserNavigationReadinessCheckpoint::Load,
            ),
            &cancellation,
        )
        .await
        .expect("fast admission");
    fixture.observed(&fixture.fast, "fast request").await;
    assert_eq!(
        terminal(fast).await.outcome(),
        BrowserNavigationOutcome::Completed
    );
    assert_eq!(
        scheduler
            .snapshot()
            .await
            .expect("snapshot")
            .active_navigations,
        1
    );
    assert_eq!(
        scheduler
            .snapshot()
            .await
            .expect("snapshot")
            .queued_navigations,
        1
    );
    fixture.slow.open();
    assert_eq!(
        terminal(slow).await.outcome(),
        BrowserNavigationOutcome::Completed
    );
    fixture
        .observed(&fixture.second, "serialized request")
        .await;
    assert_eq!(
        terminal(second).await.outcome(),
        BrowserNavigationOutcome::Completed
    );
    scheduler.shutdown().await.expect("scheduler shutdown");
}

#[tokio::test]
async fn queue_is_bounded_and_runnable_tabs_do_not_wait_behind_a_busy_tab() {
    let fixture = Fixture::start().await;
    let scheduler = scheduler(2, 1, 2);
    let cancellation = CancellationToken::new();
    let session_a = scheduler
        .acquire_session(&cancellation)
        .await
        .expect("session A");
    let session_b = scheduler
        .acquire_session(&cancellation)
        .await
        .expect("session B");
    let first = scheduler
        .schedule(
            session_a.initial_tab(),
            command(
                fixture.target("/slow"),
                BrowserNavigationReadinessCheckpoint::Load,
            ),
            &cancellation,
        )
        .await
        .expect("active A");
    fixture.observed(&fixture.slow, "active A").await;
    let second_a = scheduler
        .schedule(
            session_a.initial_tab(),
            command(
                fixture.target("/second"),
                BrowserNavigationReadinessCheckpoint::Load,
            ),
            &cancellation,
        )
        .await
        .expect("queued A");
    let first_b = scheduler
        .schedule(
            session_b.initial_tab(),
            command(
                fixture.target("/other-session"),
                BrowserNavigationReadinessCheckpoint::Load,
            ),
            &cancellation,
        )
        .await
        .expect("queued B");
    assert!(matches!(
        scheduler
            .schedule(
                session_b.initial_tab(),
                command(
                    fixture.target("/fast"),
                    BrowserNavigationReadinessCheckpoint::Load
                ),
                &cancellation
            )
            .await,
        Err(BrowserNavigationSchedulerError::QueueFull)
    ));
    fixture.slow.open();
    assert_eq!(
        terminal(first).await.outcome(),
        BrowserNavigationOutcome::Completed
    );
    fixture
        .observed(&fixture.other_session, "runnable session B")
        .await;
    assert!(!fixture.second.arrived.load(Ordering::Acquire));
    fixture.other_session.open();
    assert_eq!(
        terminal(first_b).await.outcome(),
        BrowserNavigationOutcome::Completed
    );
    assert_eq!(
        terminal(second_a).await.outcome(),
        BrowserNavigationOutcome::Completed
    );
    scheduler.shutdown().await.expect("scheduler shutdown");
}

#[tokio::test]
async fn readiness_is_typed_and_network_idle_is_rejected() {
    let fixture = Fixture::start().await;
    let scheduler = scheduler(1, 1, 2);
    let cancellation = CancellationToken::new();
    let session = scheduler
        .acquire_session(&cancellation)
        .await
        .expect("session");
    let mut handle = scheduler
        .schedule(
            session.initial_tab(),
            command(
                fixture.target("/fast"),
                BrowserNavigationReadinessCheckpoint::DomContentLoaded,
            ),
            &cancellation,
        )
        .await
        .expect("admission");
    let ready = timeout(TEST_DEADLINE, handle.wait_until_ready())
        .await
        .expect("readiness deadline")
        .expect("readiness receipt");
    assert_eq!(
        ready.kind(),
        BrowserNavigationProgressKind::DomContentLoaded
    );
    assert_eq!(ready.tab(), session.initial_tab().id());
    let instrumentation = session
        .initial_tab()
        .instrumentation_state()
        .await
        .expect("instrumentation state");
    assert!(instrumentation.low_cdp);
    assert!(!instrumentation.network_enabled);
    assert!(!instrumentation.runtime_enabled);
    assert_eq!(
        terminal(handle).await.outcome(),
        BrowserNavigationOutcome::Completed
    );
    assert!(matches!(
        scheduler
            .schedule(
                session.initial_tab(),
                command(
                    fixture.target("/fast"),
                    BrowserNavigationReadinessCheckpoint::NetworkIdle
                ),
                &cancellation
            )
            .await,
        Err(BrowserNavigationSchedulerError::UnsupportedReadiness {
            requested: BrowserNavigationReadinessCheckpoint::NetworkIdle
        })
    ));
    let instrumentation = session
        .initial_tab()
        .instrumentation_state()
        .await
        .expect("instrumentation after rejection");
    assert!(!instrumentation.network_enabled);
    assert!(!instrumentation.runtime_enabled);
    scheduler.shutdown().await.expect("scheduler shutdown");
}

#[tokio::test]
async fn cancellation_tab_release_and_shutdown_wake_every_waiter_once() {
    let fixture = Fixture::start().await;
    let scheduler = scheduler(1, 1, 2);
    let cancellation = CancellationToken::new();
    let session = scheduler
        .acquire_session(&cancellation)
        .await
        .expect("session");
    let tab = session.initial_tab().clone();
    let active = scheduler
        .schedule(
            &tab,
            command(
                fixture.target("/slow"),
                BrowserNavigationReadinessCheckpoint::Load,
            ),
            &cancellation,
        )
        .await
        .expect("active");
    fixture.observed(&fixture.slow, "active cancellation").await;
    let queued = scheduler
        .schedule(
            &tab,
            command(
                fixture.target("/fast"),
                BrowserNavigationReadinessCheckpoint::Load,
            ),
            &cancellation,
        )
        .await
        .expect("queued");
    let queued_receipt = terminal_cancel(queued).await;
    assert_eq!(
        queued_receipt.outcome(),
        BrowserNavigationOutcome::CancelledBeforeAdmission
    );
    let active_receipt = terminal_cancel(active).await;
    assert_eq!(
        active_receipt.outcome(),
        BrowserNavigationOutcome::CancelledDuringNavigation
    );
    assert_ne!(queued_receipt.request(), active_receipt.request());
    assert!(tab.instrumentation_state().await.is_err());
    session.release().await.expect("cancelled session release");
    let close_session = scheduler
        .acquire_session(&cancellation)
        .await
        .expect("tab-close session");
    let close_tab = close_session.initial_tab().clone();
    let waiter = scheduler
        .schedule(
            &close_tab,
            command(
                fixture.target("/slow"),
                BrowserNavigationReadinessCheckpoint::Load,
            ),
            &cancellation,
        )
        .await
        .expect("close waiter");
    close_tab.close().await.expect("tab close");
    assert_eq!(
        terminal(waiter).await.outcome(),
        BrowserNavigationOutcome::TabClosed
    );
    close_session
        .release()
        .await
        .expect("tab-close session release");
    let replacement = scheduler
        .acquire_session(&cancellation)
        .await
        .expect("replacement session");
    fixture.slow.reset_arrival();
    let release_waiter = scheduler
        .schedule(
            replacement.initial_tab(),
            command(
                fixture.target("/slow"),
                BrowserNavigationReadinessCheckpoint::Load,
            ),
            &cancellation,
        )
        .await
        .expect("release waiter");
    fixture
        .observed(&fixture.slow, "release cancellation")
        .await;
    let (release, release_receipt) = tokio::join!(replacement.release(), terminal(release_waiter));
    release.expect("session release with active navigation");
    assert_eq!(
        release_receipt.outcome(),
        BrowserNavigationOutcome::TabClosed
    );
    let shutdown_session = scheduler
        .acquire_session(&cancellation)
        .await
        .expect("shutdown session");
    fixture.slow.reset_arrival();
    let shutdown_waiter = scheduler
        .schedule(
            shutdown_session.initial_tab(),
            command(
                fixture.target("/slow"),
                BrowserNavigationReadinessCheckpoint::Load,
            ),
            &cancellation,
        )
        .await
        .expect("shutdown waiter");
    fixture.observed(&fixture.slow, "shutdown active").await;
    let shutdown_queued = scheduler
        .schedule(
            shutdown_session.initial_tab(),
            command(
                fixture.target("/fast"),
                BrowserNavigationReadinessCheckpoint::Load,
            ),
            &cancellation,
        )
        .await
        .expect("shutdown queued waiter");
    let (shutdown, receipt, queued_receipt) = tokio::join!(
        scheduler.shutdown(),
        terminal(shutdown_waiter),
        terminal(shutdown_queued)
    );
    shutdown.expect("scheduler shutdown");
    assert_eq!(receipt.outcome(), BrowserNavigationOutcome::ManagerShutdown);
    assert_eq!(
        queued_receipt.outcome(),
        BrowserNavigationOutcome::ManagerShutdown
    );
}

async fn terminal_cancel(
    handle: yosoi_web_capture::BrowserNavigationHandle,
) -> yosoi_web_capture::BrowserNavigationTerminalReceipt {
    timeout(TEST_DEADLINE, handle.cancel())
        .await
        .expect("cancellation deadline")
        .expect("cancellation receipt")
}
