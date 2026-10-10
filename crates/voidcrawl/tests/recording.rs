//! Integration tests for screen recording (`Page::record`,
//! `Page::start_recording`).
//!
//! The load-bearing tests here are the occlusion ones. Chrome composites only
//! the frontmost tab of a window, so a shared-window tab must be foregrounded
//! to record, while a tab in its **own** window records at full rate
//! concurrently — which is what `foreground: None` auto-detects.
//!
//! These assert a frame *rate*, never merely "some frames": a screencast
//! always emits one initial frame even from a fully occluded tab, so a `> 0`
//! assertion passes even when capture is completely broken. An earlier version
//! of this file made exactly that mistake and concluded the opposite.
//!
//! Requires a real Chromium/Chrome binary. Run serially:
//!
//!     cargo test -p yosoi-browser-core --test recording -- --test-threads=1
#![allow(clippy::expect_used, clippy::unwrap_used, clippy::panic)]

use std::time::{Duration, Instant};

use tokio::time::{sleep, timeout};
use void_crawl_core::{
    BrowserSession, BrowserTarget, BrowserTargetKind, DocumentEpoch, Page, RecordingOptions,
    VoidCrawlError,
};

/// A page that repaints continuously, so Chrome has a reason to emit frames.
/// A static page legitimately produces almost none — see the module docs on
/// paint-driven delivery.
const ANIMATED: &str = r#"
<html><body style="margin:0">
  <div id="box" style="width:200px;height:120px;background:#c00"></div>
  <div id="other" style="width:150px;height:90px;background:#0c0"></div>
  <script>
    let t = 0;
    function tick() {
      t += 4;
      document.getElementById('box').style.background =
        'hsl(' + (t % 360) + ',80%,50%)';
      document.getElementById('other').style.transform =
        'translateX(' + (t % 50) + 'px)';
      requestAnimationFrame(tick);
    }
    tick();
  </script>
</body></html>
"#;

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

async fn animated_page(session: &BrowserSession) -> Page {
    session
        .new_page(&data_url(ANIMATED))
        .await
        .expect("new_page failed")
}

fn css(value: &str) -> BrowserTarget {
    BrowserTarget {
        kind: BrowserTargetKind::Css,
        value: value.to_string(),
        regex: None,
        name: None,
        nth: None,
        x: None,
        y: None,
    }
}

fn opts_for(secs: u64) -> RecordingOptions {
    RecordingOptions::default()
        .with_max_duration(Duration::from_secs(secs))
        .with_fps(10)
}

#[tokio::test]
async fn records_the_viewport() {
    let session = headless_session().await;
    let page = animated_page(&session).await;

    let rec = page.record(opts_for(2)).await.expect("record failed");

    assert_eq!(
        rec.regions.len(),
        1,
        "no crop requested → exactly one region"
    );
    assert_eq!(rec.regions[0].label, "viewport");
    assert!(rec.regions[0].bbox.is_none());
    assert!(
        rec.frames_captured > 0,
        "an animating page must yield frames"
    );
    assert!(rec.started_at_unix_ms.is_some());
    assert!(matches!(rec.document_epoch, DocumentEpoch::Known(_)));
    assert!(rec.complete);
    assert!(rec.frame_size_pixels.is_some());
    assert!(rec.capture_viewport_css.is_some());
    assert_eq!(
        rec.frames_dropped,
        rec.frames_dropped_by_rate + rec.frames_dropped_by_limit + rec.frame_decode_failures
    );
    assert_eq!(rec.regions[0].frames.len(), rec.frames_captured);
    assert!(
        rec.regions[0].frames.iter().all(|f| !f.data.is_empty()),
        "every frame must carry image bytes"
    );
    // Offsets are real elapsed times, so they must be non-decreasing and
    // bounded by the recording duration.
    let offsets: Vec<Duration> = rec.regions[0].frames.iter().map(|f| f.offset).collect();
    assert!(
        offsets.windows(2).all(|w| w[0] <= w[1]),
        "offsets must be monotonic"
    );
    assert!(
        offsets
            .iter()
            .all(|o| *o <= rec.duration + Duration::from_millis(500))
    );
}

