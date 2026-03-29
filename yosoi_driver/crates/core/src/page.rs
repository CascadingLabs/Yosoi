//! High-level wrapper around a `chromiumoxide::Page`.

use std::collections::HashMap;

use chromiumoxide::cdp::browser_protocol::emulation::{
    SetDeviceMetricsOverrideParams, SetUserAgentOverrideParams,
};
use chromiumoxide::cdp::browser_protocol::network::{Headers, SetExtraHttpHeadersParams};
use chromiumoxide::cdp::browser_protocol::page::{
    AddScriptToEvaluateOnNewDocumentParams, CaptureScreenshotFormat, PrintToPdfParams,
    SetBypassCspParams,
};
use chromiumoxide::page::ScreenshotParams;
use chromiumoxide::Page as CdpPage;

use crate::error::{Result, YosoiError};
use crate::stealth::StealthConfig;

/// Thin wrapper over `chromiumoxide::Page` exposing a clean async API.
#[derive(Debug)]
pub struct Page {
    inner: CdpPage,
}

impl Page {
    /// Wrap an existing CDP page.
    pub(crate) fn new(inner: CdpPage) -> Self {
        Self { inner }
    }

    /// Apply stealth settings to this page.
    pub(crate) async fn apply_stealth(&self, cfg: &StealthConfig) -> Result<()> {
        // 1. Built-in stealth (patches navigator.webdriver etc.)
        if cfg.use_builtin_stealth {
            if let Some(ua) = &cfg.user_agent {
                self.inner
                    .enable_stealth_mode_with_agent(ua)
                    .await
                    .map_err(|e| YosoiError::PageError(e.to_string()))?;
            } else {
                self.inner
                    .enable_stealth_mode()
                    .await
                    .map_err(|e| YosoiError::PageError(e.to_string()))?;
            }
        }

        // 2. User-agent override (only if stealth mode didn't already handle it)
        if !cfg.use_builtin_stealth {
            if let Some(ua) = &cfg.user_agent {
                let params = SetUserAgentOverrideParams::builder()
                    .user_agent(ua.clone())
                    .accept_language(&cfg.locale)
                    .platform("Win32")
                    .build()
                    .map_err(YosoiError::PageError)?;
                self.inner
                    .execute(params)
                    .await
                    .map_err(|e| YosoiError::PageError(e.to_string()))?;
            }
        }

        // 3. Viewport / device metrics
        let metrics = SetDeviceMetricsOverrideParams::new(
            cfg.viewport_width as i64,
            cfg.viewport_height as i64,
            1.0,
            false,
        );
        self.inner
            .execute(metrics)
            .await
            .map_err(|e| YosoiError::PageError(e.to_string()))?;

        // 4. Bypass CSP so our injected JS can run
        if cfg.bypass_csp {
            let csp = SetBypassCspParams::new(true);
            self.inner
                .execute(csp)
                .await
                .map_err(|e| YosoiError::PageError(e.to_string()))?;
        }

        // 5. Inject custom JS before every navigation
        if let Some(js) = &cfg.inject_js {
            let params = AddScriptToEvaluateOnNewDocumentParams::new(js.clone());
            self.inner
                .execute(params)
                .await
                .map_err(|e| YosoiError::PageError(e.to_string()))?;
        }

        Ok(())
    }

    // ── Navigation ──────────────────────────────────────────────────────

    /// Navigate to `url` and wait for the load event.
    pub async fn navigate(&self, url: &str) -> Result<()> {
        self.inner
            .goto(url)
            .await
            .map_err(|e| YosoiError::NavigationFailed(e.to_string()))?;
        Ok(())
    }

    /// Wait for the in-flight navigation to finish.
    pub async fn wait_for_navigation(&self) -> Result<()> {
        self.inner
            .wait_for_navigation()
            .await
            .map_err(|e| YosoiError::NavigationFailed(e.to_string()))?;
        Ok(())
    }

    // ── Content ─────────────────────────────────────────────────────────

    /// Return the full HTML of the page (outer HTML of `<html>`).
    pub async fn content(&self) -> Result<String> {
        self.inner
            .content()
            .await
            .map_err(|e| YosoiError::PageError(e.to_string()))
    }

    /// Return the page title.
    pub async fn title(&self) -> Result<Option<String>> {
        self.inner
            .get_title()
            .await
            .map_err(|e| YosoiError::PageError(e.to_string()))
    }

    /// Return the current URL.
    pub async fn url(&self) -> Result<Option<String>> {
        self.inner
            .url()
            .await
            .map_err(|e| YosoiError::PageError(e.to_string()))
    }

