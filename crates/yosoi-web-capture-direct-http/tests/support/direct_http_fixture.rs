#![allow(
    dead_code,
    clippy::absolute_paths,
    clippy::ignored_unit_patterns,
    clippy::missing_const_for_fn,
    clippy::semicolon_if_nothing_returned,
    clippy::single_match_else,
    clippy::unwrap_used,
    clippy::cognitive_complexity,
    clippy::struct_field_names,
    reason = "explicit deterministic test fixture control flow"
)]
//! Deterministic loopback-only HTTP/1.1 fixture used by integration tests.
use std::{
    collections::HashMap,
    net::{IpAddr, SocketAddr},
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
    time::Duration,
};
use tokio::{
    io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt},
    net::TcpListener,
    sync::{Mutex, Semaphore},
    task::{JoinHandle, JoinSet},
};
use tokio_rustls::{
    TlsAcceptor,
    rustls::{
        ServerConfig,
        pki_types::{CertificateDer, PrivateKeyDer, PrivatePkcs8KeyDer},
    },
};
use tokio_util::sync::CancellationToken;

const CERT: &[u8] = include_bytes!("../fixtures/direct-http-tls/cert.der");
const KEY: &[u8] = include_bytes!("../fixtures/direct-http-tls/key.der");

#[derive(Clone, Copy, Debug)]
pub enum Protocol {
    Http,
    Https,
}

