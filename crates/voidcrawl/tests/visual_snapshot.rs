//! Deterministic layout and visual metadata tests (CAS-316).
#![allow(clippy::expect_used, clippy::unwrap_used, clippy::panic)]

use std::{env, time::Duration};

use tokio::time::timeout;
use void_crawl_core::{
    BrowserSession, BrowserTarget, BrowserTargetKind, DocumentEpoch, ScreenshotOptions, Viewport,
    VisualCaptureRegion,
};

const VISUAL_FIXTURE: &str = "<style>body{margin:0}.tall{height:1800px}.target{width:120px;height:80px;background:red}</style><main class='tall'><div class='target'>sensitive visual text</div></main>";

fn data_url(html: &str) -> String {
    let encoded = html
        .replace('%', "%25")
        .replace('"', "%22")
        .replace('#', "%23")
        .replace('<', "%3C")
        .replace('>', "%3E")
        .replace(' ', "%20")
        .replace('\n', "%0A");
    format!("data:text/html,{encoded}")
}

async fn page() -> (BrowserSession, void_crawl_core::Page) {
    let browser = BrowserSession::builder()
        .headless()
        .viewport(800, 600)
        .launch()
        .await
        .expect("launch Chromium");
    let page = browser
        .new_page(&data_url(VISUAL_FIXTURE))
        .await
        .expect("visual fixture");
    (browser, page)
}

#[tokio::test]
async fn layout_snapshot_reports_css_coordinate_spaces() {
    let (browser, page) = page().await;
    let layout = page.layout_snapshot().await.expect("layout snapshot");

    assert!(layout.layout_viewport.client_width > 0);
    assert!(layout.layout_viewport.client_height > 0);
    assert!(layout.visual_viewport.client_width > 0.0);
    assert!(layout.visual_viewport.client_height > 0.0);
    assert!(layout.content_size.height >= 1_800.0);
    assert!(layout.device_scale_factor.is_some_and(|dpr| dpr > 0.0));
    assert!(matches!(layout.scope.epoch, DocumentEpoch::Known(_)));

    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn visual_snapshot_pairs_png_bytes_with_dimensions_and_scope() {
    let (browser, page) = page().await;
    let snapshot = page
        .visual_snapshot(ScreenshotOptions::default().viewport_only())
        .await
        .expect("visual snapshot");

    assert_eq!(snapshot.region, VisualCaptureRegion::Viewport);
    assert_eq!(
        snapshot.image_width_pixels,
        snapshot.capture_viewport.width_css_pixels().get()
    );
    assert_eq!(
        snapshot.image_height_pixels,
        snapshot.capture_viewport.height_css_pixels().get()
    );
    assert_eq!(snapshot.retained_bytes, snapshot.bytes().len());
    assert!(snapshot.complete);
    assert_eq!(&snapshot.bytes()[..4], b"\x89PNG");
    assert!(snapshot.device_scale_factor > 0.0);
    assert!(matches!(snapshot.scope.epoch, DocumentEpoch::Known(_)));
    assert!(!format!("{snapshot:?}").contains("sensitive visual text"));

    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn known_headful_visual_capture_does_not_wait_for_target_activation() {
    if env::var_os("DISPLAY").is_none() && env::var_os("WAYLAND_DISPLAY").is_none() {
        return;
    }
    let browser = BrowserSession::builder()
        .headful()
        .viewport(800, 600)
        .launch()
        .await
        .expect("launch headful Chromium");
    let page = browser
        .new_page(&data_url("<main>headful visual</main>"))
        .await
        .expect("headful visual fixture");
    let snapshot = timeout(
        Duration::from_secs(15),
        page.visual_snapshot(ScreenshotOptions::default().viewport_only()),
    )
    .await
    .expect("headful visual capture stalled")
    .expect("headful visual capture failed");
    assert!(snapshot.complete);
    assert!(!snapshot.bytes().is_empty());
    page.close().await.expect("close headful page");
    browser.close().await.expect("close headful browser");
}

#[tokio::test]
async fn visual_snapshot_reports_bbox_target_and_one_shot_viewport_without_leak() {
    let (browser, page) = page().await;
    let before = page.layout_snapshot().await.expect("layout before");
    let target = BrowserTarget {
        kind: BrowserTargetKind::Css,
        value: ".target".into(),
        regex: None,
        name: None,
        nth: None,
        x: None,
        y: None,
    };
    let snapshot = page
        .visual_snapshot(
            ScreenshotOptions::default()
                .with_selector(target)
                .with_viewport(Viewport::custom(640, 480)),
        )
        .await
        .expect("target visual snapshot");

    assert_eq!(
        snapshot.region,
        VisualCaptureRegion::BrowserTarget {
            target_kind: BrowserTargetKind::Css
        }
    );
    assert_eq!(snapshot.capture_viewport.width_css_pixels().get(), 640);
    assert_eq!(snapshot.capture_viewport.height_css_pixels().get(), 480);
    assert!(snapshot.image_width_pixels <= 640);
    assert!(snapshot.image_height_pixels <= 480);

    let after = page.layout_snapshot().await.expect("layout after");
    assert_eq!(
        after.layout_viewport.client_width,
        before.layout_viewport.client_width
    );
    assert_eq!(
        after.layout_viewport.client_height,
        before.layout_viewport.client_height
    );

    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}
