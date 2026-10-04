//! Integration tests for `void_crawl_core`.
//!
//! These tests require a real Chromium/Chrome binary to be available.
#![allow(
    clippy::expect_used,
    clippy::unwrap_used,
    clippy::panic,
    clippy::absolute_paths
)]

use std::collections::HashMap;
use void_crawl_core::{
    Bbox, BrowserSession, ScreenshotOptions, ScreenshotOutput, ScrollTarget, StealthConfig,
    Viewport, viewport,
};

/// Read width/height from a PNG's IHDR chunk (bytes 16..24, big-endian u32
/// each — fixed by spec, right after the 8-byte signature + 4-byte length +
/// 4-byte "IHDR" tag). Avoids pulling in an image-decoding dependency just
/// to assert a capture's pixel dimensions in tests.
fn png_dimensions(bytes: &[u8]) -> (u32, u32) {
    let width = u32::from_be_bytes(
        bytes
            .get(16..20)
            .expect("IHDR width bytes")
            .try_into()
            .expect("IHDR width array"),
    );
    let height = u32::from_be_bytes(
        bytes
            .get(20..24)
            .expect("IHDR height bytes")
            .try_into()
            .expect("IHDR height array"),
    );
    (width, height)
}

/// Launch regular Stable headless with Chromium's sandbox enabled.
async fn headless_session() -> BrowserSession {
    BrowserSession::builder()
        .headless()
        .launch()
        .await
        .expect("failed to launch headless browser")
}

#[tokio::test]
async fn test_launch_and_version() {
    let session = headless_session().await;
    let version = session.version().await.expect("version() failed");
    assert!(
        version.contains("Chrome") || version.contains("Headless"),
        "unexpected version string: {version}"
    );
    session.close().await.expect("close() failed");
}

#[tokio::test]
async fn test_new_page_and_content() {
    let session = headless_session().await;
    let page = session
        .new_page("https://example.com")
        .await
        .expect("new_page failed");

    let html = page.content().await.expect("content() failed");
    assert!(
        html.contains("Example Domain"),
        "expected example.com content"
    );

    page.close().await.expect("page close failed");
    session.close().await.expect("browser close failed");
}

#[tokio::test]
async fn test_attached_pages_include_preexisting_tab() {
    let session = headless_session().await;
    let page = session
        .new_blank_page()
        .await
        .expect("new blank page failed");
    page.evaluate_js("document.title = 'yosoi-preexisting-tab';")
        .await
        .expect("mark pre-existing page");

    let attached = BrowserSession::connect(session.websocket_url().await)
        .await
        .expect("attach to launched browser failed");
    let pages = attached.pages().await.expect("attached pages failed");
    let mut found_preexisting_page = false;
    for candidate in &pages {
        if candidate
            .title()
            .await
            .expect("attached page title")
            .as_deref()
            == Some("yosoi-preexisting-tab")
        {
            found_preexisting_page = true;
            break;
        }
    }

    assert!(
        found_preexisting_page,
        "attached session omitted its pre-existing tab"
    );

    attached.close().await.expect("attached close failed");
    session.close().await.expect("browser close failed");
}

#[tokio::test]
async fn test_attach_existing_page_with_active_worker() {
    let session = headless_session().await;
    let page = session
        .new_blank_page()
        .await
        .expect("new blank page failed");
    page.evaluate_js(
        "new Promise((resolve, reject) => {\
            const source = 'self.onmessage = () => self.postMessage(true)';\
            const url = URL.createObjectURL(new Blob([source], { type: 'text/javascript' }));\
            const worker = new Worker(url);\
            worker.onmessage = () => { globalThis.cas374Worker = worker; resolve(true); };\
            worker.onerror = (event) => reject(new Error(event.message));\
            worker.postMessage(true);\
        })",
    )
    .await
    .expect("active worker setup failed");
    page.evaluate_js("document.title = 'active-worker-attach-regression';")
        .await
        .expect("mark active-worker page");

    let attached = BrowserSession::connect(session.websocket_url().await)
        .await
        .expect("attach to launched browser failed");
    let pages = attached.pages().await.expect("attached pages failed");
    let mut attached_page = None;
    for candidate in pages {
        if candidate
            .title()
            .await
            .expect("attached page title")
            .as_deref()
            == Some("active-worker-attach-regression")
        {
            attached_page = Some(candidate);
            break;
        }
    }
    let attached_page = attached_page.expect("attached session includes active-worker page");
    let title = attached_page
        .evaluate_js("document.title")
        .await
        .expect("evaluate attached page");
    assert_eq!(title.as_str(), Some("active-worker-attach-regression"));

    attached.close().await.expect("attached close failed");
    page.close().await.expect("page close failed");
    session.close().await.expect("browser close failed");
}

