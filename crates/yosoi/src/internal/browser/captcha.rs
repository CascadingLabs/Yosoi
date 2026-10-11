//! Captcha / bot-wall capture and token injection.
//!
//! Two public surfaces:
//!
//! * [`capture_captcha`] — deep single-pass probe. Returns a [`CaptchaInfo`]
//!   with everything a third-party solver (2Captcha, CapSolver, Anti-Captcha)
//!   or a human-in-the-loop flow needs: kind, sitekey, widget rect,
//!   response-field selector, page URL, any token already present.
//! * [`detect_captcha`] — backward-compatible thin wrapper returning just the
//!   kind tag. Callers who only care "is there a captcha?" keep the shorter
//!   signature.
//!
//! Plus [`inject_captcha_token`] for wiring a solver-returned token
//! back into the page's hidden response field.
//!
//! Heuristics are intentionally conservative — false negatives are
//! preferable to false positives that would poison retry logic upstream.
//! The integration tests cover the supported detection signals and known gaps.

use serde::Serialize;
use serde_json::Value;

use crate::internal::browser::{error::Result, page::Page};

/// Identified captcha / challenge surface.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CaptchaKind {
    Recaptcha,
    Hcaptcha,
    Turnstile,
    CloudflareChallenge,
    DatadomeBlock,
    /// Unknown but strong captcha signal (e.g. page title "Just a moment…").
    Unknown(String),
}

impl CaptchaKind {
    pub fn as_str(&self) -> &str {
        match self {
            Self::Recaptcha => "recaptcha",
            Self::Hcaptcha => "hcaptcha",
            Self::Turnstile => "turnstile",
            Self::CloudflareChallenge => "cloudflare_challenge",
            Self::DatadomeBlock => "datadome",
            Self::Unknown(s) => s,
        }
    }

    fn from_tag(tag: &str) -> Self {
        match tag {
            "recaptcha" => Self::Recaptcha,
            "hcaptcha" => Self::Hcaptcha,
            "turnstile" => Self::Turnstile,
            "cloudflare_challenge" => Self::CloudflareChallenge,
            "datadome" => Self::DatadomeBlock,
            other => Self::Unknown(other.strip_prefix("unknown:").unwrap_or(other).to_string()),
        }
    }
}

/// Axis-aligned widget rectangle in CSS pixels (viewport coordinates).
#[derive(Debug, Clone, Copy, PartialEq, Serialize)]
pub struct WidgetRect {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
}

/// Structured captcha description — everything a solver or
/// human-in-the-loop needs to act on the challenge.
#[derive(Debug, Clone, PartialEq)]
pub struct CaptchaInfo {
    /// What kind of wall this is.
    pub kind: CaptchaKind,
    /// Site key to send to the solver, when discoverable.
    pub sitekey: Option<String>,
    /// CSS selector of the widget container (for later `inject_token`
    /// flows or visual clicks).
    pub widget_selector: Option<String>,
    /// On-screen rect of the widget, when it has been rendered.
    pub widget_rect: Option<WidgetRect>,
    /// True when the widget iframe / container is actually in the DOM.
    /// False when only the runtime is loaded (Ahrefs-style lazy mount).
    pub widget_rendered: bool,
    /// Hidden field selector the caller should write a solved token
    /// into (Turnstile `input[name=cf-turnstile-response]` etc.).
    pub response_field_selector: Option<String>,
    /// Token already present in the response field — skip solving if set.
    pub existing_token: Option<String>,
    /// Turnstile `data-action` attribute (optional solver input).
    pub action: Option<String>,
    /// Turnstile `data-cdata` attribute (optional solver input).
    pub cdata: Option<String>,
    /// Current document URL — required by most solver APIs.
    pub page_url: String,
}

/// Full structured capture. Returns `None` only when no captcha
/// marker matched.
pub async fn capture_captcha(page: &Page) -> Result<Option<CaptchaInfo>> {
    let val = page.evaluate_js(CAPTURE_JS).await?;
    let Some(obj) = val.as_object() else {
        return Ok(None);
    };
    let Some(kind_tag) = obj.get("kind").and_then(Value::as_str) else {
        return Ok(None);
    };

    let kind = CaptchaKind::from_tag(kind_tag);
    let page_url = obj
        .get("page_url")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    Ok(Some(CaptchaInfo {
        kind,
        sitekey: obj
            .get("sitekey")
            .and_then(Value::as_str)
            .map(str::to_owned),
        widget_selector: obj
            .get("widget_selector")
            .and_then(Value::as_str)
            .map(str::to_owned),
        widget_rect: obj
            .get("widget_rect")
            .and_then(Value::as_object)
            .and_then(|r| {
                Some(WidgetRect {
                    x: r.get("x")?.as_f64()?,
                    y: r.get("y")?.as_f64()?,
                    width: r.get("width")?.as_f64()?,
                    height: r.get("height")?.as_f64()?,
                })
            }),
        widget_rendered: obj
            .get("widget_rendered")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        response_field_selector: obj
            .get("response_field_selector")
            .and_then(Value::as_str)
            .map(str::to_owned),
        existing_token: obj
            .get("existing_token")
            .and_then(Value::as_str)
            .filter(|s| !s.is_empty())
            .map(str::to_owned),
        action: obj.get("action").and_then(Value::as_str).map(str::to_owned),
        cdata: obj.get("cdata").and_then(Value::as_str).map(str::to_owned),
        page_url,
    }))
}

