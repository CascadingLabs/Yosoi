//! `capture_captcha` pulls every piece a third-party solver (2Captcha,
//! CapSolver, Anti-Captcha) needs to produce a token: kind, sitekey,
//! widget selector + rect, response-field selector, page URL, and any
//! already-present token.
//!
//! Without this the caller has to re-probe the page themselves — at
//! which point voidcrawl is a worse puppeteer. The capture API is the
//! hand-off point between "voidcrawl saw the captcha" and "solver
//! service produces a token", and it needs to be complete enough that
//! the caller never has to touch the DOM.

#![allow(clippy::expect_used, clippy::unwrap_used, clippy::panic)]

use crate::internal::browser::{
    BrowserSession, CaptchaKind, capture_captcha, detect_captcha, inject_captcha_token,
};

async fn headless_session() -> BrowserSession {
    BrowserSession::builder()
        .headless()
        .launch()
        .await
        .expect("launch")
}

#[tokio::test]
async fn captures_turnstile_sitekey_from_data_attr() {
    let session = headless_session().await;
    let page = session
        .new_page("data:text/html,<html><body><div class='cf-turnstile' data-sitekey='0x4AAAAAAA_test_key_abc' data-action='login' data-cdata='ctx123'></div></body></html>")
        .await
        .expect("new_page");

    let info = capture_captcha(&page)
        .await
        .expect("capture")
        .expect("should detect");
    assert_eq!(info.kind, CaptchaKind::Turnstile);
    assert_eq!(info.sitekey.as_deref(), Some("0x4AAAAAAA_test_key_abc"));
    assert_eq!(info.action.as_deref(), Some("login"));
    assert_eq!(info.cdata.as_deref(), Some("ctx123"));
    assert!(info.widget_rendered, "widget element present in DOM");
    assert!(info.page_url.starts_with("data:"));

    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn captures_recaptcha_sitekey_from_data_attr() {
    let session = headless_session().await;
    let page = session
        .new_page("data:text/html,<html><body><div class='g-recaptcha' data-sitekey='6LexampleSiteKey_v2'></div></body></html>")
        .await
        .expect("new_page");

    let info = capture_captcha(&page)
        .await
        .expect("capture")
        .expect("should detect");
    assert_eq!(info.kind, CaptchaKind::Recaptcha);
    assert_eq!(info.sitekey.as_deref(), Some("6LexampleSiteKey_v2"));

    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn captures_existing_turnstile_token_if_widget_already_solved() {
    let session = headless_session().await;
    let page = session
        .new_page("data:text/html,<html><body><div class='cf-turnstile' data-sitekey='0x4test'><input name='cf-turnstile-response' value='SOLVED_TOKEN_123'></div></body></html>")
        .await
        .expect("new_page");

    let info = capture_captcha(&page)
        .await
        .expect("capture")
        .expect("should detect");
    assert_eq!(info.existing_token.as_deref(), Some("SOLVED_TOKEN_123"));
    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn capture_returns_none_on_plain_page() {
    let session = headless_session().await;
    let page = session
        .new_page("data:text/html,<html><body>hi</body></html>")
        .await
        .expect("new_page");
    assert!(capture_captcha(&page).await.expect("capture").is_none());
    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn detect_captcha_remains_backward_compat_wrapper() {
    let session = headless_session().await;
    let page = session
        .new_page("data:text/html,<html><body><div class='cf-turnstile' data-sitekey='0x4t'></div></body></html>")
        .await
        .expect("new_page");
    let kind = detect_captcha(&page).await.expect("detect");
    assert_eq!(kind, Some(CaptchaKind::Turnstile));
    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn inject_token_writes_into_turnstile_response_field() {
    let session = headless_session().await;
    let page = session
        .new_page("data:text/html,<html><body><form><div class='cf-turnstile' data-sitekey='0x4t'></div><input name='cf-turnstile-response' value=''></form></body></html>")
        .await
        .expect("new_page");

    inject_captcha_token(&page, CaptchaKind::Turnstile, "SOLVED_FROM_EXTERNAL_SOLVER")
        .await
        .expect("inject");

    let v = page
        .evaluate_js("document.querySelector('input[name=cf-turnstile-response]').value")
        .await
        .expect("read");
    assert_eq!(v.as_str(), Some("SOLVED_FROM_EXTERNAL_SOLVER"));

    page.close().await.ok();
    session.close().await.ok();
}
