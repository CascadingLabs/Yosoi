#![cfg(feature = "browser")]

//! Opt-in Flow continuation acceptance against the existing loopback fixture.
//!
//! Run with a regular Stable browser: `YOSOI_BROWSER_TESTS=1 cargo test -p yosoi --features browser --test continuation_browser -- --nocapture --test-threads=1`.

use std::{
    env,
    error::Error,
    io,
    net::Ipv4Addr,
    sync::{Arc, Mutex},
    time::Duration,
};
use yosoi::automation_record as yosoi_automation_record;
use yosoi::flow as yosoi_flow;

use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    sync::{mpsc, oneshot, watch},
    task::{JoinHandle, JoinSet},
    time::timeout,
};
use tokio_util::sync::CancellationToken;
use yosoi::{
    flow::{Condition, Continuation, Flow, FlowTermination, Step, StopScope},
    policy::{Acquisition, BrowserMode, DocumentRequest, MaximumElapsed, Page, Policy},
    session::{self, SessionPolicy},
};

struct GateFixture {
    base_url: String,
    paths: Arc<Mutex<Vec<String>>>,
    hold_requests: mpsc::UnboundedReceiver<()>,
    release_hold: watch::Sender<bool>,
    shutdown: Option<oneshot::Sender<()>>,
    task: JoinHandle<io::Result<()>>,
}

impl GateFixture {
    async fn start() -> io::Result<Self> {
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).await?;
        let address = listener.local_addr()?;
        let (shutdown, mut shutdown_rx) = oneshot::channel();
        let (hold_tx, hold_requests) = mpsc::unbounded_channel();
        let (release_hold, release_rx) = watch::channel(false);
        let paths = Arc::new(Mutex::new(Vec::new()));
        let server_paths = Arc::clone(&paths);
        let task = tokio::spawn(async move {
            let mut connections = JoinSet::new();
            loop {
                tokio::select! {
                    biased;
                    _ = &mut shutdown_rx => break,
                    accepted = listener.accept() => {
                        let (stream, _) = accepted?;
                        let paths = Arc::clone(&server_paths);
                        let hold_tx = hold_tx.clone();
                        let release_rx = release_rx.clone();
                        connections.spawn(async move {
                            let _ = serve_gate_request(stream, paths, hold_tx, release_rx).await;
                        });
                    }
                    Some(_) = connections.join_next(), if !connections.is_empty() => {}
                }
            }
            connections.abort_all();
            while connections.join_next().await.is_some() {}
            Ok(())
        });

        Ok(Self {
            base_url: format!("http://{address}"),
            paths,
            hold_requests,
            release_hold,
            shutdown: Some(shutdown),
            task,
        })
    }

    fn url(&self, path: &str) -> String {
        format!("{}{path}", self.base_url)
    }

    async fn wait_for_hold_request(&mut self) -> io::Result<()> {
        self.hold_requests
            .recv()
            .await
            .ok_or_else(|| io::Error::other("held navigation request was not observed"))
    }

    fn release_held_response(&self) {
        let _ = self.release_hold.send(true);
    }

    fn paths(&self) -> io::Result<Vec<String>> {
        self.paths
            .lock()
            .map(|paths| paths.clone())
            .map_err(|error| io::Error::other(error.to_string()))
    }

    async fn shutdown(mut self) -> io::Result<()> {
        self.release_held_response();
        if let Some(shutdown) = self.shutdown.take() {
            let _ = shutdown.send(());
        }
        self.task
            .await
            .map_err(|error| io::Error::other(error.to_string()))??;
        Ok(())
    }
}

