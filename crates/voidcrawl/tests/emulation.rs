//! Integration tests for geolocation / locale / timezone emulation.
//!
//! Require a real Chromium/Chrome binary. Run serially:
//!
//!     cargo test -p void_crawl_core --test emulation -- --test-threads=1
#![allow(clippy::expect_used, clippy::unwrap_used, clippy::absolute_paths)]

use std::time::Duration;

use serde_json::Value;
use void_crawl_core::{BrowserSession, Page};

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

/// Poll `expr` until it evaluates to non-null or the budget runs out.
async fn poll_js(page: &Page, expr: &str) -> Value {
    for _ in 0..40 {
        if let Ok(v) = page.evaluate_js(expr).await
            && !v.is_null()
        {
            return v;
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    Value::Null
}

#[tokio::test]
async fn set_locale_changes_intl_resolved_locale() {
    // `setLocaleOverride` drives Intl + the Accept-Language header (the
    // server-facing lever), not `navigator.language` (the browser UI lang).
    let session = headless_session().await;
    let page = session.new_blank_page().await.expect("blank page");
    page.set_locale("fr-FR").await.expect("set_locale");
    page.navigate(&data_url("<!doctype html><title>x</title>"))
        .await
        .expect("navigate");

    let locale = poll_js(&page, "Intl.DateTimeFormat().resolvedOptions().locale").await;
    assert_eq!(locale, Value::from("fr-FR"));

    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn set_timezone_changes_resolved_timezone() {
    let session = headless_session().await;
    let page = session.new_blank_page().await.expect("blank page");
    page.set_timezone("America/New_York")
        .await
        .expect("set_timezone");
    page.navigate(&data_url("<!doctype html><title>x</title>"))
        .await
        .expect("navigate");

    let tz = poll_js(&page, "Intl.DateTimeFormat().resolvedOptions().timeZone").await;
    assert_eq!(tz, Value::from("America/New_York"));

    page.close().await.ok();
    session.close().await.ok();
}

/// Sets the override before navigation, then a load-time script calls
/// `getCurrentPosition`. Reveals whether the geolocation *permission* needs an
/// explicit grant in headless: success → coords; denial → `{error: 1}`.
#[tokio::test]
async fn set_geolocation_is_readable_by_navigator() {
    // `navigator.geolocation` requires a secure context, so the fixture is a
    // real https origin (not a `data:` URL, which is opaque/insecure).
    let session = headless_session().await;
    let page = session.new_blank_page().await.expect("blank page");
    // Times Square.
    page.set_geolocation(40.758, -73.9855, Some(10.0))
        .await
        .expect("set_geolocation");
    page.navigate("https://example.com")
        .await
        .expect("navigate");

    page.evaluate_js(
        "navigator.geolocation.getCurrentPosition(\
          p => { window.__geo = { lat: p.coords.latitude, lon: p.coords.longitude }; },\
          e => { window.__geo = { error: e.code }; }); true",
    )
    .await
    .expect("kick off getCurrentPosition");

    let geo = poll_js(&page, "window.__geo || null").await;
    let lat = geo.get("lat").and_then(Value::as_f64);
    assert!(
        lat.is_some_and(|v| (v - 40.758).abs() < 0.01),
        "navigator.geolocation should report the override, got {geo:?}"
    );

    page.close().await.ok();
    session.close().await.ok();
}
