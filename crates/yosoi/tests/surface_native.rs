#![cfg(feature = "browser")]
//! Native Surface ownership, input and shared-pool scheduling against loopback only.
use base64::{Engine as _, engine::general_purpose::STANDARD};
use flate2::{Compression, write::GzEncoder};
use futures::FutureExt;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    env,
    error::Error,
    io::{self, Write as _},
    sync::Arc,
    time::Duration,
};
#[cfg(feature = "cli")]
use std::{
    io::{BufRead, BufReader},
    process::{Child, ChildStdin, ChildStdout, Command, ExitStatus, Stdio},
    sync::Mutex,
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
    sync::{Notify, oneshot},
    task::{JoinHandle, JoinSet},
    time::timeout,
};
use yosoi::{
    Archive,
    automation_record::OperationStatus,
    browser::surface::consume_session as consume_browser_session,
    policy::{Acquisition, BrowserMode, DocumentRequest, Page, Policy},
    session::{self, ActionKind, ExecutionPool, SessionPolicy},
    surface::{
        self, NetworkEventKind, NetworkObservationPolicy, NetworkPayload, NetworkPayloadKind,
        NetworkPayloadState, SurfaceConnection, SurfacePolicy, browser::BrowserSurface,
    },
};

struct Fixture {
    base: String,
    stop: oneshot::Sender<()>,
    task: JoinHandle<()>,
}
impl Fixture {
    async fn start() -> Result<Self, Box<dyn Error>> {
        let listener = TcpListener::bind("127.0.0.1:0").await?;
        let base = format!("http://{}", listener.local_addr()?);
        let (stop, mut stopped) = oneshot::channel();
        let release = Arc::new(Notify::new());
        let task = tokio::spawn(async move {
            let mut clients = JoinSet::new();
            loop {
                tokio::select! {
                    _ = &mut stopped => break,
                    accepted = listener.accept() => {
                        let Ok((mut stream, _)) = accepted else { break; };
                        let release = Arc::clone(&release);
                        clients.spawn(async move {
                            let mut bytes = [0; 8192];
                            let Ok(count) = stream.read(&mut bytes).await else { return; };
                            let request = String::from_utf8_lossy(bytes.get(..count).unwrap_or_default());
                            let path = request.split_whitespace().nth(1).unwrap_or("/");
                            let body = match path {
                                "/await" => { release.notified().await; "Released A".to_string() },
                                "/release" => { release.notify_one(); "released".to_string() },
                                "/large" => format!("<!doctype html><title>{}</title><h1>Large title destination</h1>", "x".repeat(2000)),
                                "/a" => r#"<!doctype html><h1>Tab A</h1><p>Waiting A</p><script>fetch('/await').then(r=>r.text()).then(text=>document.querySelector('p').textContent=text)</script>"#.to_string(),
                                _ => r#"<!doctype html><h1>Tab B</h1><input aria-label="Message" value="existing content"><button onclick="this.nextElementSibling.textContent='Clicked B';fetch('/release')">Release A</button><p>Ready B</p><input aria-label="Keyboard" onkeydown="if(event.key==='Enter')this.nextElementSibling.textContent='Enter observed'"><p>Waiting for key</p><input aria-label="Steal source" value="original" onkeydown="if(event.key==='a'&&(event.ctrlKey||event.metaKey))this.nextElementSibling.focus()"><input aria-label="Steal destination" value="untouched" oninput="this.nextElementSibling.textContent='Foreign input changed'"><p>Foreign input untouched</p><a href="/large">Large document</a>"#.to_string(),
                            };
                            let response = format!("HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len());
                            let _ = stream.write_all(response.as_bytes()).await;
                        });
                    }
                    Some(_) = clients.join_next(), if !clients.is_empty() => {}
                }
            }
            clients.abort_all();
            while clients.join_next().await.is_some() {}
        });
        Ok(Self { base, stop, task })
    }
    async fn close(self) {
        let _ = self.stop.send(());
        let _ = self.task.await;
    }
}

struct NetworkFixture {
    base: String,
    slow_started: Arc<Notify>,
    stop: oneshot::Sender<()>,
    task: JoinHandle<()>,
}

impl NetworkFixture {
    async fn start() -> Result<Self, Box<dyn Error>> {
        let listener = TcpListener::bind("127.0.0.1:0").await?;
        let base = format!("http://{}", listener.local_addr()?);
        let (stop, mut stopped) = oneshot::channel();
        let slow_started = Arc::new(Notify::new());
        let release_slow = Arc::new(Notify::new());
        let task_slow = Arc::clone(&slow_started);
        let task_release = Arc::clone(&release_slow);
        let task = tokio::spawn(async move {
            let mut clients = JoinSet::new();
            loop {
                tokio::select! {
                    _ = &mut stopped => break,
                    accepted = listener.accept() => {
                        let Ok((mut stream, _)) = accepted else { break; };
                        let slow_started = Arc::clone(&task_slow);
                        let release_slow = Arc::clone(&task_release);
                        clients.spawn(async move {
                            let mut bytes = [0; 8192];
                            let Ok(count) = stream.read(&mut bytes).await else { return; };
                            let request = String::from_utf8_lossy(bytes.get(..count).unwrap_or_default());
                            let path = request.split_whitespace().nth(1).unwrap_or("/");
                            match path.split('?').next().unwrap_or("/") {
                                "/network" => {
                                    let body = r#"<!doctype html><main><button aria-label="Start network requests">Start network requests</button><button aria-label="Release delayed response">Release delayed response</button><button aria-label="Start request after capture cancellation">Start request after capture cancellation</button><p id="state">ready</p><script>
const state=document.getElementById('state');
document.querySelectorAll('button')[0].addEventListener('click',()=>{state.textContent='network requests started';const slow=fetch('/slow').then(r=>r.json());const tasks=[fetch('/api?token=secret').then(r=>r.json()),fetch('/redirect').then(r=>r.json()),fetch('/fail').catch(()=>null),fetch('/gzip-json').then(r=>r.json()),fetch('/binary').then(r=>r.arrayBuffer()),fetch('/html').then(r=>r.text()),fetch('/legacy-html').then(r=>r.text()),fetch('/sniff-html').then(r=>r.text()),fetch('/misleading-png').then(r=>r.arrayBuffer())];Promise.all(tasks).then(()=>slow).then(()=>{state.textContent='network complete'}).catch(()=>{state.textContent='network requests failed'})});
document.querySelectorAll('button')[1].addEventListener('click',()=>fetch('/release'));
document.querySelectorAll('button')[2].addEventListener('click',()=>fetch('/api?after-cancel=1').then(()=>{state.textContent='post-cancel request complete'}));
</script></main>"#;
                                    let _ = write_response(&mut stream, "200 OK", "text/html; charset=utf-8", &[], body.as_bytes()).await;
                                }
                                "/cli-network" => {
                                    let body = r#"<!doctype html><main><h1>CLI network</h1><script>fetch('/api?cli=1').then(()=>{document.title='request-complete'})</script></main>"#;
                                    let _ = write_response(&mut stream, "200 OK", "text/html; charset=utf-8", &[], body.as_bytes()).await;
                                }
                                "/bomb-page" => {
                                    let body = r#"<!doctype html><main><button aria-label="Start compressed body">Start compressed body</button><p id="state">ready</p><script>document.querySelector('button').addEventListener('click',()=>fetch('/gzip-bomb').then(r=>r.arrayBuffer()).then(()=>{document.getElementById('state').textContent='compressed response complete'}))</script></main>"#;
                                    let _ = write_response(&mut stream, "200 OK", "text/html; charset=utf-8", &[], body.as_bytes()).await;
                                }
                                "/api" | "/redirected" => {
                                    let body: &[u8] = if path.starts_with("/redirected") { br#"{"redirected":true}"# } else { br#"{"api":true}"# };
                                    let headers = [("X-Public", "kept"), ("Set-Cookie", "secret=hidden")];
                                    let _ = write_response(&mut stream, "200 OK", "application/json; charset=utf-8", &headers, body).await;
                                }
                                "/redirect" => {
                                    let _ = write_response(&mut stream, "302 Found", "text/plain", &[("Location", "/redirected")], b"").await;
                                }
                                "/fail" => {}
                                "/slow" => {
                                    slow_started.notify_one();
                                    release_slow.notified().await;
                                    let _ = write_response(&mut stream, "200 OK", "application/json; charset=utf-8", &[], br#"{"slow":true}"#).await;
                                }
                                "/release" => {
                                    release_slow.notify_one();
                                    let _ = write_response(&mut stream, "200 OK", "text/plain; charset=utf-8", &[], b"released").await;
                                }
                                "/gzip-json" => {
                                    let mut encoder = GzEncoder::new(Vec::new(), Compression::fast());
                                    if encoder.write_all(br#"{"compressed":true}"#).is_err() { return; }
                                    let Ok(body) = encoder.finish() else { return; };
                                    let _ = write_response(&mut stream, "200 OK", "application/json; charset=utf-8", &[("Content-Encoding", "gzip")], &body).await;
                                }
                                "/gzip-bomb" => {
                                    let decoded = vec![b'x'; 2 * 1024 * 1024];
                                    let mut encoder = GzEncoder::new(Vec::new(), Compression::fast());
                                    if encoder.write_all(&decoded).is_err() { return; }
                                    let Ok(body) = encoder.finish() else { return; };
                                    let _ = write_response(&mut stream, "200 OK", "text/plain; charset=utf-8", &[("Content-Encoding", "gzip")], &body).await;
                                }
                                "/binary" => {
                                    let _ = write_response(&mut stream, "200 OK", "application/octet-stream", &[], b"\0\xff\x10opaque\0bytes").await;
                                }
                                "/html" => {
                                    let _ = write_response(&mut stream, "200 OK", "text/html; charset=utf-8", &[], b"<!doctype html><main><h1>network body</h1></main>").await;
                                }
                                "/legacy-html" => {
                                    let _ = write_response(&mut stream, "200 OK", "text/html; charset=windows-1252", &[], b"<!doctype html><main><p>caf\xe9</p></main>").await;
                                }
                                "/sniff-html" => {
                                    let _ = write_response_without_content_type(&mut stream, "200 OK", &[], b"<!doctype html><main><p>sniffed HTML</p></main>").await;
                                }
                                "/misleading-png" => {
                                    let body = STANDARD.decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p3sAAAAASUVORK5CYII=").unwrap_or_default();
                                    let _ = write_response(&mut stream, "200 OK", "application/octet-stream", &[], &body).await;
                                }
                                _ => {
                                    let _ = write_response(&mut stream, "404 Not Found", "text/plain; charset=utf-8", &[], b"missing").await;
                                }
                            }
                        });
                    }
                    Some(_) = clients.join_next(), if !clients.is_empty() => {}
                }
            }
            clients.abort_all();
            while clients.join_next().await.is_some() {}
        });
        Ok(Self {
            base,
            slow_started,
            stop,
            task,
        })
    }

    async fn close(self) {
        let _ = self.stop.send(());
        let _ = self.task.await;
    }
}

async fn write_response(
    stream: &mut tokio::net::TcpStream,
    status: &str,
    content_type: &str,
    headers: &[(&str, &str)],
    body: &[u8],
) -> io::Result<()> {
    let mut response = format!(
        "HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\nConnection: close\r\n",
        body.len()
    );
    for (name, value) in headers {
        response.push_str(name);
        response.push_str(": ");
        response.push_str(value);
        response.push_str("\r\n");
    }
    response.push_str("\r\n");
    stream.write_all(response.as_bytes()).await?;
    stream.write_all(body).await?;
    Ok(())
}

async fn write_response_without_content_type(
    stream: &mut tokio::net::TcpStream,
    status: &str,
    headers: &[(&str, &str)],
    body: &[u8],
) -> io::Result<()> {
    let mut response = format!(
        "HTTP/1.1 {status}\r\nContent-Length: {}\r\nConnection: close\r\n",
        body.len()
    );
    for (name, value) in headers {
        response.push_str(name);
        response.push_str(": ");
        response.push_str(value);
        response.push_str("\r\n");
    }
    response.push_str("\r\n");
    stream.write_all(response.as_bytes()).await?;
    stream.write_all(body).await?;
    Ok(())
}

fn enabled() -> bool {
    let enabled = env::var("YOSOI_BROWSER_TESTS").as_deref() == Ok("1");
    if !enabled {
        eprintln!("SKIPPED native Surface browser proof; set YOSOI_BROWSER_TESTS=1");
    }
    enabled
}

async fn reference(surface: &mut BrowserSurface, query: &str) -> Result<Value, Box<dyn Error>> {
    let result = surface.execute(json!({"op":"find","query":query})).await?;
    let entry = result
        .get("entries")
        .and_then(Value::as_array)
        .and_then(|items| items.first())
        .ok_or_else(|| io::Error::other("fixture target not found"))?;
    let mut reference = entry
        .get("reference")
        .cloned()
        .ok_or_else(|| io::Error::other("missing reference"))?;
    if entry.get("kind").and_then(Value::as_str) == Some("text") {
        reference = surface
            .execute(json!({"op":"parent","reference":reference}))
            .await?;
    }
    Ok(reference)
}

async fn hot(surface: &mut BrowserSurface) -> Result<(), Box<dyn Error>> {
    surface.execute(json!({"op":"attach"})).await?;
    let status = surface.execute(json!({"op":"status"})).await?;
    let root = status
        .get("root")
        .cloned()
        .ok_or_else(|| io::Error::other("status root missing"))?;
    surface
        .execute(json!({"op":"focus","reference":root}))
        .await?;
    surface.execute(json!({"op":"hot"})).await?;
    Ok(())
}

#[cfg(feature = "cli")]
type CliProofError = Box<dyn Error + Send + Sync>;

#[cfg(feature = "cli")]
#[derive(Default)]
struct CliDiagnostics {
    current_operation: Option<String>,
    last_reply: Option<Value>,
}

#[cfg(feature = "cli")]
fn cli_exchange(
    input: &mut ChildStdin,
    output: &mut BufReader<ChildStdout>,
    command: Value,
    diagnostics: &Mutex<CliDiagnostics>,
) -> Result<Value, CliProofError> {
    let operation_id = command
        .get("id")
        .and_then(Value::as_str)
        .unwrap_or("unknown")
        .to_owned();
    diagnostics
        .lock()
        .map_err(|_| io::Error::other("CLI diagnostic lock was poisoned"))?
        .current_operation = Some(operation_id);
    serde_json::to_writer(&mut *input, &command)?;
    input.write_all(b"\n")?;
    input.flush()?;
    let mut line = String::new();
    if output.read_line(&mut line)? == 0 {
        return Err(io::Error::other("native Surface CLI closed before replying").into());
    }
    let reply: Value = serde_json::from_str(&line)?;
    diagnostics
        .lock()
        .map_err(|_| io::Error::other("CLI diagnostic lock was poisoned"))?
        .last_reply = Some(reply.clone());
    if reply.get("ok").and_then(Value::as_bool) != Some(true) {
        return Err(io::Error::other(format!("native Surface CLI command failed: {reply}")).into());
    }
    Ok(reply.get("result").cloned().unwrap_or(Value::Null))
}

#[cfg(feature = "cli")]
fn cli_network_window(
    input: &mut ChildStdin,
    output: &mut BufReader<ChildStdout>,
    diagnostics: &Mutex<CliDiagnostics>,
) -> Result<Value, CliProofError> {
    let observation = cli_exchange(
        input,
        output,
        json!({"id":"observe-network","op":"observe","representation":"network","budget":16384}),
        diagnostics,
    )?;
    let root = observation
        .get("root")
        .cloned()
        .ok_or_else(|| io::Error::other("CLI network observation omitted its root"))?;
    let inspected = cli_exchange(
        input,
        output,
        json!({
            "id":"inspect-network",
            "op":"read_view",
            "representation":"network",
            "budget":16384,
            "request":{
                "operation":{"kind":"inspect","reference":root},
                "budget":{"bytes":16000,"items":1}
            }
        }),
        diagnostics,
    )?;
    let content = inspected
        .pointer("/data/content")
        .and_then(Value::as_str)
        .ok_or_else(|| io::Error::other("CLI network inspection omitted window JSON"))?;
    Ok(serde_json::from_str(content)?)
}

#[cfg(feature = "cli")]
fn cli_native_reference(
    input: &mut ChildStdin,
    output: &mut BufReader<ChildStdout>,
    query: &str,
    id: &str,
    diagnostics: &Mutex<CliDiagnostics>,
) -> Result<Value, CliProofError> {
    cli_exchange(
        input,
        output,
        json!({"id":format!("refresh-{id}"),"op":"refresh"}),
        diagnostics,
    )?;
    let page = cli_exchange(
        input,
        output,
        json!({"id":format!("find-{id}"),"op":"find","query":query}),
        diagnostics,
    )?;
    let entry = page
        .get("entries")
        .and_then(Value::as_array)
        .and_then(|entries| entries.first())
        .ok_or_else(|| io::Error::other("CLI navigation target was not found"))?;
    let reference = entry
        .get("reference")
        .cloned()
        .ok_or_else(|| io::Error::other("CLI navigation target omitted its reference"))?;
    if entry.get("kind").and_then(Value::as_str) == Some("text") {
        cli_exchange(
            input,
            output,
            json!({"id":format!("parent-{id}"),"op":"parent","reference":reference}),
            diagnostics,
        )
    } else {
        Ok(reference)
    }
}

#[cfg(feature = "cli")]
fn run_native_network_cli(
    mut input: ChildStdin,
    stdout: ChildStdout,
    base: &str,
    diagnostics: &Mutex<CliDiagnostics>,
) -> Result<(), CliProofError> {
    if let Ok(mut state) = diagnostics.lock() {
        state.current_operation = Some("ready".to_owned());
    }
    let mut output = BufReader::new(stdout);
    let mut ready = String::new();
    if output.read_line(&mut ready)? == 0 {
        return Err(io::Error::other("native Surface CLI omitted its ready response").into());
    }
    let ready: Value = serde_json::from_str(&ready)?;
    if ready.pointer("/result/source/networkObservation/supported") != Some(&Value::Bool(true)) {
        return Err(
            io::Error::other("native CLI did not advertise qualified network support").into(),
        );
    }
    let subscription = cli_exchange(
        &mut input,
        &mut output,
        json!({"id":"subscribe","op":"network_subscribe","retain_bodies":true}),
        diagnostics,
    )?;
    if subscription.get("provider").and_then(Value::as_str) != Some("chrome_cdp") {
        return Err(io::Error::other("native CLI subscription did not identify Chrome CDP").into());
    }
    cli_exchange(
        &mut input,
        &mut output,
        json!({"id":"attach","op":"attach"}),
        diagnostics,
    )?;
    cli_exchange(
        &mut input,
        &mut output,
        json!({"id":"hot","op":"hot"}),
        diagnostics,
    )?;
    let root = cli_native_reference(
        &mut input,
        &mut output,
        "Start network requests",
        "one",
        diagnostics,
    )?;
    cli_exchange(
        &mut input,
        &mut output,
        json!({"id":"navigate-one","op":"navigate","reference":root,"url":format!("{base}/cli-network?cli=1")}),
        diagnostics,
    )?;

    let mut after_sequence = 0_u64;
    let mut captured_body = None;
    for _ in 0..32 {
        let waited = cli_exchange(
            &mut input,
            &mut output,
            json!({"id":"wait-network","op":"network_wait","after_sequence":after_sequence,"timeout_ms":5000}),
            diagnostics,
        )?;
        if waited.get("state").and_then(Value::as_str) != Some("event") {
            continue;
        }
        after_sequence = waited
            .get("sequence")
            .and_then(Value::as_u64)
            .ok_or_else(|| io::Error::other("CLI network wait omitted its sequence"))?;
        let window = cli_network_window(&mut input, &mut output, diagnostics)?;
        captured_body = window
            .get("payloads")
            .and_then(Value::as_array)
            .and_then(|payloads| {
                payloads.iter().find(|payload| {
                    payload.get("document_kind").and_then(Value::as_str) == Some("json")
                        && matches!(
                            payload.get("state").and_then(Value::as_str),
                            Some("retained" | "truncated")
                        )
                })
            })
            .cloned();
        if captured_body.is_some() {
            break;
        }
    }
    let payload = captured_body
        .ok_or_else(|| io::Error::other("native CLI did not retain its loopback JSON body"))?;
    let chunk = cli_exchange(
        &mut input,
        &mut output,
        json!({
            "id":"read-body",
            "op":"network_payload",
            "reference":payload,
            "offset":0,
            "max_bytes":8192,
            "budget":16384
        }),
        diagnostics,
    )?;
    let encoded = chunk
        .get("data_base64")
        .and_then(Value::as_str)
        .ok_or_else(|| io::Error::other("native CLI body chunk omitted base64 data"))?;
    let decoded = STANDARD.decode(encoded)?;
    if !decoded
        .windows(b"\"api\":true".len())
        .any(|bytes| bytes == b"\"api\":true")
    {
        return Err(
            io::Error::other("native CLI body chunk did not contain the loopback JSON").into(),
        );
    }

    cli_exchange(
        &mut input,
        &mut output,
        json!({"id":"cancel","op":"network_cancel"}),
        diagnostics,
    )?;
    let rearmed = cli_exchange(
        &mut input,
        &mut output,
        json!({"id":"subscribe-again","op":"network_subscribe","retain_bodies":true}),
        diagnostics,
    )?;
    if rearmed.get("active").and_then(Value::as_bool) != Some(true) {
        return Err(io::Error::other("native CLI could not rearm network capture").into());
    }
    let root = cli_native_reference(&mut input, &mut output, "CLI network", "two", diagnostics)?;
    cli_exchange(
        &mut input,
        &mut output,
        json!({"id":"navigate-two","op":"navigate","reference":root,"url":format!("{base}/cli-network?cli=2")}),
        diagnostics,
    )?;
    let mut fresh_request_seen = false;
    let mut after_sequence = 0_u64;
    for _ in 0..24 {
        let waited = cli_exchange(
            &mut input,
            &mut output,
            json!({"id":"wait-fresh","op":"network_wait","after_sequence":after_sequence,"timeout_ms":5000}),
            diagnostics,
        )?;
        if waited.get("state").and_then(Value::as_str) != Some("event") {
            continue;
        }
        after_sequence = waited
            .get("sequence")
            .and_then(Value::as_u64)
            .ok_or_else(|| io::Error::other("fresh CLI network wait omitted its sequence"))?;
        let window = cli_network_window(&mut input, &mut output, diagnostics)?;
        if window
            .pointer("/coverage/network_was_previously_enabled")
            .and_then(Value::as_bool)
            != Some(true)
            || window
                .pointer("/coverage/instrumentation_escalated")
                .and_then(Value::as_bool)
                != Some(false)
            || window
                .pointer("/retention/provider_resource_buffer_bytes")
                .and_then(Value::as_u64)
                != Some(u64::try_from(
                    surface::NETWORK_PROVIDER_RESOURCE_BUFFER_BYTES,
                )?)
        {
            return Err(io::Error::other(
                "rearmed CLI capture did not preserve shared Page instrumentation bounds",
            )
            .into());
        }
        fresh_request_seen = window
            .get("events")
            .and_then(Value::as_array)
            .is_some_and(|events| {
                events.iter().any(|event| {
                    event.pointer("/kind/kind").and_then(Value::as_str) == Some("request_started")
                        && event
                            .pointer("/kind/url")
                            .and_then(Value::as_str)
                            .is_some_and(|url| url.ends_with("/api"))
                })
            });
        if fresh_request_seen {
            break;
        }
    }
    if !fresh_request_seen {
        return Err(
            io::Error::other("fresh request was not observed after CLI cancellation").into(),
        );
    }
    cli_exchange(
        &mut input,
        &mut output,
        json!({"id":"close","op":"close"}),
        diagnostics,
    )?;
    Ok(())
}

#[cfg(feature = "cli")]
fn child_wait(child: Arc<Mutex<Child>>) -> io::Result<ExitStatus> {
    child
        .lock()
        .map_err(|_| io::Error::other("native CLI child lock was poisoned"))?
        .wait()
}

#[cfg(feature = "cli")]
fn cli_diagnostic_summary(diagnostics: &Mutex<CliDiagnostics>) -> String {
    diagnostics.lock().map_or_else(
        |_| "diagnostic state unavailable".to_owned(),
        |state| {
            format!(
                "operation={:?}; last_reply={:?}",
                state.current_operation, state.last_reply
            )
        },
    )
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "The proof asserts event relationships and keeps the managed Session alive until every network and Archive owner is released."
)]
async fn native_network_windows_link_bounded_bodies_and_replay_offline()
-> Result<(), Box<dyn Error>> {
    if !enabled() {
        return Ok(());
    }
    let fixture = NetworkFixture::start().await?;
    let page = Page::new(vec![
        Acquisition::Browser(BrowserMode::Headless).documents([DocumentRequest::RenderedDom]),
    ])?;
    let acquisition_policy = Policy {
        page,
        ..Policy::default()
    };
    let native = session::new()
        .bind(&acquisition_policy)
        .configure(SessionPolicy {
            operation_timeout_ms: 15_000,
            ..SessionPolicy::default()
        })
        .acquire()
        .await?;
    let output = tempfile::tempdir()?;
    let proof = Box::pin(async {
        let work = Box::pin(native.work()).await?;
        let navigated = work.navigate(&format!("{}/network", fixture.base)).await?;
        if navigated.status != OperationStatus::Observed {
            return Err(io::Error::other("native network fixture navigation was not observed").into());
        }
        let network_policy = NetworkObservationPolicy {
            retain_bodies: true,
            retain_url_path: true,
            retain_url_query: false,
            header_allowlist: vec!["x-public".into(), "set-cookie".into()],
            max_windows: 8,
            ..NetworkObservationPolicy::default()
        };
        let mut surface = BrowserSurface::consume_work(
            work,
            SurfacePolicy {
                archive: surface::ArchivePolicy::Enabled,
                archive_root: Some(output.path().join("archive")),
                output: Some(output.path().join("surface")),
                network_observation: network_policy,
                ..SurfacePolicy::default()
            },
        )
        .await?;
        let subscription = surface.subscribe_network(None).await?;
        assert!(subscription.active);
        assert_eq!(subscription.provider, "chrome_cdp");
        hot(&mut surface).await?;
        let start = reference(&mut surface, "Start network requests").await?;
        let clicked = surface
            .execute(json!({"op":"click","reference":start,"expect":{"kind":"text","text":"network requests started","present":true}}))
            .await?;
        if clicked.pointer("/receipt/status").and_then(Value::as_str) != Some("Confirmed") {
            return Err(io::Error::other(format!(
                "network fixture action was not confirmed: {clicked}"
            ))
            .into());
        }
        timeout(Duration::from_secs(5), fixture.slow_started.notified()).await?;

        let mut after_sequence = 0_u64;
        let mut first = None;
        for _ in 0..16 {
            let waited = surface.wait_network_event(after_sequence, 5_000).await?;
            if waited.get("state").and_then(Value::as_str) != Some("event") {
                return Err(io::Error::other("network start event timed out").into());
            }
            after_sequence = waited
                .get("sequence")
                .and_then(Value::as_u64)
                .ok_or_else(|| io::Error::other("network wait omitted its sequence"))?;
            let (_, window) = surface.observe_network().await?;
            if window
                .in_flight
                .iter()
                .any(|request| request.url.ends_with("/slow"))
            {
                first = Some(window);
                break;
            }
        }
        let first = first.ok_or_else(|| io::Error::other("slow request did not cross a window boundary"))?;
        assert!(first.coverage.start_boundary_unknown);
        assert!(!first.coverage.complete);
        assert!(first.in_flight.iter().any(|request| request.url.ends_with("/slow")));
        assert!(first.events.iter().filter_map(|event| match &event.kind {
            NetworkEventKind::RequestStarted { url, .. } => Some(url.as_str()),
            _ => None,
        }).all(|url| !url.contains("token=secret")), "the retained URL must not preserve the query token");
        assert!(first.retention.retain_url_path);
        assert!(!first.retention.retain_url_query);
        assert_eq!(first.retention.retained_header_names, ["x-public"]);
        assert!(first.events.iter().filter_map(|event| match &event.kind {
            NetworkEventKind::ResponseReceived { headers, .. } => Some(headers),
            _ => None,
        }).flatten().any(|header| header.name == "x-public"));
        assert!(!first.events.iter().filter_map(|event| match &event.kind {
            NetworkEventKind::ResponseReceived { headers, .. } => Some(headers),
            _ => None,
        }).flatten().any(|header| header.name == "set-cookie"));

        let release = reference(&mut surface, "Release delayed response").await?;
        let released = surface
            .execute(json!({"op":"click","reference":release,"expect":{"kind":"text","text":"network complete","present":true}}))
            .await?;
        if released.pointer("/receipt/status").and_then(Value::as_str) != Some("Confirmed") {
            return Err(io::Error::other("delayed network request did not complete").into());
        }
        let waited = surface.wait_network_event(after_sequence, 5_000).await?;
        if waited.get("state").and_then(Value::as_str) != Some("event") {
            return Err(io::Error::other("network completion event timed out").into());
        }
        let (_, second) = surface.observe_network().await?;
        assert!(second
            .in_flight_at_start
            .iter()
            .any(|request| request.url.ends_with("/slow")));
        assert!(!second
            .in_flight
            .iter()
            .any(|request| request.url.ends_with("/slow")));
        let all_events: Vec<_> = first.events.iter().chain(&second.events).collect();
        assert!(all_events.iter().any(|event| matches!(
            &event.kind,
            NetworkEventKind::Redirect { status: 302, from_url, to_url, .. }
                if from_url.ends_with("/redirect") && to_url.ends_with("/redirected")
        )));
        assert!(all_events.iter().any(|event| matches!(
            &event.kind,
            NetworkEventKind::Failed { .. }
        )));
        assert!(all_events.iter().any(|event| matches!(
            &event.kind,
            NetworkEventKind::ResponseReceived {
                content_encoding: Some(encoding), ..
            } if encoding.eq_ignore_ascii_case("gzip")
        )));

        let payload_refs: Vec<_> = first
            .payloads
            .iter()
            .chain(&second.payloads)
            .filter(|payload| matches!(payload.state, NetworkPayloadState::Retained | NetworkPayloadState::Truncated))
            .cloned()
            .collect();
        let html = payload_refs
            .iter()
            .find(|payload| payload.document_kind == Some(NetworkPayloadKind::Html))
            .ok_or_else(|| io::Error::other("HTML response body was not linked"))?;
        let json_body = payload_refs
            .iter()
            .find(|payload| {
                payload.document_kind == Some(NetworkPayloadKind::Json)
                    && payload.content_encoding.is_none()
            })
            .ok_or_else(|| io::Error::other("JSON response body was not linked"))?;
        let gzip = payload_refs
            .iter()
            .find(|payload| {
                payload.document_kind == Some(NetworkPayloadKind::Json)
                    && payload.content_encoding.as_deref() == Some("gzip")
            })
            .ok_or_else(|| io::Error::other("compressed JSON response was not linked"))?;
        let binary = payload_refs
            .iter()
            .find(|payload| {
                payload.document_kind == Some(NetworkPayloadKind::File)
                    && payload.declared_media_type.as_deref() == Some("application/octet-stream")
                    && payload.detected_media_type.is_none()
            })
            .ok_or_else(|| io::Error::other("binary response body was not linked"))?;
        let legacy_html = payload_refs
            .iter()
            .find(|payload| {
                payload
                    .browser_effective_charset
                    .as_deref()
                    == Some("windows-1252")
            })
            .ok_or_else(|| io::Error::other("legacy-charset HTML response body was not linked"))?;
        assert_eq!(legacy_html.document_kind, Some(NetworkPayloadKind::Html));
        assert_eq!(
            legacy_html.projection_basis,
            Some(surface::NetworkProjectionBasis::RequestsDeclared)
        );
        assert_eq!(
            legacy_html.declared_media_type.as_deref(),
            Some("text/html; charset=windows-1252")
        );
        assert_eq!(legacy_html.browser_effective_mime.as_deref(), Some("text/html"));
        assert_eq!(
            legacy_html.browser_effective_charset.as_deref(),
            Some("windows-1252")
        );
        assert_eq!(legacy_html.detected_media_type.as_deref(), Some("text/html"));
        let sniffed_html = payload_refs
            .iter()
            .find(|payload| {
                payload.declared_media_type.is_none()
                    && payload.document_kind == Some(NetworkPayloadKind::Html)
                    && payload.detected_media_type.as_deref() == Some("text/html")
            })
            .ok_or_else(|| io::Error::other("missing Content-Type HTML was not sniffed"))?;
        assert_eq!(
            sniffed_html.projection_basis,
            Some(surface::NetworkProjectionBasis::RequestsSniffed)
        );
        assert!(sniffed_html.browser_effective_mime.is_some());
        let misleading_png = payload_refs
            .iter()
            .find(|payload| {
                payload.declared_media_type.as_deref() == Some("application/octet-stream")
            })
            .ok_or_else(|| io::Error::other("octet-stream PNG response was not linked"))?;
        assert!(misleading_png.browser_effective_mime.is_some());
        assert_eq!(misleading_png.detected_media_type.as_deref(), Some("image/png"));
        assert_eq!(misleading_png.document_kind, Some(NetworkPayloadKind::File));
        assert_eq!(
            misleading_png.projection_basis,
            Some(surface::NetworkProjectionBasis::TypedFileMagic)
        );
        assert!(!legacy_html.provider_base64_encoded);
        assert!(legacy_html.text_utf8_normalized);
        for reference in [
            html,
            json_body,
            gzip,
            binary,
            legacy_html,
            sniffed_html,
            misleading_png,
        ] {
            let live = surface.network_payload(reference, 8192).await?;
            let digest = format!("{:x}", Sha256::digest(live.bytes()));
            assert_eq!(
                reference.sha256.as_deref(),
                Some(digest.as_str())
            );
        }
        assert!(binary.provider_base64_encoded);
        assert_eq!(gzip.byte_provenance, surface::NetworkByteProvenance::CdpDecodedResponseBody);
        let legacy_live = surface.network_payload(legacy_html, 8192).await?;
        assert!(legacy_live.bytes().windows("café".len()).any(|window| window == "café".as_bytes()));

        surface.cancel_network().await?;
        assert!(surface.observe_network().await.is_err());
        let rearmed = surface.subscribe_network(None).await?;
        assert!(rearmed.active);
        let after_cancel = reference(&mut surface, "Start request after capture cancellation").await?;
        let clicked = surface
            .execute(json!({"op":"click","reference":after_cancel,"expect":{"kind":"text","text":"post-cancel request complete","present":true}}))
            .await?;
        if clicked.pointer("/receipt/status").and_then(Value::as_str) != Some("Confirmed") {
            return Err(io::Error::other("post-cancel request did not complete").into());
        }
        let waited = surface.wait_network_event(0, 5_000).await?;
        if waited.get("state").and_then(Value::as_str) != Some("event") {
            return Err(io::Error::other("rearmed request watcher did not receive an event").into());
        }
        let (_, rearmed_window) = surface.observe_network().await?;
        assert!(!rearmed_window.coverage.instrumentation_escalated);
        assert!(rearmed_window.coverage.network_was_previously_enabled);
        assert!(rearmed_window.events.iter().any(|event| matches!(
            &event.kind,
            NetworkEventKind::RequestStarted { url, .. }
                if url.ends_with("/api")
        )));

        let portable = output.path().join("surface/surface.yosoi");
        let outcome = surface.close().await?.ok_or_else(|| io::Error::other("network outcome missing"))?;
        outcome.validate()?;
        assert!(surface.observe_network().await.is_err());
        let fresh_work = Box::pin(native.work()).await?;
        let navigated = fresh_work.navigate(&format!("{}/api", fixture.base)).await?;
        if navigated.status != OperationStatus::Observed {
            return Err(io::Error::other("fresh Work could not navigate after network Surface close").into());
        }
        fresh_work.release().await?;
        Ok::<_, Box<dyn Error>>((json_body.clone(), binary.clone(), portable))
    })
    .await;
    let closed = native.close().await;
    fixture.close().await;
    let (json_body, binary, portable) = proof?;
    closed?;
    std::fs::remove_dir_all(output.path().join("archive"))?;
    let fresh = tempfile::tempdir()?;
    let archive = Archive::open(fresh.path()).await?;
    let imported = archive.import_file(&portable).await?;
    let restored = archive.read(&imported).await?;
    let offline_json = NetworkPayload::from_outcome(&restored, &json_body, 8 * 1024 * 1024)?;
    assert!(
        offline_json
            .bytes()
            .windows(b"\"api\":true".len())
            .any(|window| window == b"\"api\":true")
    );
    let offline_file = NetworkPayload::from_outcome(&restored, &binary, 8 * 1024 * 1024)?;
    assert_eq!(offline_file.bytes(), b"\0\xff\x10opaque\0bytes");
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "The proof verifies provider buffer limits on one managed browser tab and explicitly closes Session, Work and the local fixture."
)]
async fn native_network_skips_compressed_body_over_retention_limit_before_read()
-> Result<(), Box<dyn Error>> {
    if !enabled() {
        return Ok(());
    }
    let fixture = NetworkFixture::start().await?;
    let page = Page::new(vec![
        Acquisition::Browser(BrowserMode::Headless).documents([DocumentRequest::RenderedDom]),
    ])?;
    let acquisition_policy = Policy {
        page,
        ..Policy::default()
    };
    let native = session::new()
        .bind(&acquisition_policy)
        .configure(SessionPolicy {
            operation_timeout_ms: 15_000,
            ..SessionPolicy::default()
        })
        .acquire()
        .await?;
    let proof = Box::pin(async {
        let work = Box::pin(native.work()).await?;
        let receipt = work
            .navigate(&format!("{}/bomb-page", fixture.base))
            .await?;
        if receipt.status != OperationStatus::Observed {
            return Err(io::Error::other("compressed-body fixture did not load").into());
        }
        let mut surface = BrowserSurface::consume_work(
            work,
            SurfacePolicy {
                network_observation: NetworkObservationPolicy {
                    retain_bodies: true,
                    retain_url_path: true,
                    max_body_bytes: 1024,
                    max_total_body_bytes: 4096,
                    ..NetworkObservationPolicy::default()
                },
                ..SurfacePolicy::default()
            },
        )
        .await?;
        let subscription = surface.subscribe_network(None).await?;
        assert!(subscription.active);
        let configured = surface.ready()?;
        assert_eq!(configured["source"]["networkObservation"]["active"], true);
        hot(&mut surface).await?;
        let button = reference(&mut surface, "Start compressed body").await?;
        let result = surface
            .execute(json!({"op":"click","reference":button,"expect":{"kind":"text","text":"compressed response complete","present":true}}))
            .await?;
        if result.pointer("/receipt/status").and_then(Value::as_str) != Some("Confirmed") {
            return Err(io::Error::other("compressed response did not complete in the page").into());
        }
        let mut after_sequence = 0_u64;
        let mut body_reference = None;
        let mut retained_window = None;
        for _ in 0..12 {
            let waited = surface.wait_network_event(after_sequence, 5_000).await?;
            if waited.get("state").and_then(Value::as_str) != Some("event") {
                return Err(io::Error::other("compressed response events timed out").into());
            }
            after_sequence = waited
                .get("sequence")
                .and_then(Value::as_u64)
                .ok_or_else(|| io::Error::other("network wait omitted sequence"))?;
            let (_, window) = surface.observe_network().await?;
            let response_id = window.events.iter().find_map(|event| match &event.kind {
                NetworkEventKind::ResponseReceived { url, .. } if url.ends_with("/gzip-bomb") => {
                    Some((event.request_id.clone(), event.hop, event.sequence))
                }
                _ => None,
            });
            if let Some((request_id, hop, response_sequence)) = response_id
                && let Some(reference) = window.payloads.iter().find(|payload| {
                    payload.request_id == request_id
                        && payload.hop == hop
                        && payload.response_sequence == response_sequence
                        && payload.state != NetworkPayloadState::NotRequested
                })
            {
                body_reference = Some(reference.clone());
                retained_window = Some(window);
                break;
            }
        }
        let reference = body_reference
            .ok_or_else(|| io::Error::other("compressed response had no inspectable body state"))?;
        let window = retained_window
            .ok_or_else(|| io::Error::other("compressed response window was not retained"))?;
        assert_eq!(
            window.retention.provider_resource_buffer_bytes,
            surface::NETWORK_PROVIDER_RESOURCE_BUFFER_BYTES
        );
        assert_eq!(
            window.retention.provider_total_buffer_bytes,
            surface::NETWORK_PROVIDER_TOTAL_BUFFER_BYTES
        );
        assert_eq!(window.retention.max_body_bytes, 1024);
        assert_eq!(window.retention.max_total_body_bytes, 4096);
        assert_eq!(reference.state, NetworkPayloadState::Unavailable);
        assert_eq!(reference.retained_bytes, 0);
        assert!(reference
            .provider_reported_body_bytes
            .is_some_and(|bytes| bytes > 1024));
        assert_eq!(
            reference.reason.as_deref(),
            Some("response_body_exceeds_retention_limit_before_read")
        );
        assert_eq!(reference.content_encoding.as_deref(), Some("gzip"));
        surface.cancel_network().await?;
        surface.close().await?;
        Ok::<(), Box<dyn Error>>(())
    })
    .await;
    let closed = native.close().await;
    fixture.close().await;
    proof?;
    closed?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "The loopback proof asserts overflow metadata and releases the browser owner before the fixture."
)]
async fn native_network_event_overflow_is_visible_in_frozen_coverage() -> Result<(), Box<dyn Error>>
{
    if !enabled() {
        return Ok(());
    }
    let fixture = NetworkFixture::start().await?;
    let page = Page::new(vec![
        Acquisition::Browser(BrowserMode::Headless).documents([DocumentRequest::RenderedDom]),
    ])?;
    let acquisition_policy = Policy {
        page,
        ..Policy::default()
    };
    let native = session::new()
        .bind(&acquisition_policy)
        .configure(SessionPolicy {
            operation_timeout_ms: 15_000,
            ..SessionPolicy::default()
        })
        .acquire()
        .await?;
    let work = Box::pin(native.work()).await?;
    let navigated = work.navigate(&format!("{}/network", fixture.base)).await?;
    if navigated.status != OperationStatus::Observed {
        return Err(io::Error::other("overflow fixture navigation was not observed").into());
    }
    let mut surface = BrowserSurface::consume_work(
        work,
        SurfacePolicy {
            network_observation: NetworkObservationPolicy {
                max_events: 1,
                retain_url_path: true,
                ..NetworkObservationPolicy::default()
            },
            ..SurfacePolicy::default()
        },
    )
    .await?;
    surface.subscribe_network(None).await?;
    hot(&mut surface).await?;
    let button = reference(&mut surface, "Start network requests").await?;
    let clicked = surface
        .execute(json!({"op":"click","reference":button,"expect":{"kind":"text","text":"network requests started","present":true}}))
        .await?;
    if clicked.pointer("/receipt/status").and_then(Value::as_str) != Some("Confirmed") {
        return Err(io::Error::other(format!(
            "overflow fixture request action was not confirmed: {clicked}"
        ))
        .into());
    }
    let mut after_sequence = 0_u64;
    let mut overflow_window = None;
    for _ in 0..24 {
        let waited = surface.wait_network_event(after_sequence, 5_000).await?;
        if waited.get("state").and_then(Value::as_str) != Some("event") {
            break;
        }
        after_sequence = waited
            .get("sequence")
            .and_then(Value::as_u64)
            .ok_or_else(|| io::Error::other("overflow wait omitted sequence"))?;
        let (_, window) = surface.observe_network().await?;
        if window.coverage.overflow {
            overflow_window = Some(window);
            break;
        }
    }
    let window = overflow_window
        .ok_or_else(|| io::Error::other("network journal did not report its event cap"))?;
    assert!(window.coverage.dropped_events > 0);
    assert!(
        window
            .gaps
            .iter()
            .any(|gap| gap.reason == "event_retention_limit")
    );
    surface.cancel_network().await?;
    surface.close().await?;
    native.close().await?;
    fixture.close().await;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "The loopback proof asserts explicit body omissions and releases the browser owner before the fixture."
)]
async fn native_network_body_disabled_keeps_response_link_as_explicit_omission()
-> Result<(), Box<dyn Error>> {
    if !enabled() {
        return Ok(());
    }
    let fixture = NetworkFixture::start().await?;
    let page = Page::new(vec![
        Acquisition::Browser(BrowserMode::Headless).documents([DocumentRequest::RenderedDom]),
    ])?;
    let acquisition_policy = Policy {
        page,
        ..Policy::default()
    };
    let native = session::new()
        .bind(&acquisition_policy)
        .configure(SessionPolicy {
            operation_timeout_ms: 15_000,
            ..SessionPolicy::default()
        })
        .acquire()
        .await?;
    let work = Box::pin(native.work()).await?;
    let navigated = work.navigate(&format!("{}/network", fixture.base)).await?;
    if navigated.status != OperationStatus::Observed {
        return Err(io::Error::other("no-body fixture navigation was not observed").into());
    }
    let mut surface = BrowserSurface::consume_work(
        work,
        SurfacePolicy {
            network_observation: NetworkObservationPolicy {
                retain_url_path: true,
                ..NetworkObservationPolicy::default()
            },
            ..SurfacePolicy::default()
        },
    )
    .await?;
    surface.subscribe_network(Some(false)).await?;
    hot(&mut surface).await?;
    let button = reference(&mut surface, "Start network requests").await?;
    let clicked = surface
        .execute(json!({"op":"click","reference":button,"expect":{"kind":"text","text":"network requests started","present":true}}))
        .await?;
    if clicked.pointer("/receipt/status").and_then(Value::as_str) != Some("Confirmed") {
        return Err(io::Error::other(format!(
            "no-body fixture request action was not confirmed: {clicked}"
        ))
        .into());
    }
    let mut after_sequence = 0_u64;
    let mut omission = None;
    for _ in 0..24 {
        let waited = surface.wait_network_event(after_sequence, 5_000).await?;
        if waited.get("state").and_then(Value::as_str) != Some("event") {
            break;
        }
        after_sequence = waited
            .get("sequence")
            .and_then(Value::as_u64)
            .ok_or_else(|| io::Error::other("no-body wait omitted sequence"))?;
        let (_, window) = surface.observe_network().await?;
        let response = window.events.iter().find_map(|event| match &event.kind {
            NetworkEventKind::ResponseReceived { url, .. } if url.ends_with("/api") => {
                Some((event.request_id.as_str(), event.hop, event.sequence))
            }
            _ => None,
        });
        let reference = response.and_then(|(request_id, hop, sequence)| {
            window
                .payloads
                .iter()
                .find(|payload| {
                    payload.request_id == request_id
                        && payload.hop == hop
                        && payload.response_sequence == sequence
                })
                .cloned()
        });
        if let Some(reference) = reference {
            omission = Some((window, reference));
            break;
        }
    }
    let (_, reference) = omission
        .ok_or_else(|| io::Error::other("body-disabled response omission was not inspectable"))?;
    assert_eq!(reference.state, NetworkPayloadState::NotRequested);
    assert_eq!(reference.reason.as_deref(), Some("body_retention_disabled"));
    assert!(reference.document_id.is_none());
    assert!(reference.sha256.is_none());
    assert_eq!(reference.retained_bytes, 0);
    assert!(reference.projection_basis.is_none());
    surface.cancel_network().await?;
    surface.close().await?;
    native.close().await?;
    fixture.close().await;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "The loopback proof asserts authority-loss coverage and reacquires a fresh tab before cleanup."
)]
async fn native_network_authority_loss_freezes_coverage_and_releases_the_page()
-> Result<(), Box<dyn Error>> {
    if !enabled() {
        return Ok(());
    }
    let fixture = NetworkFixture::start().await?;
    let page = Page::new(vec![
        Acquisition::Browser(BrowserMode::Headless).documents([DocumentRequest::RenderedDom]),
    ])?;
    let acquisition_policy = Policy {
        page,
        ..Policy::default()
    };
    let native = session::new()
        .bind(&acquisition_policy)
        .configure(SessionPolicy {
            maximum_tabs: 2,
            operation_timeout_ms: 15_000,
            ..SessionPolicy::default()
        })
        .acquire()
        .await?;
    let tab = native.new_tab().await?;
    let work = tab.work().await?;
    let navigated = work.navigate(&format!("{}/network", fixture.base)).await?;
    if navigated.status != OperationStatus::Observed {
        return Err(io::Error::other("native network fixture did not load").into());
    }
    let mut surface = BrowserSurface::consume_work(
        work,
        SurfacePolicy {
            network_observation: NetworkObservationPolicy::default(),
            ..SurfacePolicy::default()
        },
    )
    .await?;
    surface.subscribe_network(None).await?;
    hot(&mut surface).await?;
    let stale_button = reference(&mut surface, "Start network requests").await?;

    tab.close().await?;
    assert!(surface.wait_network_event(0, 5_000).await.is_err());
    let (_, window) = surface.observe_network().await?;
    assert!(window.coverage.disconnected);
    assert!(
        window
            .gaps
            .iter()
            .any(|gap| gap.reason == "native_work_authority_lost")
    );
    assert!(
        surface
            .execute(json!({"op":"click","reference":stale_button}))
            .await
            .is_err()
    );
    surface.close().await?;

    let fresh_tab = native.new_tab().await?;
    let fresh_work = fresh_tab.work().await?;
    let navigated = fresh_work
        .navigate(&format!("{}/api", fixture.base))
        .await?;
    if navigated.status != OperationStatus::Observed {
        return Err(io::Error::other(
            "fresh Work could not navigate after prior capture authority loss",
        )
        .into());
    }
    fresh_work.release().await?;
    fresh_tab.close().await?;
    native.close().await?;
    fixture.close().await;
    Ok(())
}