async fn serve_gate_request(
    mut stream: TcpStream,
    paths: Arc<Mutex<Vec<String>>>,
    hold_requests: mpsc::UnboundedSender<()>,
    mut release_hold: watch::Receiver<bool>,
) -> io::Result<()> {
    let mut request = Vec::with_capacity(2_048);
    loop {
        let mut buffer = [0_u8; 1_024];
        let read = stream.read(&mut buffer).await?;
        if read == 0 {
            return Ok(());
        }
        let Some(read_buffer) = buffer.get(..read) else {
            return Err(io::Error::other("loopback read length exceeded its buffer"));
        };
        request.extend_from_slice(read_buffer);
        if request.windows(4).any(|window| window == b"\r\n\r\n") {
            break;
        }
        if request.len() >= 8_192 {
            return Err(io::Error::other("loopback request headers exceeded 8 KiB"));
        }
    }

    let request_text = String::from_utf8_lossy(&request);
    let request_line = request_text
        .lines()
        .next()
        .ok_or_else(|| io::Error::other("loopback request had no request line"))?;
    let raw_path = request_line
        .split_whitespace()
        .nth(1)
        .ok_or_else(|| io::Error::other("loopback request had no path"))?;
    let path = raw_path
        .split_once('?')
        .map_or(raw_path, |(path, _query)| path);
    paths
        .lock()
        .map_err(|error| io::Error::other(error.to_string()))?
        .push(path.to_owned());

    if path == "/hold" {
        let _ = hold_requests.send(());
        while !*release_hold.borrow() {
            if release_hold.changed().await.is_err() {
                break;
            }
        }
    }

    let body =
        "<!doctype html><html><body><main><h1>Continuation fixture</h1></main></body></html>";
    let response_head = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    );
    stream.write_all(response_head.as_bytes()).await?;
    stream.write_all(body.as_bytes()).await?;
    stream.shutdown().await
}

fn enabled() -> bool {
    if env::var("YOSOI_BROWSER_TESTS").ok().as_deref() == Some("1") {
        true
    } else {
        eprintln!("SKIPPED Flow continuation browser acceptance: set YOSOI_BROWSER_TESTS=1");
        false
    }
}

fn browser_policy() -> Result<Policy, Box<dyn Error>> {
    let mut policy = Policy {
        page: Page::new(vec![
            Acquisition::Browser(BrowserMode::Headless).documents([DocumentRequest::RenderedDom]),
        ])?,
        ..Policy::default()
    };
    policy.request.maximum_elapsed = MaximumElapsed::try_from(10_000_000)?;
    Ok(policy)
}

fn exists(selector: &str) -> Step {
    Step::Assert {
        condition: Condition::Exists {
            selector: selector.to_owned(),
        },
    }
}

