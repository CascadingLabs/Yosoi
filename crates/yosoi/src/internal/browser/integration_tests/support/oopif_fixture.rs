//! Deterministic, loopback-only cross-site iframe fixture for OOPIF tests.

use std::{io, net::Ipv4Addr, sync::Arc, time::Duration};

use crate::internal::browser::{BrowserSession, CdpMode, Page};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    sync::oneshot,
    task::JoinHandle,
    time::timeout,
};

const PARENT_TEMPLATE: &str = include_str!("../conformance/oopif-parent.html");
const CHILD_TEMPLATE: &str = include_str!("../conformance/oopif-child.html");
const REQUEST_LIMIT: usize = 8 * 1024;

pub struct OopifFixture {
    port: u16,
    shutdown: Option<oneshot::Sender<()>>,
    server: JoinHandle<()>,
}

impl OopifFixture {
    pub async fn start() -> Self {
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0))
            .await
            .expect("bind OOPIF fixture to IPv4 loopback");
        let address = listener.local_addr().expect("OOPIF fixture address");
        assert!(address.ip().is_loopback());

        let port = address.port();
        let parent_html = Arc::<str>::from(parent_html(port));
        let (shutdown, mut shutdown_rx) = oneshot::channel();
        let server = tokio::spawn(async move {
            loop {
                tokio::select! {
                    _ = &mut shutdown_rx => break,
                    accepted = listener.accept() => {
                        let Ok((stream, peer)) = accepted else { break };
                        if !peer.ip().is_loopback() {
                            continue;
                        }
                        let parent_html = Arc::clone(&parent_html);
                        tokio::spawn(async move {
                            serve(stream, port, parent_html).await;
                        });
                    }
                }
            }
        });

        Self {
            port,
            shutdown: Some(shutdown),
            server,
        }
    }

    pub fn parent_url(&self) -> String {
        format!("http://a.test:{}/parent", self.port)
    }

    #[allow(dead_code, reason = "used by the conformance test crate")]
    pub fn child_url(&self, host: &str, path: &str) -> String {
        format!("http://{host}:{}{path}", self.port)
    }

    pub const fn host_resolver_rule() -> &'static str {
        "host-resolver-rules=MAP a.test 127.0.0.1,MAP b.test 127.0.0.1,MAP c.test 127.0.0.1"
    }

    pub async fn launch_browser(&self, mode: CdpMode) -> BrowserSession {
        BrowserSession::builder()
            .headless()
            .cdp_mode(mode)
            .arg(Self::host_resolver_rule())
            .launch()
            .await
            .expect("launch regular sandboxed Chromium for OOPIF fixture")
    }

    pub async fn navigate_parent(&self, page: &Page) {
        page.navigate(&self.parent_url())
            .await
            .expect("navigate to OOPIF parent fixture");
        page.evaluate_js("window.__loadInitialOopif()")
            .await
            .expect("start the initial OOPIF after parent navigation");
        self.wait_for_child_message(page, "OOPIF-CHILD-B1").await;
    }

    pub async fn wait_for_child_message(&self, page: &Page, marker: &str) {
        let result = timeout(
            Duration::from_secs(10),
            page.evaluate_js("window.__waitForOopifMessage()"),
        )
        .await
        .expect("OOPIF child postMessage readiness timed out")
        .expect("receive OOPIF child postMessage");
        assert_eq!(
            result.get("fixture").and_then(serde_json::Value::as_str),
            Some("cas-383")
        );
        assert_eq!(
            result.get("nonce").and_then(serde_json::Value::as_str),
            Some("oopif-v1")
        );
        assert_eq!(
            result.get("marker").and_then(serde_json::Value::as_str),
            Some(marker)
        );
    }
}

impl Drop for OopifFixture {
    fn drop(&mut self) {
        if let Some(shutdown) = self.shutdown.take() {
            let _ = shutdown.send(());
        }
        self.server.abort();
    }
}

fn parent_html(port: u16) -> String {
    let allowed_origins = serde_json::to_string(&[
        format!("http://a.test:{port}"),
        format!("http://b.test:{port}"),
        format!("http://c.test:{port}"),
    ])
    .expect("encode allowed OOPIF origins");
    PARENT_TEMPLATE
        .replace("__ALLOWED_CHILD_ORIGINS__", &allowed_origins)
        .replace(
            "__INITIAL_CHILD_URL__",
            &serde_json::to_string(&format!("http://b.test:{port}/child-first"))
                .expect("encode initial OOPIF URL"),
        )
}

async fn serve(mut stream: TcpStream, port: u16, parent_html: Arc<str>) {
    let Some((host, path)) = read_request(&mut stream).await else {
        return;
    };
    let body = match (host.as_str(), path.as_str()) {
        ("a.test", "/parent") => parent_html.to_string(),
        ("a.test", "/child-middle") => child_html(port, "OOPIF-CHILD-A2"),
        ("b.test", "/child-first") => initial_child_html(port),
        ("b.test", "/nested") => nested_html(),
        ("c.test", "/child-final") => child_html(port, "OOPIF-CHILD-C3"),
        _ => {
            let _ = write_response(&mut stream, "404 Not Found", "text/plain", "missing").await;
            return;
        }
    };
    let _ = write_response(&mut stream, "200 OK", "text/html; charset=utf-8", &body).await;
}

async fn read_request(stream: &mut TcpStream) -> Option<(String, String)> {
    let mut bytes = Vec::with_capacity(1024);
    let mut chunk = [0_u8; 1024];
    loop {
        let read = stream.read(&mut chunk).await.ok()?;
        if read == 0 {
            return None;
        }
        if bytes.len().checked_add(read)? > REQUEST_LIMIT {
            return None;
        }
        bytes.extend_from_slice(chunk.get(..read)?);
        if bytes.windows(4).any(|window| window == b"\r\n\r\n") {
            break;
        }
    }

    let request = String::from_utf8_lossy(&bytes);
    let mut lines = request.lines();
    let path = lines
        .next()?
        .split_whitespace()
        .nth(1)?
        .split('?')
        .next()?
        .to_string();
    let host = lines.find_map(|line| {
        let (name, value) = line.split_once(':')?;
        name.eq_ignore_ascii_case("host").then(|| {
            value
                .trim()
                .split(':')
                .next()
                .unwrap_or_default()
                .to_ascii_lowercase()
        })
    })?;
    Some((host, path))
}

async fn write_response(
    stream: &mut TcpStream,
    status: &str,
    content_type: &str,
    body: &str,
) -> io::Result<()> {
    let response = format!(
        "HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n{body}",
        body.len(),
    );
    stream.write_all(response.as_bytes()).await?;
    stream.shutdown().await
}

fn child_html(port: u16, marker: &str) -> String {
    CHILD_TEMPLATE
        .replace("__CHILD_MARKER__", marker)
        .replace("__PARENT_ORIGIN__", &format!("http://a.test:{port}"))
}

fn initial_child_html(port: u16) -> String {
    child_html(port, "OOPIF-CHILD-B1").replace(
        "<script>",
        &format!("<iframe src=\"http://b.test:{port}/nested\"></iframe><script>"),
    )
}

fn nested_html() -> String {
    "<!doctype html><body data-marker=\"OOPIF-NESTED\"><button aria-label=\"OOPIF-NESTED\">OOPIF-NESTED</button></body>".to_owned()
}
