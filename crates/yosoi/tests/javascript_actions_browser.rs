#![cfg(feature = "browser")]

//! Opt-in JavaScript action coverage against loopback-only pages and regular
//! Chrome Stable. Run through `spikes/browser-automation/run-container.sh`.

use std::{
    env,
    error::Error,
    fs, io,
    net::Ipv4Addr,
    path::{Path, PathBuf},
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use tokio::time::timeout;
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    sync::oneshot,
    task::JoinHandle,
};
use tokio_util::sync::CancellationToken;
use yosoi::{
    action,
    flow::{Condition, Flow, FlowTermination},
    policy::{Acquisition, BrowserMode, DocumentRequest, MaximumElapsed, Page, Policy},
    session::{self, SessionError, SessionPolicy},
};

#[path = "support/session_fixture.rs"]
mod session_fixture;

struct TemporaryDirectory(PathBuf);

impl TemporaryDirectory {
    fn new(label: &str) -> io::Result<Self> {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(io::Error::other)?
            .as_nanos();
        let path = env::temp_dir().join(format!(
            "yosoi-javascript-browser-{label}-{}-{nonce}",
            std::process::id()
        ));
        fs::create_dir(&path)?;
        Ok(Self(path))
    }

    fn path(&self) -> &Path {
        &self.0
    }
}

struct ModuleFixture {
    base_url: String,
    shutdown: Option<oneshot::Sender<()>>,
    task: Option<JoinHandle<io::Result<()>>>,
    hold_received: Option<oneshot::Receiver<()>>,
    release_hold: Option<oneshot::Sender<()>>,
}

impl ModuleFixture {
    async fn start(
        page: impl Into<String>,
        content_security_policy: Option<&str>,
    ) -> io::Result<Self> {
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).await?;
        let address = listener.local_addr()?;
        let (shutdown, mut shutdown_rx) = oneshot::channel();
        let (hold_signal, hold_received) = oneshot::channel();
        let (release_hold, release_hold_rx) = oneshot::channel();
        let base_url = format!("http://{address}");
        let page = page.into().replace("__YOSOI_FIXTURE_ORIGIN__", &base_url);
        let content_security_policy = content_security_policy.map(str::to_owned);
        let task_page = page.clone();
        let task_policy = content_security_policy.clone();
        let task = tokio::spawn(async move {
            let mut hold_signal = Some(hold_signal);
            let mut release_hold_rx = Some(release_hold_rx);
            loop {
                tokio::select! {
                    biased;
                    _ = &mut shutdown_rx => break,
                    accepted = listener.accept() => {
                        let (stream, _) = accepted?;
                        let _ = serve_module_fixture(
                            stream,
                            &task_page,
                            task_policy.as_deref(),
                            &mut hold_signal,
                            &mut release_hold_rx,
                        ).await;
                    }
                }
            }
            Ok(())
        });

        Ok(Self {
            base_url,
            shutdown: Some(shutdown),
            task: Some(task),
            hold_received: Some(hold_received),
            release_hold: Some(release_hold),
        })
    }

    fn url(&self, path: &str) -> String {
        format!("{}{path}", self.base_url)
    }

    async fn wait_for_hold_request(&mut self) -> io::Result<()> {
        self.hold_received
            .take()
            .ok_or_else(|| io::Error::other("hold notification was already consumed"))?
            .await
            .map_err(|_| io::Error::other("fixture stopped before the hold request"))
    }

    fn release_held_request(&mut self) {
        if let Some(release) = self.release_hold.take() {
            let _ = release.send(());
        }
    }

    async fn shutdown(mut self) -> io::Result<()> {
        self.release_held_request();
        if let Some(shutdown) = self.shutdown.take() {
            let _ = shutdown.send(());
        }
        if let Some(task) = self.task.take() {
            task.await
                .map_err(|error| io::Error::other(error.to_string()))??;
        }
        Ok(())
    }
}

impl Drop for ModuleFixture {
    fn drop(&mut self) {
        self.release_held_request();
        if let Some(shutdown) = self.shutdown.take() {
            let _ = shutdown.send(());
        }
    }
}

