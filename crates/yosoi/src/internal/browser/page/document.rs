use crate::internal::types as yosoi_types;

use super::Page;
use crate::internal::browser::document_snapshot::RenderedDomSnapshot;
use crate::internal::browser::document_snapshot::rendered_dom;
use crate::internal::browser::error::Result;
use crate::internal::browser::error::VoidCrawlError;
use serde_json::Value;

/// Classify the in-page selector-wait status without inspecting provider error
/// text. A rejected promise/CDP failure is handled separately as `JsEvalError`.
pub(super) fn selector_wait_status(
    status: Option<&Value>,
    selector: &str,
    timeout_ms: u64,
) -> Result<()> {
    match status.and_then(Value::as_bool) {
        Some(true) => Ok(()),
        Some(false) => Err(VoidCrawlError::Timeout(format!(
            "selector {selector:?} did not appear within {timeout_ms}ms"
        ))),
        None => Err(VoidCrawlError::JsEvalError(
            "wait_for_selector returned a non-boolean status".into(),
        )),
    }
}

const DOCUMENT_SNAPSHOT_JS: &str = r#"
(() => {
  const MAX = {
    headings: 80,
    textBlocks: 240,
    links: 160,
    controls: 160,
    forms: 60,
    formControls: 30,
    textChars: 700,
    smallChars: 220
  };
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const clip = (value, limit) => {
    const text = clean(value);
    return text.length > limit ? text.slice(0, Math.max(0, limit - 3)) + '...' : text;
  };
  const visible = (el) => {
    if (!el || !el.isConnected) return false;
    const style = window.getComputedStyle(el);
    if (!style || style.display === 'none' || style.visibility === 'hidden') return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };
  const attr = (el, name) => {
    const value = el.getAttribute(name);
    return value == null || value === '' ? null : clip(value, MAX.smallChars);
  };
  const labelText = (el) => {
    const id = el.id ? CSS.escape(el.id) : null;
    const label = id ? document.querySelector(`label[for="${id}"]`) : null;
    return clip(
      el.getAttribute('aria-label')
        || el.getAttribute('title')
        || el.getAttribute('placeholder')
        || (label && label.textContent)
        || el.value
        || el.textContent
        || el.name
        || '',
      MAX.smallChars
    );
  };
  const control = (el) => ({
    tag: el.tagName.toLowerCase(),
    type: attr(el, 'type'),
    role: attr(el, 'role'),
    name: labelText(el) || null,
    placeholder: attr(el, 'placeholder'),
    disabled: Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true')
  });
  const all = (selector) => Array.from(document.querySelectorAll(selector)).filter(visible);
  const unique = (items) => Array.from(new Set(items));

  const headingNodes = all('h1,h2,h3,h4,h5,h6');
  const headings = headingNodes.slice(0, MAX.headings).map((el) => ({
    level: Number(el.tagName.slice(1)),
    text: clip(el.textContent, MAX.smallChars)
  })).filter((h) => h.text);

  const textNodes = unique([
    ...all('main p, main li, article p, article li, section p, blockquote, body > p, td, th'),
    ...all('[role="main"] p, [role="article"] p')
  ]).filter((el) => clean(el.textContent).length >= 20);
  const text_blocks = textNodes.slice(0, MAX.textBlocks).map((el) => ({
    tag: el.tagName.toLowerCase(),
    text: clip(el.textContent, MAX.textChars)
  })).filter((b) => b.text);

  const linkNodes = all('a[href]');
  const links = linkNodes.slice(0, MAX.links).map((el) => ({
    text: clip(el.textContent || el.getAttribute('aria-label') || el.href, MAX.smallChars),
    href: clip(el.href, MAX.smallChars)
  })).filter((l) => l.href);

  const controlNodes = all('button,input,select,textarea,[role="button"],[role="link"],[role="textbox"],[role="combobox"],[contenteditable="true"]');
  const controls = controlNodes.slice(0, MAX.controls).map(control);

  const formNodes = all('form');
  const forms = formNodes.slice(0, MAX.forms).map((form) => {
    const fields = Array.from(form.querySelectorAll('button,input,select,textarea,[role="button"],[role="textbox"],[role="combobox"]'))
      .filter(visible)
      .slice(0, MAX.formControls)
      .map(control);
    return {
      action: attr(form, 'action') || (form.action ? clip(form.action, MAX.smallChars) : null),
      method: clip(form.method || 'get', 20).toLowerCase(),
      controls: fields
    };
  });

  return {
    url: location.href,
    title: document.title || null,
    headings,
    text_blocks,
    links,
    controls,
    forms,
    total: {
      headings: headingNodes.length,
      text_blocks: textNodes.length,
      links: linkNodes.length,
      controls: controlNodes.length,
      forms: formNodes.length
    }
  };
})()
"#;

