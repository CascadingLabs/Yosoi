#![allow(clippy::expect_used, clippy::unwrap_used, clippy::panic)]

use std::error::Error;

use crate::internal::browser::{
    BrowserSession, DocumentEpoch, ObservationResponseFilter, ObservationWatchOptions,
    VoidCrawlError,
};

type TestError = Box<dyn Error + Send + Sync>;

const ORIGINAL_DOCUMENT: &str = r#"<!doctype html>
<html><body>
  <button id="trigger" type="button">Original trigger</button>
  <input id="field" type="text">
</body></html>"#;

const REPLACEMENT_DOCUMENT: &str = r#"<!doctype html>
<html><body>
  <button id="trigger" type="button" onclick="window.clickCount += 1">Replacement trigger</button>
  <input id="field" type="text">
  <script>window.clickCount = 0;</script>
</body></html>"#;

fn data_url(html: &str) -> String {
    let mut encoded = String::with_capacity(html.len().saturating_mul(3));
    for byte in html.bytes() {
        if byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'.' | b'_' | b'~') {
            encoded.push(char::from(byte));
        } else {
            use std::fmt::Write as _;
            let _ = write!(&mut encoded, "%{byte:02X}");
        }
    }
    format!("data:text/html,{encoded}")
}

async fn browser_session() -> BrowserSession {
    let mode = std::env::var("YOSOI_MODE")
        .ok()
        .or_else(|| std::env::var("YOSOI_YIELD_MODE").ok());
    if mode.as_deref() == Some("headful") {
        BrowserSession::builder()
            .headful()
            .launch()
            .await
            .expect("launch regular Stable headful Chrome")
    } else {
        BrowserSession::builder()
            .headless()
            .launch()
            .await
            .expect("launch regular Stable headless Chrome")
    }
}

fn browser_tests_enabled() -> bool {
    if std::env::var("YOSOI_BROWSER_TESTS").as_deref() == Ok("1") {
        true
    } else {
        eprintln!("SKIPPED: set YOSOI_BROWSER_TESTS=1 for scoped provider input tests");
        false
    }
}

fn network_only_watch_options() -> ObservationWatchOptions {
    ObservationWatchOptions {
        observe_dom: false,
        observe_accessibility: false,
        response_filters: vec![ObservationResponseFilter {
            url: "https://voidcrawl.invalid/scoped-eval-never-requested".to_owned(),
            method: Some("GET".to_owned()),
            status: Some(200),
        }],
        max_events: 8,
        max_bytes: 1_024,
    }
}