/// Why a shared-window tab must be foregrounded.
///
/// A tab sharing a window with others stops painting the moment a sibling
/// takes focus, so an unforegrounded recording on such a tab collects
/// essentially nothing. Asserted so that flipping the default silently would
/// fail loudly here.
#[tokio::test]
async fn shared_window_tab_stalls_when_not_foregrounded() {
    let session = headless_session().await;
    let recorded = animated_page(&session).await;
    let stealer = animated_page(&session).await;

    // `screenshot` is the focus-stealer of record: it brings its own tab to
    // front before capturing (see `Page::screenshot`), which is exactly the
    // contention this reproduces.
    stealer
        .screenshot_png()
        .await
        .expect("stealer screenshot failed");

    let rec = recorded
        .record(RecordingOptions {
            foreground: Some(false),
            ..opts_for(3)
        })
        .await
        .expect("record failed");

    assert!(
        rec.effective_fps() < 2.0,
        "a shared-window tab is expected to stall while occluded, but captured {} frames \
         ({:.1} fps). If Chrome has changed here, RecordingOptions::foreground could default \
         to false and the module docs need updating.",
        rec.frames_captured,
        rec.effective_fps()
    );
}

/// The escape hatch: a tab in its own window records at full rate while
/// another window holds the foreground, so no capture lock is needed.
///
/// Note the construction order — `new_page` puts its tab in the most
/// recently active window, so the sibling must be created *before* the
/// recorded page gets its own window, or it lands inside it.
#[tokio::test]
async fn own_window_tab_records_while_another_window_is_focused() {
    let session = headless_session().await;
    // Order matters: `new_page` lands in the most recently active window, so
    // the stealer must exist before the recorded page claims its own window.
    let stealer = animated_page(&session).await;
    let recorded = session
        .new_page_in_window(&data_url(ANIMATED))
        .await
        .expect("new_page_in_window failed");
    assert!(
        recorded
            .alone_in_window()
            .await
            .expect("alone_in_window failed"),
        "test setup: the recorded page is not alone in its window"
    );

    stealer
        .screenshot_png()
        .await
        .expect("stealer screenshot failed");

    let rec = {
        let handle = recorded
            .start_recording(RecordingOptions {
                foreground: Some(false),
                ..opts_for(4)
            })
            .await
            .expect("start_recording failed");
        sleep(Duration::from_secs(2)).await;
        // Steal focus again mid-recording — the recorded window must not care.
        stealer
            .screenshot_png()
            .await
            .expect("stealer screenshot failed");
        sleep(Duration::from_secs(1)).await;
        handle.stop(&recorded).await.expect("stop failed")
    };

    assert!(
        rec.effective_fps() > 3.0,
        "an own-window tab must keep recording at rate while another window is focused, \
         but captured {} frames ({:.1} fps)",
        rec.frames_captured,
        rec.effective_fps()
    );
}

/// The concrete benefit: with the recorded tab in its own window and
/// `foreground: false`, a screenshot elsewhere isn't blocked by the
/// in-flight recording.
#[tokio::test]
async fn own_window_recording_does_not_block_sibling_screenshots() {
    let session = headless_session().await;
    // Order matters — see the sibling test.
    let sibling = animated_page(&session).await;
    let recorded = session
        .new_page_in_window(&data_url(ANIMATED))
        .await
        .expect("new_page_in_window failed");
    assert!(
        recorded
            .alone_in_window()
            .await
            .expect("alone_in_window failed"),
        "test setup: the recorded page is not alone in its window"
    );

    let rec = {
        let handle = recorded
            .start_recording(RecordingOptions {
                foreground: Some(false),
                ..opts_for(10)
            })
            .await
            .expect("start failed");

        // Well under the recording's 10s duration: if the capture lock were held,
        // this would block until the recording ended.
        let shot = timeout(Duration::from_secs(4), sibling.screenshot_png())
            .await
            .expect("sibling screenshot blocked on the in-flight recording")
            .expect("sibling screenshot failed");
        assert_ne!(shot.as_slice(), b"");

        // Keep recording after the sibling stole focus, so the assertion below is
        // about frames captured *while occluded* rather than about the handful
        // that arrived before the screenshot returned.
        sleep(Duration::from_secs(2)).await;
        handle.stop(&recorded).await.expect("stop failed")
    };

    let after_steal = rec.regions[0]
        .frames
        .iter()
        .filter(|f| f.offset > Duration::from_secs(1))
        .count();
    assert!(
        after_steal > 3,
        "recording must continue at rate after a sibling window took focus, but only \
         {after_steal} of {} frames arrived after it",
        rec.frames_captured
    );
}

