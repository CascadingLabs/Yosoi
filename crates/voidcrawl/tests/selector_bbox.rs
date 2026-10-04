//! Integration tests for selector-backed screenshot bbox resolution
//! (`Page::resolve_target`, `ScreenshotOptions::selector`) — CAS-252.
//!
//! Covers all 8 VoidCrawl `BrowserTarget` kinds (css, xpath, regex, jsonld,
//! attr, global_id, role, visual), ambiguous/hidden/zero-area/out-of-range
//! edge cases, and one end-to-end `screenshot(selector: ...)` crop.
//!
//! Requires a real Chromium/Chrome binary. Run serially:
//!
//!     cargo test -p void_crawl_core --test selector_bbox -- --test-threads=1
#![allow(clippy::expect_used, clippy::unwrap_used, clippy::panic)]

use void_crawl_core::{
    BrowserSession, BrowserTarget, BrowserTargetKind, Page, ScreenshotOptions, ScreenshotOutput,
    TargetResolution, VoidCrawlError,
};

async fn headless_session() -> BrowserSession {
    BrowserSession::builder()
        .headless()
        .launch()
        .await
        .expect("failed to launch headless browser")
}

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

async fn page_with(html: &str, session: &BrowserSession) -> Page {
    session
        .new_page(&data_url(html))
        .await
        .expect("new_page failed")
}

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

fn entry(kind: BrowserTargetKind, value: &str) -> BrowserTarget {
    BrowserTarget {
        kind,
        value: value.to_string(),
        regex: None,
        name: None,
        nth: None,
        x: None,
        y: None,
    }
}

/// The shared fixture: one element per selector kind, an ambiguous pair, a
/// hidden element, and a zero-area element — all with known, distinct
/// positions/sizes so a resolved bbox can be asserted exactly.
const FIXTURE: &str = r#"
<!doctype html>
<html>
<head><title>Selector Bbox Fixture</title></head>
<body style="margin:0">
  <h1 style="position:absolute; left:10px; top:10px; width:200px; height:30px; margin:0;">
    Unique Heading
  </h1>
  <time datetime="2024-01-01"
        style="position:absolute; left:10px; top:60px; width:80px; height:20px; display:block;">
    Jan 1
  </time>
  <table><tbody>
  <tr id="score_100"
      style="position:absolute; left:10px; top:100px; width:50px; height:15px; display:block;">
    100
  </tr>
  <tr id="score_200"
      style="position:absolute; left:10px; top:130px; width:50px; height:15px; display:block;">
    200
  </tr>
  </tbody></table>
  <button aria-label="Save Document"
          style="position:absolute; left:10px; top:160px; width:120px; height:40px;">
    Save
  </button>
  <div class="dup" style="position:absolute; left:300px; top:10px; width:40px; height:40px;">A</div>
  <div class="dup" style="position:absolute; left:300px; top:60px; width:40px; height:40px;">B</div>
  <div class="hidden-target" style="display:none; width:50px; height:50px;">hidden</div>
  <div class="zero-area-target" style="position:absolute; left:400px; top:10px; width:0; height:0;"></div>
  <script type="application/ld+json">{"@context":"https://schema.org","@type":"Person","name":"Ada Lovelace"}</script>
</body>
</html>
"#;

// ── css ──────────────────────────────────────────────────────────────────