async fn close(session: &session::Session) -> Result<(), Box<dyn Error>> {
    timeout(Duration::from_secs(10), session.close())
        .await
        .map_err(|_| io::Error::other("Session close did not finish within 10 seconds"))??;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn continuation_respects_nearest_scope_and_cancellation_authority()
-> Result<(), Box<dyn Error>> {
    if !enabled() {
        return Ok(());
    }

    let fixture = GateFixture::start().await?;
    let mut policy = browser_policy()?;
    policy.flow.on_failure = Continuation::Continue;
    policy.flow.on_cancellation = Continuation::Continue;
    let session = session::new()
        .bind(&policy)
        .configure(SessionPolicy {
            maximum_tabs: 1,
            operation_timeout_ms: 5_000,
            ..SessionPolicy::default()
        })
        .acquire()
        .await?;
    let work = session.work().await?;
    work.navigate(&fixture.url("/")).await?;

    // An explicit leaf Continue overrides the parent's Stop(Invocation).
    let continue_flow = Flow::new([
        exists("#missing").on_failure(Continuation::Continue),
        exists("h1"),
    ])
    .on_failure(Continuation::Stop(StopScope::Invocation));
    // This borrowed invocation intentionally uses the owning Session's policy fallback.
    let continued = continue_flow.with_lease(&work).invoke().await?;
    assert_eq!(continued.continuation_defaults, policy.flow);
    assert_eq!(continued.steps.len(), 2);
    assert_eq!(
        continued.steps[0].failure,
        Some(yosoi_flow::FlowFailureCause::Rejected)
    );
    assert_eq!(
        continued.steps[0].receipt.status,
        yosoi_automation_record::OperationStatus::Rejected
    );
    assert_eq!(continued.terminal, FlowTermination::CompletedWithIssues);
    assert!(continued.require_completed().is_err());

    // Stop(CurrentFlow) in a nested child skips that child's sibling, then
    // returns to the parent sibling with the child's failure still recorded.
    let child = Flow::new([exists("#missing"), exists("h1")])
        .on_failure(Continuation::Stop(StopScope::CurrentFlow));
    let nested = Flow::new([child.into(), exists("h1")]);
    let stopped_child = nested.bind(&policy).with_lease(&work).invoke().await?;
    assert_eq!(stopped_child.continuation_defaults, policy.flow);
    assert_eq!(stopped_child.steps.len(), 2);
    assert_eq!(stopped_child.steps[0].flow_path, [0, 0]);
    assert_eq!(stopped_child.steps[1].flow_path, [1]);
    assert_eq!(stopped_child.skipped_steps.len(), 1);
    assert_eq!(stopped_child.skipped_steps[0].flow_path, [0, 1]);
    assert_eq!(stopped_child.skipped_steps[0].stopped_by, [0, 0]);
    assert_eq!(stopped_child.skipped_steps[0].scope, StopScope::CurrentFlow);
    assert!(stopped_child.stop_reason.is_none());
    assert!(stopped_child.require_completed().is_err());

    // A pre-dispatch cancellation local to one Step can continue while the
    // borrowed root invocation and its lease remain live.
    let local_cancel = CancellationToken::new();
    local_cancel.cancel();
    let local_cancel_flow = Flow::new([
        Step::Navigate {
            url: fixture.url("/drop"),
        }
        .with_cancellation(&local_cancel),
        exists("h1"),
    ]);
    let local_cancelled = local_cancel_flow
        .bind(&policy)
        .with_lease(&work)
        .invoke()
        .await?;
    assert_eq!(local_cancelled.steps.len(), 2);
    assert_eq!(
        local_cancelled.steps[0].cancellation,
        Some(yosoi_flow::FlowCancellationCause::Step)
    );
    assert_eq!(
        local_cancelled.steps[0].receipt.status,
        yosoi_automation_record::OperationStatus::Rejected
    );
    assert_eq!(
        local_cancelled.steps[1].receipt.status,
        yosoi_automation_record::OperationStatus::Observed
    );
    assert!(!fixture.paths()?.iter().any(|path| path == "/drop"));
    assert!(local_cancelled.require_completed().is_err());

    // Cancellation on a nested Flow step keeps its runtime authority scoped to
    // that child step and permits the parent's next step to run.
    let nested_cancel = CancellationToken::new();
    nested_cancel.cancel();
    let cancelled_child =
        Step::from(Flow::new([exists("#missing")])).with_cancellation(&nested_cancel);
    let nested_cancel_flow = Flow::new([cancelled_child, exists("h1")]);
    let nested_cancelled = nested_cancel_flow
        .bind(&policy)
        .with_lease(&work)
        .invoke()
        .await?;
    assert_eq!(nested_cancelled.steps.len(), 2);
    assert_eq!(nested_cancelled.steps[0].flow_path, [0, 0]);
    assert_eq!(
        nested_cancelled.steps[0].cancellation,
        Some(yosoi_flow::FlowCancellationCause::Step)
    );
    assert_eq!(nested_cancelled.steps[1].flow_path, [1]);
    assert!(nested_cancelled.require_completed().is_err());

    // Root cancellation remains authoritative even when every policy level
    // chooses Continue.
    let root_cancel = CancellationToken::new();
    root_cancel.cancel();
    let root_cancel_flow = Flow::new([
        exists("h1").on_cancellation(Continuation::Continue),
        exists("h1"),
    ])
    .on_cancellation(Continuation::Continue);
    let root_cancelled = root_cancel_flow
        .bind(&policy)
        .with_lease(&work)
        .with_cancellation(&root_cancel)
        .invoke()
        .await?;
    assert_eq!(root_cancelled.continuation_defaults, policy.flow);
    assert_eq!(root_cancelled.steps.len(), 1);
    assert_eq!(
        root_cancelled.steps[0].cancellation,
        Some(yosoi_flow::FlowCancellationCause::Invocation)
    );
    assert_ne!(root_cancelled.terminal, FlowTermination::Completed);
    assert_eq!(
        root_cancelled
            .stop_reason
            .as_ref()
            .map(|reason| reason.cause),
        Some(yosoi_flow::FlowStopCause::Cancellation)
    );
    assert_eq!(root_cancelled.skipped_steps.len(), 1);
    assert_eq!(root_cancelled.skipped_steps[0].flow_path, [1]);
    assert_eq!(
        root_cancelled
            .stop_reason
            .as_ref()
            .and_then(|reason| reason.continuation),
        None
    );
    assert!(root_cancelled.require_completed().is_err());

    // Local cancellation did not release or invalidate the caller-owned Work.
    let observation = work.observe().await?;
    let expected_url = fixture.url("/");
    assert_eq!(observation.url.as_deref(), Some(expected_url.as_str()));
    work.release().await?;
    close(&session).await?;

    // A pre-cancelled local Step does not cancel managed Session acquisition;
    // later root actions still execute and managed cleanup receipts remain.
    let acquisition_local_cancel = CancellationToken::new();
    acquisition_local_cancel.cancel();
    let acquisition_root_cancel = CancellationToken::new();
    let managed_flow = Flow::new([
        Step::Navigate {
            url: fixture.url("/drop"),
        }
        .with_cancellation(&acquisition_local_cancel)
        .on_cancellation(Continuation::Continue),
        Step::Navigate {
            url: fixture.url("/"),
        },
        exists("h1"),
    ]);
    let managed = managed_flow
        .bind(&policy)
        .with_cancellation(&acquisition_root_cancel)
        .invoke()
        .await?;
    assert_eq!(managed.continuation_defaults, policy.flow);
    assert_eq!(managed.steps.len(), 3);
    assert_eq!(
        managed.steps[0].cancellation,
        Some(yosoi_flow::FlowCancellationCause::Step)
    );
    assert_eq!(
        managed.steps[2].receipt.status,
        yosoi_automation_record::OperationStatus::Observed
    );
    assert_eq!(managed.cleanup.len(), 2);
    assert!(
        managed
            .cleanup
            .iter()
            .all(|receipt| receipt.status == yosoi_automation_record::OperationStatus::Observed)
    );
    assert!(!acquisition_root_cancel.is_cancelled());
    assert!(managed.require_completed().is_err());

    assert!(!fixture.paths()?.iter().any(|path| path == "/drop"));
    fixture.shutdown().await?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn unknown_dispatch_stops_safely_under_continue_and_fences_the_borrowed_tab()
-> Result<(), Box<dyn Error>> {
    if !enabled() {
        return Ok(());
    }

    let mut fixture = GateFixture::start().await?;
    let mut policy = browser_policy()?;
    policy.flow.on_failure = Continuation::Continue;
    policy.flow.on_cancellation = Continuation::Continue;
    let session = session::new()
        .bind(&policy)
        .configure(SessionPolicy {
            maximum_tabs: 1,
            operation_timeout_ms: 5_000,
            ..SessionPolicy::default()
        })
        .acquire()
        .await?;
    let work = session.work().await?;
    work.navigate(&fixture.url("/")).await?;

    let local_cancel = CancellationToken::new();
    let flow = Flow::new([
        Step::Navigate {
            url: fixture.url("/hold"),
        }
        .with_cancellation(&local_cancel)
        .on_failure(Continuation::Continue),
        Step::Navigate {
            url: fixture.url("/write"),
        },
    ])
    .on_failure(Continuation::Continue)
    .on_cancellation(Continuation::Continue);
    let bound = flow.bind(&policy).with_lease(&work);
    let mut invocation = Box::pin(bound.invoke());
    tokio::select! {
        biased;
        result = &mut invocation => {
            return Err(io::Error::other(format!(
                "Flow finished before the held navigation reached the fixture: {result:?}"
            )).into());
        }
        held = timeout(Duration::from_secs(10), fixture.wait_for_hold_request()) => {
            held.map_err(|_| io::Error::other("held navigation was not dispatched"))??;
        }
    }
    local_cancel.cancel();
    let outcome = timeout(Duration::from_secs(10), &mut invocation)
        .await
        .map_err(|_| io::Error::other("unknown navigation did not stop"))??;

    drop(invocation);

    fixture.release_held_response();
    assert_eq!(outcome.continuation_defaults, policy.flow);
    assert_eq!(outcome.terminal, FlowTermination::Unknown);
    assert_eq!(outcome.steps.len(), 1);
    assert_eq!(
        outcome.steps[0].receipt.status,
        yosoi_automation_record::OperationStatus::Unknown
    );
    assert_eq!(
        outcome.steps[0].failure,
        Some(yosoi_flow::FlowFailureCause::UnknownOutcome)
    );
    assert_eq!(
        outcome.steps[0].cancellation,
        Some(yosoi_flow::FlowCancellationCause::Step)
    );
    assert_eq!(
        outcome.stop_reason.as_ref().map(|reason| reason.cause),
        Some(yosoi_flow::FlowStopCause::UnknownOutcome)
    );
    assert_eq!(
        outcome
            .stop_reason
            .as_ref()
            .and_then(|reason| reason.continuation),
        None
    );
    assert_eq!(outcome.skipped_steps.len(), 1);
    assert_eq!(outcome.skipped_steps[0].flow_path, [1]);

    let fenced_write = work.navigate(&fixture.url("/write")).await;
    assert!(fenced_write.is_err());
    work.release().await?;
    close(&session).await?;
    let paths = fixture.paths()?;
    assert!(paths.iter().any(|path| path == "/hold"));
    assert!(!paths.iter().any(|path| path == "/write"));
    fixture.shutdown().await?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Regression assertions intentionally fail on violated invariants; fixture owners and receipts remain live through explicit cleanup."
)]
async fn owning_session_cancel_hard_stops_continue_flow_and_records_unknown_fencing()
-> Result<(), Box<dyn Error>> {
    if !enabled() {
        return Ok(());
    }

    let mut fixture = GateFixture::start().await?;
    let mut policy = browser_policy()?;
    policy.flow.on_failure = Continuation::Continue;
    policy.flow.on_cancellation = Continuation::Continue;
    let session = session::new()
        .bind(&policy)
        .configure(SessionPolicy {
            maximum_tabs: 1,
            operation_timeout_ms: 5_000,
            ..SessionPolicy::default()
        })
        .acquire()
        .await?;
    let work = session.work().await?;
    work.navigate(&fixture.url("/")).await?;

    let flow = Flow::new([
        Step::Navigate {
            url: fixture.url("/hold"),
        }
        .on_failure(Continuation::Continue)
        .on_cancellation(Continuation::Continue),
        Step::Navigate {
            url: fixture.url("/write"),
        }
        .on_failure(Continuation::Continue)
        .on_cancellation(Continuation::Continue),
    ])
    .on_failure(Continuation::Continue)
    .on_cancellation(Continuation::Continue);
    let bound = flow.bind(&policy).with_lease(&work);
    let mut invocation = Box::pin(bound.invoke());
    tokio::select! {
        biased;
        result = &mut invocation => {
            return Err(io::Error::other(format!(
                "Flow finished before the held action reached the fixture: {result:?}"
            )).into());
        }
        held = timeout(Duration::from_secs(10), fixture.wait_for_hold_request()) => {
            held.map_err(|_| io::Error::other("held action was not dispatched"))??;
        }
    }
    session.cancel();
    let outcome = timeout(Duration::from_secs(10), &mut invocation)
        .await
        .map_err(|_| io::Error::other("Session cancellation did not stop the Flow"))??;

    drop(invocation);

    fixture.release_held_response();
    assert_eq!(outcome.continuation_defaults, policy.flow);
    assert_eq!(outcome.terminal, FlowTermination::Unknown);
    assert_eq!(outcome.steps.len(), 1);
    assert_eq!(
        outcome.steps[0].cancellation,
        Some(yosoi_flow::FlowCancellationCause::Session)
    );
    assert_eq!(
        outcome.steps[0].failure,
        Some(yosoi_flow::FlowFailureCause::UnknownOutcome)
    );
    assert_eq!(
        outcome.steps[0].receipt.status,
        yosoi_automation_record::OperationStatus::Unknown
    );
    assert_eq!(
        outcome.stop_reason.as_ref().map(|reason| reason.cause),
        Some(yosoi_flow::FlowStopCause::UnknownOutcome)
    );
    assert_eq!(outcome.skipped_steps.len(), 1);
    assert_eq!(outcome.skipped_steps[0].flow_path, [1]);
    assert_eq!(outcome.skipped_steps[0].scope, StopScope::Invocation);
    // The caller owns this borrowed Work's release and Session close.
    assert_eq!(
        outcome.cleanup,
        Vec::<yosoi_automation_record::OperationReceipt>::new()
    );

    assert!(work.navigate(&fixture.url("/write")).await.is_err());
    work.release().await?;
    close(&session).await?;
    let paths = fixture.paths()?;
    assert!(paths.iter().any(|path| path == "/hold"));
    assert!(!paths.iter().any(|path| path == "/write"));
    fixture.shutdown().await?;
    Ok(())
}