    // ── JavaScript ──────────────────────────────────────────────────────

    /// Evaluate a JS expression and return the result as a JSON value.
    pub async fn evaluate_js(&self, expression: &str) -> Result<serde_json::Value> {
        let result = self
            .inner
            .evaluate(expression)
            .await
            .map_err(|e| YosoiError::JsEvalError(e.to_string()))?;
        result
            .into_value()
            .map_err(|e| YosoiError::JsEvalError(e.to_string()))
    }

    // ── Screenshots & PDF ───────────────────────────────────────────────

    /// Capture a full-page PNG screenshot, returned as raw bytes.
    pub async fn screenshot_png(&self) -> Result<Vec<u8>> {
        let params = ScreenshotParams::builder()
            .format(CaptureScreenshotFormat::Png)
            .full_page(true)
            .build();
        self.inner
            .screenshot(params)
            .await
            .map_err(|e| YosoiError::ScreenshotError(e.to_string()))
    }

    /// Generate a PDF of the page, returned as raw bytes.
    pub async fn pdf_bytes(&self) -> Result<Vec<u8>> {
        let params = PrintToPdfParams::default();
        self.inner
            .pdf(params)
            .await
            .map_err(|e| YosoiError::PdfError(e.to_string()))
    }

    // ── DOM Queries ─────────────────────────────────────────────────────

    /// Run `document.querySelector(selector)` and return the inner HTML.
    /// Returns `None` if no element matches. Void elements (e.g. `<input>`)
    /// return `Some("")`.
    pub async fn query_selector(&self, selector: &str) -> Result<Option<String>> {
        match self.inner.find_element(selector).await {
            Ok(el) => {
                let html = el
                    .inner_html()
                    .await
                    .map_err(|e| YosoiError::PageError(e.to_string()))?;
                Ok(Some(html.unwrap_or_default()))
            }
            Err(_) => Ok(None),
        }
    }

    /// Run `document.querySelectorAll(selector)` and return inner HTML of each.
    /// One entry is returned per matched element; void elements yield `""`.
    pub async fn query_selector_all(&self, selector: &str) -> Result<Vec<String>> {
        let elements = self
            .inner
            .find_elements(selector)
            .await
            .map_err(|e| YosoiError::PageError(e.to_string()))?;

        let mut results = Vec::with_capacity(elements.len());
        for el in elements {
            match el.inner_html().await {
                Ok(html) => results.push(html.unwrap_or_default()),
                Err(_) => results.push(String::new()),
            }
        }
        Ok(results)
    }

    // ── Interaction ─────────────────────────────────────────────────────

    /// Click on the first element matching `selector`.
    pub async fn click_element(&self, selector: &str) -> Result<()> {
        let el = self
            .inner
            .find_element(selector)
            .await
            .map_err(|e| YosoiError::ElementNotFound(e.to_string()))?;
        el.click()
            .await
            .map_err(|e| YosoiError::PageError(e.to_string()))?;
        Ok(())
    }

    /// Type text into the first element matching `selector`.
    ///
    /// Focuses the element first so that key events are directed to it.
    pub async fn type_into(&self, selector: &str, text: &str) -> Result<()> {
        let el = self
            .inner
            .find_element(selector)
            .await
            .map_err(|e| YosoiError::ElementNotFound(e.to_string()))?;
        el.focus()
            .await
            .map_err(|e| YosoiError::PageError(e.to_string()))?;
        el.type_str(text)
            .await
            .map_err(|e| YosoiError::PageError(e.to_string()))?;
        Ok(())
    }

    // ── Headers & Network ───────────────────────────────────────────────

    /// Set extra HTTP headers for all subsequent requests from this page.
    pub async fn set_headers(&self, headers: HashMap<String, String>) -> Result<()> {
        let json_val = serde_json::to_value(&headers)
            .map_err(|e| YosoiError::PageError(e.to_string()))?;
        let params = SetExtraHttpHeadersParams::new(Headers::new(json_val));
        self.inner
            .execute(params)
            .await
            .map_err(|e| YosoiError::PageError(e.to_string()))?;
        Ok(())
    }

    /// Close this page / tab.
    pub async fn close(self) -> Result<()> {
        self.inner
            .close()
            .await
            .map_err(|e| YosoiError::PageError(e.to_string()))?;
        Ok(())
    }

    /// Access the underlying chromiumoxide Page for advanced usage.
    pub fn inner(&self) -> &CdpPage {
        &self.inner
    }
}