async fn serve_module_fixture(
    mut stream: TcpStream,
    page: &str,
    content_security_policy: Option<&str>,
    hold_signal: &mut Option<oneshot::Sender<()>>,
    release_hold: &mut Option<oneshot::Receiver<()>>,
) -> io::Result<()> {
    let mut request = Vec::with_capacity(2_048);
    loop {
        let mut buffer = [0_u8; 1_024];
        let read = stream.read(&mut buffer).await?;
        if read == 0 {
            return Ok(());
        }
        request.extend_from_slice(
            buffer
                .get(..read)
                .ok_or_else(|| io::Error::other("request length exceeded its buffer"))?,
        );
        if request.windows(4).any(|window| window == b"\r\n\r\n") {
            break;
        }
        if request.len() >= 8_192 {
            return Err(io::Error::other("request headers exceeded 8 KiB"));
        }
    }

    let request_text = String::from_utf8_lossy(&request);
    let request_line = request_text
        .lines()
        .next()
        .ok_or_else(|| io::Error::other("request had no request line"))?;
    let path = request_line
        .split_whitespace()
        .nth(1)
        .ok_or_else(|| io::Error::other("request had no path"))?
        .split('?')
        .next()
        .ok_or_else(|| io::Error::other("request path was empty"))?;

    if path == "/hold" {
        if let Some(signal) = hold_signal.take() {
            let _ = signal.send(());
        }
        if let Some(release) = release_hold.take() {
            let _ = release.await;
        }
        return write_fixture_response(&mut stream, "200 OK", "text/plain", "").await;
    }

    let (status, content_type, body) = match path {
        "/" => ("200 OK", "text/html; charset=utf-8", page),
        "/baseline.js" => (
            "200 OK",
            "text/javascript; charset=utf-8",
            "export const baseline = 17;",
        ),
        path if path.starts_with("/redirect/") => (
            "200 OK",
            "text/javascript; charset=utf-8",
            "export const result = { prior: 999, local: 'redirected' };",
        ),
        _ => ("404 Not Found", "text/plain", "not found"),
    };
    let policy_header = content_security_policy
        .map(|policy| format!("Content-Security-Policy: {policy}\r\n"))
        .unwrap_or_default();
    let response_head = format!(
        "HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\n{policy_header}Connection: close\r\n\r\n",
        body.len()
    );
    stream.write_all(response_head.as_bytes()).await?;
    stream.write_all(body.as_bytes()).await?;
    stream.shutdown().await
}

