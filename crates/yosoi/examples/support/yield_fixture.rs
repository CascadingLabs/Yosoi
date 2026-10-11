//! A real HTTP quote service. Controlled completions are test events; timed
//! completions model upstream I/O latency for the live comparison, not polling.
use std::{
    io,
    net::Ipv4Addr,
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    sync::{Notify, Semaphore, broadcast, oneshot},
    task::{JoinHandle, JoinSet},
};

pub struct QuoteService {
    pub base: String,
    pub started: broadcast::Receiver<u32>,
    requests: broadcast::Sender<RequestArrival>,
    completed: Arc<Vec<Notify>>,
    shutdown: Option<oneshot::Sender<()>>,
    task: JoinHandle<io::Result<()>>,
}
#[derive(Clone, Copy, Debug)]
pub struct RequestArrival {
    pub id: u32,
    pub at: Instant,
}
impl QuoteService {
    pub async fn start(latency: Option<Duration>) -> io::Result<Self> {
        Self::start_bottleneck(latency, None).await
    }
    pub async fn start_bottleneck(
        latency: Option<Duration>,
        backend_concurrency: Option<u32>,
    ) -> io::Result<Self> {
        let backend = match backend_concurrency {
            Some(n) if n > 0 => Some(Arc::new(Semaphore::new(
                usize::try_from(n).map_err(io::Error::other)?,
            ))),
            Some(_) => return Err(io::Error::other("backend concurrency must be positive")),
            None => None,
        };
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).await?;
        let base = format!("http://{}", listener.local_addr()?);
        let (shutdown, mut stopping) = oneshot::channel();
        let (events, started) = broadcast::channel(64);
        let (requests, _) = broadcast::channel(64);
        let request_events = requests.clone();
        let completed = Arc::new((0..32).map(|_| Notify::new()).collect::<Vec<_>>());
        let releases = Arc::clone(&completed);
        let task = tokio::spawn(async move {
            let mut connections = JoinSet::new();
            loop {
                tokio::select! {
                    biased;
                    _ = &mut stopping => break,
                    result = listener.accept() => {
                        let (stream, _) = result?;
                        let events = events.clone();
                        let releases = Arc::clone(&releases);
                        let requests = request_events.clone();
                        let backend = backend.clone();
                        connections.spawn(async move { serve(stream, events, requests, releases, latency, backend).await });
                    }
                    Some(result) = connections.join_next(), if !connections.is_empty() => {
                        // Browsers may legitimately abandon sockets during cancellation.
                        let _ = result;
                    }
                }
            }
            connections.abort_all();
            while connections.join_next().await.is_some() {}
            Ok(())
        });
        Ok(Self {
            base,
            started,
            requests,
            completed,
            shutdown: Some(shutdown),
            task,
        })
    }
    pub fn subscribe_requests(&self) -> broadcast::Receiver<RequestArrival> {
        self.requests.subscribe()
    }
    pub fn url(&self, id: u32) -> String {
        format!("{}/quote?id={id}", self.base)
    }
    pub fn complete(&self, id: u32) -> io::Result<()> {
        let index = usize::try_from(id).map_err(|_| io::Error::other("invalid job"))?;
        self.completed
            .get(index)
            .ok_or_else(|| io::Error::other("invalid job"))?
            .notify_one();
        Ok(())
    }
    pub async fn stop(mut self) -> io::Result<()> {
        if let Some(shutdown) = self.shutdown.take() {
            let _ = shutdown.send(());
        }
        self.task.await.map_err(io::Error::other)?
    }
}
async fn serve(
    mut stream: TcpStream,
    events: broadcast::Sender<u32>,
    requests: broadcast::Sender<RequestArrival>,
    releases: Arc<Vec<Notify>>,
    latency: Option<Duration>,
    backend: Option<Arc<Semaphore>>,
) -> io::Result<()> {
    let mut request = Vec::new();
    loop {
        let mut bytes = [0_u8; 1024];
        let read = stream.read(&mut bytes).await?;
        if read == 0 {
            return Ok(());
        }
        request.extend_from_slice(
            bytes
                .get(..read)
                .ok_or_else(|| io::Error::other("read bound"))?,
        );
        if request.windows(4).any(|bytes| bytes == b"\r\n\r\n") {
            break;
        }
        if request.len() > 16_384 {
            return Err(io::Error::other("request too large"));
        }
    }
    let text = String::from_utf8_lossy(&request);
    let target = text.split_whitespace().nth(1).unwrap_or("/");
    let id = target
        .split("id=")
        .nth(1)
        .and_then(|s| s.split('&').next())
        .and_then(|s| s.parse::<u32>().ok())
        .unwrap_or(0);
    let index = usize::try_from(id).map_err(|_| io::Error::other("invalid job"))?;
    let signal = releases
        .get(index)
        .ok_or_else(|| io::Error::other("invalid job"))?;
    let (content_type, body) = if target == "/htmx.js" {
        (
            "text/javascript",
            include_str!(concat!(
                env!("CARGO_MANIFEST_DIR"),
                "/../../spikes/browser-automation/fixtures/htmx-2.0.11.min.js"
            ))
            .to_owned(),
        )
    } else if target.starts_with("/job?") {
        let _ = requests.send(RequestArrival {
            id,
            at: Instant::now(),
        });
        let _ = events.send(id);
        let _backend = match backend {
            Some(slots) => Some(slots.acquire_owned().await.map_err(io::Error::other)?),
            None => None,
        };
        match latency {
            Some(duration) => tokio::time::sleep(duration).await,
            None => signal.notified().await,
        }
        (
            "text/html",
            format!(
                r#"<p>Request <span class="job-id">{id}</span></p><p class="status">ready</p><p class="price">$10.{id:02}</p><p id="done">Quote confirmed from the service</p>"#
            ),
        )
    } else {
        (
            "text/html",
            format!(
                r##"<!doctype html><html><head><title>Shipping quote {id}</title>
        <style>body{{font:20px system-ui;margin:48px;background:#f4f7fb}}article{{padding:24px;background:white;border-radius:16px;max-width:600px}}button{{padding:12px;font-size:18px}}.price{{font-size:40px}}</style>
        <script src="/htmx.js"></script><script>document.addEventListener('htmx:load', () => {{ document.body.dataset.htmxReady='true'; }});</script></head>
        <body><h1>HTMX shipping quote {id}</h1><article class="quote"><div id="result">
        <p>Request <span class="job-id">{id}</span></p><p class="status">idle</p><p class="price">$0.00</p>
        <button id="start" hx-get="/job?id={id}" hx-target="#result" hx-swap="innerHTML" hx-disabled-elt="this">Fetch shipping quote</button>
        </div></article></body></html>"##
            ),
        )
    };
    let response = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: {content_type}; charset=utf-8\r\nContent-Length: {}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n{body}",
        body.len()
    );
    stream.write_all(response.as_bytes()).await?;
    stream.shutdown().await
}
