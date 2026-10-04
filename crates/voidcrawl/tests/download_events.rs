//! Loopback coverage for event-driven browser download completion.

#![allow(
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::panic,
    reason = "test harness"
)]

use std::{
    fs,
    io::{Read, Write},
    net::{SocketAddr, TcpListener, TcpStream},
    sync::mpsc,
    thread,
    time::Duration,
};

use void_crawl_core::BrowserSession;

const PAYLOAD: &[u8] = b"voidcrawl-event-download";

struct FixtureServer {
    address: SocketAddr,
    stop: mpsc::Sender<()>,
    thread: Option<thread::JoinHandle<()>>,
}

impl FixtureServer {
    fn start() -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind fixture server");
        let address = listener.local_addr().expect("fixture address");
        let (stop, stopped) = mpsc::channel();
        let thread = thread::spawn(move || {
            for connection in listener.incoming() {
                if stopped.try_recv().is_ok() {
                    break;
                }
                let Ok(mut stream) = connection else {
                    continue;
                };
                let mut request = [0_u8; 4096];
                let Ok(read) = stream.read(&mut request) else {
                    continue;
                };
                if read == 0 {
                    continue;
                }
                let request = String::from_utf8_lossy(&request[..read]);
                let path = request.split_whitespace().nth(1).unwrap_or("/");
                let (content_type, body): (&str, &[u8]) = if path == "/file.bin" {
                    ("application/octet-stream", PAYLOAD)
                } else {
                    ("text/html", b"<main>download fixture</main>")
                };
                let headers = format!(
                    "HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                    body.len()
                );
                if stream.write_all(headers.as_bytes()).is_err() {
                    continue;
                }
                let _ = stream.write_all(body);
            }
        });
        Self {
            address,
            stop,
            thread: Some(thread),
        }
    }

    fn file_url(&self) -> String {
        format!("http://{}/file.bin", self.address)
    }
}

impl Drop for FixtureServer {
    fn drop(&mut self) {
        let _ = self.stop.send(());
        let _ = TcpStream::connect(self.address);
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
    }
}

#[tokio::test]
async fn browser_download_completes_from_filesystem_event() {
    let fixture = FixtureServer::start();
    let browser = BrowserSession::builder()
        .headless()
        .launch()
        .await
        .expect("launch browser");
    let page = browser.new_blank_page().await.expect("blank page");
    let directory = tempfile::tempdir().expect("download directory");

    let outcome = page
        .download_to_dir(
            &fixture.file_url(),
            directory.path(),
            Duration::from_secs(10),
            1024,
        )
        .await
        .expect("event-driven download");

    assert_eq!(
        outcome.bytes,
        u64::try_from(PAYLOAD.len()).expect("payload length fits u64")
    );
    assert_eq!(fs::read(&outcome.path).expect("download bytes"), PAYLOAD);
    assert_eq!(
        outcome.content_type.as_deref(),
        Some("application/octet-stream")
    );

    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}
