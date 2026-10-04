//! Loopback-only browser-adapter stimuli. This harness never launches a browser.
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    io,
    net::{IpAddr, Ipv4Addr, SocketAddr},
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
    time::Duration,
};
use thiserror::Error;
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    sync::{Mutex, Semaphore},
    task::{JoinError, JoinHandle, JoinSet},
    time::timeout,
};
use tokio_util::sync::CancellationToken;

pub const CORPUS_VERSION: u8 = 1;
pub const MANIFEST: &str = include_str!("fixtures/browser-acquisition-v1.json");
pub const SHELL_HTML: &[u8] = include_bytes!("fixtures/shell.html");
pub const SECONDARY_BYTES: &[u8] = include_bytes!("fixtures/secondary.json");
pub const SERVED_ROUTES: &[&str] = &[
    "/redirect",
    "/shell",
    "/secondary",
    "/delayed",
    "/endless",
    "/event-flood",
    "/byte-flood",
    "/partial",
    "/frame-parent",
    "/frame-child",
    "/cache",
    "/service-worker",
    "/sw.js",
    "/isolated-state",
    "/challenge",
];
const MAX_HEADER_BYTES: usize = 8 * 1024;
const MAX_FIXTURE_ERRORS: usize = 16;
const MAX_PREFIX_READ: usize = 16 * 1024;
const EVENT_COUNT: usize = 256;
const BYTE_FLOOD: usize = 65_536;
const DELAYED_BODY: &[u8] = b"released-by-durable-barrier";
const ENDLESS_CHUNK_PREFIX: &[u8] = b"6\r\nstart!\r\n";
const PARTIAL_RETAINED_PREFIX: &[u8] = b"partial";
const FRAME_PARENT_BODY: &[u8] = b"<!doctype html><iframe src='/frame-child'></iframe>";
const FRAME_CHILD_BODY: &[u8] = b"<!doctype html><main>child document epoch</main>";
const CACHE_BODY: &[u8] = b"cache";
const SERVICE_WORKER_PAGE: &[u8] =
    b"<!doctype html><script>navigator.serviceWorker.register('/sw.js')</script>";
const SERVICE_WORKER_SCRIPT: &[u8] =
    b"self.addEventListener('fetch', event => event.respondWith(fetch(event.request)))";
const ISOLATED_STATE_PAGE: &[u8] = b"<!doctype html><output id=isolation-result></output><script>const state=[document.cookie.includes('yosoi-isolation=seen')?'cookie-seen':'cookie-fresh',localStorage.getItem('yosoi-isolation')||'local-fresh',sessionStorage.getItem('yosoi-isolation')||'session-fresh'];document.cookie='yosoi-isolation=seen; SameSite=Lax';localStorage.setItem('yosoi-isolation','seen');sessionStorage.setItem('yosoi-isolation','seen');document.querySelector('#isolation-result').textContent=state.join('|')</script>";
const CHALLENGE_BODY: &[u8] =
    b"<!doctype html><title>Just a moment...</title><main>challenge fixture</main>";

