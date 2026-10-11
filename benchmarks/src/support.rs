use chrono::{DateTime, Utc};
use serde::Deserialize;
use std::{
    collections::BTreeMap,
    fmt::Write as FmtWrite,
    fs,
    io::{Read, Write as IoWrite},
    net::{Ipv4Addr, SocketAddr, TcpListener},
    path::PathBuf,
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, AtomicUsize, Ordering},
    },
    thread::{self, JoinHandle},
};
use yosoi_dev_support::internal::direct_http::*;
use yosoi_dev_support::internal::types::{CaptureId, Schema, SchemaId, SchemaVersion};

#[derive(Debug, Deserialize)]
pub struct Manifest {
    pub fixtures: Vec<Fixture>,
}
#[derive(Clone, Debug, Deserialize)]
pub struct Fixture {
    pub name: String,
    pub file: String,
    pub uncompressed_bytes: u64,
    pub encoded_bytes: u64,
    pub media_type: String,
    pub character_encoding: String,
    pub content_coding: String,
    pub extent: String,
    pub route: String,
}
pub fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("fixtures/web-capture/v1")
}
pub fn manifest() -> Manifest {
    serde_json::from_slice(
        &fs::read(root().join("manifest.json")).unwrap_or_else(|e| panic!("manifest read: {e}")),
    )
    .unwrap_or_else(|e| panic!("manifest parse: {e}"))
}
pub fn bytes(f: &Fixture) -> Vec<u8> {
    fs::read(root().join(&f.file)).unwrap_or_else(|e| panic!("fixture {}: {e}", f.name))
}
pub fn fixture(name: &str) -> Fixture {
    manifest()
        .fixtures
        .into_iter()
        .find(|f| f.name == name)
        .unwrap_or_else(|| panic!("fixture missing: {name}"))
}
pub fn capture_fixture() -> WebCapture {
    let path = root().join("complete-capture-v1.json");
    WebCaptureWire::from_json(&fs::read(path).unwrap_or_else(|e| panic!("wire read: {e}")))
        .unwrap_or_else(|e| panic!("wire parse: {e}"))
}
pub fn schema(name: &str) -> Schema {
    Schema::new(
        SchemaId::new(name).unwrap_or_else(|e| panic!("schema: {e}")),
        SchemaVersion::try_from(1).unwrap_or_else(|e| panic!("version: {e}")),
    )
}
pub fn started_at() -> DateTime<Utc> {
    DateTime::from_timestamp(1_700_000_000, 0).unwrap_or_else(|| panic!("timestamp"))
}

pub fn capture_spec(
    url: &str,
    limit: u64,
    redirects: DirectHttpRedirectPolicy,
) -> ResolvedDirectHttpCaptureSpec {
    capture_spec_with_limits(url, limit, limit, limit, redirects)
}

pub fn capture_spec_with_limits(
    url: &str,
    content_coded_limit: u64,
    representation_limit: u64,
    unicode_limit: u64,
    redirects: DirectHttpRedirectPolicy,
) -> ResolvedDirectHttpCaptureSpec {
    capture_spec_with_id(
        capture_fixture().id(),
        url,
        content_coded_limit,
        representation_limit,
        unicode_limit,
        redirects,
    )
}

#[allow(clippy::too_many_arguments)]
pub fn capture_spec_with_id(
    capture_id: CaptureId,
    url: &str,
    content_coded_limit: u64,
    representation_limit: u64,
    unicode_limit: u64,
    redirects: DirectHttpRedirectPolicy,
) -> ResolvedDirectHttpCaptureSpec {
    let capture = capture_fixture();
    let request = WebCaptureRequest::new(
        capture_id,
        RequestedWebTarget::parse(url).unwrap_or_else(|e| panic!("url: {e}")),
        WebAcquisitionStrategy::DirectHttp(DirectHttpAcquisition::new(
            DirectHttpTransportProfile::Standard,
            HttpSessionUse::Isolated,
        )),
    );
    ResolvedDirectHttpCaptureSpec::new(
        request,
        WebArtifactRequestSet::new(
            ArtifactRequest::Required,
            ArtifactRequest::NotRequested,
            ArtifactRequest::NotRequested,
            ArtifactRequest::Optional,
            ArtifactRequest::NotRequested,
            ArtifactRequest::NotRequested,
            ArtifactRequest::NotRequested,
            ArtifactRequest::NotRequested,
            ArtifactRequest::NotRequested,
        ),
        ObservationPolicy::new(
            ObservationLimits::new(
                CaptureDeadline::try_from(5_000_000).unwrap_or_else(|e| panic!("deadline: {e}")),
                None,
                None,
            ),
            SettlementPolicy::Disabled,
        ),
        DirectHttpContentLimits::new(
            ByteLimit::try_from(content_coded_limit)
                .unwrap_or_else(|e| panic!("content-coded limit: {e}")),
            ByteLimit::try_from(representation_limit)
                .unwrap_or_else(|e| panic!("representation limit: {e}")),
            ByteLimit::try_from(unicode_limit).unwrap_or_else(|e| panic!("Unicode limit: {e}")),
        ),
        redirects,
        AcceptedSourceFormats::new([
            AcceptedSourceFormat::Html,
            AcceptedSourceFormat::Json,
            AcceptedSourceFormat::Xml(XmlSourceProfile::Generic),
            AcceptedSourceFormat::PlainText,
        ])
        .unwrap_or_else(|e| panic!("formats: {e}")),
        UnsupportedSourceFormatBehavior::RetainAndReport,
        SourceRetentionPolicy::RepresentationAndUnicodeView,
        wreq_adapter_producer().unwrap_or_else(|e| panic!("producer: {e}")),
        capture
            .acquisition()
            .receipt()
            .receipt()
            .operation()
            .clone(),
        DirectHttpOutputSchemas::new(
            schema("com.cascadinglabs.yosoi.benchmark.source"),
            schema("com.cascadinglabs.yosoi.benchmark.source-representation"),
            Some(schema("com.cascadinglabs.yosoi.benchmark.network")),
            Some(schema("com.cascadinglabs.yosoi.benchmark.unicode")),
        ),
    )
    .unwrap_or_else(|e| panic!("spec: {e}"))
}

