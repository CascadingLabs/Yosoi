//! Real loopback Chrome coverage for native Work download capture.

#![allow(
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::panic,
    reason = "browser integration test harness"
)]

use std::{
    fs,
    io::{Read, Write},
    net::{SocketAddr, TcpListener, TcpStream},
    path::Path,
    sync::mpsc,
    thread,
    time::Duration,
};

use tokio::{
    sync::mpsc as tokio_mpsc,
    time::{self, Instant},
};

use crate::{
    documents::{FileDocument, MAX_FILE_BYTES},
    policy::{Acquisition, BrowserMode, Page, Policy},
    session::{ActionKind, DownloadError, DownloadOptions, Session, SessionPolicy, new},
};

const ATTACHMENT: &[u8] = b"authenticated-native-download";
const BLOB: &[u8] = b"blob-native-download";
const AUTH_PAGE: &[u8] = br#"<!doctype html><a id="download" href="/protected">download</a><a id="empty" href="/empty">empty</a>"#;
const BLOB_PAGE: &[u8] = br#"<!doctype html><button id="download" onclick="{ const blob = new Blob(['blob-native-download'], { type: 'text/plain' }); const a = document.createElement('a'); a.href = window.URL.createObjectURL(blob); a.download = 'blob.txt'; a.click(); }">download</button>"#;
const IFRAME_PAGE: &[u8] = br#"<!doctype html><button id="iframe-download" onclick="{ const frame = document.createElement('iframe'); frame.src = '/protected'; document.body.appendChild(frame); }">download in new iframe</button>"#;

struct LoopbackServer {
    address: SocketAddr,
    stop: mpsc::Sender<()>,
    thread: Option<thread::JoinHandle<()>>,
}

impl LoopbackServer {
    fn start() -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind loopback fixture");
        let address = listener.local_addr().expect("fixture address");
        let (stop, stopped) = mpsc::channel();
        let thread = thread::spawn(move || {
            while let Ok((mut stream, _)) = listener.accept() {
                if stopped.try_recv().is_ok() {
                    break;
                }
                let mut request_bytes = [0_u8; 8192];
                let Ok(read) = stream.read(&mut request_bytes) else {
                    continue;
                };
                if read == 0 {
                    continue;
                }
                let request = String::from_utf8_lossy(&request_bytes[..read]);
                let request_lower = request.to_ascii_lowercase();
                let path = request.split_whitespace().nth(1).unwrap_or("/");
                match path {
                    "/auth" => write_response(
                        &mut stream,
                        "200 OK",
                        "text/html",
                        Some("Set-Cookie: auth=allowed; Path=/; SameSite=Lax\r\n"),
                        AUTH_PAGE,
                    ),
                    "/protected" if request_lower.contains("cookie: auth=allowed") => {
                        write_response(
                            &mut stream,
                            "200 OK",
                            "text/plain",
                            Some("Content-Disposition: attachment; filename=authenticated.txt\r\n"),
                            ATTACHMENT,
                        );
                    }
                    "/protected" => write_response(
                        &mut stream,
                        "403 Forbidden",
                        "text/plain",
                        None,
                        b"authentication required",
                    ),
                    "/empty" => write_response(
                        &mut stream,
                        "200 OK",
                        "application/octet-stream",
                        Some("Content-Disposition: attachment; filename=empty.bin\r\n"),
                        b"",
                    ),
                    "/blob-page" => {
                        write_response(&mut stream, "200 OK", "text/html", None, BLOB_PAGE);
                    }
                    "/iframe-page" => {
                        write_response(&mut stream, "200 OK", "text/html", None, IFRAME_PAGE);
                    }
                    _ => write_response(
                        &mut stream,
                        "200 OK",
                        "text/html",
                        None,
                        b"<!doctype html><main>loopback sibling</main>",
                    ),
                }
            }
        });
        Self {
            address,
            stop,
            thread: Some(thread),
        }
    }

    fn url(&self, path: &str) -> String {
        format!("http://{}{path}", self.address)
    }
}

fn write_response(
    stream: &mut TcpStream,
    status: &str,
    content_type: &str,
    extra_headers: Option<&str>,
    body: &[u8],
) {
    let headers = format!(
        "HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\nConnection: close\r\n{}\r\n",
        body.len(),
        extra_headers.unwrap_or_default(),
    );
    let _ = stream.write_all(headers.as_bytes());
    let _ = stream.write_all(body);
}

impl Drop for LoopbackServer {
    fn drop(&mut self) {
        let _ = self.stop.send(());
        let _ = TcpStream::connect(self.address);
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
    }
}

async fn session(maximum_tabs: u32) -> Session {
    let policy = Policy {
        page: Page {
            acquisitions: vec![Acquisition::Browser(BrowserMode::Headless)],
        },
        ..Policy::default()
    };
    let settings = SessionPolicy {
        mode: BrowserMode::Headless,
        maximum_tabs,
        dom: false,
        allowed_actions: vec![
            ActionKind::Navigate,
            ActionKind::Click,
            ActionKind::Download,
        ],
        operation_timeout_ms: 20_000,
        ..SessionPolicy::default()
    };
    new()
        .bind(&policy)
        .configure(settings)
        .acquire()
        .await
        .expect("acquire native Chrome Session")
}