#[derive(Debug, Error)]
pub enum FixtureError {
    #[error("fixture I/O failed: {0}")]
    Io(#[from] io::Error),
    #[error("connection task failed: {0}")]
    Task(String),
    #[error("fixture peer was not loopback: {0}")]
    NonLoopback(IpAddr),
    #[error("request header exceeds {MAX_HEADER_BYTES} bytes")]
    HeaderTooLarge,
    #[error("malformed HTTP request")]
    MalformedRequest,
    #[error("barrier was closed before release")]
    BarrierClosed,
    #[error("fixture URL path must be a nonempty slash path")]
    InvalidPath,
    #[error("active connection count overflow")]
    ActiveConnectionOverflow,
}

fn task_error(error: &JoinError) -> FixtureError {
    FixtureError::Task(error.to_string())
}

/// A counted barrier: permits persist when a consumer arrives after its producer.
#[derive(Debug)]
pub struct Barrier(Semaphore);
impl Default for Barrier {
    fn default() -> Self {
        Self(Semaphore::new(0))
    }
}
impl Barrier {
    pub fn release(&self) {
        self.0.add_permits(1);
    }
    pub async fn wait(&self) -> Result<(), FixtureError> {
        self.0
            .acquire()
            .await
            .map_err(|_| FixtureError::BarrierClosed)?
            .forget();
        Ok(())
    }
}

#[derive(Debug, Default)]
pub struct Barriers {
    pub redirect_requested: Barrier,
    pub shell_requested: Barrier,
    pub secondary_requested: Barrier,
    pub delayed_requested: Barrier,
    pub release_delayed: Barrier,
    pub delayed_written: Barrier,
    pub partial_requested: Barrier,
    pub endless_requested: Barrier,
    pub event_flood_requested: Barrier,
    pub byte_flood_requested: Barrier,
}
const EXPOSED_BARRIERS: &[&str] = &[
    "redirect_requested",
    "shell_requested",
    "secondary_requested",
    "delayed_requested",
    "release_delayed",
    "delayed_written",
    "partial_requested",
    "endless_requested",
    "event_flood_requested",
    "byte_flood_requested",
];

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ScenarioDescriptor {
    ProviderClose,
    RendererCrash,
    BrowserClose,
    DeadlineCancellation,
}
impl ScenarioDescriptor {
    const ALL: [Self; 4] = [
        Self::ProviderClose,
        Self::RendererCrash,
        Self::BrowserClose,
        Self::DeadlineCancellation,
    ];
    const fn name(self) -> &'static str {
        match self {
            Self::ProviderClose => "provider-close",
            Self::RendererCrash => "renderer-crash",
            Self::BrowserClose => "browser-close",
            Self::DeadlineCancellation => "deadline-cancellation",
        }
    }
}

#[derive(Debug)]
pub struct BrowserFixture {
    address: SocketAddr,
    shutdown: CancellationToken,
    task: JoinHandle<Result<(), FixtureError>>,
    requests: Arc<Mutex<Vec<String>>>,
    errors: Arc<Mutex<Vec<String>>>,
    active_connections: Arc<AtomicUsize>,
    pub barriers: Arc<Barriers>,
}
impl BrowserFixture {
    pub async fn start() -> Result<Self, FixtureError> {
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).await?;
        let address = listener.local_addr()?;
        let shutdown = CancellationToken::new();
        let barriers = Arc::new(Barriers::default());
        let requests = Arc::new(Mutex::new(Vec::new()));
        let errors = Arc::new(Mutex::new(Vec::new()));
        let active_connections = Arc::new(AtomicUsize::new(0));
        let task = tokio::spawn(accept_loop(
            listener,
            shutdown.clone(),
            barriers.clone(),
            requests.clone(),
            errors.clone(),
            active_connections.clone(),
        ));
        Ok(Self {
            address,
            shutdown,
            task,
            requests,
            errors,
            active_connections,
            barriers,
        })
    }
    pub fn url(&self, path: &str) -> Result<String, FixtureError> {
        if path.trim().is_empty()
            || !path.starts_with('/')
            || path
                .chars()
                .any(|character| character.is_control() || character.is_whitespace())
        {
            return Err(FixtureError::InvalidPath);
        }
        Ok(format!("http://127.0.0.1:{}{path}", self.address.port()))
    }
    pub async fn requests(&self) -> Vec<String> {
        self.requests.lock().await.clone()
    }
    pub async fn errors(&self) -> Vec<String> {
        self.errors.lock().await.clone()
    }
    pub fn active_connections(&self) -> usize {
        self.active_connections.load(Ordering::SeqCst)
    }
    pub async fn shutdown(self) -> Result<(), FixtureError> {
        let Self {
            shutdown,
            task,
            errors,
            active_connections,
            ..
        } = self;
        shutdown.cancel();
        task.await.map_err(|error| task_error(&error))??;
        if active_connections.load(Ordering::SeqCst) != 0 {
            return Err(FixtureError::Task(
                "connections remained after shutdown".into(),
            ));
        }
        let errors = errors.lock().await.clone();
        if errors.is_empty() {
            Ok(())
        } else {
            Err(FixtureError::Task(errors.join("; ")))
        }
    }
}