#[tokio::test]
async fn css_selector_resolves_unique_element_bbox() {
    let session = headless_session().await;
    let page = page_with(FIXTURE, &session).await;

    let resolution = page
        .resolve_target(&entry(BrowserTargetKind::Css, "h1"))
        .await
        .expect("resolve ok");
    match resolution {
        TargetResolution::Resolved { bbox } => {
            assert_eq!((bbox.x, bbox.y), (10, 10));
            assert_eq!((bbox.width, bbox.height), (200, 30));
        }
        other => panic!("expected Resolved, got {other:?}"),
    }

    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn css_selector_multiple_matches_without_nth_is_ambiguous() {
    let session = headless_session().await;
    let page = page_with(FIXTURE, &session).await;

    let resolution = page
        .resolve_target(&entry(BrowserTargetKind::Css, ".dup"))
        .await
        .expect("resolve ok");
    match resolution {
        TargetResolution::Ambiguous { candidates, .. } => assert_eq!(candidates, 2),
        other => panic!("expected Ambiguous, got {other:?}"),
    }

    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn css_selector_with_nth_disambiguates() {
    let session = headless_session().await;
    let page = page_with(FIXTURE, &session).await;

    let mut sel = entry(BrowserTargetKind::Css, ".dup");
    sel.nth = Some(1);
    let resolution = page.resolve_target(&sel).await.expect("resolve ok");
    match resolution {
        TargetResolution::Resolved { bbox } => assert_eq!((bbox.x, bbox.y), (300, 60)),
        other => panic!("expected Resolved, got {other:?}"),
    }

    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn css_selector_no_match_is_empty() {
    let session = headless_session().await;
    let page = page_with(FIXTURE, &session).await;

    let resolution = page
        .resolve_target(&entry(BrowserTargetKind::Css, ".nope"))
        .await
        .expect("resolve ok");
    match resolution {
        TargetResolution::Empty { reason } => assert!(reason.contains("no elements")),
        other => panic!("expected Empty, got {other:?}"),
    }

    page.close().await.ok();
    session.close().await.ok();
}

// ── xpath ────────────────────────────────────────────────────────────────

#[tokio::test]
async fn xpath_selector_resolves_element_bbox() {
    let session = headless_session().await;
    let page = page_with(FIXTURE, &session).await;

    let resolution = page
        .resolve_target(&entry(BrowserTargetKind::Xpath, "//h1"))
        .await
        .expect("resolve ok");
    match resolution {
        TargetResolution::Resolved { bbox } => assert_eq!((bbox.x, bbox.y), (10, 10)),
        other => panic!("expected Resolved, got {other:?}"),
    }

    page.close().await.ok();
    session.close().await.ok();
}

// ── attr ─────────────────────────────────────────────────────────────────

#[tokio::test]
async fn attr_selector_resolves_via_the_css_value_ignoring_name_in_the_query() {
    let session = headless_session().await;
    let page = page_with(FIXTURE, &session).await;

    let mut sel = entry(BrowserTargetKind::Attr, "time");
    sel.name = Some("datetime".into());
    let resolution = page.resolve_target(&sel).await.expect("resolve ok");
    match resolution {
        TargetResolution::Resolved { bbox } => assert_eq!((bbox.x, bbox.y), (10, 60)),
        other => panic!("expected Resolved, got {other:?}"),
    }

    page.close().await.ok();
    session.close().await.ok();
}

// ── global_id ────────────────────────────────────────────────────────────

#[tokio::test]
async fn global_id_selector_filters_by_shared_id_prefix() {
    let session = headless_session().await;
    let page = page_with(FIXTURE, &session).await;

    // Without a prefix filter, both score_* rows match -> Ambiguous.
    let unfiltered = entry(BrowserTargetKind::GlobalId, "tr");
    match page.resolve_target(&unfiltered).await.expect("resolve ok") {
        TargetResolution::Ambiguous { candidates, .. } => assert_eq!(candidates, 2),
        other => panic!("expected Ambiguous, got {other:?}"),
    }

    // nth picks the second row deterministically (prefix filter is a no-op
    // here since both ids share the same "score_" prefix).
    let mut nth_sel = entry(BrowserTargetKind::GlobalId, "tr");
    nth_sel.name = Some("score_".into());
    nth_sel.nth = Some(1);
    match page.resolve_target(&nth_sel).await.expect("resolve ok") {
        TargetResolution::Resolved { bbox } => assert_eq!((bbox.x, bbox.y), (10, 130)),
        other => panic!("expected Resolved, got {other:?}"),
    }

    page.close().await.ok();
    session.close().await.ok();
}

// ── role ─────────────────────────────────────────────────────────────────

#[tokio::test]
async fn role_selector_resolves_via_ax_tree() {
    let session = headless_session().await;
    let page = page_with(FIXTURE, &session).await;

    let mut sel = entry(BrowserTargetKind::Role, "button");
    sel.name = Some("Save Document".into());
    let resolution = page.resolve_target(&sel).await.expect("resolve ok");
    match resolution {
        TargetResolution::Resolved { bbox } => {
            assert_eq!((bbox.x, bbox.y), (10, 160));
            assert_eq!((bbox.width, bbox.height), (120, 40));
        }
        other => panic!("expected Resolved, got {other:?}"),
    }

    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn role_selector_no_match_is_empty() {
    let session = headless_session().await;
    let page = page_with(FIXTURE, &session).await;

    let mut sel = entry(BrowserTargetKind::Role, "button");
    sel.name = Some("Nonexistent Button".into());
    match page.resolve_target(&sel).await.expect("resolve ok") {
        TargetResolution::Empty { .. } => {}
        other => panic!("expected Empty, got {other:?}"),
    }

    page.close().await.ok();
    session.close().await.ok();
}

// ── visual ───────────────────────────────────────────────────────────────

#[tokio::test]
async fn visual_selector_resolves_to_exact_1x1_box() {
    let session = headless_session().await;
    let page = page_with(FIXTURE, &session).await;

    let mut sel = entry(BrowserTargetKind::Visual, "");
    sel.x = Some(50.0);
    sel.y = Some(75.0);
    match page.resolve_target(&sel).await.expect("resolve ok") {
        TargetResolution::Resolved { bbox } => {
            assert_eq!((bbox.x, bbox.y), (50, 75));
            assert_eq!((bbox.width, bbox.height), (1, 1));
        }
        other => panic!("expected Resolved, got {other:?}"),
    }

    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn visual_selector_missing_coords_is_invalid_input() {
    let session = headless_session().await;
    let page = page_with(FIXTURE, &session).await;

    match page
        .resolve_target(&entry(BrowserTargetKind::Visual, ""))
        .await
    {
        Err(VoidCrawlError::InvalidInput { operation, reason }) => {
            assert_eq!(operation, "browser_target");
            assert_eq!(reason, "visual target requires both x and y coordinates");
        }
        other => panic!("expected InvalidInput, got {other:?}"),
    }

    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn visual_selector_out_of_viewport_is_empty() {
    let session = headless_session().await;
    let page = page_with(FIXTURE, &session).await;

    let mut sel = entry(BrowserTargetKind::Visual, "");
    sel.x = Some(999_999.0);
    sel.y = Some(10.0);
    match page.resolve_target(&sel).await.expect("resolve ok") {
        TargetResolution::Empty { reason } => assert!(reason.contains("outside")),
        other => panic!("expected Empty, got {other:?}"),
    }

    page.close().await.ok();
    session.close().await.ok();
}

// ── jsonld / regex: always non-visual ───────────────────────────────────

#[tokio::test]
async fn jsonld_selector_is_always_empty() {
    let session = headless_session().await;
    let page = page_with(FIXTURE, &session).await;

    match page
        .resolve_target(&entry(BrowserTargetKind::Jsonld, "$.name"))
        .await
        .expect("resolve ok")
    {
        TargetResolution::Empty { reason } => assert!(reason.contains("non-visual")),
        other => panic!("expected Empty, got {other:?}"),
    }

    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn regex_selector_is_always_empty() {
    let session = headless_session().await;
    let page = page_with(FIXTURE, &session).await;

    match page
        .resolve_target(&entry(BrowserTargetKind::Regex, "Ada.*Lovelace"))
        .await
        .expect("ok")
    {
        TargetResolution::Empty { reason } => assert!(reason.contains("raw HTML")),
        other => panic!("expected Empty, got {other:?}"),
    }

    page.close().await.ok();
    session.close().await.ok();
}

// ── hidden / zero-area ───────────────────────────────────────────────────

#[tokio::test]
async fn hidden_element_is_empty_not_resolved() {
    let session = headless_session().await;
    let page = page_with(FIXTURE, &session).await;

    match page
        .resolve_target(&entry(BrowserTargetKind::Css, ".hidden-target"))
        .await
        .expect("ok")
    {
        TargetResolution::Empty { reason } => assert!(reason.contains("none are visible")),
        other => panic!("expected Empty, got {other:?}"),
    }

    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn zero_area_element_is_empty_not_resolved() {
    let session = headless_session().await;
    let page = page_with(FIXTURE, &session).await;

    match page
        .resolve_target(&entry(BrowserTargetKind::Css, ".zero-area-target"))
        .await
        .expect("ok")
    {
        TargetResolution::Empty { reason } => assert!(reason.contains("none are visible")),
        other => panic!("expected Empty, got {other:?}"),
    }

    page.close().await.ok();
    session.close().await.ok();
}

// ── end-to-end: screenshot(selector: ...) ───────────────────────────────

#[tokio::test]
async fn screenshot_selector_crops_the_resolved_element() {
    let session = headless_session().await;
    let page = page_with(FIXTURE, &session).await;

    let output = page
        .screenshot(ScreenshotOptions::default().with_selector(entry(BrowserTargetKind::Css, "h1")))
        .await
        .expect("screenshot ok");
    let ScreenshotOutput::Bytes(bytes) = output else {
        panic!("expected bytes")
    };
    assert_eq!(png_dimensions(&bytes), (200, 30));

    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn screenshot_selector_empty_becomes_element_not_visible_error() {
    let session = headless_session().await;
    let page = page_with(FIXTURE, &session).await;

    let err = page
        .screenshot(
            ScreenshotOptions::default().with_selector(entry(BrowserTargetKind::Css, ".nope")),
        )
        .await
        .expect_err("should error");
    assert!(
        matches!(err, VoidCrawlError::ElementNotVisible(_)),
        "expected ElementNotVisible, got {err:?}"
    );

    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn screenshot_selector_ambiguous_becomes_ambiguous_selector_error() {
    let session = headless_session().await;
    let page = page_with(FIXTURE, &session).await;

    let err = page
        .screenshot(
            ScreenshotOptions::default().with_selector(entry(BrowserTargetKind::Css, ".dup")),
        )
        .await
        .expect_err("should error");
    assert!(
        matches!(err, VoidCrawlError::AmbiguousSelector(_)),
        "expected AmbiguousSelector, got {err:?}"
    );

    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn screenshot_bbox_and_selector_together_is_rejected() {
    let session = headless_session().await;
    let page = page_with(FIXTURE, &session).await;

    let opts = ScreenshotOptions::default()
        .with_bbox(void_crawl_core::Bbox {
            x: 0,
            y: 0,
            width: 10,
            height: 10,
        })
        .with_selector(entry(BrowserTargetKind::Css, "h1"));
    let err = page.screenshot(opts).await.expect_err("should error");
    assert!(err.to_string().contains("mutually exclusive"), "got: {err}");

    page.close().await.ok();
    session.close().await.ok();
}