async fn wait_for_preserved_download(directory: &Path) {
    let (events, mut receiver) = tokio_mpsc::channel(1);
    let mut watcher = notify::recommended_watcher(move |_| {
        let _ = events.try_send(());
    })
    .expect("watch preserved downloads");
    notify::Watcher::watch(&mut watcher, directory, notify::RecursiveMode::NonRecursive)
        .expect("watch recovery directory");
    let deadline = Instant::now()
        .checked_add(Duration::from_secs(5))
        .expect("test deadline");
    loop {
        if let Ok(entries) = fs::read_dir(directory) {
            for entry in entries.flatten() {
                let path = entry.path();
                if path
                    .file_name()
                    .and_then(|name| name.to_str())
                    .is_some_and(|name| !name.ends_with(".crdownload"))
                    && fs::read(path).is_ok_and(|bytes| bytes == ATTACHMENT)
                {
                    return;
                }
            }
        }
        tokio::select! {
            () = time::sleep_until(deadline) => panic!("foreign download did not reach recovery directory"),
            event = receiver.recv() => assert!(event.is_some(), "filesystem watcher stopped"),
        }
    }
}

#[tokio::test]
#[expect(
    clippy::significant_drop_tightening,
    reason = "Capture guards are consumed by async wait calls; the shared Work and Session stay live through the trigger assertions and explicit close."
)]
async fn captures_authenticated_attachment_blob_and_dynamic_iframe_downloads() {
    let fixture = LoopbackServer::start();
    let session = session(1).await;
    let work = session.work().await.expect("acquire Work");

    work.navigate(&fixture.url("/auth"))
        .await
        .expect("load authenticated attachment page");
    let capture = work
        .expect_download(DownloadOptions::default())
        .await
        .expect("arm authenticated download");
    work.click("#download")
        .await
        .expect("trigger authenticated attachment");
    let file = capture.wait().await.expect("capture attachment");
    assert_eq!(file.bytes(), ATTACHMENT);
    assert_eq!(file.metadata().filename(), Some("authenticated.txt"));
    assert!(
        file.metadata()
            .source()
            .is_some_and(|source| source.ends_with("/protected"))
    );
    assert!(file.metadata().download_id().is_some());

    work.navigate(&fixture.url("/blob-page"))
        .await
        .expect("load blob download page");
    let capture = work
        .expect_download(DownloadOptions::default())
        .await
        .expect("arm blob download");
    work.click("#download")
        .await
        .expect("trigger blob download");
    let file = capture.wait().await.expect("capture blob download");
    assert_eq!(file.bytes(), BLOB);
    assert_eq!(file.metadata().filename(), Some("blob.txt"));

    work.navigate(&fixture.url("/iframe-page"))
        .await
        .expect("load dynamic iframe download page");
    let capture = work
        .expect_download(DownloadOptions::default())
        .await
        .expect("arm before the iframe exists");
    work.click("#iframe-download")
        .await
        .expect("create iframe and trigger its attachment");
    let file = capture
        .wait()
        .await
        .expect("capture download from the newly created iframe");
    assert_eq!(file.bytes(), ATTACHMENT);
    assert_eq!(file.metadata().filename(), Some("authenticated.txt"));
    session.close().await.expect("close browser Session");
}

#[tokio::test]
#[expect(
    clippy::significant_drop_tightening,
    reason = "The capture guard is consumed by async cancel and wait calls while the same Work is reused before explicit Session close."
)]
async fn explicit_cancel_restores_download_behavior_for_reuse() {
    let fixture = LoopbackServer::start();
    let session = session(1).await;
    let work = session.work().await.expect("acquire Work");
    work.navigate(&fixture.url("/auth"))
        .await
        .expect("load attachment page");

    let capture = work
        .expect_download(DownloadOptions::default())
        .await
        .expect("arm canceled capture");
    work.click("#download")
        .await
        .expect("trigger before explicit cancellation");
    capture.cancel().await.expect("cancel and restore behavior");

    let capture = work
        .expect_download(DownloadOptions::default())
        .await
        .expect("arm reused context");
    work.click("#download")
        .await
        .expect("trigger reused capture");
    let file = capture.wait().await.expect("capture after cancellation");
    assert_eq!(file.bytes(), ATTACHMENT);
    session.close().await.expect("close browser Session");
}