async fn record_error(errors: &Mutex<Vec<String>>, error: FixtureError) {
    let mut errors = errors.lock().await;
    if errors.len() < MAX_FIXTURE_ERRORS {
        errors.push(error.to_string());
    }
}
fn admit_active_connection(active: &AtomicUsize) -> Result<(), FixtureError> {
    active
        .try_update(Ordering::SeqCst, Ordering::SeqCst, |count| {
            count.checked_add(1)
        })
        .map(|_| ())
        .map_err(|_| FixtureError::ActiveConnectionOverflow)
}

async fn decrement_active(active: &AtomicUsize, errors: &Mutex<Vec<String>>) {
    if active
        .try_update(Ordering::SeqCst, Ordering::SeqCst, |count| {
            count.checked_sub(1)
        })
        .is_err()
    {
        record_error(
            errors,
            FixtureError::Task("active connection count underflow".into()),
        )
        .await;
    }
}
async fn accept_loop(
    listener: TcpListener,
    shutdown: CancellationToken,
    barriers: Arc<Barriers>,
    requests: Arc<Mutex<Vec<String>>>,
    errors: Arc<Mutex<Vec<String>>>,
    active: Arc<AtomicUsize>,
) -> Result<(), FixtureError> {
    let mut tasks = JoinSet::new();
    loop {
        tokio::select! {
            () = shutdown.cancelled() => break,
            joined = tasks.join_next(), if !tasks.is_empty() => if let Some(joined) = joined { match joined { Ok(Ok(())) => {}, Ok(Err(error)) => record_error(&errors, error).await, Err(error) => record_error(&errors, task_error(&error)).await } },
            accepted = listener.accept() => match accepted {
                Ok((stream, peer)) if peer.ip().is_loopback() => {
                    if admit_active_connection(&active).is_err() {
                        record_error(&errors, FixtureError::ActiveConnectionOverflow).await;
                        continue;
                    }
                    let task_active = active.clone(); let task_errors = errors.clone(); let task_shutdown = shutdown.clone(); let task_barriers = barriers.clone(); let task_requests = requests.clone();
                    tasks.spawn(async move { let result = serve(stream, task_shutdown, task_barriers, task_requests).await; decrement_active(&task_active, &task_errors).await; result });
                },
                Ok((_, peer)) => record_error(&errors, FixtureError::NonLoopback(peer.ip())).await,
                Err(error) => record_error(&errors, FixtureError::Io(error)).await,
            },
        }
    }
    shutdown.cancel();
    while let Some(joined) = tasks.join_next().await {
        match joined {
            Ok(Ok(())) => {}
            Ok(Err(error)) => record_error(&errors, error).await,
            Err(error) => record_error(&errors, task_error(&error)).await,
        }
    }
    Ok(())
}

