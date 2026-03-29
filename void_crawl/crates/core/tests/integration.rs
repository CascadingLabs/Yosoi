//! Integration tests for void_crawl_core.
//!
//! These tests require a real Chromium/Chrome binary to be available.

use std::collections::HashMap;

use void_crawl_core::{BrowserPool, BrowserSession, PoolConfig, StealthConfig};

/// Helper: launch headless with no-sandbox (required for CI / containers).
async fn headless_session() -> BrowserSession {
    BrowserSession::builder()
        .headless()
        .no_sandbox()
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
    page.set_headers(headers)
        .await
        .expect("set_headers failed");

    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn test_no_stealth_mode() {
    let session = BrowserSession::builder()
        .headless()
        .no_sandbox()
        .no_stealth()
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

#[tokio::test]
async fn test_custom_stealth_config() {
    let stealth = StealthConfig {
        user_agent: Some("YosoiTestBot/1.0".into()),
        viewport_width: 1280,
        viewport_height: 720,
        locale: "en-GB,en;q=0.9".into(),
        inject_js: None,
        use_builtin_stealth: false,
        bypass_csp: false,
    };

    let session = BrowserSession::builder()
        .headless()
        .no_sandbox()
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

// ── Pool tests ─────────────────────────────────────────────────────────

/// Helper: create a pool with the given config, launching headless no-sandbox.
async fn test_pool(config: PoolConfig) -> BrowserPool {
    let mut sessions = Vec::with_capacity(config.browsers);
    for _ in 0..config.browsers {
        let session = BrowserSession::builder()
            .headless()
            .no_sandbox()
            .launch()
            .await
            .expect("failed to launch browser for pool");
        sessions.push(session);
    }
    BrowserPool::new(config, sessions)
}

#[tokio::test]
async fn test_pool_basic() {
    let config = PoolConfig {
        browsers: 1,
        tabs_per_browser: 1,
        tab_max_uses: 50,
        tab_max_idle_secs: 60,
    };
    let pool = test_pool(config).await;
    pool.warmup().await.expect("warmup failed");

    // First acquire
    let tab = pool.acquire().await.expect("acquire failed");
    assert_eq!(tab.use_count, 0);
    tab.page
        .navigate("https://example.com")
        .await
        .expect("navigate failed");
    let html = tab.page.content().await.expect("content failed");
    assert!(html.contains("Example Domain"));
    pool.release(tab).await.expect("release failed");

    // Second acquire — should get a recycled tab with use_count == 1
    let tab2 = pool.acquire().await.expect("second acquire failed");
    assert_eq!(tab2.use_count, 1);
    pool.release(tab2).await.expect("second release failed");

    pool.close().await.expect("pool close failed");
}

#[tokio::test]
async fn test_pool_parallel() {
    let config = PoolConfig {
        browsers: 1,
        tabs_per_browser: 4,
        tab_max_uses: 50,
        tab_max_idle_secs: 60,
    };
    let pool = test_pool(config).await;
    pool.warmup().await.expect("warmup failed");

    // Acquire all 4 tabs concurrently
    let (t1, t2, t3, t4) = tokio::join!(
        pool.acquire(),
        pool.acquire(),
        pool.acquire(),
        pool.acquire(),
    );
    let t1 = t1.expect("acquire 1");
    let t2 = t2.expect("acquire 2");
    let t3 = t3.expect("acquire 3");
    let t4 = t4.expect("acquire 4");

    // Navigate all to example.com
    for tab in [&t1, &t2, &t3, &t4] {
        tab.page
            .navigate("https://example.com")
            .await
            .expect("navigate failed");
        let html = tab.page.content().await.expect("content failed");
        assert!(html.contains("Example Domain"));
    }

    // Release all
    pool.release(t1).await.expect("release 1");
    pool.release(t2).await.expect("release 2");
    pool.release(t3).await.expect("release 3");
    pool.release(t4).await.expect("release 4");

    pool.close().await.expect("pool close failed");
}

#[tokio::test]
async fn test_pool_hard_recycle() {
    let config = PoolConfig {
        browsers: 1,
        tabs_per_browser: 1,
        tab_max_uses: 2,
        tab_max_idle_secs: 60,
    };
    let pool = test_pool(config).await;
    pool.warmup().await.expect("warmup failed");

    // Use 1
    let tab = pool.acquire().await.expect("acquire 1");
    assert_eq!(tab.use_count, 0);
    pool.release(tab).await.expect("release 1");

    // Use 2
    let tab = pool.acquire().await.expect("acquire 2");
    assert_eq!(tab.use_count, 1);
    pool.release(tab).await.expect("release 2");

    // Use 3 — should trigger hard recycle (use_count was 2, >= tab_max_uses)
    let tab = pool.acquire().await.expect("acquire 3");
    assert_eq!(tab.use_count, 0, "tab should have been hard-recycled");
    pool.release(tab).await.expect("release 3");

    pool.close().await.expect("pool close failed");
}

#[tokio::test]
async fn test_pool_idle_eviction() {
    let config = PoolConfig {
        browsers: 1,
        tabs_per_browser: 1,
        tab_max_uses: 50,
        tab_max_idle_secs: 1,
    };
    let pool = test_pool(config).await;
    pool.warmup().await.expect("warmup failed");

    // Acquire, use, release
    let tab = pool.acquire().await.expect("acquire");
    pool.release(tab).await.expect("release");

    // Wait for idle timeout
    tokio::time::sleep(std::time::Duration::from_secs(2)).await;

    // Evict idle tabs — should replace with fresh ones
    pool.evict_idle().await.expect("evict_idle failed");

    // Acquire again — should get a fresh tab (use_count reset)
    let tab = pool.acquire().await.expect("acquire after eviction");
    assert_eq!(tab.use_count, 0, "evicted tab should be fresh");
    pool.release(tab).await.expect("release after eviction");

    pool.close().await.expect("pool close failed");
}
