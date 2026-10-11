//! Integration tests for accessibility-tree access.
//!
//! Require a real Chromium/Chrome binary. Run serially:
//!
//!     cargo test -p yosoi --features browser --lib internal::browser::integration_tests::ax_tree -- --test-threads=1
#![allow(clippy::expect_used, clippy::unwrap_used)]

use crate::internal::browser as internal_browser;
use crate::internal::browser::{BrowserSession, Page};
use serde_json::Value;

async fn headless_session() -> BrowserSession {
    BrowserSession::builder()
        .headless()
        .launch()
        .await
        .expect("failed to launch headless browser")
}

/// Wrap HTML in a `data:` URL, percent-encoding the few characters that would
/// otherwise break URL parsing. Keeps fixtures inline — no test server needed.
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

/// Pull the inner accessible-name string out of an AXValue-wrapped field.
fn ax_name(node: &Value) -> &str {
    node.get("name")
        .and_then(|v| v.get("value"))
        .and_then(Value::as_str)
        .unwrap_or("")
}

fn ax_role(node: &Value) -> &str {
    node.get("role")
        .and_then(|v| v.get("value"))
        .and_then(Value::as_str)
        .unwrap_or("")
}

#[tokio::test]
async fn full_ax_tree_exposes_implicit_role_and_computed_name() {
    let session = headless_session().await;
    let html = "<!doctype html><html><body><main>\
        <button>Load more</button></main></body></html>";
    let page = page_with(html, &session).await;

    let tree = page
        .get_full_ax_tree(None)
        .await
        .expect("get_full_ax_tree failed");
    let nodes = tree.as_array().expect("AX tree should be a JSON array");

    // The <button> carries no aria-* attribute, yet the browser computes
    // role=button with the text as its accessible name.
    let button = nodes
        .iter()
        .find(|n| ax_role(n) == "button")
        .expect("expected a node with role=button");
    assert_eq!(ax_name(button), "Load more");
    // A landmark <main> should be present too.
    assert!(
        nodes.iter().any(|n| ax_role(n) == "main"),
        "expected a main landmark"
    );

    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn query_ax_tree_matches_by_role_and_name() {
    let session = headless_session().await;
    let html = "<!doctype html><html><body>\
        <button>Save</button><button>Cancel</button></body></html>";
    let page = page_with(html, &session).await;

    let matches = page
        .query_ax_tree(Some("button"), Some("Cancel"))
        .await
        .expect("query_ax_tree failed");
    let matched = matches.as_array().expect("array");
    assert_eq!(matched.len(), 1, "exactly one button named Cancel");
    assert_eq!(ax_name(&matched[0]), "Cancel");

    let none = page
        .query_ax_tree(Some("button"), Some("Nonexistent"))
        .await
        .expect("query_ax_tree failed");
    assert_eq!(
        none.as_array().expect("array").as_slice().len(),
        0,
        "no match → empty"
    );

    page.close().await.ok();
    session.close().await.ok();
}

/// The CAS-27 headline test: an AX selector survives a markup refactor that
/// breaks a CSS selector. `<div role=button aria-label>` → `<button>` keeps
/// the same role + accessible name, so the AX query holds while the CSS
/// selector tied to the old shape no longer matches.
#[tokio::test]
async fn ax_selector_survives_markup_change_that_breaks_css() {
    let session = headless_session().await;

    // Old shape: an ARIA-decorated div.
    let old_html = "<!doctype html><html><body><main>\
        <div role=\"button\" aria-label=\"Load more\">x</div></main></body></html>";
    let old_page = page_with(old_html, &session).await;
    let old_ax = old_page
        .query_ax_tree(Some("button"), Some("Load more"))
        .await
        .unwrap();
    let old_css = old_page
        .query_selector("div[role=\"button\"][aria-label=\"Load more\"]")
        .await
        .unwrap();
    assert_eq!(
        old_ax.as_array().unwrap().len(),
        1,
        "AX matches the old div"
    );
    assert!(old_css.is_some(), "CSS matches the old div");
    old_page.close().await.ok();

    // New shape: a native button. Same semantics, different markup.
    let new_html = "<!doctype html><html><body><main>\
        <button>Load more</button></main></body></html>";
    let new_page = page_with(new_html, &session).await;
    let new_ax = new_page
        .query_ax_tree(Some("button"), Some("Load more"))
        .await
        .unwrap();
    let new_css = new_page
        .query_selector("div[role=\"button\"][aria-label=\"Load more\"]")
        .await
        .unwrap();
    assert_eq!(
        new_ax.as_array().unwrap().len(),
        1,
        "AX selector SURVIVES the refactor"
    );
    assert!(new_css.is_none(), "CSS selector BREAKS on the refactor");
    new_page.close().await.ok();

    session.close().await.ok();
}

#[tokio::test]
async fn click_by_role_clicks_the_named_element() {
    let session = headless_session().await;
    let html = "<!doctype html><html><body>\
        <button onclick=\"window.__hits=(window.__hits||0)+1\">Subscribe</button>\
        </body></html>";
    let page = page_with(html, &session).await;

    page.click_by_role("button", "Subscribe", 0, false)
        .await
        .expect("click_by_role failed");
    let hits = page
        .evaluate_js("window.__hits")
        .await
        .expect("eval failed");
    assert_eq!(
        hits,
        Value::from(1),
        "the button's onclick should have fired once"
    );

    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn click_by_role_disambiguates_with_nth() {
    let session = headless_session().await;
    // Two same-named buttons; nth picks the second.
    let html = "<!doctype html><html><body>\
        <button onclick=\"window.__which='first'\">Go</button>\
        <button onclick=\"window.__which='second'\">Go</button>\
        </body></html>";
    let page = page_with(html, &session).await;

    page.click_by_role("button", "Go", 1, false)
        .await
        .expect("click_by_role nth=1 failed");
    let which = page
        .evaluate_js("window.__which")
        .await
        .expect("eval failed");
    assert_eq!(
        which,
        Value::from("second"),
        "nth=1 should click the second match"
    );

    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn click_by_role_errors_when_no_match() {
    let session = headless_session().await;
    let html = "<!doctype html><html><body><button>Only</button></body></html>";
    let page = page_with(html, &session).await;

    let err = page
        .click_by_role("button", "Missing", 0, false)
        .await
        .expect_err("should error");
    assert!(
        matches!(&err, internal_browser::VoidCrawlError::ElementNotFound(_)),
        "expected element-not-found error"
    );
    if let internal_browser::VoidCrawlError::ElementNotFound(diagnostic) = &err {
        assert!(
            diagnostic.contains("Missing"),
            "raw diagnostic should name the target"
        );
    }

    page.close().await.ok();
    session.close().await.ok();
}