#[tokio::test]
async fn records_multiple_selector_regions_from_one_screencast() {
    let session = headless_session().await;
    let page = animated_page(&session).await;

    let rec = page
        .record(
            opts_for(2)
                .with_selector(css("#box"))
                .with_selector(css("#other")),
        )
        .await
        .expect("record failed");

    assert_eq!(rec.regions.len(), 2, "one region per selector");
    assert_eq!(rec.regions[0].label, "0_box");
    assert_eq!(rec.regions[1].label, "1_other");
    for region in &rec.regions {
        assert!(
            region.bbox.is_some(),
            "a selector region must carry its resolved rect"
        );
        assert_eq!(
            region.frames.len(),
            rec.frames_captured,
            "every region is cut from the same frame sequence"
        );
    }
    // The two regions have different source rects, so their cropped frames
    // must differ — proof the crop actually happened per region.
    let (a, b) = (&rec.regions[0], &rec.regions[1]);
    assert_ne!(a.bbox, b.bbox);
    if let (Some(fa), Some(fb)) = (a.frames.first(), b.frames.first()) {
        assert_ne!(
            fa.data, fb.data,
            "distinct regions must produce distinct crops"
        );
    }
}

#[tokio::test]
async fn rejects_bbox_and_selectors_together() {
    let session = headless_session().await;
    let page = animated_page(&session).await;

    let err = page
        .record(
            opts_for(1)
                .with_bbox(void_crawl_core::Bbox {
                    x: 0,
                    y: 0,
                    width: 10,
                    height: 10,
                })
                .with_selector(css("#box")),
        )
        .await
        .expect_err("bbox + selectors must be rejected");
    assert!(
        matches!(err, VoidCrawlError::RecordingError(_)),
        "got {err:?}"
    );
}

/// A selector that matches nothing must fail *before* the screencast runs,
/// not after burning the full duration and returning empty regions.
#[tokio::test]
async fn unresolvable_selector_fails_fast() {
    let session = headless_session().await;
    let page = animated_page(&session).await;

    let started = Instant::now();
    let err = page
        .record(opts_for(30).with_selector(css("#nope")))
        .await
        .expect_err("a selector matching nothing must error");
    assert!(
        matches!(err, VoidCrawlError::ElementNotVisible(_)),
        "got {err:?}"
    );
    assert!(
        started.elapsed() < Duration::from_secs(10),
        "must fail before the 30s recording duration elapses, took {:?}",
        started.elapsed()
    );
}

/// The one-shot viewport override must not leak, exactly as it doesn't for
/// `screenshot` — a recording lives long enough for a leak to matter more.
#[tokio::test]
async fn viewport_override_is_restored() {
    use void_crawl_core::Viewport;

    let session = headless_session().await;
    let page = animated_page(&session).await;
    let before = page.current_viewport();

    let rec = page
        .record(opts_for(1).with_viewport(Viewport::custom(500, 400)))
        .await
        .expect("record failed");
    assert!(rec.frames_captured > 0);

    assert_eq!(
        page.current_viewport(),
        before,
        "viewport override leaked past the recording"
    );
}

/// `fps` is a ceiling: frames closer together than 1/fps are dropped, and
/// the drop is reported rather than hidden.
#[tokio::test]
async fn fps_ceiling_is_enforced_and_reported() {
    let session = headless_session().await;
    let page = animated_page(&session).await;

    let rec = page
        .record(opts_for(2).with_fps(2))
        .await
        .expect("record failed");

    assert!(rec.frames_captured > 0);
    // 2s at a 2fps ceiling can't produce more than ~5 frames.
    assert!(
        rec.frames_captured <= 6,
        "captured {} frames at 2fps",
        rec.frames_captured
    );
    assert!(
        rec.effective_fps() <= 3.0,
        "effective fps {} exceeded the ceiling",
        rec.effective_fps()
    );
    let gaps: Vec<Duration> = rec.regions[0]
        .frames
        .windows(2)
        .map(|w| w[1].offset.saturating_sub(w[0].offset))
        .collect();
    assert!(
        gaps.iter().all(|g| *g >= Duration::from_millis(400)),
        "frames arrived closer together than the fps ceiling allows: {gaps:?}"
    );
}