impl Page {
    // ── Content ─────────────────────────────────────────────────────────

    /// Return the full HTML of the page (outer HTML of `<html>`).
    pub async fn content(&self) -> Result<String> {
        self.inner
            .content()
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))
    }

    /// Capture the current rendered DOM as bounded UTF-8 bytes.
    ///
    /// This serializes the live DOM after page execution. It is deliberately
    /// distinct from [`MainDocumentSource`](crate::internal::browser::MainDocumentSource), which
    /// contains the browser-observed response representation.
    pub async fn rendered_dom_snapshot(&self, max_bytes: usize) -> Result<RenderedDomSnapshot> {
        if max_bytes == 0 {
            return Err(VoidCrawlError::InvalidInput {
                operation: "rendered_dom_snapshot",
                reason: "max_bytes must be positive",
            });
        }
        for attempt in 0..2 {
            let before = self.top_level_document_identity().await?;
            let html = self.content().await?;
            let after = self.top_level_document_identity().await?;
            if before.same_document(&after) {
                let scope = self.scope_for_identity(&after, false)?;
                return rendered_dom(html, scope, max_bytes).map_err(|_| {
                    VoidCrawlError::InvalidInput {
                        operation: "rendered_dom_snapshot",
                        reason: "max_bytes does not fit browser byte accounting",
                    }
                });
            }
            // Record the newly observed document even when this attempt raced,
            // so a subsequent snapshot receives the advanced epoch.
            self.observe_document_identity(&after, false)?;
            if attempt == 1 {
                return Err(VoidCrawlError::PageError(
                    "document changed during rendered DOM capture".into(),
                ));
            }
        }
        Err(VoidCrawlError::PageError(
            "document changed during rendered DOM capture".into(),
        ))
    }

    /// Capture the current rendered DOM using a validated browser byte limit.
    pub async fn rendered_dom_snapshot_with_limit(
        &self,
        max_bytes: yosoi_types::ByteLimit,
    ) -> Result<RenderedDomSnapshot> {
        let max_bytes = max_bytes
            .as_usize()
            .map_err(|_| VoidCrawlError::InvalidInput {
                operation: "rendered_dom_snapshot",
                reason: "max_bytes does not fit in usize",
            })?;
        self.rendered_dom_snapshot(max_bytes).await
    }

    /// Return the page title.
    pub async fn title(&self) -> Result<Option<String>> {
        self.inner
            .get_title()
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))
    }

    /// Return the current URL.
    pub async fn url(&self) -> Result<Option<String>> {
        self.inner
            .url()
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))
    }

    /// Collect Yosoi's fixed, read-only document snapshot.
    ///
    /// This deliberately bypasses [`Self::ensure_active`]: the script is
    /// internal, has no caller-provided input, and only reads the current DOM.
    /// Arbitrary JavaScript remains blocked while an interrupt is active.
    pub async fn document_snapshot(&self) -> Result<Value> {
        let result = self
            .inner
            .evaluate(DOCUMENT_SNAPSHOT_JS)
            .await
            .map_err(|e| VoidCrawlError::JsEvalError(e.to_string()))?;
        Ok(result.value().cloned().unwrap_or(Value::Null))
    }

    // ── JavaScript ──────────────────────────────────────────────────────

    /// Evaluate a JS expression and return the result as a JSON value.
    pub async fn evaluate_js(&self, expression: &str) -> Result<Value> {
        self.ensure_active().await?;
        let result = self
            .inner
            .evaluate(expression)
            .await
            .map_err(|e| VoidCrawlError::JsEvalError(e.to_string()))?;
        // `into_value()` fails when the JS expression returns null/undefined
        // (the RemoteObject has no `value` field).  Fall back to Value::Null.
        Ok(result.value().cloned().unwrap_or(Value::Null))
    }
}
