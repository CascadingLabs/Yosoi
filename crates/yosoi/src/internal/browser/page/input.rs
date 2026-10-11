use super::ObservationWatch;
use super::Page;
use crate::internal::browser::DocumentEpoch;
use crate::internal::browser::DocumentScope;
use crate::internal::browser::environment::EnvironmentObservation;
use crate::internal::browser::error::Result;
use crate::internal::browser::error::VoidCrawlError;
use crate::internal::browser::input::HumanizeOptions;
use crate::internal::browser::input::Rng;
use crate::internal::browser::input::humanized_path;
use crate::internal::browser::vendor::chromiumoxide::Element;
use crate::internal::browser::vendor::chromiumoxide::cdp::browser_protocol::input::DispatchKeyEventParams;
use crate::internal::browser::vendor::chromiumoxide::cdp::browser_protocol::input::DispatchKeyEventType;
use crate::internal::browser::vendor::chromiumoxide::cdp::browser_protocol::input::DispatchMouseEventParams;
use crate::internal::browser::vendor::chromiumoxide::cdp::browser_protocol::input::DispatchMouseEventType;
use crate::internal::browser::vendor::chromiumoxide::cdp::browser_protocol::input::MouseButton;
use crate::internal::types as internal_types;
use serde_json::Value;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use tokio::time;

/// Wall-clock-derived seed for live humanized pointer paths. Tests seed the
/// generator explicitly for determinism; production just wants variety.
pub(super) fn runtime_seed() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0x1234_5678_9ABC_DEF0, |d| {
            d.as_secs() ^ u64::from(d.subsec_nanos()).rotate_left(32)
        })
}

fn same_input_scope(expected: &DocumentScope, current: &DocumentScope) -> bool {
    expected.frame_id == current.frame_id
        && expected.epoch == current.epoch
        && expected.frame == current.frame
}

impl Page {
    async fn prepare_native_input_surface(&self) -> Result<()> {
        if matches!(
            &self.browser_mode,
            EnvironmentObservation::Known {
                value: internal_types::BrowserMode::Headful
            }
        ) {
            // A new headful tab can put this leased page in the background.
            // Native pointer input needs its visible surface, while activating
            // an already visible headful page can stall the compositor.
            let visibility = self.evaluate_js("document.visibilityState").await?;
            if visibility.as_str() == Some("hidden") {
                let original_scope = self.document_scope().await?;
                self.inner
                    .bring_to_front()
                    .await
                    .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
                let visible = self.evaluate_js("document.visibilityState").await?;
                let current_scope = self.document_scope().await?;
                if current_scope.frame_id != original_scope.frame_id
                    || current_scope.epoch != original_scope.epoch
                    || current_scope.frame != original_scope.frame
                {
                    return Err(VoidCrawlError::NavigationStateUncertain);
                }
                if visible.as_str() != Some("visible") {
                    return Err(VoidCrawlError::PageError(
                        "headful native input surface did not become visible".into(),
                    ));
                }
            } else if visibility.as_str() != Some("visible") {
                return Err(VoidCrawlError::PageError(
                    "headful native input surface is unavailable".into(),
                ));
            }
        } else {
            self.inner
                .activate()
                .await
                .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
        }
        Ok(())
    }

    async fn ensure_expected_scope(&self, expected: Option<&ObservationWatch>) -> Result<()> {
        let Some(watch) = expected else {
            return Ok(());
        };
        if !watch.belongs_to_page(self) {
            return Err(VoidCrawlError::NavigationStateUncertain);
        }
        let expected = watch.start_scope();
        if !matches!(expected.epoch, DocumentEpoch::Known(_)) {
            return Err(VoidCrawlError::NavigationStateUncertain);
        }
        let current = self
            .document_scope()
            .await
            .map_err(|_| VoidCrawlError::NavigationStateUncertain)?;
        if !matches!(current.epoch, DocumentEpoch::Known(_))
            || !same_input_scope(expected, &current)
        {
            return Err(VoidCrawlError::NavigationStateUncertain);
        }
        Ok(())
    }

    /// Resolve once and retain that element through native input dispatch.
    async fn input_element(&self, selector: &str, unique: bool) -> Result<Element> {
        if !unique {
            return self
                .inner
                .find_element(selector)
                .await
                .map_err(|error| VoidCrawlError::ElementNotFound(error.to_string()));
        }
        let mut elements = self
            .inner
            .find_elements(selector)
            .await
            .map_err(|error| VoidCrawlError::ElementNotFound(error.to_string()))?;
        if elements.len() != 1 {
            return Err(VoidCrawlError::InvalidInput {
                operation: "resolve_input",
                reason: "target_is_not_unique",
            });
        }
        elements.pop().ok_or(VoidCrawlError::InvalidInput {
            operation: "resolve_input",
            reason: "target_is_not_unique",
        })
    }