#[tokio::test(flavor = "current_thread")]
async fn scoped_native_input_rejects_replacement_document_and_accepts_current_scope()
-> Result<(), TestError> {
    if !browser_tests_enabled() {
        return Ok(());
    }

    let browser = browser_session().await;
    let page = browser.new_page(&data_url(ORIGINAL_DOCUMENT)).await?;
    let original_scope = page.document_scope().await?;
    assert!(matches!(original_scope.epoch, DocumentEpoch::Known(_)));
    let mut original_watch = page
        .start_observation_watch(network_only_watch_options())
        .await?;
    assert_eq!(original_watch.start_scope(), &original_scope);

    page.navigate(&data_url(REPLACEMENT_DOCUMENT)).await?;
    let replacement_scope = page.document_scope().await?;
    assert!(matches!(replacement_scope.epoch, DocumentEpoch::Known(_)));
    assert_ne!(
        original_scope.epoch, replacement_scope.epoch,
        "fixture navigation must advance the document epoch"
    );

    let stale_click = page
        .click_element_in_scope("#trigger", &original_watch)
        .await;
    assert!(matches!(
        stale_click,
        Err(VoidCrawlError::NavigationStateUncertain)
    ));
    let stale_type = page
        .type_into_in_scope("#field", "must-not-be-typed", &original_watch)
        .await;
    assert!(matches!(
        stale_type,
        Err(VoidCrawlError::NavigationStateUncertain)
    ));

    let unchanged = page
        .evaluate_js(
            "({ clicks: window.clickCount, value: document.querySelector('#field').value })",
        )
        .await?;
    let unchanged = unchanged
        .as_object()
        .ok_or("replacement state probe did not return an object")?;
    assert_eq!(
        unchanged.get("clicks").and_then(serde_json::Value::as_u64),
        Some(0)
    );
    assert_eq!(
        unchanged.get("value").and_then(serde_json::Value::as_str),
        Some("")
    );

    original_watch.settle().await?;
    drop(original_watch);
    let current_scope = page.document_scope().await?;
    assert_eq!(current_scope, replacement_scope);
    let mut current_watch = page
        .start_observation_watch(network_only_watch_options())
        .await?;
    assert_eq!(current_watch.start_scope(), &current_scope);
    page.click_element_in_scope("#trigger", &current_watch)
        .await?;
    page.type_into_in_scope("#field", "current-document", &current_watch)
        .await?;

    let updated = page
        .evaluate_js(
            "({ clicks: window.clickCount, value: document.querySelector('#field').value })",
        )
        .await?;
    let updated = updated
        .as_object()
        .ok_or("current state probe did not return an object")?;
    assert_eq!(
        updated.get("clicks").and_then(serde_json::Value::as_u64),
        Some(1)
    );
    assert_eq!(
        updated.get("value").and_then(serde_json::Value::as_str),
        Some("current-document")
    );

    current_watch.settle().await?;
    page.close().await?;
    browser.close().await?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn observation_watch_cannot_authorize_native_input_on_another_page() -> Result<(), TestError>
{
    if !browser_tests_enabled() {
        return Ok(());
    }

    let browser = browser_session().await;
    let page_a = browser.new_page(&data_url(REPLACEMENT_DOCUMENT)).await?;
    let scope_a = page_a.document_scope().await?;
    let mut watch_a = page_a
        .start_observation_watch(network_only_watch_options())
        .await?;
    assert_eq!(watch_a.start_scope(), &scope_a);

    let page_b = browser.new_page(&data_url(REPLACEMENT_DOCUMENT)).await?;
    let scope_b = page_b.document_scope().await?;
    assert_eq!(
        scope_a, scope_b,
        "fixture pages must exercise equal capture-local scope numbers"
    );

    let foreign_click = page_b.click_element_in_scope("#trigger", &watch_a).await;
    assert!(matches!(
        foreign_click,
        Err(VoidCrawlError::NavigationStateUncertain)
    ));
    let foreign_type = page_b
        .type_into_in_scope("#field", "must-not-cross-pages", &watch_a)
        .await;
    assert!(matches!(
        foreign_type,
        Err(VoidCrawlError::NavigationStateUncertain)
    ));

    let state = page_b
        .evaluate_js(
            "({ clicks: window.clickCount, value: document.querySelector('#field').value })",
        )
        .await?;
    let state = state
        .as_object()
        .ok_or("foreign-page state probe did not return an object")?;
    assert_eq!(
        state.get("clicks").and_then(serde_json::Value::as_u64),
        Some(0)
    );
    assert_eq!(
        state.get("value").and_then(serde_json::Value::as_str),
        Some("")
    );

    watch_a.settle().await?;
    page_b.close().await?;
    page_a.close().await?;
    browser.close().await?;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn observation_scoped_eval_rejects_replacement_context_and_accepts_current_watch()
-> Result<(), TestError> {
    if !browser_tests_enabled() {
        return Ok(());
    }

    let browser = browser_session().await;
    let page = browser.new_page(&data_url(ORIGINAL_DOCUMENT)).await?;
    let original_scope = page.document_scope().await?;
    let options = network_only_watch_options();
    let mut stale_watch = page.start_observation_watch(options.clone()).await?;
    assert_eq!(stale_watch.start_scope(), &original_scope);

    page.navigate(&data_url(REPLACEMENT_DOCUMENT)).await?;
    let replacement_scope = page.document_scope().await?;
    assert!(matches!(replacement_scope.epoch, DocumentEpoch::Known(_)));
    assert_ne!(original_scope.epoch, replacement_scope.epoch);

    let expression =
        "(() => { window.__evalHits = (window.__evalHits || 0) + 1; return window.__evalHits; })()";
    let stale_result = page
        .evaluate_js_in_observation_scope(expression, &stale_watch)
        .await;
    assert!(matches!(
        stale_result,
        Err(VoidCrawlError::NavigationStateUncertain)
    ));
    let arrow_function = "() => { window.__evalHits += 1; return window.__evalHits; }";
    let stale_arrow_result = page
        .evaluate_js_in_observation_scope(arrow_function, &stale_watch)
        .await;
    assert!(matches!(
        stale_arrow_result,
        Err(VoidCrawlError::NavigationStateUncertain)
    ));
    let hits_after_stale = page.evaluate_js("window.__evalHits || 0").await?;
    assert_eq!(hits_after_stale.as_u64(), Some(0));

    // This watch has network subscriptions only: settling it owns no DOM
    // observer RemoteObject or page binding from the departed context.
    stale_watch.settle().await?;
    drop(stale_watch);
    let mut current_watch = page.start_observation_watch(options).await?;
    assert_eq!(current_watch.start_scope(), &replacement_scope);
    let current_result = page
        .evaluate_js_in_observation_scope(expression, &current_watch)
        .await?;
    assert_eq!(current_result.as_u64(), Some(1));
    let arrow_result = page
        .evaluate_js_in_observation_scope(arrow_function, &current_watch)
        .await?;
    assert_eq!(arrow_result.as_u64(), Some(2));
    let final_hits = page.evaluate_js("window.__evalHits").await?;
    assert_eq!(final_hits.as_u64(), Some(2));
    current_watch.settle().await?;

    page.close().await?;
    browser.close().await?;
    Ok(())
}