/// Backward-compat wrapper. Returns only the kind tag.
pub async fn detect_captcha(page: &Page) -> Result<Option<CaptchaKind>> {
    Ok(capture_captcha(page).await?.map(|info| info.kind))
}

/// Write a solved token into the page's hidden response field.
///
/// This is the "back half" of the external-solver flow: you captured
/// the sitekey via [`capture_captcha`], sent it to 2Captcha/CapSolver,
/// got a token back, and now need to hand it to the page. We write
/// the token into the standard response field for the kind, fire
/// `input` + `change` events so React-controlled inputs update their
/// state, and — for Turnstile — invoke any registered `cf-callback`
/// callback so the host's JS knows a token is available.
///
/// Does not submit the form; that's the caller's next step.
pub async fn inject_captcha_token(page: &Page, kind: CaptchaKind, token: &str) -> Result<()> {
    let kind_tag = kind.as_str();
    // Escape only `\` and `"` — that's sufficient for a JSON string literal
    // being pasted into a JS double-quoted string.
    let token_lit = token.replace('\\', "\\\\").replace('"', "\\\"");
    let kind_lit = kind_tag.replace('\\', "\\\\").replace('"', "\\\"");
    let js = format!(
        r#"
        (function(kind, token) {{
            const selectors = {{
                turnstile: ['input[name="cf-turnstile-response"]', 'textarea[name="cf-turnstile-response"]'],
                recaptcha: ['textarea[name="g-recaptcha-response"]', '#g-recaptcha-response'],
                hcaptcha:  ['textarea[name="h-captcha-response"]', '[name="h-captcha-response"]'],
            }};
            const list = selectors[kind] || [];
            let written = 0;
            for (const sel of list) {{
                const nodes = document.querySelectorAll(sel);
                for (const el of nodes) {{
                    const proto = el.tagName === 'TEXTAREA'
                        ? window.HTMLTextAreaElement.prototype
                        : window.HTMLInputElement.prototype;
                    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
                    setter.call(el, token);
                    el.dispatchEvent(new Event('input',  {{ bubbles: true }}));
                    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    written += 1;
                }}
            }}
            // Turnstile: invoke the widget's success callback if the page
            // registered one via data-callback="fnName".
            if (kind === 'turnstile') {{
                const cb_el = document.querySelector('[data-callback]');
                const fn_name = cb_el ? cb_el.getAttribute('data-callback') : null;
                if (fn_name && typeof window[fn_name] === 'function') {{
                    try {{ window[fn_name](token); }} catch (e) {{}}
                }}
            }}
            return written;
        }})("{kind_lit}", "{token_lit}")
        "#
    );
    page.evaluate_js(&js).await?;
    Ok(())
}