    pub async fn click_unique_element(&self, selector: &str) -> Result<()> {
        self.click_element_with_scope(selector, None, true).await
    }

    pub async fn type_into_unique_element(&self, selector: &str, text: &str) -> Result<()> {
        self.type_into_with_scope(selector, text, None, true).await
    }

    async fn click_element_with_scope(
        &self,
        selector: &str,
        expected: Option<&ObservationWatch>,
        unique: bool,
    ) -> Result<()> {
        self.ensure_active().await?;
        // Native input and screenshots share the browser's foreground surface.
        let _input_guard = self.capture_lock.lock().await;
        self.ensure_expected_scope(expected).await?;
        let element_result = self.input_element(selector, unique).await;
        self.ensure_expected_scope(expected).await?;
        let element = element_result?;
        let surface_result = self.prepare_native_input_surface().await;
        self.ensure_expected_scope(expected).await?;
        surface_result?;
        element
            .click()
            .await
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
        Ok(())
    }

    async fn type_into_with_scope(
        &self,
        selector: &str,
        text: &str,
        expected: Option<&ObservationWatch>,
        unique: bool,
    ) -> Result<()> {
        self.ensure_active().await?;
        let _input_guard = self.capture_lock.lock().await;
        self.ensure_expected_scope(expected).await?;
        let element_result = self.input_element(selector, unique).await;
        self.ensure_expected_scope(expected).await?;
        let element = element_result?;
        let surface_result = self.prepare_native_input_surface().await;
        self.ensure_expected_scope(expected).await?;
        surface_result?;

        let original_scope = match expected {
            Some(watch) => watch.start_scope().clone(),
            None => self.document_scope().await?,
        };
        let focus_result = element.focus().await;
        let focused = if focus_result.is_ok() {
            element
                .call_js_fn(
                    "function() { return this.isConnected && this.ownerDocument.activeElement === this; }",
                    false,
                )
                .await
                .map(|response| {
                    response.result.value.and_then(|value| value.as_bool()) == Some(true)
                })
        } else {
            Ok(false)
        };
        let current_scope = self
            .document_scope()
            .await
            .map_err(|_| VoidCrawlError::NavigationStateUncertain)?;
        if !same_input_scope(&original_scope, &current_scope) {
            return Err(VoidCrawlError::NavigationStateUncertain);
        }
        focus_result.map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
        if !focused.map_err(|error| VoidCrawlError::PageError(error.to_string()))? {
            return Err(VoidCrawlError::InvalidInput {
                operation: "type_into",
                reason: "target_lost_before_typing",
            });
        }
        element
            .type_str(text)
            .await
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
        Ok(())
    }

    // ── Humanized pointer input (CAS-147) ───────────────────────────────

    /// Move the virtual cursor to `(x, y)` via CDP `Input.dispatchMouseEvent`.
    ///
    /// With `humanize = true` the cursor travels a realistic path from its last
    /// position — non-linear (arc) curvature, a minimum-jerk velocity profile,
    /// small tremor, and a brief dwell — as multiple `MouseMoved` events
    /// ([`crate::internal::browser::input`]). With `humanize = false` it jumps in a single event.
    /// **No page-world JS** is injected. The path length/duration scale with
    /// distance and stay bounded for agent workflows.
    pub async fn move_mouse(&self, x: f64, y: f64, humanize: bool) -> Result<()> {
        self.ensure_active().await?;
        if humanize {
            let start = *self
                .cursor
                .lock()
                .map_err(|_| VoidCrawlError::Other("cursor lock poisoned".into()))?;
            let mut rng = Rng::seed(runtime_seed());
            let path = humanized_path(start, (x, y), &HumanizeOptions::default(), &mut rng);
            for step in path {
                // EVENT_DRIVEN_SLEEP_APPROVED: Humanized pointer pacing
                // intentionally models elapsed physical movement time between
                // CDP input events.
                time::sleep(Duration::from_millis(step.delay_ms)).await;
                self.dispatch_mouse_event(
                    DispatchMouseEventType::MouseMoved,
                    step.x,
                    step.y,
                    None,
                    None,
                    None,
                    None,
                    None,
                )
                .await?;
            }
        } else {
            self.dispatch_mouse_event(
                DispatchMouseEventType::MouseMoved,
                x,
                y,
                None,
                None,
                None,
                None,
                None,
            )
            .await?;
        }
        *self
            .cursor
            .lock()
            .map_err(|_| VoidCrawlError::Other("cursor lock poisoned".into()))? = (x, y);
        Ok(())
    }