#[cfg(feature = "cli")]
#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "The JSON-lines proof owns one child process and loopback fixture through bounded shutdown."
)]
async fn native_network_cli_json_lines_reads_body_and_rearms_after_cancel()
-> Result<(), Box<dyn Error>> {
    if !enabled() {
        return Ok(());
    }
    let fixture = NetworkFixture::start().await?;
    let proof = Box::pin(async {
        let temporary = tempfile::tempdir()?;
        let policy_file = temporary.path().join("network-policy.json");
        std::fs::write(
            &policy_file,
            br#"{"retain_bodies":true,"retain_url_path":true,"max_events":256}"#,
        )?;
        let output = temporary.path().join("output");
        let archive = temporary.path().join("archive");
        let mut child = Command::new(env!("CARGO_BIN_EXE_yosoi"))
            .args(["surface", "native-web", "--url"])
            .arg(format!("{}/network", fixture.base))
            .args(["--headless", "--network-bodies", "--output"])
            .arg(&output)
            .arg("--archive")
            .arg(&archive)
            .arg("--network-policy")
            .arg(&policy_file)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()?;
        let input = child
            .stdin
            .take()
            .ok_or_else(|| io::Error::other("native Surface CLI stdin is unavailable"))?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| io::Error::other("native Surface CLI stdout is unavailable"))?;
        let child = Arc::new(Mutex::new(child));
        let diagnostics = Arc::new(Mutex::new(CliDiagnostics::default()));
        let worker = tokio::task::spawn_blocking({
            let base = fixture.base.clone();
            let diagnostics = Arc::clone(&diagnostics);
            move || run_native_network_cli(input, stdout, &base, &diagnostics)
        });
        let mut worker = worker;
        let proof_result = match timeout(Duration::from_secs(60), &mut worker).await {
            Ok(Ok(result)) => result,
            Ok(Err(error)) => {
                if let Ok(mut child) = child.lock() {
                    let _ = child.kill();
                }
                let child_for_wait = Arc::clone(&child);
                let mut waiter = tokio::task::spawn_blocking(move || child_wait(child_for_wait));
                let _ = timeout(Duration::from_secs(5), &mut waiter).await;
                return Err(io::Error::other(error.to_string()).into());
            }
            Err(_) => {
                if let Ok(mut child) = child.lock() {
                    let _ = child.kill();
                }
                let _ = timeout(Duration::from_secs(5), &mut worker).await;
                let child_for_wait = Arc::clone(&child);
                let mut waiter = tokio::task::spawn_blocking(move || child_wait(child_for_wait));
                let _ = timeout(Duration::from_secs(5), &mut waiter).await;
                return Err(io::Error::other(format!(
                    "native network CLI proof exceeded its timeout: {}",
                    cli_diagnostic_summary(&diagnostics)
                ))
                .into());
            }
        };
        if let Err(error) = proof_result {
            if let Ok(mut child) = child.lock() {
                let _ = child.kill();
            }
            let child_for_wait = Arc::clone(&child);
            let waiter = tokio::task::spawn_blocking(move || child_wait(child_for_wait));
            let _ = timeout(Duration::from_secs(5), waiter).await;
            return Err(io::Error::other(error.to_string()).into());
        }
        let child_for_wait = Arc::clone(&child);
        let mut waiter = tokio::task::spawn_blocking(move || child_wait(child_for_wait));
        let status = match timeout(Duration::from_secs(15), &mut waiter).await {
            Ok(joined) => joined
                .map_err(|error| io::Error::other(error.to_string()))?
                .map_err(|error| io::Error::other(error.to_string()))?,
            Err(_) => {
                if let Ok(mut child) = child.lock() {
                    let _ = child.kill();
                }
                let _ = timeout(Duration::from_secs(5), &mut waiter).await;
                return Err(io::Error::other("native network CLI did not shut down").into());
            }
        };
        if !status.success() {
            return Err(
                io::Error::other(format!("native network CLI exited with {status}")).into(),
            );
        }
        if !output.join("surface.yosoi").is_file() {
            return Err(io::Error::other(
                "native network CLI omitted its portable Archive outcome",
            )
            .into());
        }
        Ok::<(), Box<dyn Error>>(())
    })
    .await;
    fixture.close().await;
    proof?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Keep Session and per-tab Work leases alive through the shared-pool interleaving; assertions verify ownership, and every lease is explicitly released before Session close."
)]
async fn consumed_surfaces_share_native_tab_ownership_and_yield_capacity()
-> Result<(), Box<dyn Error>> {
    if !enabled() {
        return Ok(());
    }
    let fixture = Fixture::start().await?;
    let policy = Policy {
        page: Page::new(vec![
            Acquisition::Browser(BrowserMode::Headless).documents([DocumentRequest::RenderedDom]),
        ])?,
        ..Policy::default()
    };
    let pool = ExecutionPool::new(1, 8)?;
    let native = session::new()
        .bind(&policy)
        .configure(SessionPolicy {
            maximum_tabs: 2,
            operation_timeout_ms: 10000,
            ..SessionPolicy::default()
        })
        .execution_pool(&pool)
        .acquire()
        .await?;
    let proof = Box::pin(async {
        let first = Box::pin(native.work()).await?;
        first.navigate(&format!("{}/a", fixture.base)).await?;
        let second = native.new_tab().await?;
        let work = second.work().await?;
        work.navigate(&format!("{}/b", fixture.base)).await?;
        let original_b = work.observe().await?;
        work.release().await?;
        let mut a = BrowserSurface::consume_work(first, SurfacePolicy::default()).await?;
        let mut b = BrowserSurface::consume_tab(&second, SurfacePolicy {
            archive: surface::ArchivePolicy::Enabled,
            ..SurfacePolicy::default()
        }).await?;
        hot(&mut a).await?;
        hot(&mut b).await?;
        assert!(Box::pin(native.work()).now_or_never().is_none(), "Surface must retain the existing tab's single Work owner");
        let mut events = pool.subscribe();
        let mut wait_a = Box::pin(a.execute(json!({"op":"wait","text":"Released A","present":true})));
        timeout(Duration::from_secs(5), async {
            loop {
                tokio::select! {
                    value = &mut wait_a => return Err(io::Error::other(format!("wait unexpectedly completed before sibling action: {value:?}"))),
                    _ = events.recv() => { if pool.snapshot().parked > 0 { return Ok(()); } }
                }
            }
        }).await??;
        let button = reference(&mut b, "Release A").await?;
        let clicked = b.execute(json!({"op":"click","reference":button,"expect":{"kind":"text","text":"Clicked B","present":true}})).await?;
        if clicked["receipt"]["status"] != "Confirmed" {
            drop(wait_a);
            a.close().await?;
            b.close().await?;
            return Err(io::Error::other(format!("native click did not confirm: {clicked:#}")).into());
        }
        assert!(clicked["outcome"]["native_receipt_id"].is_string());
        let waited = timeout(Duration::from_secs(5), &mut wait_a).await??;
        assert_eq!(waited["condition"]["state"], "text_matched");
        drop(wait_a);
        a.close().await?;
        let reacquired = Box::pin(native.work()).await?;
        reacquired.release().await?;
        let mut facade = surface::consume_session(native.clone(), SurfacePolicy::default()).await?;
        let old = facade.ready()?;
        assert_eq!(old["source"]["backend"], "native_session");
        facade.close().await?;
        let mut rebound = consume_browser_session(native.clone(), SurfacePolicy::default()).await?;
        let fresh = rebound.ready()?;
        assert_ne!(old["state"]["root"]["capture"], fresh["state"]["root"]["capture"],
            "reconnecting unchanged native evidence must not revive foreign binding references");
        assert!(rebound.execute(json!({"op":"inspect","reference":old["state"]["root"]})).await.is_err());
        rebound.close().await?;
        let message = reference(&mut b, "Message").await?;
        let filled = b.execute(json!({"op":"fill","reference":message,"text":"native input"})).await?;
        assert_eq!(filled["receipt"]["status"], "Confirmed");
        assert!(b.execute(json!({"op":"eligibility","reference":message})).await.is_err(), "pre-effect capture reference must become stale");
        let key = reference(&mut b, "Keyboard").await?;
        let keyed = b.execute(json!({"op":"key","reference":key,"key":"Enter","expect":{"kind":"text","text":"Enter observed","present":true}})).await?;
        assert_eq!(keyed["receipt"]["status"], "Confirmed");
        let ax = b.observe(surface::browser::BrowserRepresentation::Ax).await?;
        assert!(!ax.descriptor.controllable);
        let outcome = b.close().await?.ok_or_else(|| io::Error::other("native archive outcome missing"))?;
        assert!(outcome.record.observations().iter().all(|observation|
            observation.session_id == original_b.session_id && observation.tab_id == original_b.tab_id
                && observation.document_epoch == original_b.document_epoch));
        let released = outcome.record.operations().iter().find(|operation| operation.kind == "surface.released")
            .ok_or_else(|| io::Error::other("native release receipt missing"))?;
        assert_eq!(released.result.as_ref().and_then(|value|value.get("browser_closed_by_surface")), Some(&Value::Bool(false)));
        let rerun = surface::browser::archive::rerun(&outcome, SurfacePolicy { archive: surface::ArchivePolicy::Enabled, ..SurfacePolicy::default() }, 1, true).await;
        assert!(rerun.err().is_some_and(|error| error.to_string().contains("native Session/Work")),
            "generic rerun must not replace the consumed Session policy with a fresh driver");
        let work = second.work().await?;
        assert_eq!(work.observe().await?.document_epoch, original_b.document_epoch);
        work.release().await?;
        assert_eq!(pool.snapshot().active, 0);
        assert_eq!(pool.snapshot().parked, 0);
        Ok::<(), Box<dyn Error>>(())
    })
    .await;
    let closed = native.close().await;
    fixture.close().await;
    proof?;
    closed?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Keep Session, Work, and Surface owners alive while verifying archive cleanup, result bounds, and focus fencing; each is explicitly released before Session close."
)]
async fn native_setup_failure_finalizes_archive_and_focus_loss_stops_typing()
-> Result<(), Box<dyn Error>> {
    if !enabled() {
        return Ok(());
    }
    let fixture = Fixture::start().await?;
    let policy = Policy {
        page: Page::new(vec![
            Acquisition::Browser(BrowserMode::Headless).documents([DocumentRequest::RenderedDom]),
        ])?,
        ..Policy::default()
    };
    let native = session::new()
        .bind(&policy)
        .configure(SessionPolicy {
            maximum_result_bytes: 1024,
            ..SessionPolicy::default()
        })
        .acquire()
        .await?;
    let proof = Box::pin(async {
        let work = Box::pin(native.work()).await?;
        work.navigate(&format!("{}/b", fixture.base)).await?;
        let output = tempfile::tempdir()?;
        let mut constrained = SurfacePolicy {
            archive: surface::ArchivePolicy::Enabled,
            output: Some(output.path().join("output")),
            archive_root: Some(output.path().join("archive")),
            ..SurfacePolicy::default()
        };
        constrained.documents.dom.max_nodes = 1;
        let failed = BrowserSurface::consume_work(work, constrained).await;
        let error = match failed {
            Err(error) => error,
            Ok(mut source) => {
                source.close().await?;
                return Err(
                    io::Error::other("over-limit initial capture unexpectedly succeeded").into(),
                );
            }
        };
        let surface::ExecutionError::Execution { outcomes, .. } = error else {
            return Err(io::Error::other(
                "failed setup did not retain its partial archive outcome",
            )
            .into());
        };
        let outcome = outcomes
            .first()
            .ok_or_else(|| io::Error::other("partial setup outcome missing"))?;
        assert!(outcome.sealed);
        assert!(
            outcome
                .record
                .operations()
                .iter()
                .any(|operation| operation.kind == "surface.released")
        );
        let work = Box::pin(native.work()).await?;
        work.release().await?;
        let mut source = surface::consume_session(native.clone(), SurfacePolicy::default()).await?;
        hot(&mut source).await?;
        let field = reference(&mut source, "Message").await?;
        let replaced = source
            .execute(json!({"op":"fill","reference":field,"text":"replacement"}))
            .await?;
        assert_eq!(replaced["receipt"]["status"], "Confirmed");
        assert_eq!(replaced["outcome"]["value"]["characters"], 11);
        let field = reference(&mut source, "Steal source").await?;
        let stopped = source
            .execute(json!({"op":"fill","reference":field,"text":"must not reach another input"}))
            .await?;
        assert_eq!(stopped["receipt"]["status"], "Unconfirmed");
        let changed = source
            .execute(json!({"op":"find","query":"Foreign input changed"}))
            .await?;
        assert!(
            changed["entries"]
                .as_array()
                .ok_or_else(|| io::Error::other("find entries missing"))?
                .iter()
                .all(|entry| entry["kind"] != "text")
        );
        source.execute(json!({"op":"refresh"})).await?;
        let link = reference(&mut source, "Large document").await?;
        let bounded = source
            .execute(json!({"op":"click","reference":link,"expect":{"kind":"navigation"}}))
            .await?;
        assert_eq!(bounded["receipt"]["status"], "Unconfirmed");
        assert!(
            bounded["outcome"]["error"]
                .as_str()
                .is_some_and(|message| message.contains("byte limit")),
            "wait result must honor the native Session result limit: {bounded:#}"
        );
        source.close().await?;
        let work = Box::pin(native.work()).await?;
        assert_eq!(
            work.observe().await?.url.as_deref(),
            Some(format!("{}/large", fixture.base).as_str())
        );
        work.release().await?;
        Ok::<(), Box<dyn Error>>(())
    })
    .await;
    let closed = native.close().await;
    fixture.close().await;
    proof?;
    closed?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
#[expect(
    clippy::panic_in_result_fn,
    clippy::significant_drop_tightening,
    reason = "Keep the native Session and transferred Work alive for policy-denial checks, then explicitly release Work and close the shared Session."
)]
async fn consumed_surface_preserves_native_policy_without_arbitrary_javascript()
-> Result<(), Box<dyn Error>> {
    if !enabled() {
        return Ok(());
    }
    let fixture = Fixture::start().await?;
    let policy = Policy {
        page: Page::new(vec![
            Acquisition::Browser(BrowserMode::Headless).documents([DocumentRequest::RenderedDom]),
        ])?,
        ..Policy::default()
    };
    let mut settings = SessionPolicy::default();
    settings
        .allowed_actions
        .retain(|kind| !matches!(kind, ActionKind::EnterText | ActionKind::Scroll));
    let native = session::new()
        .bind(&policy)
        .configure(settings)
        .acquire()
        .await?;
    let proof = Box::pin(async {
        let work = Box::pin(native.work()).await?;
        assert!(matches!(
            work.evaluate("1").await,
            Err(session::SessionError::Denied)
        ));
        work.navigate(&format!("{}/b", fixture.base)).await?;
        work.release().await?;
        let mut source =
            surface::browser::consume_session(native.clone(), SurfacePolicy::default()).await?;
        hot(&mut source).await?;
        let field = reference(&mut source, "Message").await?;
        let denied = source
            .execute(json!({"op":"fill","reference":field,"text":"denied"}))
            .await?;
        assert_eq!(denied["receipt"]["status"], "Rejected");
        assert_eq!(denied["receipt"]["dispatched"], false);
        let status = source.execute(json!({"op":"status"})).await?;
        let root = status
            .get("root")
            .cloned()
            .ok_or_else(|| io::Error::other("status root missing"))?;
        let denied = source
            .execute(json!({"op":"scroll","reference":root,"delta_y":100}))
            .await?;
        assert_eq!(denied["receipt"]["status"], "Rejected");
        assert_eq!(denied["receipt"]["dispatched"], false);
        source.close().await?;
        let work = Box::pin(native.work()).await?;
        assert!(matches!(
            work.evaluate("1").await,
            Err(session::SessionError::Denied)
        ));
        work.release().await?;
        Ok::<(), Box<dyn Error>>(())
    })
    .await;
    let closed = native.close().await;
    fixture.close().await;
    proof?;
    closed?;
    Ok(())
}