#[derive(Clone, Debug)]
pub struct Route {
    pub status: &'static str,
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
}
impl Route {
    pub fn body(body: Vec<u8>, media: &str, coding: Option<&str>) -> Self {
        let mut headers = vec![("Content-Type".into(), media.into())];
        if let Some(value) = coding {
            headers.push(("Content-Encoding".into(), value.into()));
        }
        Self {
            status: "200 OK",
            headers,
            body,
        }
    }
    pub fn redirect(location: &str) -> Self {
        Self {
            status: "302 Found",
            headers: vec![("Location".into(), location.into())],
            body: Vec::new(),
        }
    }
}
#[derive(Debug)]
pub struct LoopbackServer {
    address: SocketAddr,
    stop: Arc<AtomicBool>,
    requests: Arc<Mutex<Vec<String>>>,
    log_requests: Arc<AtomicBool>,
    request_count: Arc<AtomicUsize>,
    task: Option<JoinHandle<Result<(), String>>>,
}
impl LoopbackServer {
    pub fn start(routes: BTreeMap<String, Route>) -> Self {
        let listener =
            TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).unwrap_or_else(|e| panic!("bind: {e}"));
        listener
            .set_nonblocking(true)
            .unwrap_or_else(|e| panic!("nonblocking: {e}"));
        let address = listener
            .local_addr()
            .unwrap_or_else(|e| panic!("address: {e}"));
        assert!(address.ip().is_loopback());
        let stop = Arc::new(AtomicBool::new(false));
        let requests = Arc::new(Mutex::new(Vec::new()));
        let log_requests = Arc::new(AtomicBool::new(false));
        let request_count = Arc::new(AtomicUsize::new(0));
        let task_stop = Arc::clone(&stop);
        let task_requests = Arc::clone(&requests);
        let task_log_requests = Arc::clone(&log_requests);
        let task_request_count = Arc::clone(&request_count);
        let task = thread::spawn(move || {
            while !task_stop.load(Ordering::Acquire) {
                match listener.accept() {
                    Ok((mut stream, peer)) => {
                        assert!(peer.ip().is_loopback());
                        let mut request = [0_u8; 8192];
                        let read = stream
                            .read(&mut request)
                            .map_err(|e| format!("request read: {e}"))?;
                        let request_bytes = request.get(..read).unwrap_or_default();
                        let first = String::from_utf8_lossy(request_bytes)
                            .lines()
                            .next()
                            .unwrap_or("")
                            .to_owned();
                        let path = first.split_whitespace().nth(1).unwrap_or("/").to_owned();
                        task_request_count.fetch_add(1, Ordering::Relaxed);
                        if task_log_requests.load(Ordering::Acquire)
                            && let Ok(mut log) = task_requests.lock()
                        {
                            log.push(path.clone());
                        }
                        let route = routes
                            .get(&path)
                            .or_else(|| routes.get("/"))
                            .cloned()
                            .unwrap_or_else(|| Route::body(Vec::new(), "text/plain", None));
                        let mut head = format!(
                            "HTTP/1.1 {}\r\nContent-Length: {}\r\nConnection: close\r\n",
                            route.status,
                            route.body.len()
                        );
                        for (name, value) in route.headers {
                            write!(head, "{name}: {value}\r\n")
                                .unwrap_or_else(|e| panic!("response head format: {e}"));
                        }
                        head.push_str("\r\n");
                        stream
                            .write_all(head.as_bytes())
                            .map_err(|e| format!("response head write: {e}"))?;
                        stream
                            .write_all(&route.body)
                            .map_err(|e| format!("response body write: {e}"))?;
                    }
                    Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => thread::yield_now(),
                    Err(error) => return Err(format!("accept: {error}")),
                }
            }
            Ok(())
        });
        Self {
            address,
            stop,
            requests,
            log_requests,
            request_count,
            task: Some(task),
        }
    }
    pub fn url(&self, path: &str) -> String {
        format!("http://127.0.0.1:{}{path}", self.address.port())
    }
    pub fn enable_request_logging(&self) {
        if let Ok(mut paths) = self.requests.lock() {
            paths.clear();
        }
        self.log_requests.store(true, Ordering::Release);
    }
    pub fn take_request_paths(&self) -> Vec<String> {
        self.requests
            .lock()
            .map_or_else(|_| Vec::new(), |mut paths| std::mem::take(&mut *paths))
    }
    pub fn disable_request_logging(&self) {
        self.log_requests.store(false, Ordering::Release);
    }
    pub fn request_count(&self) -> usize {
        self.request_count.load(Ordering::Relaxed)
    }
}
impl Drop for LoopbackServer {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Release);
        let _ = std::net::TcpStream::connect(self.address);
        if let Some(task) = self.task.take() {
            task.join()
                .unwrap_or_else(|_| panic!("server task panicked"))
                .unwrap_or_else(|e| panic!("server task failed: {e}"));
        }
    }
}
