//! A page that has loaded Turnstile's runtime
//! (`challenges.cloudflare.com/turnstile/v0/api.js`
//! + `window.turnstile`) but hasn't rendered the widget yet is still a
//! captcha wall in practice — the widget will mount on the next user
//! action and block the agent's flow. Report it as such.
//!
//! Ahrefs' free backlink-checker + website-authority-checker are the
//! real-world exemplars; without this detection the agent happily
//! submits a form, gets no results, and never understands why.

#![allow(clippy::expect_used, clippy::unwrap_used, clippy::panic)]

use crate::internal::browser::{BrowserSession, CaptchaKind, detect_captcha};

async fn headless_session() -> BrowserSession {
    BrowserSession::builder()
        .headless()
        .launch()
        .await
        .expect("launch")
}

#[tokio::test]
async fn detects_turnstile_when_runtime_is_loaded_but_widget_absent() {
    let session = headless_session().await;

    // Simulate what Ahrefs' free checker looks like before submit:
    // Turnstile's runtime JS is present (script tag + a fake
    // `window.turnstile` object), but no widget iframe or
    // `.cf-turnstile` element has mounted.
    let page = session
        .new_page("data:text/html,<html><body>placeholder</body></html>")
        .await
        .expect("new_page");
    // Inject the Turnstile-loaded state via JS so we don't have to
    // URL-encode an HTML fixture.
    let _ = page
        .evaluate_js(
            r#"(() => {
              const s = document.createElement('script');
              s.id = 'cf-turnstile-script';
              s.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js';
              document.head.appendChild(s);
              window.turnstile = { render: function(){}, ready: function(){} };
              return true;
            })()"#,
        )
        .await
        .expect("inject");

    let kind = detect_captcha(&page).await.expect("detect_captcha");
    assert_eq!(
        kind,
        Some(CaptchaKind::Turnstile),
        "Turnstile runtime was loaded (script + window.turnstile); detector should flag it as a captcha wall even before the widget renders"
    );

    page.close().await.ok();
    session.close().await.ok();
}

#[tokio::test]
async fn does_not_false_positive_on_plain_page() {
    let session = headless_session().await;
    let page = session
        .new_page("data:text/html,<html><body>hello</body></html>")
        .await
        .expect("new_page");
    let kind = detect_captcha(&page).await.expect("detect_captcha");
    assert_eq!(kind, None, "plain page should not trip the detector");
    page.close().await.ok();
    session.close().await.ok();
}
