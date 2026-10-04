//! Hermetic runtime contract for the supported browser identity policy.

#![allow(
    clippy::expect_used,
    clippy::indexing_slicing,
    clippy::panic,
    clippy::unwrap_used
)]

use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
    task::JoinHandle,
};
use void_crawl_core::BrowserSession;

async fn headless_session() -> BrowserSession {
    BrowserSession::builder()
        .headless()
        .launch()
        .await
        .expect("failed to launch headless browser")
}

async fn loopback_page() -> (String, JoinHandle<()>) {
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind identity fixture");
    let address = listener.local_addr().expect("identity fixture address");
    let server = tokio::spawn(async move {
        let (mut stream, peer) = listener.accept().await.expect("accept identity probe");
        assert!(peer.ip().is_loopback());
        let mut request = [0_u8; 1_024];
        let _ = stream
            .read(&mut request)
            .await
            .expect("read identity probe");
        stream
            .write_all(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 36\r\nConnection: close\r\n\r\n<!doctype html><body>ua probe</body>",
            )
            .await
            .expect("write identity fixture");
        stream.shutdown().await.expect("close identity fixture");
    });
    (format!("http://{address}/"), server)
}

#[tokio::test]
async fn default_identity_is_coherent_and_uses_native_false_webdriver() {
    let session = headless_session().await;
    // UA Client Hints are a secure-context API. Loopback is both hermetic and
    // potentially trustworthy; a data URL has an opaque, non-secure origin.
    let (url, server) = loopback_page().await;
    let page = session.new_page(&url).await.expect("new_page");
    server.await.expect("identity fixture task");

    let identity = page
        .evaluate_js(
            r#"(async () => {
                const high = await navigator.userAgentData.getHighEntropyValues([
                    'fullVersionList', 'platformVersion'
                ]);
                const descriptor = Object.getOwnPropertyDescriptor(
                    Object.getPrototypeOf(navigator), 'webdriver'
                );
                return {
                    userAgent: navigator.userAgent,
                    fullVersionList: high.fullVersionList,
                    platformVersion: high.platformVersion,
                    languages: Array.from(navigator.languages),
                    webdriver: navigator.webdriver,
                    webdriverGetter: Function.prototype.toString.call(descriptor.get),
                    innerWidth: window.innerWidth,
                    innerHeight: window.innerHeight,
                    screenWidth: screen.width,
                    screenHeight: screen.height,
                };
            })()"#,
        )
        .await
        .expect("evaluate_js");
    let ua = identity["userAgent"]
        .as_str()
        .expect("userAgent must be a string");
    assert!(
        !ua.contains("Headless"),
        "User-Agent leaks headless fingerprint: {ua:?} — stealth preset should strip \"HeadlessChrome\""
    );
    assert!(
        ua.contains("Chrome/"),
        "User-Agent should still identify as Chrome/<version>: {ua:?}"
    );
    assert_eq!(identity["webdriver"], false);
    assert_eq!(
        identity["webdriverGetter"],
        "function get webdriver() { [native code] }"
    );
    let languages = identity["languages"]
        .as_array()
        .expect("languages must be an array");
    assert_eq!(languages, &["en-US", "en"]);
    assert_eq!(identity["innerWidth"], identity["screenWidth"]);
    assert_eq!(identity["innerHeight"], identity["screenHeight"]);
    assert!(
        identity["platformVersion"]
            .as_str()
            .is_some_and(|value| !value.is_empty())
    );
    assert!(
        identity["fullVersionList"]
            .as_array()
            .is_some_and(|brands| !brands.is_empty())
    );

    page.close().await.expect("page close");
    session.close().await.expect("session close");
}