#[tokio::test]
async fn test_title_and_url() {
    let session = headless_session().await;
    let page = session
        .new_page("https://example.com")
        .await
        .expect("new_page failed");

    let title = page.title().await.expect("title() failed");
    assert_eq!(title, Some("Example Domain".to_string()));

    let url = page.url().await.expect("url() failed");
    assert_eq!(url, Some("https://example.com/".to_string()));

    page.close().await.expect("close failed");
    session.close().await.ok();
}

#[tokio::test]
async fn test_evaluate_js() {
    let session = headless_session().await;
    let page = session
        .new_page("https://example.com")
        .await
        .expect("new_page failed");

    let result = page.evaluate_js("1 + 1").await.expect("evaluate_js failed");
    assert_eq!(result, serde_json::json!(2));

    let title_js = page
        .evaluate_js("document.title")
        .await
        .expect("evaluate_js failed");
    assert_eq!(title_js, serde_json::json!("Example Domain"));

    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn test_query_selector() {
    let session = headless_session().await;
    let page = session
        .new_page("https://example.com")
        .await
        .expect("new_page failed");

    let h1 = page
        .query_selector("h1")
        .await
        .expect("query_selector failed");
    assert!(h1.is_some(), "expected to find <h1>");
    assert!(
        h1.unwrap().contains("Example Domain"),
        "h1 should contain Example Domain"
    );

    let missing = page
        .query_selector(".nonexistent-class")
        .await
        .expect("query_selector failed for missing element");
    assert!(missing.is_none());

    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn test_navigate() {
    let session = headless_session().await;
    let page = session
        .new_page("https://example.com")
        .await
        .expect("new_page failed");

    page.navigate("https://www.iana.org/domains/reserved")
        .await
        .expect("navigate failed");

    let html = page.content().await.expect("content failed");
    assert!(
        html.to_lowercase().contains("iana"),
        "expected IANA content after navigation"
    );

    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn test_screenshot_png() {
    let session = headless_session().await;
    let page = session
        .new_page("https://example.com")
        .await
        .expect("new_page failed");

    let png = page.screenshot_png().await.expect("screenshot failed");
    // PNG files start with the magic bytes 0x89 0x50 0x4E 0x47
    assert!(png.len() > 100, "screenshot too small");
    assert_eq!(&png[..4], b"\x89PNG", "not a valid PNG");

    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn test_set_headers() {
    let session = headless_session().await;
    let page = session
        .new_page("about:blank")
        .await
        .expect("new_page failed");

    let mut headers = HashMap::new();
    headers.insert("X-Custom-Header".to_string(), "test-value".to_string());
    page.set_headers(headers).await.expect("set_headers failed");

    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn test_custom_identity_geometry_and_locale() {
    let stealth = StealthConfig {
        navigator_webdriver: void_crawl_core::NavigatorWebdriverPolicy::BrowserReported,
        viewport_width: 1280,
        viewport_height: 720,
        locale: "en-GB,en".into(),
    };

    let session = BrowserSession::builder()
        .headless()
        .stealth(stealth)
        .launch()
        .await
        .expect("launch failed");

    let page = session
        .new_page("https://example.com")
        .await
        .expect("new_page failed");

    let html = page.content().await.expect("content failed");
    assert!(html.contains("Example Domain"));

    page.close().await.ok();
    session.close().await.ok();
}

// ── Viewport tests ────────────────────────────────────────────────────

#[tokio::test]
async fn set_viewport_overrides_dimensions_scale_and_mobile_ua_persistently() {
    let session = headless_session().await;
    let page = session
        .new_page("https://example.com")
        .await
        .expect("new_page failed");

    let vp = viewport::preset("iPhone 16 Pro Max").expect("known preset");
    page.set_viewport(vp.clone())
        .await
        .expect("set_viewport failed");

    let width = page
        .evaluate_js("window.innerWidth")
        .await
        .expect("eval failed");
    let height = page
        .evaluate_js("window.innerHeight")
        .await
        .expect("eval failed");
    assert_eq!(width.as_f64(), Some(f64::from(vp.width)));
    assert_eq!(height.as_f64(), Some(f64::from(vp.height)));

    let ua = page
        .evaluate_js("navigator.userAgent")
        .await
        .expect("eval failed");
    assert!(
        ua.as_str().expect("string").contains("iPhone"),
        "expected iPhone UA, got {ua:?}"
    );

    let max_touch = page
        .evaluate_js("navigator.maxTouchPoints")
        .await
        .expect("eval failed");
    assert!(
        max_touch.as_f64().expect("number") > 0.0,
        "mobile preset should enable touch"
    );

    assert_eq!(page.current_viewport(), Some(vp));

    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn clear_viewport_removes_the_override() {
    let session = headless_session().await;
    let page = session
        .new_page("https://example.com")
        .await
        .expect("new_page failed");

    page.set_viewport(Viewport::custom(500, 400))
        .await
        .expect("set_viewport failed");
    assert_eq!(
        page.evaluate_js("window.innerWidth")
            .await
            .expect("eval failed")
            .as_f64(),
        Some(500.0)
    );

    page.clear_viewport().await.expect("clear_viewport failed");
    assert!(
        page.current_viewport().is_none(),
        "clear_viewport should drop the override"
    );

    let width_after_clear = page
        .evaluate_js("window.innerWidth")
        .await
        .expect("eval failed")
        .as_f64();
    assert_ne!(
        width_after_clear,
        Some(500.0),
        "clearing the override should stop reporting the custom width"
    );

    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn screenshot_one_shot_viewport_restores_after_capture() {
    let session = headless_session().await;
    let page = session
        .new_page("https://example.com")
        .await
        .expect("new_page failed");

    page.set_viewport(Viewport::custom(1024, 768))
        .await
        .expect("set_viewport failed");

    let mobile = viewport::preset("Pixel 7").expect("known preset");
    let opts = ScreenshotOptions::default().with_viewport(mobile);
    page.screenshot(opts).await.expect("screenshot failed");

    // The one-shot override must be undone, restoring the persistent
    // 1024x768 override set above — not left on the mobile preset, and not
    // cleared to the session default either.
    let width = page
        .evaluate_js("window.innerWidth")
        .await
        .expect("eval failed");
    assert_eq!(
        width.as_f64(),
        Some(1024.0),
        "one-shot viewport should restore prior override"
    );
    assert_eq!(page.current_viewport(), Some(Viewport::custom(1024, 768)));

    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn screenshot_scroll_then_bbox_crops_relative_to_scrolled_position() {
    let session = headless_session().await;
    let html = "data:text/html,<body%20style='margin:0'>\
                <div%20style='height:5000px;background:red'></div>\
                <div%20style='height:5000px;background:blue'></div></body>";
    let page = session.new_page(html).await.expect("new_page failed");
    page.set_viewport(Viewport::custom(800, 600))
        .await
        .expect("set_viewport failed");

    let opts = ScreenshotOptions::default()
        .with_scroll(ScrollTarget::Viewports(2.0))
        .with_bbox(Bbox {
            x: 10,
            y: 20,
            width: 200,
            height: 150,
        });
    let output = page.screenshot(opts).await.expect("screenshot failed");
    let ScreenshotOutput::Bytes(bytes) = output else {
        panic!("expected in-memory bytes")
    };
    assert_eq!(png_dimensions(&bytes), (200, 150));

    // Scroll position must be restored after the capture.
    let scroll_y = page
        .evaluate_js("window.scrollY")
        .await
        .expect("eval failed");
    assert_eq!(
        scroll_y.as_f64(),
        Some(0.0),
        "scroll position should be restored after capture"
    );

    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn screenshot_viewport_only_is_shorter_than_full_page() {
    let session = headless_session().await;
    let html = "data:text/html,<body%20style='margin:0'>\
                <div%20style='height:6000px;background:linear-gradient(red,blue)'></div></body>";
    let page = session.new_page(html).await.expect("new_page failed");
    page.set_viewport(Viewport::custom(800, 600))
        .await
        .expect("set_viewport failed");

    let full = page
        .screenshot(ScreenshotOptions::default())
        .await
        .expect("full-page failed");
    let ScreenshotOutput::Bytes(full_bytes) = full else {
        panic!("expected bytes")
    };
    let (full_w, full_h) = png_dimensions(&full_bytes);

    let cropped = page
        .screenshot(ScreenshotOptions::default().viewport_only())
        .await
        .expect("viewport-only failed");
    let ScreenshotOutput::Bytes(cropped_bytes) = cropped else {
        panic!("expected bytes")
    };
    let (crop_w, crop_h) = png_dimensions(&cropped_bytes);

    assert_eq!(
        full_w, 800,
        "full-page width should still match the viewport"
    );
    assert_eq!(
        crop_w, 800,
        "viewport-only width should match the viewport exactly (explicit clip)"
    );
    assert!(
        full_h >= 5900,
        "full-page height should cover the 6000px page, got {full_h}"
    );
    assert_eq!(
        crop_h, 600,
        "viewport-only height should be exactly the viewport height"
    );
    assert!(
        full_h > crop_h * 2,
        "full-page capture should be much taller than viewport-only"
    );

    page.close().await.ok();
    session.close().await.ok();
}
