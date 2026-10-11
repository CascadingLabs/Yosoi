//! Deterministic rendered-DOM and accessibility snapshot tests (CAS-311).
#![allow(clippy::expect_used, clippy::unwrap_used, clippy::panic)]

use crate::internal::browser as internal_browser;
use crate::internal::browser::{
    AccessibilitySnapshotOptions, BrowserSession, DocumentEpoch, DocumentFrameScope, SnapshotState,
};
use crate::internal::types::{
    BrowserAccessibilityCaptureMode, BrowserAccessibilityIgnoredNodes, BrowserAccessibilitySchema,
};

use super::oopif_fixture;

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

async fn navigate_frame(page: &internal_browser::Page, url: &str) {
    let url = serde_json::to_string(url).expect("frame URL JSON");
    let script = format!(
        r#"new Promise((resolve, reject) => {{
            const frame = document.querySelector('iframe');
            if (!frame) {{ reject(new Error('iframe missing')); return; }}
            frame.addEventListener('load', () => resolve(frame.src), {{ once: true }});
            frame.addEventListener('error', () => reject(new Error('iframe navigation failed')), {{ once: true }});
            frame.src = {url};
        }})"#
    );
    page.evaluate_js(&script)
        .await
        .expect("event-driven frame navigation");
}

async fn session() -> BrowserSession {
    BrowserSession::builder()
        .headless()
        .launch()
        .await
        .expect("launch Chromium")
}