#[tokio::test]
#[expect(
    clippy::significant_drop_tightening,
    reason = "Capture guards are consumed by async wait calls; the shared Work remains live across invalid, timeout, oversize, and empty-file assertions before explicit close."
)]
async fn timeout_and_oversize_cleanup_allow_reuse_and_zero_bytes_are_retained() {
    let fixture = LoopbackServer::start();
    let session = session(1).await;
    let work = session.work().await.expect("acquire Work");
    work.navigate(&fixture.url("/auth"))
        .await
        .expect("load attachment page");

    for options in [
        DownloadOptions {
            max_bytes: 0,
            ..DownloadOptions::default()
        },
        DownloadOptions {
            max_bytes: MAX_FILE_BYTES + 1,
            ..DownloadOptions::default()
        },
        DownloadOptions {
            timeout_ms: 0,
            ..DownloadOptions::default()
        },
    ] {
        assert!(matches!(
            work.expect_download(options).await,
            Err(DownloadError::InvalidOptions)
        ));
    }

    let timeout = DownloadOptions {
        timeout_ms: 150,
        ..DownloadOptions::default()
    };
    let capture = work
        .expect_download(timeout)
        .await
        .expect("arm no-trigger timeout");
    assert!(matches!(capture.wait().await, Err(DownloadError::Timeout)));

    let too_small = DownloadOptions {
        max_bytes: 1,
        timeout_ms: 5_000,
    };
    let capture = work
        .expect_download(too_small)
        .await
        .expect("arm bounded oversize capture");
    work.click("#download")
        .await
        .expect("trigger oversized file");
    assert!(matches!(
        capture.wait().await,
        Err(DownloadError::TooLarge { maximum: 1 })
    ));

    let capture = work
        .expect_download(DownloadOptions::default())
        .await
        .expect("arm empty download capture");
    work.click("#empty").await.expect("trigger empty file");
    let file = capture.wait().await.expect("capture empty file");
    assert_eq!(file.bytes(), b"");
    assert!(matches!(file, FileDocument::Binary(_)));
    session.close().await.expect("close browser Session");
}

#[tokio::test]
#[expect(
    clippy::significant_drop_tightening,
    reason = "The capture guard is consumed by async wait; both tab Work leases stay live through sibling-action assertions and explicit tab and Session cleanup."
)]
async fn sibling_actions_continue_while_same_context_capture_is_armed() {
    let fixture = LoopbackServer::start();
    let session = session(2).await;
    let work = session.work().await.expect("acquire initial Work");
    work.navigate(&fixture.url("/auth"))
        .await
        .expect("load attachment page");
    let tab = session.new_tab().await.expect("create sibling tab");
    let sibling = tab.work().await.expect("acquire sibling Work");

    let capture = work
        .expect_download(DownloadOptions::default())
        .await
        .expect("arm first context capture");
    assert!(matches!(
        sibling.expect_download(DownloadOptions::default()).await,
        Err(DownloadError::Busy)
    ));
    sibling
        .navigate(&fixture.url("/sibling"))
        .await
        .expect("sibling navigation remains available");
    work.click("#download")
        .await
        .expect("trigger first-tab attachment");
    let file = capture.wait().await.expect("capture first-tab attachment");
    assert_eq!(file.bytes(), ATTACHMENT);

    tab.close().await.expect("close sibling tab");
    session.close().await.expect("close browser Session");
}

#[tokio::test]
#[expect(
    clippy::significant_drop_tightening,
    reason = "The capture guard is consumed by async wait; both tab Work leases stay live through preservation and fencing assertions and explicit tab and Session cleanup."
)]
async fn same_context_sibling_download_is_reported_and_preserved() {
    let fixture = LoopbackServer::start();
    let session = session(2).await;
    let work = session.work().await.expect("acquire initial Work");
    work.navigate(&fixture.url("/auth"))
        .await
        .expect("load initial attachment page");
    let tab = session.new_tab().await.expect("create sibling tab");
    let sibling = tab.work().await.expect("acquire sibling Work");
    sibling
        .navigate(&fixture.url("/auth"))
        .await
        .expect("load sibling attachment page");

    let capture = work
        .expect_download(DownloadOptions::default())
        .await
        .expect("arm first-tab capture");
    sibling
        .click("#download")
        .await
        .expect("trigger sibling download");
    let error = capture
        .wait()
        .await
        .expect_err("foreign file must be explicit");
    let DownloadError::UnrelatedDownload { recovery_directory } = error else {
        panic!("expected a recovery directory for the sibling download");
    };
    assert!(recovery_directory.is_dir());
    wait_for_preserved_download(&recovery_directory).await;
    assert!(matches!(
        work.expect_download(DownloadOptions::default()).await,
        Err(DownloadError::Fenced)
    ));
    sibling
        .navigate(&fixture.url("/sibling"))
        .await
        .expect("foreign capture does not fence sibling control");
    tab.close().await.expect("close sibling tab");
    session.close().await.expect("close browser Session");
}

#[tokio::test]
#[expect(
    clippy::significant_drop_tightening,
    reason = "The fenced Work and owning Session remain live until capture settlement is asserted and browser shutdown completes."
)]
async fn revoked_work_still_awaits_explicit_capture_cleanup() {
    for wait in [false, true] {
        let session = session(1).await;
        let work = session.work().await.expect("acquire Work");
        let capture = work
            .expect_download(DownloadOptions::default())
            .await
            .expect("arm capture");
        work.control.fence();
        if wait {
            assert!(matches!(
                capture.wait().await,
                Err(DownloadError::Cancelled)
            ));
        } else {
            capture
                .cancel()
                .await
                .expect("cancel after input authority was revoked");
        }
        session
            .close()
            .await
            .expect("close owner after settled cleanup");
    }
}