async fn serve(
    mut stream: TcpStream,
    shutdown: CancellationToken,
    barriers: Arc<Barriers>,
    requests: Arc<Mutex<Vec<String>>>,
) -> Result<(), FixtureError> {
    let Some(path) = read_path(&mut stream, &shutdown).await? else {
        return Ok(());
    };
    requests.lock().await.push(path.clone());
    match path.as_str() {
        "/redirect" => { barriers.redirect_requested.release(); write_response(&mut stream, b"HTTP/1.1 302 Found\r\nLocation: /shell\r\nContent-Length: 0\r\n\r\n").await?; },
        "/shell" => { barriers.shell_requested.release(); write_ok(&mut stream, b"text/html; charset=utf-8", SHELL_HTML).await?; },
        "/secondary" => { barriers.secondary_requested.release(); write_ok(&mut stream, b"application/json", SECONDARY_BYTES).await?; },
        "/delayed" => { barriers.delayed_requested.release(); tokio::select! { () = shutdown.cancelled() => return Ok(()), result = barriers.release_delayed.wait() => result? } write_ok(&mut stream, b"text/plain", DELAYED_BODY).await?; barriers.delayed_written.release(); },
        "/endless" => { barriers.endless_requested.release(); write_head(&mut stream, b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nTransfer-Encoding: chunked\r\n\r\n").await?; stream.write_all(ENDLESS_CHUNK_PREFIX).await?; shutdown.cancelled().await; },
        "/event-flood" => { barriers.event_flood_requested.release(); write_ok(&mut stream, b"text/html", event_flood_html().as_bytes()).await?; },
        "/byte-flood" => { barriers.byte_flood_requested.release(); write_ok(&mut stream, b"application/octet-stream", &byte_flood()).await?; },
        "/partial" => { barriers.partial_requested.release(); write_head(&mut stream, b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 100\r\n\r\npartial").await?; },
        "/frame-parent" => write_ok(&mut stream, b"text/html", FRAME_PARENT_BODY).await?, "/frame-child" => write_ok(&mut stream, b"text/html", FRAME_CHILD_BODY).await?,
        "/cache" => write_head(&mut stream, b"HTTP/1.1 200 OK\r\nCache-Control: max-age=3600\r\nETag: \"fixture-v1\"\r\nContent-Length: 5\r\n\r\ncache").await?,
        "/service-worker" => write_ok(&mut stream, b"text/html", SERVICE_WORKER_PAGE).await?, "/sw.js" => write_ok(&mut stream, b"application/javascript", SERVICE_WORKER_SCRIPT).await?, "/isolated-state" => write_ok(&mut stream, b"text/html; charset=utf-8", ISOLATED_STATE_PAGE).await?,
        "/challenge" => write_challenge(&mut stream).await?,
        _ => write_response(&mut stream, b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n").await?,
    }
    Ok(())
}
async fn read_path(
    stream: &mut TcpStream,
    shutdown: &CancellationToken,
) -> Result<Option<String>, FixtureError> {
    let mut request = Vec::with_capacity(1024);
    let mut chunk = [0_u8; 1024];
    loop {
        if request.windows(4).any(|bytes| bytes == b"\r\n\r\n") {
            break;
        }
        if request.len() >= MAX_HEADER_BYTES {
            return Err(FixtureError::HeaderTooLarge);
        }
        let remaining = MAX_HEADER_BYTES
            .checked_sub(request.len())
            .ok_or(FixtureError::HeaderTooLarge)?;
        let limit = remaining.min(chunk.len());
        let readable = chunk.get_mut(..limit).ok_or(FixtureError::HeaderTooLarge)?;
        let count = tokio::select! { () = shutdown.cancelled() => return Ok(None), result = stream.read(readable) => result? };
        if count == 0 {
            return Ok(None);
        }
        request.extend_from_slice(chunk.get(..count).ok_or(FixtureError::MalformedRequest)?);
    }
    let line_end = request
        .windows(2)
        .position(|bytes| bytes == b"\r\n")
        .ok_or(FixtureError::MalformedRequest)?;
    let line = request
        .get(..line_end)
        .ok_or(FixtureError::MalformedRequest)?;
    let mut parts = line.split(|byte| *byte == b' ');
    let method = parts.next();
    let path = parts.next();
    let version = parts.next();
    if method != Some(b"GET".as_slice())
        || parts.next().is_some()
        || !matches!(version, Some(b"HTTP/1.0" | b"HTTP/1.1"))
    {
        return Err(FixtureError::MalformedRequest);
    }
    let path = path
        .filter(|path| !path.is_empty() && path.starts_with(b"/"))
        .ok_or(FixtureError::MalformedRequest)?;
    String::from_utf8(path.to_vec())
        .map(Some)
        .map_err(|_| FixtureError::MalformedRequest)
}
async fn write_ok(
    stream: &mut TcpStream,
    content_type: &[u8],
    body: &[u8],
) -> Result<(), FixtureError> {
    let head = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: {}\r\nContent-Length: {}\r\n\r\n",
        String::from_utf8_lossy(content_type),
        body.len()
    );
    write_head(stream, head.as_bytes()).await?;
    stream.write_all(body).await?;
    Ok(())
}
async fn write_response(stream: &mut TcpStream, response: &[u8]) -> Result<(), FixtureError> {
    stream.write_all(response).await?;
    Ok(())
}
async fn write_challenge(stream: &mut TcpStream) -> Result<(), FixtureError> {
    let head = format!(
        "HTTP/1.1 403 Forbidden\r\nContent-Type: text/html\r\nServer: cloudflare\r\nCf-Mitigated: challenge\r\nContent-Length: {}\r\n\r\n",
        CHALLENGE_BODY.len()
    );
    write_head(stream, head.as_bytes()).await?;
    stream.write_all(CHALLENGE_BODY).await?;
    Ok(())
}
async fn write_head(stream: &mut TcpStream, head: &[u8]) -> Result<(), FixtureError> {
    stream.write_all(head).await?;
    Ok(())
}
fn event_flood_html() -> String {
    use std::fmt::Write;
    let mut events = String::from("<!doctype html><script>");
    for index in 0..EVENT_COUNT {
        let _ = write!(events, "console.log('fixture-event-{index}');");
    }
    events.push_str("</script>");
    events
}
fn byte_flood() -> Vec<u8> {
    vec![b'x'; BYTE_FLOOD]
}
pub fn sha256_hex(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn body_facts() -> BTreeMap<&'static str, Vec<u8>> {
    [
        ("/redirect", Vec::new()),
        ("/shell", SHELL_HTML.to_vec()),
        ("/secondary", SECONDARY_BYTES.to_vec()),
        ("/delayed", DELAYED_BODY.to_vec()),
        ("/endless", ENDLESS_CHUNK_PREFIX.to_vec()),
        ("/event-flood", event_flood_html().into_bytes()),
        ("/byte-flood", byte_flood()),
        ("/partial", PARTIAL_RETAINED_PREFIX.to_vec()),
        ("/frame-parent", FRAME_PARENT_BODY.to_vec()),
        ("/frame-child", FRAME_CHILD_BODY.to_vec()),
        ("/cache", CACHE_BODY.to_vec()),
        ("/service-worker", SERVICE_WORKER_PAGE.to_vec()),
        ("/sw.js", SERVICE_WORKER_SCRIPT.to_vec()),
        ("/isolated-state", ISOLATED_STATE_PAGE.to_vec()),
        ("/challenge", CHALLENGE_BODY.to_vec()),
        ("404", Vec::new()),
    ]
    .into_iter()
    .collect()
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Manifest {
    schema: String,
    version: u8,
    provenance: Provenance,
    fixtures: BTreeMap<String, FixtureFile>,
    responses: BTreeMap<String, BodyFact>,
    scenarios: Vec<Scenario>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Provenance {
    network: String,
    browser_execution: String,
    headless_default: bool,
    headful_compatible: bool,
    pixel_equality: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct FixtureFile {
    sha256: String,
    source_vs_dom: Option<String>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BodyFact {
    bytes: usize,
    sha256: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Scenario {
    id: String,
    routes: Option<Vec<String>>,
    barriers: Option<Vec<String>>,
    descriptor: Option<String>,
    expected: Vec<String>,
}
fn parse_manifest(value: &str) -> Result<Manifest, serde_json::Error> {
    serde_json::from_str(value)
}
fn manifest() -> Manifest {
    parse_manifest(MANIFEST).expect("embedded manifest must be valid")
}
fn has_duplicates(values: &[String]) -> bool {
    values.iter().collect::<BTreeSet<_>>().len() != values.len()
}

#[test]
fn manifest_parser_rejects_unknown_and_malformed_shapes() {
    assert!(parse_manifest("{}").is_err());
    assert!(
        parse_manifest(r#"{"schema":"yosoi.browser-acquisition-fixture","unknown":true}"#).is_err()
    );
}
fn assert_manifest_metadata_and_bodies(manifest: &Manifest) {
    assert_eq!(manifest.schema, "yosoi.browser-acquisition-fixture");
    assert_eq!(manifest.version, CORPUS_VERSION);
    assert_eq!(manifest.provenance.network, "loopback-only");
    assert_eq!(manifest.provenance.browser_execution, "not-required");
    assert!(manifest.provenance.headless_default && manifest.provenance.headful_compatible);
    assert_eq!(manifest.provenance.pixel_equality, "not-asserted");
    let facts = body_facts();
    assert_eq!(manifest.responses.len(), facts.len());
    for (name, bytes) in facts {
        let fact = manifest.responses.get(name).expect("body fact exists");
        assert_eq!(fact.bytes, bytes.len(), "{name}");
        assert_eq!(fact.sha256, sha256_hex(&bytes), "{name}");
    }
}
fn assert_manifest_files(manifest: &Manifest) {
    let digests: BTreeMap<_, _> = [
        ("shell.html", sha256_hex(SHELL_HTML)),
        ("secondary.json", sha256_hex(SECONDARY_BYTES)),
    ]
    .into_iter()
    .collect();
    assert_eq!(manifest.fixtures.len(), digests.len());
    for (name, digest) in digests {
        assert_eq!(
            manifest.fixtures.get(name).map(|file| &file.sha256),
            Some(&digest)
        );
    }
    assert_eq!(
        manifest
            .fixtures
            .get("shell.html")
            .and_then(|file| file.source_vs_dom.as_deref()),
        Some("source contains shell; live DOM contains secondary message")
    );
}
fn assert_manifest_scenarios(manifest: &Manifest) {
    let descriptors: BTreeSet<_> = ScenarioDescriptor::ALL
        .into_iter()
        .map(ScenarioDescriptor::name)
        .collect();
    let mut ids = BTreeSet::new();
    let mut routes: BTreeSet<String> = BTreeSet::new();
    let mut barriers: BTreeSet<String> = BTreeSet::new();
    let mut named_descriptors: BTreeSet<&str> = BTreeSet::new();
    for scenario in &manifest.scenarios {
        assert_ne!(scenario.id.trim(), "");
        assert!(ids.insert(&scenario.id));
        assert_ne!(scenario.routes.is_some(), scenario.descriptor.is_some());
        assert_ne!(scenario.expected.len(), 0);
        assert!(scenario.expected.iter().all(|fact| !fact.trim().is_empty()));
        let scenario_routes = scenario.routes.as_deref().unwrap_or_default();
        let scenario_barriers = scenario.barriers.as_deref().unwrap_or_default();
        assert!(!has_duplicates(scenario_routes));
        assert!(!has_duplicates(scenario_barriers));
        for route in scenario_routes {
            assert!(SERVED_ROUTES.contains(&route.as_str()));
            assert!(routes.insert(route.clone()));
        }
        for barrier in scenario_barriers {
            assert!(EXPOSED_BARRIERS.contains(&barrier.as_str()));
            assert!(barriers.insert(barrier.clone()));
        }
        if let Some(descriptor) = &scenario.descriptor {
            assert_ne!(descriptor.trim(), "");
            assert!(descriptors.contains(descriptor.as_str()));
            assert!(named_descriptors.insert(descriptor.as_str()));
        }
    }
    assert_eq!(
        routes,
        SERVED_ROUTES
            .iter()
            .map(|route| (*route).to_owned())
            .collect()
    );
    assert_eq!(
        barriers,
        EXPOSED_BARRIERS
            .iter()
            .map(|barrier| (*barrier).to_owned())
            .collect()
    );
    assert_eq!(named_descriptors, descriptors);
}
#[test]
fn manifest_is_a_strict_complete_contract() {
    let manifest = manifest();
    assert_manifest_metadata_and_bodies(&manifest);
    assert_manifest_files(&manifest);
    assert_manifest_scenarios(&manifest);
}

async fn request(fixture: &BrowserFixture, route: &str) -> TcpStream {
    let mut stream = TcpStream::connect(fixture.address)
        .await
        .expect("loopback connection");
    stream
        .write_all(format!("GET {route} HTTP/1.1\r\nHost: localhost\r\n\r\n").as_bytes())
        .await
        .expect("request write");
    stream
}
async fn response(stream: &mut TcpStream) -> Vec<u8> {
    let mut bytes = Vec::new();
    stream.read_to_end(&mut bytes).await.expect("response read");
    bytes
}
async fn read_until_contains(stream: &mut TcpStream, needle: &[u8]) -> io::Result<Vec<u8>> {
    let mut bytes = Vec::new();
    let mut chunk = [0_u8; 512];
    while bytes.len() < MAX_PREFIX_READ && !bytes.windows(needle.len()).any(|part| part == needle) {
        let remaining = MAX_PREFIX_READ
            .checked_sub(bytes.len())
            .ok_or_else(|| io::Error::other("prefix read limit"))?;
        let limit = remaining.min(chunk.len());
        let count = timeout(
            Duration::from_secs(5),
            stream.read(
                chunk
                    .get_mut(..limit)
                    .ok_or_else(|| io::Error::other("prefix buffer"))?,
            ),
        )
        .await
        .map_err(|_| io::Error::new(io::ErrorKind::TimedOut, "prefix read deadline exceeded"))??;
        if count == 0 {
            break;
        }
        bytes.extend_from_slice(
            chunk
                .get(..count)
                .ok_or_else(|| io::Error::other("prefix count"))?,
        );
    }
    Ok(bytes)
}

#[tokio::test]
async fn composite_receipts_and_source_stimulus_are_exact() {
    let fixture = BrowserFixture::start().await.expect("start");
    let mut redirect = request(&fixture, "/redirect").await;
    fixture
        .barriers
        .redirect_requested
        .wait()
        .await
        .expect("barrier");
    assert_eq!(
        response(&mut redirect).await,
        b"HTTP/1.1 302 Found\r\nLocation: /shell\r\nContent-Length: 0\r\n\r\n"
    );
    let mut shell = request(&fixture, "/shell").await;
    fixture
        .barriers
        .shell_requested
        .wait()
        .await
        .expect("barrier");
    assert!(response(&mut shell).await.ends_with(SHELL_HTML));
    let secondary: serde_json::Value =
        serde_json::from_slice(SECONDARY_BYTES).expect("secondary JSON");
    let message = secondary
        .get("message")
        .and_then(serde_json::Value::as_str)
        .expect("message");
    assert!(
        !SHELL_HTML
            .windows(message.len())
            .any(|part| part == message.as_bytes())
    );
    assert!(
        SHELL_HTML
            .windows(b"fetch(\"/secondary\")".len())
            .any(|part| part == b"fetch(\"/secondary\")")
    );
    assert!(
        SHELL_HTML
            .windows(b"payload.message".len())
            .any(|part| part == b"payload.message")
    );
    assert!(
        SHELL_HTML
            .windows(b"live.textContent = payload.message".len())
            .any(|part| part == b"live.textContent = payload.message")
    );
    let mut secondary = request(&fixture, "/secondary").await;
    fixture
        .barriers
        .secondary_requested
        .wait()
        .await
        .expect("barrier");
    assert!(response(&mut secondary).await.ends_with(SECONDARY_BYTES));
    assert_eq!(
        fixture.requests().await,
        vec!["/redirect", "/shell", "/secondary"]
    );
    fixture.shutdown().await.expect("clean shutdown");
}

#[tokio::test]
async fn delayed_endless_partial_and_flood_stimuli_are_exact() {
    let fixture = BrowserFixture::start().await.expect("start");
    let mut delayed = request(&fixture, "/delayed").await;
    fixture
        .barriers
        .delayed_requested
        .wait()
        .await
        .expect("barrier");
    let mut probe = [0; 1];
    assert_eq!(
        delayed
            .try_read(&mut probe)
            .expect_err("body blocked")
            .kind(),
        io::ErrorKind::WouldBlock
    );
    fixture.barriers.release_delayed.release();
    fixture
        .barriers
        .delayed_written
        .wait()
        .await
        .expect("barrier");
    assert!(response(&mut delayed).await.ends_with(DELAYED_BODY));
    let mut endless = request(&fixture, "/endless").await;
    fixture
        .barriers
        .endless_requested
        .wait()
        .await
        .expect("barrier");
    assert!(
        read_until_contains(&mut endless, ENDLESS_CHUNK_PREFIX)
            .await
            .expect("endless prefix")
            .windows(ENDLESS_CHUNK_PREFIX.len())
            .any(|part| part == ENDLESS_CHUNK_PREFIX)
    );
    assert_eq!(fixture.active_connections(), 1);
    let mut partial = request(&fixture, "/partial").await;
    fixture
        .barriers
        .partial_requested
        .wait()
        .await
        .expect("barrier");
    assert!(
        response(&mut partial)
            .await
            .ends_with(PARTIAL_RETAINED_PREFIX)
    );
    let mut events = request(&fixture, "/event-flood").await;
    fixture
        .barriers
        .event_flood_requested
        .wait()
        .await
        .expect("barrier");
    assert_eq!(
        response(&mut events)
            .await
            .windows(b"console.log".len())
            .filter(|part| *part == b"console.log")
            .count(),
        EVENT_COUNT
    );
    let mut flood = request(&fixture, "/byte-flood").await;
    fixture
        .barriers
        .byte_flood_requested
        .wait()
        .await
        .expect("barrier");
    assert!(response(&mut flood).await.ends_with(&byte_flood()));
    fixture.shutdown().await.expect("clean shutdown");
}

#[tokio::test]
async fn auxiliary_routes_and_parallel_servers_are_isolated() {
    let first = BrowserFixture::start().await.expect("first");
    let second = BrowserFixture::start().await.expect("second");
    assert_ne!(first.address, second.address);
    assert!(
        first
            .url("/shell")
            .expect("valid URL")
            .starts_with("http://127.0.0.1:")
    );
    assert!(first.url("shell").is_err());
    assert!(first.url("/shell path").is_err());
    assert!(first.url("/shell\npath").is_err());
    for route in [
        "/frame-parent",
        "/frame-child",
        "/cache",
        "/service-worker",
        "/sw.js",
        "/missing",
    ] {
        let mut stream = request(&first, route).await;
        let bytes = response(&mut stream).await;
        match route {
            "/frame-parent" => assert!(bytes.ends_with(FRAME_PARENT_BODY)),
            "/frame-child" => assert!(bytes.ends_with(FRAME_CHILD_BODY)),
            "/cache" => assert!(bytes.ends_with(CACHE_BODY)),
            "/service-worker" => assert!(bytes.ends_with(SERVICE_WORKER_PAGE)),
            "/sw.js" => assert!(bytes.ends_with(SERVICE_WORKER_SCRIPT)),
            _ => assert_eq!(
                bytes,
                b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n"
            ),
        }
    }
    assert_eq!(second.requests().await, Vec::<String>::new());
    first.shutdown().await.expect("first shutdown");
    second.shutdown().await.expect("second shutdown");
}

#[test]
fn active_connection_admission_rejects_overflow() {
    let active = AtomicUsize::new(usize::MAX);
    assert!(matches!(
        admit_active_connection(&active),
        Err(FixtureError::ActiveConnectionOverflow)
    ));
    assert_eq!(active.load(Ordering::SeqCst), usize::MAX);
}

#[tokio::test]
async fn malformed_connections_are_observable_without_stopping_acceptance() {
    let fixture = BrowserFixture::start().await.expect("start");
    let mut bad = TcpStream::connect(fixture.address).await.expect("connect");
    bad.write_all(b"POST /shell HTTP/2\r\n\r\n")
        .await
        .expect("bad write");
    let _ = response(&mut bad).await;
    let mut good = request(&fixture, "/shell").await;
    fixture
        .barriers
        .shell_requested
        .wait()
        .await
        .expect("barrier");
    assert!(response(&mut good).await.ends_with(SHELL_HTML));
    assert_ne!(fixture.errors().await, Vec::<String>::new());
    assert!(fixture.shutdown().await.is_err());
}

#[tokio::test]
async fn split_and_strict_headers_do_not_escape_bounds() {
    let fixture = BrowserFixture::start().await.expect("start");
    let mut split = TcpStream::connect(fixture.address).await.expect("connect");
    split
        .write_all(b"GET /shell HTTP/1.1\r\nHost: local")
        .await
        .expect("first split");
    split
        .write_all(b"host\r\n\r\n")
        .await
        .expect("second split");
    fixture
        .barriers
        .shell_requested
        .wait()
        .await
        .expect("barrier");
    assert!(response(&mut split).await.ends_with(SHELL_HTML));
    for bad_line in [
        b"GET /shell HTTP/2\r\n\r\n".as_slice(),
        b"GET /shell HTTP/1.1 extra\r\n\r\n",
        b"GET  HTTP/1.1\r\n\r\n",
    ] {
        let mut bad = TcpStream::connect(fixture.address).await.expect("connect");
        bad.write_all(bad_line).await.expect("bad write");
        let _ = response(&mut bad).await;
    }
    let mut good = request(&fixture, "/secondary").await;
    fixture
        .barriers
        .secondary_requested
        .wait()
        .await
        .expect("barrier");
    assert!(response(&mut good).await.ends_with(SECONDARY_BYTES));
    assert!(fixture.shutdown().await.is_err());
}
