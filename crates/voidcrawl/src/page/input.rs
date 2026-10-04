use super::Page;
use crate::environment::EnvironmentObservation;
use crate::error::Result;
use crate::error::VoidCrawlError;
use crate::input::HumanizeOptions;
use crate::input::Rng;
use crate::input::humanized_path;
use chromiumoxide::cdp::browser_protocol::input::DispatchKeyEventParams;
use chromiumoxide::cdp::browser_protocol::input::DispatchKeyEventType;
use chromiumoxide::cdp::browser_protocol::input::DispatchMouseEventParams;
use chromiumoxide::cdp::browser_protocol::input::DispatchMouseEventType;
use chromiumoxide::cdp::browser_protocol::input::MouseButton;
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

impl Page {
    // ── Humanized pointer input (CAS-147) ───────────────────────────────

    /// Move the virtual cursor to `(x, y)` via CDP `Input.dispatchMouseEvent`.
    ///
    /// With `humanize = true` the cursor travels a realistic path from its last
    /// position — non-linear (arc) curvature, a minimum-jerk velocity profile,
    /// small tremor, and a brief dwell — as multiple `MouseMoved` events
    /// ([`crate::input`]). With `humanize = false` it jumps in a single event.
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
                value: yosoi_types::BrowserMode::Headful
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
        self.ensure_active().await?;
        let el = self
            .inner
            .find_element(selector)
            .await
            .map_err(|e| VoidCrawlError::ElementNotFound(e.to_string()))?;
        el.click()
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(())
    }

    /// Type text into the first element matching `selector`.
    ///
    /// Focuses the element first so that key events are directed to it.
    pub async fn type_into(&self, selector: &str, text: &str) -> Result<()> {
        self.ensure_active().await?;
        let el = self
            .inner
            .find_element(selector)
            .await
            .map_err(|e| VoidCrawlError::ElementNotFound(e.to_string()))?;
        el.focus()
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        el.type_str(text)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(())
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