    /// Click at `(x, y)` with a **trusted** compositor event (press → release).
    /// With `humanize = true`, the cursor first travels a human-like path to
    /// the point (see [`move_mouse`]). The analogue of
    /// `click_visual_coords`.
    ///
    /// [`move_mouse`]: Self::move_mouse
    pub async fn click_xy(&self, x: f64, y: f64, humanize: bool) -> Result<()> {
        self.ensure_active().await?;
        let input_guard = self.capture_lock.lock().await;
        if !matches!(
            &self.browser_mode,
            EnvironmentObservation::Known {
                value: internal_types::BrowserMode::Headful
            }
        ) {
            self.inner
                .bring_to_front()
                .await
                .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
        }
        self.move_mouse(x, y, humanize).await?;
        self.dispatch_mouse_event(
            DispatchMouseEventType::MousePressed,
            x,
            y,
            Some(MouseButton::Left),
            Some(1),
            None,
            None,
            None,
        )
        .await?;
        self.dispatch_mouse_event(
            DispatchMouseEventType::MouseReleased,
            x,
            y,
            Some(MouseButton::Left),
            Some(1),
            None,
            None,
            None,
        )
        .await?;
        drop(input_guard);
        Ok(())
    }

    // ── DOM Queries ─────────────────────────────────────────────────────

    /// Run `document.querySelector(selector)` and return the inner HTML.
    /// Returns `None` if no element matches. Void elements (e.g. `<input>`)
    /// return `Some("")`.
    ///
    /// Uses a JS eval rather than `find_element` so that a missing element
    /// returns `Ok(None)` without any CDP error — real errors (closed browser,
    /// network failure, etc.) still propagate as `Err`.
    pub async fn query_selector(&self, selector: &str) -> Result<Option<String>> {
        // `querySelector` returns null for no match — never throws — so the
        // only error path here is a real CDP failure, not a missing element.
        let js = format!(
            "(function(){{ var el = document.querySelector({selector:?}); \
             return el === null ? null : el.innerHTML; }})()"
        );
        let result = self
            .inner
            .evaluate_expression(js)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;

        // `into_value()` returns Err("No value found") when JS evaluates to
        // null/undefined — that is exactly the "not found" case, not a real
        // error, so map it to Ok(None).
        let val: Value = match result.into_value() {
            Ok(v) => v,
            Err(_) => return Ok(None),
        };

        match val {
            Value::Null => Ok(None),
            Value::String(s) => Ok(Some(s)),
            other => Ok(Some(other.to_string())),
        }
    }

    /// Run `document.querySelectorAll(selector)` and return inner HTML of each.
    /// One entry is returned per matched element; void elements yield `""`.
    pub async fn query_selector_all(&self, selector: &str) -> Result<Vec<String>> {
        // Single JS eval returns all innerHTML at once — avoids N serial CDP
        // round-trips (one per element) that the old find_elements approach
        // needed.
        let js = format!("[...document.querySelectorAll({selector:?})].map(e => e.innerHTML)");
        let val: Value = self
            .inner
            .evaluate_expression(js)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?
            .into_value()
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;

        match val {
            Value::Array(arr) => Ok(arr
                .into_iter()
                .map(|v| match v {
                    Value::String(s) => s,
                    other => other.to_string(),
                })
                .collect()),
            _ => Ok(Vec::new()),
        }
    }

    // ── Interaction ─────────────────────────────────────────────────────

    /// Click on the first element matching `selector`.
    pub async fn click_element(&self, selector: &str) -> Result<()> {
        self.click_element_with_scope(selector, None, false).await
    }

    /// Click an element only while the supplied page watch remains active and
    /// its original document scope still matches.
    pub async fn click_element_in_scope(
        &self,
        selector: &str,
        watch: &ObservationWatch,
    ) -> Result<()> {
        self.click_element_with_scope(selector, Some(watch), true)
            .await
    }

    /// Type text into the first element matching `selector`.
    ///
    /// Focuses the element first so that key events are directed to it.
    pub async fn type_into(&self, selector: &str, text: &str) -> Result<()> {
        self.type_into_with_scope(selector, text, None, false).await
    }

    /// Type into an element only while the supplied page watch remains active
    /// and its original document scope still matches.
    pub async fn type_into_in_scope(
        &self,
        selector: &str,
        text: &str,
        watch: &ObservationWatch,
    ) -> Result<()> {
        self.type_into_with_scope(selector, text, Some(watch), true)
            .await
    }

    // ── CDP Input ───────────────────────────────────────────────────────