/// `foreground: None` must detect which situation it's in, so neither the
/// safe case nor the concurrent case requires the caller to know anything
/// about Chrome's per-window compositing.
#[tokio::test]
async fn foreground_is_auto_detected_from_window_placement() {
    let session = headless_session().await;
    // Sibling first: `new_page` targets the most recently active window, so
    // creating it after `new_page_in_window` would put it in that window.
    let shared = animated_page(&session).await;
    let owned = session
        .new_page_in_window(&data_url(ANIMATED))
        .await
        .expect("new_page_in_window failed");

    assert!(
        !shared
            .alone_in_window()
            .await
            .expect("alone_in_window failed")
    );
    assert!(
        owned
            .alone_in_window()
            .await
            .expect("alone_in_window failed")
    );

    let shared_rec = shared.record(opts_for(2)).await.expect("record failed");
    assert!(
        shared_rec.foregrounded,
        "a shared-window tab must be foregrounded automatically"
    );
    assert!(
        shared_rec.effective_fps() > 3.0,
        "{} frames",
        shared_rec.frames_captured
    );

    let owned_rec = owned.record(opts_for(2)).await.expect("record failed");
    assert!(
        !owned_rec.foregrounded,
        "a tab alone in its window must record without taking the capture lock"
    );
    assert!(
        owned_rec.effective_fps() > 3.0,
        "{} frames",
        owned_rec.frames_captured
    );
}

/// GIF encoding is feature-gated; when the feature is on it must produce a
/// real file, and when a region is cropped the artifact must be per-region.
#[cfg(feature = "encode-gif")]
#[tokio::test]
async fn encodes_regions_to_gif() {
    use std::{fs, io::Write as _};

    use void_crawl_core::{BrowserByteDomain, Encoding};

    let session = headless_session().await;
    let page = animated_page(&session).await;
    let dir = tempfile::tempdir().expect("tempdir");

    let rec = page
        .record(
            opts_for(2)
                .with_selector(css("#box"))
                .with_selector(css("#other"))
                .with_dir(dir.path())
                .with_encoding(Encoding::Gif),
        )
        .await
        .expect("record failed");

    assert_eq!(rec.regions.len(), 2);
    for region in &rec.regions {
        assert_eq!(region.outputs.len(), 1, "one artifact per region");
        let path = &region.outputs[0];
        let meta = fs::metadata(path).expect("gif was not written");
        assert!(meta.len() > 0, "empty gif at {}", path.display());
        let header = fs::read(path).expect("read gif");
        assert_eq!(&header[..6], b"GIF89a", "not a GIF at {}", path.display());

        let reports = region
            .output_byte_reports()
            .expect("encoded output byte reports");
        assert_eq!(reports.len(), 1, "one report per artifact");
        assert_eq!(reports[0].domain(), BrowserByteDomain::EncodedRecording);
        assert_eq!(reports[0].accounting().retained().get(), meta.len());

        // Facts describe the artifact when encoding completed, not a mutable
        // path reread after the recording was returned.
        fs::OpenOptions::new()
            .append(true)
            .open(path)
            .expect("open gif for mutation")
            .write_all(b"later mutation")
            .expect("mutate gif");
        assert_eq!(
            region.output_byte_reports().expect("stored output report")[0]
                .accounting()
                .retained()
                .get(),
            meta.len(),
            "report must retain the capture-time file size"
        );
    }
}

/// Asking for an encoding whose feature is off must fail loudly and keep the
/// frames, rather than silently producing nothing.
#[cfg(not(feature = "encode-gif"))]
#[tokio::test]
async fn gif_without_the_feature_is_an_actionable_error() {
    use void_crawl_core::Encoding;

    let session = headless_session().await;
    let page = animated_page(&session).await;
    let dir = tempfile::tempdir().expect("tempdir");

    let err = page
        .record(
            opts_for(2)
                .with_dir(dir.path())
                .with_encoding(Encoding::Gif),
        )
        .await
        .expect_err("must error without the encode-gif feature");
    let VoidCrawlError::RecordingEncodeError(diagnostic) = err else {
        panic!("expected recording encode error");
    };
    assert!(
        diagnostic.contains("encode-gif"),
        "raw local diagnostic must name the feature"
    );
}