async fn write_fixture_response(
    stream: &mut TcpStream,
    status: &str,
    content_type: &str,
    body: &str,
) -> io::Result<()> {
    let response_head = format!(
        "HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    );
    stream.write_all(response_head.as_bytes()).await?;
    stream.write_all(body.as_bytes()).await?;
    stream.shutdown().await
}

impl Drop for TemporaryDirectory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn enabled(test_name: &str) -> bool {
    if env::var("YOSOI_BROWSER_TESTS").ok().as_deref() == Some("1") {
        true
    } else {
        eprintln!("SKIPPED {test_name}: set YOSOI_BROWSER_TESTS=1 to opt in");
        false
    }
}

fn browser_policy(maximum_elapsed_micros: u64) -> Result<Policy, Box<dyn Error>> {
    let mut policy = Policy::default();
    policy.page = Page::new(vec![
        Acquisition::Browser(BrowserMode::Headless).documents([DocumentRequest::RenderedDom]),
    ])?;
    policy.request.maximum_elapsed = MaximumElapsed::try_from(maximum_elapsed_micros)?;
    Ok(policy)
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
    reason = "Browser assertions report authorization and lease regressions."
)]
async fn file_actions_are_opt_in_and_a_borrowed_lease_cannot_elevate_javascript()
-> Result<(), Box<dyn Error>> {
    if !enabled("file_actions_are_opt_in_and_a_borrowed_lease_cannot_elevate_javascript") {
        return Ok(());
    }

    let fixture = session_fixture::SessionFixture::start().await?;
    let temporary = TemporaryDirectory::new("file")?;
    let path = temporary.path().join("effect.js");
    fs::write(
        &path,
        "const marker = document.createElement('span'); marker.id = 'file-effect'; document.body.append(marker); 'file-ran';",
    )?;
    let file_action = action::evaluate_file(&path)?;
    let policy = browser_policy(5_000_000)?;

    let managed_flow = Flow::new([
        action::navigate(fixture.url("/")),
        file_action.clone(),
        action::assert(Condition::Exists {
            selector: "#file-effect".to_owned(),
        })
        .into(),
    ]);
    let managed = managed_flow
        .bind(&policy)
        .allow_javascript()
        .invoke()
        .await?;

    let default_denied = Flow::new([action::navigate(fixture.url("/")), file_action.clone()])
        .bind(&policy)
        .invoke()
        .await?;

    let session = session::new().bind(&policy).acquire().await?;
    let work = session.work().await?;
    work.navigate(&fixture.url("/")).await?;
    let borrowed_denied = Flow::new([file_action])
        .with_lease(&work)
        .allow_javascript()
        .invoke()
        .await?;
    let marker_absent = Flow::new([action::assert(Condition::Exists {
        selector: "#file-effect".to_owned(),
    })
    .into()])
    .with_lease(&work)
    .invoke()
    .await?;

    let release = work.release().await;
    let session_close = close(&session).await;
    let fixture_close = fixture.shutdown().await;
    release?;
    session_close?;
    fixture_close?;

    assert_eq!(managed.terminal, FlowTermination::Completed);
    let file_receipt = managed
        .steps
        .get(1)
        .ok_or_else(|| io::Error::other("managed Flow omitted its file action receipt"))?;
    assert_eq!(
        file_receipt.receipt.result,
        Some(serde_json::Value::String("file-ran".to_owned()))
    );
    let managed_coordinates = managed.steps.first().and_then(|step| {
        step.receipt
            .observation
            .as_ref()
            .map(|observation| (observation.session_id.clone(), observation.tab_id.clone()))
    });
    assert!(
        managed.steps.iter().all(|step| {
            step.receipt
                .observation
                .as_ref()
                .is_some_and(|observation| {
                    managed_coordinates
                        .as_ref()
                        .is_some_and(|(session_id, tab_id)| {
                            &observation.session_id == session_id && &observation.tab_id == tab_id
                        })
                })
        }),
        "managed Flow actions did not share one observed Session and tab"
    );
    assert!(managed_coordinates.is_some());
    assert_eq!(default_denied.terminal, FlowTermination::Failed);
    assert_eq!(
        default_denied.steps.last().map(|step| step.receipt.status),
        Some(yosoi::automation_record::OperationStatus::Rejected)
    );
    assert_eq!(borrowed_denied.terminal, FlowTermination::Failed);
    assert_eq!(
        borrowed_denied
            .steps
            .first()
            .map(|step| step.receipt.status),
        Some(yosoi::automation_record::OperationStatus::Rejected)
    );
    assert_eq!(
        marker_absent.terminal,
        FlowTermination::Failed,
        "a borrowed JavaScript opt-in changed the page despite denied dispatch"
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Browser assertions report ECMAScript module semantics."
)]
async fn modules_support_live_bindings_imports_reexports_and_top_level_await_on_one_flow_tab()
-> Result<(), Box<dyn Error>> {
    if !enabled(
        "modules_support_live_bindings_imports_reexports_and_top_level_await_on_one_flow_tab",
    ) {
        return Ok(());
    }

    let fixture = session_fixture::SessionFixture::start().await?;
    let temporary = TemporaryDirectory::new("modules")?;
    let entry = temporary.path().join("entry.js");
    fs::write(
        temporary.path().join("counter.js"),
        "import { readCounter } from './peer.js';\nexport let count = 0;\nexport function increment() { count += 1; return count; }\nexport function peerValue() { return readCounter(); }\n",
    )?;
    fs::write(
        temporary.path().join("peer.js"),
        "import { count } from './counter.js';\nexport function readCounter() { return count; }\n",
    )?;
    fs::write(
        temporary.path().join("values.js"),
        "export const answer = 42;\nexport default { label: 'dynamic' };\n",
    )?;
    fs::write(
        temporary.path().join("delayed.js"),
        "export const answer = 84;\n",
    )?;
    fs::write(
        temporary.path().join("barrel.js"),
        "export { answer } from './values.js';\n",
    )?;
    fs::write(
        &entry,
        "import { count, increment, peerValue } from './counter.js';\nimport { answer } from './barrel.js';\nconst dynamic = await import('./values.js');\nconst after = increment();\nawait Promise.resolve();\ndocument.body.dataset.moduleEffect = `${count}:${peerValue()}:${dynamic.answer}`;\nglobalThis.__delayedModule = () => import('./delayed.js');\nexport const result = { count, peer: peerValue(), answer, dynamicAnswer: dynamic.answer, dynamicLabel: dynamic.default.label, after };\nexport { answer as reexported } from './barrel.js';\nexport default result;\nexport function shouldNotRun() { document.body.dataset.exportFunctionCalled = 'yes'; return 'called'; }\nexport function then(resolve) { document.body.dataset.thenExportCalled = 'yes'; resolve('then-assimilated'); }\n",
    )?;
    let policy = browser_policy(5_000_000)?;
    let child = Flow::new([action::run_module(&entry)?]);
    let flow = Flow::new([
        child.into(),
        action::evaluate("document.body.dataset.moduleEffect"),
        action::evaluate("globalThis.__delayedModule().then(module => module.answer)"),
        action::run_module_with_export(&entry, "result")?,
        action::run_module_with_export(&entry, "default")?,
        action::run_module_with_export(&entry, "reexported")?,
    ]);
    let outcome = flow.bind(&policy).allow_javascript().invoke().await?;

    let invalid = temporary.path().join("invalid-exports.js");
    fs::write(
        &invalid,
        "export const undefinedValue = undefined;\nexport const nonFiniteValue = NaN;\nexport const nestedFunction = { callback: () => 'called' };\n",
    )?;
    let invalid_session = session::new()
        .bind(&policy)
        .configure(SessionPolicy {
            allow_arbitrary_js: true,
            ..SessionPolicy::default()
        })
        .acquire()
        .await?;
    let invalid_work = invalid_session.work().await?;
    invalid_work.navigate(&fixture.url("/")).await?;
    let no_then_invocation = Flow::new([
        action::run_module(&entry)?,
        action::assert(Condition::Exists {
            selector: "body[data-then-export-called='yes']".to_owned(),
        })
        .into(),
    ])
    .with_lease(&invalid_work)
    .invoke()
    .await?;
    let mut invalid_outcomes = Vec::new();
    for export in [
        "shouldNotRun",
        "undefinedValue",
        "nonFiniteValue",
        "nestedFunction",
    ] {
        let selected = if export == "shouldNotRun" {
            &entry
        } else {
            &invalid
        };
        let invocation = Flow::new([action::run_module_with_export(selected, export)?]);
        invalid_outcomes.push(invocation.with_lease(&invalid_work).invoke().await?);
    }
    let function_not_called = Flow::new([action::assert(Condition::Exists {
        selector: "body[data-export-function-called='yes']".to_owned(),
    })
    .into()])
    .with_lease(&invalid_work)
    .invoke()
    .await?;
    let invalid_release = invalid_work.release().await;
    let invalid_close = close(&invalid_session).await;

    let throwing = temporary.path().join("throwing.js");
    fs::write(
        &throwing,
        "document.body.dataset.beforeModuleThrow = 'mutated'; throw new Error('module-marker-exception');",
    )?;
    let exception = Flow::new([
        action::navigate(fixture.url("/")),
        action::run_module(&throwing)?,
    ])
    .bind(&policy)
    .allow_javascript()
    .invoke()
    .await?;

    fixture.shutdown().await?;
    invalid_release?;
    invalid_close?;

    assert_eq!(outcome.terminal, FlowTermination::Completed);
    assert_eq!(
        outcome.steps.first().map(|step| step.flow_path.as_slice()),
        Some(&[0, 0][..]),
        "JavaScript child Flow path was not preserved"
    );
    assert_eq!(
        outcome
            .steps
            .first()
            .map(|step| step.receipt.result.clone()),
        Some(Some(serde_json::Value::Null)),
        "entry effects without export selection should return JSON null"
    );
    assert_eq!(
        outcome
            .steps
            .get(1)
            .and_then(|step| step.receipt.result.clone()),
        Some(serde_json::Value::String("1:1:42".to_owned()))
    );
    assert_eq!(
        outcome
            .steps
            .get(2)
            .and_then(|step| step.receipt.result.clone()),
        Some(serde_json::json!(84))
    );
    assert_eq!(
        outcome
            .steps
            .get(3)
            .and_then(|step| step.receipt.result.clone()),
        Some(serde_json::json!({
            "count": 1,
            "peer": 1,
            "answer": 42,
            "dynamicAnswer": 42,
            "dynamicLabel": "dynamic",
            "after": 1
        }))
    );
    assert_eq!(
        outcome
            .steps
            .get(4)
            .and_then(|step| step.receipt.result.clone()),
        Some(serde_json::json!({
            "count": 1,
            "peer": 1,
            "answer": 42,
            "dynamicAnswer": 42,
            "dynamicLabel": "dynamic",
            "after": 1
        }))
    );
    assert_eq!(
        outcome
            .steps
            .get(5)
            .and_then(|step| step.receipt.result.clone()),
        Some(serde_json::json!(42))
    );
    let session_and_tab = outcome.steps.first().and_then(|step| {
        step.receipt
            .observation
            .as_ref()
            .map(|observation| (observation.session_id.clone(), observation.tab_id.clone()))
    });
    assert!(session_and_tab.is_some());
    assert!(
        outcome.steps.iter().all(|step| {
            step.receipt
                .observation
                .as_ref()
                .is_some_and(|observation| {
                    session_and_tab
                        .as_ref()
                        .is_some_and(|(session_id, tab_id)| {
                            &observation.session_id == session_id && &observation.tab_id == tab_id
                        })
                })
        }),
        "nested module actions left their caller's Session or tab"
    );
    assert_eq!(invalid_outcomes.len(), 4);
    assert_eq!(
        no_then_invocation.terminal,
        FlowTermination::Failed,
        "an unselected `then` export was invoked during module evaluation"
    );
    assert_eq!(
        no_then_invocation
            .steps
            .first()
            .and_then(|step| step.receipt.result.clone()),
        Some(serde_json::Value::Null)
    );
    assert!(
        invalid_outcomes.iter().all(|outcome| {
            outcome.terminal == FlowTermination::Unknown
                && outcome.steps.first().is_some_and(|step| {
                    step.receipt.status == yosoi::automation_record::OperationStatus::Unknown
                        && step.receipt.result.is_none()
                        && step
                            .receipt
                            .error
                            .as_ref()
                            .is_some_and(|error| !error.is_empty())
                })
        }),
        "non-JSON exports were silently converted or observed"
    );
    assert_eq!(
        function_not_called.terminal,
        FlowTermination::Failed,
        "selecting an exported function invoked it"
    );
    assert_eq!(exception.terminal, FlowTermination::Unknown);
    assert!(
        exception
            .steps
            .last()
            .and_then(|step| step.receipt.error.as_deref())
            .is_some_and(|error| error.contains("module-marker-exception"))
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Browser assertions report interaction with an existing module graph."
)]
async fn module_action_adds_a_second_import_map_after_a_page_module_has_run()
-> Result<(), Box<dyn Error>> {
    if !enabled("module_action_adds_a_second_import_map_after_a_page_module_has_run") {
        return Ok(());
    }

    let page = "<!doctype html><html><head><script type=\"importmap\">{\"imports\":{\"baseline\":\"/baseline.js\",\"blob:__YOSOI_FIXTURE_ORIGIN__/\":\"/redirect/\"}}</script></head><body><script type=\"module\">import { baseline } from 'baseline'; globalThis.__existingModuleValue = baseline; const marker = document.createElement('span'); marker.id = 'existing-module-ready'; document.body.append(marker);</script></body></html>";
    let fixture = ModuleFixture::start(page, None).await?;
    let temporary = TemporaryDirectory::new("existing-import-map")?;
    let entry = temporary.path().join("entry.js");
    fs::write(
        &entry,
        "import { localValue } from './local.js';\nexport const result = { prior: globalThis.__existingModuleValue, local: localValue };\n",
    )?;
    fs::write(
        temporary.path().join("local.js"),
        "export const localValue = 'second-map';\n",
    )?;
    let policy = browser_policy(5_000_000)?;
    let flow = Flow::new([
        action::navigate(fixture.url("/")),
        action::wait_until(
            Condition::Exists {
                selector: "#existing-module-ready".to_owned(),
            },
            5_000,
        ),
        action::run_module_with_export(&entry, "result")?,
        action::evaluate("globalThis.__existingModuleValue"),
    ]);
    let outcome = flow.bind(&policy).allow_javascript().invoke().await?;
    fixture.shutdown().await?;

    assert_eq!(outcome.terminal, FlowTermination::Completed);
    assert_eq!(
        outcome
            .steps
            .get(2)
            .and_then(|step| step.receipt.result.clone()),
        Some(serde_json::json!({"prior": 17, "local": "second-map"}))
    );
    assert_eq!(
        outcome
            .steps
            .get(3)
            .and_then(|step| step.receipt.result.clone()),
        Some(serde_json::json!(17))
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Browser assertions report cancellation and CSP outcome certainty."
)]
async fn cancellation_after_module_mutation_and_csp_denial_keep_unknown_receipts()
-> Result<(), Box<dyn Error>> {
    if !enabled("cancellation_after_module_mutation_and_csp_denial_keep_unknown_receipts") {
        return Ok(());
    }

    let mut fixture = ModuleFixture::start(
        "<!doctype html><html><body><main><h1>Controlled module page</h1></main></body></html>",
        None,
    )
    .await?;
    let temporary = TemporaryDirectory::new("cancel")?;
    let pending = temporary.path().join("pending.js");
    let hold_url = serde_json::to_string(&fixture.url("/hold"))?;
    fs::write(
        &pending,
        format!(
            "import './ready.js'; document.body.dataset.mutatedBeforeStop = 'yes'; await fetch({hold_url}); export const result = 'finished';\n"
        ),
    )?;
    fs::write(
        temporary.path().join("ready.js"),
        "export const ready = true;\n",
    )?;
    // Browser process startup is independent of the cancellation wait below.
    let policy = browser_policy(20_000_000)?;
    let session = session::new()
        .bind(&policy)
        .configure(SessionPolicy {
            allow_arbitrary_js: true,
            ..SessionPolicy::default()
        })
        .acquire()
        .await?;
    let work = session.work().await?;
    work.navigate(&fixture.url("/")).await?;
    let flow = Flow::new([action::run_module_with_export(&pending, "result")?]);
    let cancellation = CancellationToken::new();
    let cancelled = {
        let bound = flow.with_lease(&work).with_cancellation(&cancellation);
        let mut invocation = Box::pin(bound.invoke());
        let received = tokio::select! {
            result = &mut invocation => {
                let outcome = result?;
                return Err(io::Error::other(format!(
                    "module finished before its external wait was cancelled: {:?}",
                    outcome.terminal
                )).into());
            }
            result = timeout(Duration::from_secs(5), fixture.wait_for_hold_request()) => {
                result.map_err(|_| io::Error::other("module did not reach the held request"))??;
                Ok::<(), Box<dyn Error>>(())
            }
        };
        received?;
        cancellation.cancel();
        fixture.release_held_request();
        let outcome = timeout(Duration::from_secs(5), &mut invocation)
            .await
            .map_err(|_| {
                io::Error::other("cancelled module did not settle within five seconds")
            })??;
        drop(invocation);
        outcome
    };
    let fenced_after_cancel = work.evaluate("'must-not-run'").await;
    let close_result = close(&session).await;
    let release_result = work.release().await;
    let fixture_result = fixture.shutdown().await;
    close_result?;
    release_result?;
    fixture_result?;

    assert_eq!(cancelled.terminal, FlowTermination::Unknown);
    assert_eq!(
        cancelled.steps.first().map(|step| step.receipt.status),
        Some(yosoi::automation_record::OperationStatus::Unknown)
    );
    assert!(matches!(fenced_after_cancel, Err(SessionError::Closed)));

    let csp_fixture = ModuleFixture::start(
        "<!doctype html><html><body><main><h1>CSP module page</h1></main></body></html>",
        Some("default-src 'self'; script-src 'self'"),
    )
    .await?;
    let csp_module = temporary.path().join("csp.js");
    fs::write(&csp_module, "export const result = 42;\n")?;
    let csp_outcome = Flow::new([
        action::navigate(csp_fixture.url("/")),
        action::run_module_with_export(&csp_module, "result")?,
    ])
    .bind(&policy)
    .allow_javascript()
    .invoke()
    .await?;
    csp_fixture.shutdown().await?;

    assert_eq!(csp_outcome.terminal, FlowTermination::Unknown);
    let csp_receipt = csp_outcome
        .steps
        .last()
        .ok_or_else(|| io::Error::other("CSP failure omitted its module receipt"))?;
    assert_eq!(
        csp_receipt.receipt.status,
        yosoi::automation_record::OperationStatus::Unknown
    );
    assert!(csp_receipt.receipt.kind.contains("evaluate_module"));
    assert!(
        csp_receipt
            .receipt
            .error
            .as_deref()
            .is_some_and(|error| !error.is_empty())
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Browser assertions report result caps and unknown dispatch outcomes."
)]
async fn module_result_caps_and_timeout_after_mutation_remain_unknown() -> Result<(), Box<dyn Error>>
{
    if !enabled("module_result_caps_and_timeout_after_mutation_remain_unknown") {
        return Ok(());
    }

    let fixture = session_fixture::SessionFixture::start().await?;
    let temporary = TemporaryDirectory::new("bounds")?;
    let large = temporary.path().join("large.js");
    let small = temporary.path().join("small.js");
    let pending = temporary.path().join("pending.js");
    fs::write(&large, "export const result = 'x'.repeat(4096);\n")?;
    fs::write(&small, "export const result = 42;\n")?;
    fs::write(
        &pending,
        "document.body.dataset.mutatedBeforeAwait = 'yes'; await new Promise(() => {}); export const result = 'never';\n",
    )?;
    let policy = browser_policy(5_000_000)?;
    let small_session = session::new()
        .bind(&policy)
        .configure(SessionPolicy {
            allow_arbitrary_js: true,
            maximum_input_bytes: 128,
            ..SessionPolicy::default()
        })
        .acquire()
        .await?;
    let small_work = small_session.work().await?;
    small_work.navigate(&fixture.url("/")).await?;
    let small_outcome = Flow::new([action::run_module_with_export(&small, "result")?])
        .with_lease(&small_work)
        .invoke()
        .await?;
    small_work.release().await?;
    close(&small_session).await?;

    let bounded = session::new()
        .bind(&policy)
        .configure(SessionPolicy {
            allow_arbitrary_js: true,
            maximum_result_bytes: 64,
            ..SessionPolicy::default()
        })
        .acquire()
        .await?;
    let bounded_work = bounded.work().await?;
    bounded_work.navigate(&fixture.url("/")).await?;
    let capped = Flow::new([action::run_module_with_export(&large, "result")?])
        .with_lease(&bounded_work)
        .invoke()
        .await?;
    bounded_work.release().await?;
    close(&bounded).await?;

    let timed = session::new()
        .bind(&policy)
        .configure(SessionPolicy {
            allow_arbitrary_js: true,
            ..SessionPolicy::default()
        })
        .acquire()
        .await?;
    let timed_work = timed.work().await?;
    timed_work.navigate(&fixture.url("/")).await?;
    let pending_flow = Flow::new([action::run_module(&pending)?.timeout(300)]);
    let timed_result = timeout(
        Duration::from_secs(5),
        pending_flow.with_lease(&timed_work).invoke(),
    )
    .await
    .map_err(|_| io::Error::other("pending module outlasted the outer test guard"))??;
    let fenced = timed_work.evaluate("'must-not-run'").await;
    let timed_close = close(&timed).await;
    let release = timed_work.release().await;
    let fixture_close = fixture.shutdown().await;
    timed_close?;
    release?;
    fixture_close?;

    assert_eq!(capped.terminal, FlowTermination::Unknown);
    assert!(
        capped
            .steps
            .last()
            .and_then(|step| step.receipt.error.as_deref())
            .is_some_and(|error| error.contains("64"))
    );
    assert_eq!(small_outcome.terminal, FlowTermination::Completed);
    assert_eq!(
        small_outcome
            .steps
            .first()
            .and_then(|step| step.receipt.result.clone()),
        Some(serde_json::json!(42))
    );
    assert_eq!(timed_result.terminal, FlowTermination::Unknown);
    assert_eq!(
        timed_result.steps.first().map(|step| step.receipt.status),
        Some(yosoi::automation_record::OperationStatus::Unknown)
    );
    assert!(matches!(fenced, Err(SessionError::Closed)));
    Ok(())
}