    /// Dispatch a mouse event via the CDP `Input.dispatchMouseEvent` command.
    ///
    /// This sends a **browser-level** input event — as opposed to a JS
    /// `dispatchEvent(new MouseEvent(...))` — so it is processed by the
    /// compositor and behaves like a real user action (including triggering
    /// hover states, native drag, etc.).
    #[allow(clippy::too_many_arguments)]
    pub async fn dispatch_mouse_event(
        &self,
        event_type: DispatchMouseEventType,
        x: f64,
        y: f64,
        button: Option<MouseButton>,
        click_count: Option<i64>,
        delta_x: Option<f64>,
        delta_y: Option<f64>,
        modifiers: Option<i64>,
    ) -> Result<()> {
        self.ensure_active().await?;
        let mut builder = DispatchMouseEventParams::builder()
            .r#type(event_type)
            .x(x)
            .y(y);

        if let Some(b) = button {
            builder = builder.button(b);
        }
        if let Some(c) = click_count {
            builder = builder.click_count(c);
        }
        if let Some(dx) = delta_x {
            builder = builder.delta_x(dx);
        }
        if let Some(dy) = delta_y {
            builder = builder.delta_y(dy);
        }
        if let Some(m) = modifiers {
            builder = builder.modifiers(m);
        }

        let params = builder.build().map_err(VoidCrawlError::PageError)?;
        self.inner
            .execute(params)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(())
    }

    /// Dispatch a key event via the CDP `Input.dispatchKeyEvent` command.
    ///
    /// Sends a browser-level keyboard event. Use `KeyDown` + `KeyUp` for
    /// modifier keys or special keys, and `Char` for text input.
    pub async fn dispatch_key_event(
        &self,
        event_type: DispatchKeyEventType,
        key: Option<&str>,
        code: Option<&str>,
        text: Option<&str>,
        modifiers: Option<i64>,
    ) -> Result<()> {
        self.ensure_active().await?;
        let mut builder = DispatchKeyEventParams::builder().r#type(event_type);

        if let Some(k) = key {
            builder = builder.key(k);
        }
        if let Some(c) = code {
            builder = builder.code(c);
        }
        if let Some(t) = text {
            builder = builder.text(t);
        }
        if let Some(m) = modifiers {
            builder = builder.modifiers(m);
        }

        let params = builder.build().map_err(VoidCrawlError::PageError)?;
        self.inner
            .execute(params)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(())
    }
}

#[cfg(test)]
mod unique_input_tests {
    use crate::internal::browser::{BrowserSession, VoidCrawlError};
    use std::env as std_env;
    use std::error::Error;

    #[tokio::test]
    async fn unique_input_retains_original_node_and_rejects_ambiguous_matches()
    -> Result<(), Box<dyn Error + Send + Sync>> {
        if std_env::var("YOSOI_BROWSER_TESTS").as_deref() != Ok("1") {
            eprintln!("SKIPPED: set YOSOI_BROWSER_TESTS=1 for unique native input regression");
            return Ok(());
        }
        let browser = BrowserSession::builder().headless().launch().await?;
        let page = browser.new_page("about:blank").await?;
        page.evaluate_js("document.body.innerHTML = '<button class=target onclick=window.originalClicked=true>original</button>'; window.originalClicked = false; window.replacementClicked = false").await?;
        let original = page.input_element(".target", true).await?;
        // Insert a new first match after resolution. Dispatch must use the
        // retained original node rather than query the selector a second time.
        page.evaluate_js("document.body.insertAdjacentHTML('afterbegin', '<button class=target onclick=window.replacementClicked=true>replacement</button>')").await?;
        original.click().await?;
        let state = page
            .evaluate_js("[window.originalClicked, window.replacementClicked]")
            .await?;
        if state != serde_json::json!([true, false]) {
            return Err("native click changed target after resolution".into());
        }
        if !matches!(
            page.click_unique_element(".target").await,
            Err(VoidCrawlError::InvalidInput {
                reason: "target_is_not_unique",
                ..
            })
        ) {
            return Err("ambiguous click target was accepted".into());
        }
        if !matches!(
            page.type_into_unique_element(".target", "must-not-type")
                .await,
            Err(VoidCrawlError::InvalidInput {
                reason: "target_is_not_unique",
                ..
            })
        ) {
            return Err("ambiguous typing target was accepted".into());
        }
        page.evaluate_js(
            "document.querySelectorAll('.target').forEach(element => element.remove())",
        )
        .await?;
        if original.click().await.is_ok() {
            return Err("detached original target was accepted".into());
        }
        page.close().await?;
        browser.close().await?;
        Ok(())
    }
}