#[tokio::test]
async fn rendered_dom_is_bounded_and_tracks_document_epochs() {
    let browser = session().await;
    let page = browser
        .new_page(&data_url(
            "<main id='value'>source</main><script>document.getElementById('value').textContent='rendered'</script>",
        ))
        .await
        .expect("first page");

    let first = page
        .rendered_dom_snapshot(1024)
        .await
        .expect("first DOM snapshot");
    assert_eq!(first.state, SnapshotState::Complete);
    assert!(String::from_utf8_lossy(first.bytes()).contains(">rendered</main>"));
    let DocumentEpoch::Known(first_epoch) = first.scope.epoch else {
        panic!("launched page epoch should be known")
    };

    page.evaluate_js("document.getElementById('value').textContent='spa-update'")
        .await
        .expect("SPA mutation");
    let spa = page
        .rendered_dom_snapshot(1024)
        .await
        .expect("SPA DOM snapshot");
    assert_eq!(spa.scope.epoch, DocumentEpoch::Known(first_epoch));
    assert!(String::from_utf8_lossy(spa.bytes()).contains("spa-update"));

    let second_url = data_url("<main>second-document</main>");
    page.navigate(&second_url).await.expect("second navigation");
    let second = page
        .rendered_dom_snapshot(1024)
        .await
        .expect("second DOM snapshot");
    assert_eq!(second.scope.epoch, DocumentEpoch::Known(first_epoch + 1));

    page.navigate(&second_url).await.expect("same-URL reload");
    let reloaded = page
        .rendered_dom_snapshot(1024)
        .await
        .expect("reloaded DOM snapshot");
    assert_eq!(
        reloaded.scope.epoch,
        DocumentEpoch::Known(first_epoch + 2),
        "a new loader at the same URL must advance the epoch",
    );

    page.evaluate_js("location.hash = 'same-document'")
        .await
        .expect("hash navigation");
    let hashed = page
        .rendered_dom_snapshot(1024)
        .await
        .expect("hash DOM snapshot");
    assert_eq!(hashed.scope.epoch, reloaded.scope.epoch);

    page.evaluate_js("history.pushState({}, '', '#history-state')")
        .await
        .expect("history navigation");
    let history = page
        .rendered_dom_snapshot(1024)
        .await
        .expect("history DOM snapshot");
    assert_eq!(history.scope.epoch, reloaded.scope.epoch);

    let truncated = page
        .rendered_dom_snapshot(8)
        .await
        .expect("truncated DOM snapshot");
    assert_eq!(truncated.state, SnapshotState::Truncated);
    assert_eq!(truncated.retained_bytes, 8);
    assert!(
        truncated
            .complete_bytes
            .is_some_and(|complete| complete > 8)
    );
    assert_eq!(truncated.bytes().len(), 8);
    assert!(!format!("{truncated:?}").contains("second-document"));

    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn accessibility_snapshot_preserves_raw_payload_and_explicit_limits() {
    let browser = session().await;
    let page = browser
        .new_page(&data_url(
            "<main><h1>Account</h1><button>Save</button><input aria-label='Email'></main>",
        ))
        .await
        .expect("AX page");

    let complete = page
        .accessibility_snapshot(AccessibilitySnapshotOptions::default())
        .await
        .expect("complete AX snapshot");
    let repeated = page
        .accessibility_snapshot(AccessibilitySnapshotOptions::default())
        .await
        .expect("repeated AX snapshot");
    assert_eq!(complete.state, SnapshotState::Complete);
    assert_eq!(
        complete.payload_schema,
        BrowserAccessibilitySchema::ChromiumCdpAxNodeJson
    );
    assert_eq!(complete.payload_version, 1);
    assert_eq!(
        complete.capture_mode,
        BrowserAccessibilityCaptureMode::FullTree
    );
    assert_eq!(
        complete.ignored_node_policy,
        BrowserAccessibilityIgnoredNodes::Included
    );
    assert!(complete.nodes_observed > 0);
    assert_eq!(complete.nodes_retained, complete.nodes_observed);
    let payload: serde_json::Value =
        serde_json::from_slice(complete.bytes()).expect("raw AX JSON payload");
    assert!(payload.as_array().is_some_and(|nodes| !nodes.is_empty()));
    assert_eq!(
        complete.bytes(),
        repeated.bytes(),
        "unchanged AX serialization must be stable"
    );
    let outline = page
        .ax_tree_outline(None)
        .await
        .expect("compact AX projection");
    assert_ne!(outline, "");
    assert_ne!(
        complete.bytes(),
        outline.as_bytes(),
        "outline is a projection, not raw evidence"
    );

    let node_limited = page
        .accessibility_snapshot(AccessibilitySnapshotOptions {
            max_nodes: 1,
            ..AccessibilitySnapshotOptions::default()
        })
        .await
        .expect("node-limited AX snapshot");
    assert_eq!(node_limited.state, SnapshotState::Truncated);
    assert_eq!(node_limited.nodes_retained, 1);
    assert!(node_limited.nodes_observed > 1);

    let depth_limited = page
        .accessibility_snapshot(AccessibilitySnapshotOptions {
            depth: Some(2),
            ..AccessibilitySnapshotOptions::default()
        })
        .await
        .expect("depth-limited AX snapshot");
    assert_eq!(
        depth_limited.capture_mode,
        BrowserAccessibilityCaptureMode::DepthLimited
    );
    assert_eq!(depth_limited.requested_depth, Some(2));

    let byte_limited = page
        .accessibility_snapshot(AccessibilitySnapshotOptions {
            max_bytes: 4,
            ..AccessibilitySnapshotOptions::default()
        })
        .await
        .expect("byte-limited AX snapshot");
    assert_eq!(byte_limited.state, SnapshotState::Truncated);
    assert!(byte_limited.retained_bytes <= 4);
    assert_eq!(byte_limited.nodes_retained, 0);
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(byte_limited.bytes())
            .expect("byte-limited AX remains valid JSON"),
        serde_json::json!([]),
    );
    assert!(!format!("{byte_limited:?}").contains("Email"));

    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn frame_accessibility_scope_is_explicit() {
    let browser = session().await;
    let child = data_url("<button aria-label=\"CHILDAX button\">Child</button>");
    let page = browser
        .new_page(&data_url(&format!(
            "<main>parent</main><iframe src='{child}'></iframe>"
        )))
        .await
        .expect("framed page");

    let snapshot = page
        .accessibility_snapshot_in_frame(
            "data:text/html,%3Cbutton%20aria-label",
            AccessibilitySnapshotOptions::default(),
        )
        .await
        .expect("frame AX snapshot");
    assert!(matches!(
        snapshot.scope.frame,
        DocumentFrameScope::Frame { .. }
    ));
    assert!(matches!(
        snapshot.state,
        SnapshotState::Complete | SnapshotState::Unavailable { .. }
    ));
    if snapshot.state == SnapshotState::Complete {
        assert!(String::from_utf8_lossy(snapshot.bytes()).contains("CHILDAX"));
    }

    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn site_isolated_child_frame_is_readable_through_its_own_session() {
    let fixture = oopif_fixture::OopifFixture::start().await;
    let browser = fixture
        .launch_browser(internal_browser::CdpMode::Normal)
        .await;
    let page = browser.new_blank_page().await.expect("blank OOPIF page");

    fixture.navigate_parent(&page).await;

    let marker = page
        .evaluate_js_in_frame(
            "/child-first",
            "document.querySelector('button').getAttribute('aria-label')",
        )
        .await
        .expect("evaluate inside cross-site child frame");
    assert_eq!(marker.as_str(), Some("OOPIF-CHILD-B1"));

    let snapshot = page
        .accessibility_snapshot_in_frame("/child-first", AccessibilitySnapshotOptions::default())
        .await
        .expect("capture cross-site child accessibility tree");
    assert_eq!(snapshot.state, SnapshotState::Complete);
    assert!(matches!(
        snapshot.scope.frame,
        DocumentFrameScope::Frame { .. }
    ));
    assert!(String::from_utf8_lossy(snapshot.bytes()).contains("OOPIF-CHILD-B1"));

    page.close().await.expect("close OOPIF page");
    browser.close().await.expect("close OOPIF browser");
}

#[tokio::test]
async fn frame_document_epoch_advances_without_changing_capture_local_frame_identity() {
    let browser = session().await;
    let first_url = data_url("<button aria-label=\"FRAME-EPOCH-ONE\">One</button>");
    let page = browser
        .new_page(&data_url(&format!(
            "<main>parent</main><iframe src='{first_url}'></iframe>"
        )))
        .await
        .expect("framed page");
    let options = AccessibilitySnapshotOptions::default();

    let first = page
        .accessibility_snapshot_in_frame("data:text/html,%3Cbutton", options)
        .await
        .expect("first frame snapshot");
    let DocumentEpoch::Known(first_epoch) = first.scope.epoch else {
        panic!("owned frame epoch should be known")
    };

    let second_url = data_url("<button aria-label=\"FRAME-EPOCH-TWO\">Two</button>");
    navigate_frame(&page, &second_url).await;
    let second = page
        .accessibility_snapshot_in_frame("data:text/html,%3Cbutton", options)
        .await
        .expect("second frame snapshot");
    assert_eq!(second.scope.frame_id, first.scope.frame_id);
    assert_eq!(second.scope.epoch, DocumentEpoch::Known(first_epoch + 1));

    navigate_frame(&page, &second_url).await;
    let reloaded = page
        .accessibility_snapshot_in_frame("data:text/html,%3Cbutton", options)
        .await
        .expect("reloaded frame snapshot");
    assert_eq!(reloaded.scope.frame_id, first.scope.frame_id);
    assert_eq!(reloaded.scope.epoch, DocumentEpoch::Known(first_epoch + 2));

    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn attached_page_epoch_is_explicitly_unavailable() {
    let owner = session().await;
    let owner_page = owner
        .new_page(&data_url(
            "<title>snapshot-owner-page</title><main>owner</main>",
        ))
        .await
        .expect("owner page");
    assert_eq!(
        owner_page
            .title()
            .await
            .expect("owner page title")
            .as_deref(),
        Some("snapshot-owner-page")
    );
    let attached = BrowserSession::connect(owner.websocket_url().await)
        .await
        .expect("attach browser");
    let pages = attached.pages().await.expect("attached pages");
    let mut adopted_page = None;
    for candidate in pages {
        if candidate
            .title()
            .await
            .expect("attached page title")
            .as_deref()
            == Some("snapshot-owner-page")
        {
            adopted_page = Some(candidate);
            break;
        }
    }
    let page = adopted_page.expect("attached session includes owner page");

    let adopted = page
        .rendered_dom_snapshot(1024)
        .await
        .expect("adopted snapshot");
    assert_eq!(
        adopted.scope.epoch,
        DocumentEpoch::UnavailableForAttachedPage
    );

    attached.close().await.expect("release attached browser");
    owner.close().await.expect("close owner browser");
}