/// A durable one-shot/multi-shot synchronization point (unlike `Notify`, signals are not lost).
#[derive(Debug)]
pub struct Signal(Semaphore);
impl Default for Signal {
    fn default() -> Self {
        Self(Semaphore::new(0))
    }
}
impl Signal {
    pub fn signal(&self) {
        self.0.add_permits(1);
    }
    pub async fn wait(&self) {
        self.0.acquire().await.unwrap().forget();
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RequestLine {
    pub method: String,
    pub path: String,
    pub line: Vec<u8>,
}

#[derive(Debug, Default)]
pub struct ResponseControl {
    /// Signalled after the request is parsed and logged, before any response bytes are written.
    pub requested: Signal,
    /// If true, serving pauses before the response head until `allow_head` is signalled.
    pub hold_before_head: bool,
    pub allow_head: Signal,
    pub head_written: Signal,
    /// One durable signal is emitted after each complete configured chunk write.
    pub chunk_written: Signal,
    /// If true, serving pauses after every chunk until `allow_next_chunk` is signalled.
    pub hold_after_chunks: bool,
    pub allow_next_chunk: Signal,
    pub connection_finished: Signal,
}

#[derive(Clone, Debug)]
pub struct Response {
    pub status: u16,
    pub reason: &'static str,
    /// Exact field lines without CRLF. Repetitions and invalid values are preserved.
    pub raw_headers: Vec<Vec<u8>>,
    pub chunks: Vec<Vec<u8>>,
    pub delay_before_head: Duration,
    pub delay_between_chunks: Duration,
    pub close_after_chunks: Option<usize>,
    /// Exact head bytes, replacing the generated status line, headers, and final CRLF.
    pub raw_head: Option<Vec<u8>>,
    /// Exact complete response bytes. When present no generated head/chunks are written.
    pub raw_response: Option<Vec<u8>>,
    pub control: Option<Arc<ResponseControl>>,
}
impl Response {
    pub fn bytes(status: u16, content_type: Option<&str>, bytes: &[u8]) -> Self {
        let mut raw_headers = Vec::new();
        if let Some(value) = content_type {
            raw_headers.push(format!("Content-Type: {value}").into_bytes());
        }
        raw_headers.push(format!("Content-Length: {}", bytes.len()).into_bytes());
        Self {
            status,
            reason: reason(status),
            raw_headers,
            chunks: vec![bytes.to_vec()],
            delay_before_head: Duration::ZERO,
            delay_between_chunks: Duration::ZERO,
            close_after_chunks: None,
            raw_head: None,
            raw_response: None,
            control: None,
        }
    }
    pub fn raw(bytes: impl Into<Vec<u8>>) -> Self {
        Self {
            raw_response: Some(bytes.into()),
            ..Self::bytes(200, None, b"")
        }
    }
    pub fn redirect(location: &str) -> Self {
        assert_safe_redirect_destination(location);
        let mut response = Self::bytes(302, None, b"");
        response
            .raw_headers
            .push(format!("Location: {location}").into_bytes());
        response
    }
}

pub struct FixtureService {
    address: SocketAddr,
    protocol: Protocol,
    shutdown: CancellationToken,
    task: JoinHandle<()>,
    requests: Arc<Mutex<Vec<RequestLine>>>,
    active_connections: Arc<AtomicUsize>,
}
impl FixtureService {
    pub async fn start(
        protocol: Protocol,
        routes: impl IntoIterator<Item = (String, Response)>,
    ) -> Self {
        let listener = TcpListener::bind((std::net::Ipv4Addr::LOCALHOST, 0))
            .await
            .unwrap();
        let address = listener.local_addr().unwrap();
        assert_loopback(address.ip());
        let routes = Arc::new(routes.into_iter().collect::<HashMap<_, _>>());
        let requests = Arc::new(Mutex::new(Vec::new()));
        let active_connections = Arc::new(AtomicUsize::new(0));
        let shutdown = CancellationToken::new();
        let task_shutdown = shutdown.clone();
        let task_requests = requests.clone();
        let task_active = active_connections.clone();
        let task = tokio::spawn(async move {
            let tls = match protocol {
                Protocol::Http => None,
                Protocol::Https => Some(tls_acceptor()),
            };
            let mut connections = JoinSet::new();
            loop {
                tokio::select! {
                    _ = task_shutdown.cancelled() => break,
                    Some(result) = connections.join_next(), if !connections.is_empty() => {
                        result.unwrap();
                    }
                    accepted = listener.accept() => {
                        let Ok((stream, peer)) = accepted else { break };
                        assert_loopback(peer.ip());
                        let routes = routes.clone();
                        let tls = tls.clone();
                        let requests = task_requests.clone();
                        let shutdown = task_shutdown.clone();
                        let active = task_active.clone();
                        active.fetch_add(1, Ordering::SeqCst);
                        connections.spawn(async move {
                            match tls {
                                Some(acceptor) => {
                                    if let Ok(mut stream) = acceptor.accept(stream).await {
                                        serve(&mut stream, &routes, &requests, &shutdown).await;
                                    }
                                }
                                None => {
                                    let mut stream = stream;
                                    serve(&mut stream, &routes, &requests, &shutdown).await;
                                }
                            }
                            active.fetch_sub(1, Ordering::SeqCst);
                        });
                    }
                }
            }
            task_shutdown.cancel();
            while let Some(result) = connections.join_next().await {
                result.unwrap();
            }
        });
        Self {
            address,
            protocol,
            shutdown,
            task,
            requests,
            active_connections,
        }
    }
    pub fn url(&self, path: &str) -> String {
        assert!(path.starts_with('/'));
        assert_loopback(self.address.ip());
        let scheme = match self.protocol {
            Protocol::Http => "http",
            Protocol::Https => "https",
        };
        format!("{scheme}://localhost:{}{path}", self.address.port())
    }
    pub fn address(&self) -> SocketAddr {
        self.address
    }
    pub async fn requests(&self) -> Vec<RequestLine> {
        self.requests.lock().await.clone()
    }
    pub fn active_connections(&self) -> usize {
        self.active_connections.load(Ordering::SeqCst)
    }
    pub async fn shutdown(self) {
        self.shutdown.cancel();
        self.task.await.unwrap();
        assert_eq!(self.active_connections.load(Ordering::SeqCst), 0);
    }
}

async fn serve<S: AsyncRead + AsyncWrite + Unpin>(
    stream: &mut S,
    routes: &HashMap<String, Response>,
    requests: &Mutex<Vec<RequestLine>>,
    shutdown: &CancellationToken,
) {
    let Some(request) = read_request(stream, shutdown).await else {
        return;
    };
    let first_line = request
        .split(|byte| *byte == b'\n')
        .next()
        .unwrap_or_default();
    let line = first_line.strip_suffix(b"\r").unwrap_or(first_line);
    let mut parts = line.split(|byte| *byte == b' ');
    let method = String::from_utf8_lossy(parts.next().unwrap_or_default()).into_owned();
    let path = String::from_utf8_lossy(parts.next().unwrap_or(b"/")).into_owned();
    requests.lock().await.push(RequestLine {
        method,
        path: path.clone(),
        line: line.to_vec(),
    });
    let response = routes
        .get(&path)
        .cloned()
        .unwrap_or_else(|| Response::bytes(404, Some("text/plain"), b"missing fixture route"));
    let control = response.control.clone();
    if let Some(value) = &control {
        value.requested.signal();
        if value.hold_before_head && wait_or_shutdown(&value.allow_head, shutdown).await {
            return;
        }
    }
    if !response.delay_before_head.is_zero() {
        tokio::select! { _ = shutdown.cancelled() => return, _ = tokio::time::sleep(response.delay_before_head) => {} }
    }
    if let Some(raw) = response.raw_response {
        let _ = stream.write_all(&raw).await;
        if let Some(value) = &control {
            value.head_written.signal();
            value.connection_finished.signal();
        }
        return;
    }
    let mut head = response
        .raw_head
        .clone()
        .unwrap_or_else(|| generated_head(&response));
    if stream.write_all(&head).await.is_err() {
        return;
    }
    head.clear();
    if let Some(value) = &control {
        value.head_written.signal();
    }
    for (index, chunk) in response.chunks.iter().enumerate() {
        if response.close_after_chunks == Some(index) {
            break;
        }
        if stream.write_all(chunk).await.is_err() {
            break;
        }
        if let Some(value) = &control {
            value.chunk_written.signal();
            if value.hold_after_chunks && wait_or_shutdown(&value.allow_next_chunk, shutdown).await
            {
                break;
            }
        }
        if !response.delay_between_chunks.is_zero() {
            tokio::select! { _ = shutdown.cancelled() => break, _ = tokio::time::sleep(response.delay_between_chunks) => {} }
        }
    }
    let _ = stream.shutdown().await;
    if let Some(value) = &control {
        value.connection_finished.signal();
    }
}

async fn read_request<S: AsyncRead + Unpin>(
    stream: &mut S,
    shutdown: &CancellationToken,
) -> Option<Vec<u8>> {
    let mut request = Vec::with_capacity(1024);
    let mut byte = [0_u8; 1];
    while request.len() < 16 * 1024 {
        let read = tokio::select! { _ = shutdown.cancelled() => return None, value = stream.read(&mut byte) => value };
        match read {
            Ok(0) | Err(_) => return None,
            Ok(_) => request.push(byte[0]),
        }
        if request.ends_with(b"\r\n\r\n") {
            return Some(request);
        }
    }
    None
}
async fn wait_or_shutdown(signal: &Signal, shutdown: &CancellationToken) -> bool {
    tokio::select! { _ = shutdown.cancelled() => true, _ = signal.wait() => false }
}
fn generated_head(response: &Response) -> Vec<u8> {
    let mut head = format!("HTTP/1.1 {} {}\r\n", response.status, response.reason).into_bytes();
    for header in &response.raw_headers {
        head.extend_from_slice(header);
        head.extend_from_slice(b"\r\n");
    }
    head.extend_from_slice(b"\r\n");
    head
}
fn tls_acceptor() -> TlsAcceptor {
    let config = ServerConfig::builder()
        .with_no_client_auth()
        .with_single_cert(
            vec![CertificateDer::from(CERT.to_vec())],
            PrivateKeyDer::Pkcs8(PrivatePkcs8KeyDer::from(KEY.to_vec())),
        )
        .unwrap();
    TlsAcceptor::from(Arc::new(config))
}
fn assert_loopback(ip: IpAddr) {
    assert!(ip.is_loopback(), "fixture endpoint must be loopback: {ip}");
}
fn assert_safe_redirect_destination(location: &str) {
    if let Ok(url) = url::Url::parse(location)
        && matches!(url.scheme(), "http" | "https")
    {
        let host = url.host_str().and_then(|host| host.parse::<IpAddr>().ok());
        assert!(
            host.is_some_and(|ip| ip.is_loopback()) || url.host_str() == Some("localhost"),
            "fixture redirect must remain loopback: {location}"
        );
    }
}
const fn reason(status: u16) -> &'static str {
    match status {
        200 => "OK",
        201 => "Created",
        301 => "Moved Permanently",
        302 => "Found",
        303 => "See Other",
        307 => "Temporary Redirect",
        308 => "Permanent Redirect",
        404 => "Not Found",
        500 => "Internal Server Error",
        _ => "Fixture",
    }
}
/// Certificate DER for constructing a pinned fixture-only client.
pub const fn certificate_der() -> &'static [u8] {
    CERT
}
