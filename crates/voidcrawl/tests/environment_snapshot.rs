//! Black-box contract tests for `Page::environment_snapshot` (CAS-319).
//!
//! These tests require Chromium. Run serially:
//!
//!     cargo test -p void_crawl_core --test environment_snapshot --
//! --test-threads=1
#![allow(clippy::expect_used, clippy::unwrap_used, clippy::panic)]

use std::time::Duration;

use void_crawl_core::{
    BrowserSession, CapabilityDisabledReason, CapabilityState, CdpMode, EnvironmentObservation,
    EnvironmentUnavailableReason, InstrumentationMode,
};
use yosoi_types::{BrowserMode, ColorScheme, ReducedMotion};

async fn session(mode: CdpMode) -> BrowserSession {
    BrowserSession::builder()
        .headless()
        .cdp_mode(mode)
        .launch()
        .await
        .expect("launching local Chromium")
}

#[tokio::test]
async fn normal_headless_snapshot_contains_effective_environment() {
    let browser = session(CdpMode::Normal).await;
    let page = browser
        .new_page("data:text/html,<title>environment</title>")
        .await
        .expect("new local data page");
    let snapshot = page
        .environment_snapshot()
        .await
        .expect("environment snapshot");
    let serialized = serde_json::to_string(&snapshot).expect("serialize snapshot");
    for forbidden in [
        "user_data_dir",
        "profile_path",
        "ws_url",
        "proxy",
        "request_headers",
        "cookie_values",
        "target_id",
    ] {
        assert!(
            !serialized.contains(forbidden),
            "snapshot leaked forbidden field {forbidden}"
        );
    }

    assert_eq!(snapshot.controller.name, "void_crawl_core");
    assert!(!snapshot.controller.version.is_empty());
    assert!(
        snapshot.renderer.product.contains("Chrome")
            || snapshot.renderer.product.contains("Chromium"),
        "unexpected renderer product: {:?}",
        snapshot.renderer.product
    );
    assert_eq!(
        snapshot.mode,
        EnvironmentObservation::Known {
            value: BrowserMode::Headless
        }
    );

    let EnvironmentObservation::Known { value: viewport } = snapshot.rendering.viewport else {
        panic!("effective viewport was not observed")
    };
    assert!(viewport.width_css_pixels().get() > 0);
    assert!(viewport.height_css_pixels().get() > 0);

    let EnvironmentObservation::Known { value: dpr } = snapshot.rendering.device_scale_factor
    else {
        panic!("effective device scale factor was not observed")
    };
    assert!(dpr.is_finite() && dpr > 0.0);

    let EnvironmentObservation::Known { value: user_agent } = snapshot.rendering.user_agent else {
        panic!("effective user agent was not observed")
    };
    assert!(user_agent.contains("Chrome/"));
    assert!(!user_agent.contains("Headless"));

    assert!(matches!(
        snapshot.rendering.locale,
        EnvironmentObservation::Known { .. }
    ));
    assert!(matches!(
        snapshot.rendering.timezone,
        EnvironmentObservation::Known { .. }
    ));
    assert!(matches!(
        snapshot.rendering.color_scheme,
        EnvironmentObservation::Known {
            value: ColorScheme::Light | ColorScheme::Dark | ColorScheme::NoPreference,
        }
    ));
    assert!(matches!(
        snapshot.rendering.reduced_motion,
        EnvironmentObservation::Known {
            value: ReducedMotion::Reduce | ReducedMotion::NoPreference,
        }
    ));

    assert_eq!(
        snapshot.instrumentation.configured_mode,
        InstrumentationMode::Normal
    );
    assert!(snapshot.instrumentation.network_enabled);
    assert!(snapshot.instrumentation.runtime_enabled);
    assert_eq!(
        snapshot.capabilities.rendered_dom,
        CapabilityState::Supported
    );
    assert_eq!(
        snapshot.capabilities.accessibility_tree,
        CapabilityState::Supported
    );

    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn minimal_network_capability_requires_explicit_escalation() {
    let browser = session(CdpMode::Minimal).await;
    let page = browser
        .new_page("data:text/html,<p>local</p>")
        .await
        .expect("new local data page");
    let before = page
        .environment_snapshot()
        .await
        .expect("snapshot before escalation");
    let disabled = CapabilityState::Disabled {
        reason: CapabilityDisabledReason::MinimalCdpMode,
    };

    assert_eq!(
        before.instrumentation.configured_mode,
        InstrumentationMode::Minimal
    );
    assert!(!before.instrumentation.network_enabled);
    // This snapshot must use one-shot main-world evaluation: Minimal has no
    // Runtime execution-context events to wait for.
    assert!(!before.instrumentation.runtime_enabled);
    assert!(matches!(
        before.rendering.user_agent,
        EnvironmentObservation::Known { .. }
    ));
    assert!(!before.instrumentation.escalated_from_minimal);
    assert_eq!(before.capabilities.document_response_metadata, disabled);
    assert_eq!(before.capabilities.selected_response_bodies, disabled);

    let _ = page
        .wait_for_network_idle(Duration::from_millis(25))
        .await
        .expect("network instrumentation escalation");
    let after = page
        .environment_snapshot()
        .await
        .expect("snapshot after escalation");

    assert!(after.instrumentation.network_enabled);
    assert!(after.instrumentation.escalated_from_minimal);
    assert_eq!(
        after.capabilities.document_response_metadata,
        CapabilityState::Supported
    );
    assert_eq!(
        after.capabilities.selected_response_bodies,
        CapabilityState::Supported
    );

    page.close().await.expect("close page");
    browser.close().await.expect("close browser");
}

#[tokio::test]
async fn attached_browser_mode_reports_unavailable() {
    let owner = session(CdpMode::Normal).await;
    let owner_page = owner.new_blank_page().await.expect("new owner page");
    owner_page
        .evaluate_js("document.title = 'attached-environment-owner';")
        .await
        .expect("mark owner page");
    assert_eq!(
        owner_page
            .title()
            .await
            .expect("owner page title")
            .as_deref(),
        Some("attached-environment-owner")
    );
    let attached = BrowserSession::builder()
        .remote_debug(owner.websocket_url().await)
        .minimal_cdp()
        .launch()
        .await
        .expect("attach to local browser");
    let pages = attached.pages().await.expect("attached pages");
    let mut attached_page = None;
    for candidate in pages {
        if candidate
            .title()
            .await
            .expect("attached page title")
            .as_deref()
            == Some("attached-environment-owner")
        {
            attached_page = Some(candidate);
            break;
        }
    }
    let attached_page = attached_page.expect("attached session includes owner page");
    let snapshot = attached_page
        .environment_snapshot()
        .await
        .expect("attached snapshot");

    assert_eq!(
        snapshot.mode,
        EnvironmentObservation::Unavailable {
            reason: EnvironmentUnavailableReason::AttachedBrowserNotControlled,
        }
    );
    assert!(snapshot.instrumentation.attached_browser);
    assert_eq!(
        snapshot.capabilities.document_response_metadata,
        CapabilityState::Unavailable {
            reason: void_crawl_core::CapabilityUnavailableReason::AttachedBrowserStateNotControlled,
        }
    );

    attached.close().await.expect("release attached session");
    owner.close().await.expect("close owner browser");
}