/// One-shot JS capture: classifies the wall and pulls every useful
/// piece into a single object. Kept as a long string literal so it
/// ships verbatim at compile time.
const CAPTURE_JS: &str = r#"
(function() {
    try {
        const page_url = (typeof location !== 'undefined') ? location.href : '';

        function rectOf(el) {
            if (!el || !el.getBoundingClientRect) return null;
            const r = el.getBoundingClientRect();
            if (r.width < 1 && r.height < 1) return null;
            return { x: r.left, y: r.top, width: r.width, height: r.height };
        }

        function readHidden(sel) {
            const el = document.querySelector(sel);
            if (!el) return '';
            return el.value || el.textContent || '';
        }

        // ── Turnstile ───────────────────────────────────────────
        // Rendered widget OR a data-sitekey container OR just the
        // runtime loaded (Ahrefs-style lazy mount).
        const ts_iframe = document.querySelector('iframe[src*="challenges.cloudflare.com/turnstile"]');
        const ts_container = document.querySelector('.cf-turnstile, [data-sitekey][class*="turnstile" i]');
        const ts_runtime_loaded = !!document.querySelector('script[src*="challenges.cloudflare.com/turnstile"]')
                               || (typeof window.turnstile === 'object');
        if (ts_iframe || ts_container || ts_runtime_loaded) {
            const rect_src = ts_iframe || ts_container;
            const sk_node = document.querySelector('.cf-turnstile[data-sitekey], [data-sitekey]');
            return {
                kind: 'turnstile',
                sitekey: sk_node ? sk_node.getAttribute('data-sitekey') : null,
                widget_selector: ts_container ? '.cf-turnstile' : (ts_iframe ? 'iframe[src*="challenges.cloudflare.com/turnstile"]' : null),
                widget_rect: rectOf(rect_src),
                widget_rendered: !!(ts_iframe || ts_container),
                response_field_selector: 'input[name="cf-turnstile-response"]',
                existing_token: readHidden('input[name="cf-turnstile-response"], textarea[name="cf-turnstile-response"]'),
                action: sk_node ? sk_node.getAttribute('data-action') : null,
                cdata: sk_node ? sk_node.getAttribute('data-cdata') : null,
                page_url,
            };
        }

        // ── reCAPTCHA v2/v3 ─────────────────────────────────────
        const rc_iframe = document.querySelector('iframe[src*="google.com/recaptcha"], iframe[src*="recaptcha/api2"]');
        const rc_container = document.querySelector('.g-recaptcha, #g-recaptcha');
        if (rc_iframe || rc_container) {
            const rect_src = rc_iframe || rc_container;
            const sk_node = document.querySelector('.g-recaptcha[data-sitekey], [data-sitekey]');
            // reCAPTCHA iframe src carries `k=<sitekey>` too
            let sitekey = sk_node ? sk_node.getAttribute('data-sitekey') : null;
            if (!sitekey && rc_iframe) {
                const m = rc_iframe.src.match(/[?&]k=([^&]+)/);
                if (m) sitekey = decodeURIComponent(m[1]);
            }
            return {
                kind: 'recaptcha',
                sitekey,
                widget_selector: rc_container ? '.g-recaptcha' : 'iframe[src*="recaptcha"]',
                widget_rect: rectOf(rect_src),
                widget_rendered: true,
                response_field_selector: 'textarea[name="g-recaptcha-response"]',
                existing_token: readHidden('textarea[name="g-recaptcha-response"], #g-recaptcha-response'),
                action: null,
                cdata: null,
                page_url,
            };
        }

        // ── hCaptcha ────────────────────────────────────────────
        const hc_iframe = document.querySelector('iframe[src*="hcaptcha.com"]');
        const hc_container = document.querySelector('.h-captcha, [data-hcaptcha-widget-id]');
        if (hc_iframe || hc_container) {
            const rect_src = hc_iframe || hc_container;
            const sk_node = document.querySelector('[data-sitekey]');
            let sitekey = sk_node ? sk_node.getAttribute('data-sitekey') : null;
            if (!sitekey && hc_iframe) {
                const m = hc_iframe.src.match(/[?&]sitekey=([^&]+)/);
                if (m) sitekey = decodeURIComponent(m[1]);
            }
            return {
                kind: 'hcaptcha',
                sitekey,
                widget_selector: hc_container ? '.h-captcha' : 'iframe[src*="hcaptcha"]',
                widget_rect: rectOf(rect_src),
                widget_rendered: true,
                response_field_selector: 'textarea[name="h-captcha-response"]',
                existing_token: readHidden('textarea[name="h-captcha-response"], [name="h-captcha-response"]'),
                action: null,
                cdata: null,
                page_url,
            };
        }

        // ── Cloudflare interstitial (managed challenge) ─────────
        const cf_el = document.querySelector('#cf-challenge-running, #challenge-running, #cf-chl-widget, .cf-browser-verification');
        const title_l = (document.title || '').toLowerCase();
        if (cf_el || title_l.includes('just a moment') || title_l.includes('attention required')) {
            return {
                kind: 'cloudflare_challenge',
                sitekey: null,
                widget_selector: cf_el ? '#cf-challenge-running, #challenge-running, #cf-chl-widget' : null,
                widget_rect: rectOf(cf_el),
                widget_rendered: !!cf_el,
                response_field_selector: null,
                existing_token: '',
                action: null,
                cdata: null,
                page_url,
            };
        }

        // ── DataDome ────────────────────────────────────────────
        const dd_el = document.querySelector('#datadome-captcha, [id^="dd_"]');
        if (dd_el) {
            return {
                kind: 'datadome',
                sitekey: null,
                widget_selector: '#datadome-captcha',
                widget_rect: rectOf(dd_el),
                widget_rendered: true,
                response_field_selector: null,
                existing_token: '',
                action: null,
                cdata: null,
                page_url,
            };
        }

        // ── PerimeterX ──────────────────────────────────────────
        const px_el = document.querySelector('#px-captcha');
        if (px_el) {
            return {
                kind: 'unknown:perimeterx',
                sitekey: null,
                widget_selector: '#px-captcha',
                widget_rect: rectOf(px_el),
                widget_rendered: true,
                response_field_selector: null,
                existing_token: '',
                action: null,
                cdata: null,
                page_url,
            };
        }

        return null;
    } catch (e) { return null; }
})()
"#;
