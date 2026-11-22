//! Bounded Surface capture and native input on an existing browser page.

use super::Page;
use crate::internal::browser::error::{Result, VoidCrawlError};
use crate::internal::browser::vendor::chromiumoxide::Page as NativePage;
use crate::internal::browser::vendor::chromiumoxide::cdp::browser_protocol::input::{
    DispatchKeyEventParams, DispatchKeyEventType, DispatchMouseEventType, InsertTextParams,
    MouseButton,
};
use crate::internal::browser::vendor::chromiumoxide::cdp::js_protocol::runtime::{
    CallFunctionOnParams, EvaluateParams, ReleaseObjectParams, RemoteObjectId,
};
use crate::internal::browser::{DocumentEpoch, DocumentScope};
use serde_json::{Value, json};
use std::{ops::Deref, time::Duration};
use tokio::{runtime::Handle, time::timeout};

const SURFACE_EVIDENCE: &str = include_str!("../../../surface/browser/extract.js");
const MAX_SCRIPT_INPUT_BYTES: usize = 65_536;
const SURFACE_POINT_TOLERANCE: f64 = f64::EPSILON;

struct SurfaceObject {
    id: RemoteObjectId,
    page: NativePage,
}

impl Deref for SurfaceObject {
    type Target = RemoteObjectId;
    fn deref(&self) -> &Self::Target {
        &self.id
    }
}

impl Drop for SurfaceObject {
    fn drop(&mut self) {
        let page = self.page.clone();
        let id = self.id.clone();
        if let Ok(runtime) = Handle::try_current() {
            runtime.spawn(async move {
                let _ = timeout(
                    Duration::from_secs(1),
                    page.execute(ReleaseObjectParams::new(id)),
                )
                .await;
            });
        }
    }
}

/// A capture-local browser action addressed by the node ID issued by Surface evidence.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SurfaceInput {
    /// Click the current capture's node using native mouse events.
    Click { node: u64 },
    /// Replace an editable input or textarea using native keyboard and insert-text events.
    Fill { node: u64, text: String },
    /// Send one supported key to the captured, focused node.
    Key { node: u64, key: String },
    /// Send a bounded native wheel event over the current viewport.
    Scroll { delta_x: i32, delta_y: i32 },
}

impl Page {
    /// Runs one fixed operation from the bundled Surface evidence adapter.
    ///
    /// The operation name is allowlisted and input is encoded as JSON; caller
    /// input is never interpreted as JavaScript. Every bundled operation here
    /// is synchronous, including the condition predicate.
    pub(crate) async fn surface_script(&self, operation: &str, input: &Value) -> Result<Value> {
        let script_operation = match operation {
            "capture" | "eligibility" | "binding" | "location" | "article" | "value"
            | "target_region" | "condition" => operation,
            _ => {
                return Err(surface_input_error(
                    "surface_script",
                    "operation is not supported by the Surface adapter",
                ));
            }
        };
        let input_json = serde_json::to_string(input)
            .map_err(|_| surface_input_error("surface_script", "input is not JSON serializable"))?;
        if input_json.len() > MAX_SCRIPT_INPUT_BYTES {
            return Err(surface_input_error(
                "surface_script",
                "input exceeds the Surface script limit",
            ));
        }
        if operation == "value"
            && (input.get("id").and_then(Value::as_u64).is_none()
                || input.get("expected").is_none())
        {
            return Err(surface_input_error(
                "surface_script",
                "value requires a node ID and expected value",
            ));
        }
        if operation == "target_region"
            && (input.get("id").and_then(Value::as_u64).is_none()
                || input
                    .get("expected_epoch")
                    .and_then(Value::as_u64)
                    .is_none())
        {
            return Err(surface_input_error(
                "surface_script",
                "target_region requires a node ID and expected document epoch",
            ));
        }

        self.ensure_active().await?;
        let before = self.document_scope().await?;
        let operation_json = serde_json::to_string(script_operation)
            .map_err(|_| surface_input_error("surface_script", "invalid operation"))?;
        let expression = format!(
            "(function() {{{SURFACE_EVIDENCE}}}).apply(null, [{operation_json}, {input_json}])"
        );
        let params = EvaluateParams::builder()
            .expression(expression)
            .await_promise(false)
            .return_by_value(true)
            .build()
            .map_err(VoidCrawlError::PageError)?;
        let evaluated = self
            .inner
            .evaluate(params)
            .await
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
        let mut value = evaluated.value().cloned().unwrap_or(Value::Null);
        self.ensure_surface_scope(&before).await?;
        if let (DocumentEpoch::Known(epoch), Some(fields)) = (before.epoch, value.as_object_mut()) {
            fields.insert("native_document_epoch".into(), epoch.into());
        }
        Ok(value)
    }

    /// Returns the raw browser AX tree while guarding the capture's frame and document scope.
    pub(crate) async fn surface_ax(&self, depth: Option<i64>) -> Result<Value> {
        if depth.is_some_and(|depth| depth < 0) {
            return Err(surface_input_error(
                "surface_ax",
                "depth must not be negative",
            ));
        }
        self.ensure_active().await?;
        let before = self.document_scope().await?;
        let nodes = self.get_full_ax_tree(depth).await?;
        self.ensure_surface_scope(&before).await?;
        let epoch = match before.epoch {
            DocumentEpoch::Known(epoch) => epoch,
            DocumentEpoch::UnavailableForAttachedPage => {
                return Err(VoidCrawlError::NavigationStateUncertain);
            }
        };
        Ok(json!({"nodes":nodes,"native_document_epoch":epoch}))
    }

    /// Dispatches input to the exact node retained by the latest bundled capture.
    /// CSS/XPath resolution and page-world click, typing, key, and scroll effects
    /// are intentionally not used here.
    pub(crate) async fn surface_input(&self, input: &SurfaceInput) -> Result<()> {
        self.ensure_active().await?;
        let _input_guard = self.capture_lock.lock().await;
        self.prepare_native_input_surface().await?;
        match input {
            SurfaceInput::Scroll { delta_x, delta_y } => {
                self.surface_scroll(*delta_x, *delta_y).await
            }
            _ => self.surface_node_input(input).await,
        }
    }

    async fn surface_scroll(&self, delta_x: i32, delta_y: i32) -> Result<()> {
        if delta_x.unsigned_abs() > 10_000 || delta_y.unsigned_abs() > 10_000 {
            return Err(surface_input_error(
                "surface_input",
                "scroll deltas must be within 10000 pixels",
            ));
        }
        let scope = self.document_scope().await?;
        self.validate_surface_binding(&scope).await?;
        let layout = self.layout_snapshot().await?;
        let width = layout.visual_viewport.client_width;
        let height = layout.visual_viewport.client_height;
        if !width.is_finite() || !height.is_finite() || width <= 0.0 || height <= 0.0 {
            return Err(surface_input_error(
                "surface_input",
                "browser reported an invalid viewport for scroll",
            ));
        }
        self.ensure_surface_scope(&scope).await?;
        let (x, y) = (width / 2.0, height / 2.0);
        self.move_mouse(x, y, false).await?;
        self.validate_surface_binding(&scope).await?;
        self.dispatch_mouse_event(
            DispatchMouseEventType::MouseWheel,
            x,
            y,
            None,
            None,
            Some(f64::from(delta_x)),
            Some(f64::from(delta_y)),
            None,
        )
        .await?;
        self.ensure_surface_scope(&scope).await
    }

    async fn surface_node_input(&self, input: &SurfaceInput) -> Result<()> {
        let original_scope = self.document_scope().await?;
        let node = match input {
            SurfaceInput::Click { node }
            | SurfaceInput::Fill { node, .. }
            | SurfaceInput::Key { node, .. } => *node,
            SurfaceInput::Scroll { .. } => {
                return Err(surface_input_error(
                    "surface_input",
                    "scroll requires the viewport input path",
                ));
            }
        };

        let object_id = self.surface_node_object(node).await?;
        let initial = self
            .validate_surface_node(node, &object_id, &original_scope)
            .await?;
        match input {
            SurfaceInput::Click { .. } => {
                self.surface_click(node, &object_id, &original_scope, &initial)
                    .await
            }
            SurfaceInput::Fill { text, .. } => {
                self.surface_fill(node, &object_id, &original_scope, &initial, text)
                    .await
            }
            SurfaceInput::Key { key, .. } => {
                self.surface_key(node, &object_id, &original_scope, key)
                    .await
            }
            SurfaceInput::Scroll { .. } => Err(surface_input_error(
                "surface_input",
                "scroll requires the viewport input path",
            )),
        }
    }

    async fn surface_click(
        &self,
        node: u64,
        object_id: &RemoteObjectId,
        scope: &DocumentScope,
        initial: &Value,
    ) -> Result<()> {
        let (x, y) = surface_point(initial)?;
        self.move_mouse(x, y, false).await?;
        let current = self.validate_surface_node(node, object_id, scope).await?;
        let current_point = surface_point(&current)?;
        if !surface_points_match((x, y), current_point) {
            return Err(surface_input_error(
                "surface_input",
                "target moved during native click preparation",
            ));
        }
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
        .await
    }

    async fn surface_fill(
        &self,
        node: u64,
        object_id: &RemoteObjectId,
        scope: &DocumentScope,
        initial: &Value,
        text: &str,
    ) -> Result<()> {
        let tag = initial.get("tag").and_then(Value::as_str);
        if !matches!(tag, Some("input" | "textarea"))
            || initial.get("readonly") == Some(&Value::Bool(true))
        {
            return Err(surface_input_error(
                "surface_input",
                "fill target must be an editable input or textarea",
            ));
        }
        self.focus_surface_node(object_id).await?;
        self.validate_surface_node(node, object_id, scope).await?;
        self.ensure_surface_focus(node, object_id, scope).await?;
        self.clear_focused_text(node, object_id, scope).await?;
        self.ensure_surface_focus(node, object_id, scope).await?;
        if !text.is_empty() {
            self.inner
                .execute(InsertTextParams::new(text.to_owned()))
                .await
                .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
        }
        Ok(())
    }

    async fn surface_key(
        &self,
        node: u64,
        object_id: &RemoteObjectId,
        scope: &DocumentScope,
        key: &str,
    ) -> Result<()> {
        self.focus_surface_node(object_id).await?;
        self.validate_surface_node(node, object_id, scope).await?;
        self.ensure_surface_focus(node, object_id, scope).await?;
        let key = surface_key(key)?;
        self.dispatch_surface_key(key).await
    }

    async fn surface_node_object(&self, node: u64) -> Result<SurfaceObject> {
        let expression = format!("window.__ysArticle?.nodes.get({node})");
        let params = EvaluateParams::builder()
            .expression(expression)
            .await_promise(false)
            .return_by_value(false)
            .build()
            .map_err(VoidCrawlError::PageError)?;
        let result = self
            .inner
            .evaluate(params)
            .await
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
        let id = result.object().object_id.clone().ok_or_else(|| {
            surface_input_error("surface_input", "captured DOM node is no longer available")
        })?;
        Ok(SurfaceObject {
            id,
            page: self.inner.clone(),
        })
    }

    async fn validate_surface_node(
        &self,
        node: u64,
        object_id: &RemoteObjectId,
        scope: &DocumentScope,
    ) -> Result<Value> {
        self.ensure_surface_scope(scope).await?;
        let binding = self.surface_script("binding", &json!({})).await?;
        if binding.get("current") != Some(&Value::Bool(true)) {
            return Err(surface_input_error(
                "surface_input",
                "captured DOM binding is stale",
            ));
        }
        let eligibility = self
            .surface_script("eligibility", &json!({"id":node}))
            .await?;
        if eligibility.get("eligible") != Some(&Value::Bool(true))
            || eligibility.get("unchanged") != Some(&Value::Bool(true))
        {
            return Err(surface_input_error(
                "surface_input",
                "captured DOM node is stale or ineligible",
            ));
        }
        let same_node = self
            .call_surface_node(
                object_id,
                &format!(
                    "function() {{ return this instanceof Element && this.isConnected && window.__ysArticle?.nodes.get({node}) === this; }}"
                ),
            )
            .await?;
        if same_node.as_bool() != Some(true) {
            return Err(surface_input_error(
                "surface_input",
                "captured DOM node identity changed",
            ));
        }
        self.ensure_surface_scope(scope).await?;
        Ok(eligibility)
    }

    async fn focus_surface_node(&self, object_id: &RemoteObjectId) -> Result<()> {
        let focused = self
            .call_surface_node(
                object_id,
                "function() { if (!(this instanceof Element) || !this.isConnected) return false; this.focus(); return this.isConnected && this.ownerDocument.activeElement === this; }",
            )
            .await?;
        if focused.as_bool() != Some(true) {
            return Err(surface_input_error(
                "surface_input",
                "captured node could not be focused",
            ));
        }
        Ok(())
    }

    async fn ensure_surface_focus(
        &self,
        node: u64,
        object_id: &RemoteObjectId,
        scope: &DocumentScope,
    ) -> Result<()> {
        self.ensure_surface_scope(scope).await?;
        let focused = self
            .call_surface_node(
                object_id,
                &format!(
                    "function() {{ return this.isConnected && this.ownerDocument.activeElement === this && window.__ysArticle?.nodes.get({node}) === this; }}"
                ),
            )
            .await?;
        if focused.as_bool() != Some(true) {
            return Err(surface_input_error(
                "surface_input",
                "captured input lost focus before keyboard dispatch",
            ));
        }
        self.ensure_surface_scope(scope).await
    }

    async fn call_surface_node(&self, object_id: &RemoteObjectId, function: &str) -> Result<Value> {
        let params = CallFunctionOnParams::builder()
            .object_id(object_id.clone())
            .function_declaration(function)
            .await_promise(true)
            .return_by_value(true)
            .build()
            .map_err(VoidCrawlError::PageError)?;
        let result = self
            .inner
            // Object-bound calls must not use evaluate_function: that helper
            // adds an execution-context ID, which CDP forbids alongside objectId.
            .execute(params)
            .await
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?
            .result;
        if result.exception_details.is_some() {
            return Err(surface_input_error(
                "surface_input",
                "captured DOM predicate failed",
            ));
        }
        result
            .result
            .value
            .ok_or_else(|| surface_input_error("surface_input", "DOM target returned no value"))
    }

    async fn clear_focused_text(
        &self,
        node: u64,
        object_id: &RemoteObjectId,
        scope: &DocumentScope,
    ) -> Result<()> {
        let (modifier, code, virtual_key, flags) = if cfg!(target_os = "macos") {
            ("Meta", "MetaLeft", 91, 4)
        } else {
            ("Control", "ControlLeft", 17, 2)
        };
        self.dispatch_native_key(
            DispatchKeyEventType::KeyDown,
            modifier,
            code,
            virtual_key,
            None,
            Some(flags),
        )
        .await?;
        let mut selected = false;
        let selection = async {
            self.ensure_surface_focus(node, object_id, scope).await?;
            self.dispatch_native_key(
                DispatchKeyEventType::RawKeyDown,
                "a",
                "KeyA",
                65,
                None,
                Some(flags),
            )
            .await?;
            selected = true;
            Ok::<(), VoidCrawlError>(())
        }
        .await;
        // Release modifiers even if a page handler moved focus. Never delete or
        // insert into the newly focused element after such a change.
        let released_a = if selected {
            self.dispatch_native_key(
                DispatchKeyEventType::KeyUp,
                "a",
                "KeyA",
                65,
                None,
                Some(flags),
            )
            .await
        } else {
            Ok(())
        };
        let released_modifier = self
            .dispatch_native_key(
                DispatchKeyEventType::KeyUp,
                modifier,
                code,
                virtual_key,
                None,
                None,
            )
            .await;
        selection?;
        released_a?;
        released_modifier?;
        self.ensure_surface_focus(node, object_id, scope).await?;
        self.dispatch_native_key(
            DispatchKeyEventType::RawKeyDown,
            "Backspace",
            "Backspace",
            8,
            None,
            None,
        )
        .await?;
        self.dispatch_native_key(
            DispatchKeyEventType::KeyUp,
            "Backspace",
            "Backspace",
            8,
            None,
            None,
        )
        .await
    }

    async fn dispatch_surface_key(&self, key: SurfaceKey) -> Result<()> {
        let event_type = if key.text.is_some() {
            DispatchKeyEventType::KeyDown
        } else {
            DispatchKeyEventType::RawKeyDown
        };
        self.dispatch_native_key(
            event_type,
            key.key,
            key.code,
            key.virtual_code,
            key.text,
            None,
        )
        .await?;
        self.dispatch_native_key(
            DispatchKeyEventType::KeyUp,
            key.key,
            key.code,
            key.virtual_code,
            None,
            None,
        )
        .await
    }

    async fn dispatch_native_key(
        &self,
        event_type: DispatchKeyEventType,
        key: &str,
        code: &str,
        virtual_code: i64,
        text: Option<&str>,
        modifiers: Option<i64>,
    ) -> Result<()> {
        let mut builder = DispatchKeyEventParams::builder()
            .r#type(event_type)
            .key(key)
            .code(code)
            .windows_virtual_key_code(virtual_code);
        if let Some(text) = text {
            builder = builder.text(text).unmodified_text(text);
        }
        if let Some(modifiers) = modifiers {
            builder = builder.modifiers(modifiers);
        }
        let params = builder.build().map_err(VoidCrawlError::PageError)?;
        self.inner
            .execute(params)
            .await
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
        Ok(())
    }

    async fn validate_surface_binding(&self, scope: &DocumentScope) -> Result<()> {
        self.ensure_surface_scope(scope).await?;
        let binding = self.surface_script("binding", &json!({})).await?;
        if binding.get("current") != Some(&Value::Bool(true)) {
            return Err(surface_input_error(
                "surface_input",
                "captured DOM binding is stale",
            ));
        }
        self.ensure_surface_scope(scope).await
    }

    async fn ensure_surface_scope(&self, expected: &DocumentScope) -> Result<()> {
        let current = self.document_scope().await?;
        if same_surface_scope(expected, &current) {
            Ok(())
        } else {
            Err(VoidCrawlError::NavigationStateUncertain)
        }
    }
}

fn same_surface_scope(expected: &DocumentScope, current: &DocumentScope) -> bool {
    expected.frame_id == current.frame_id
        && expected.epoch == current.epoch
        && expected.frame == current.frame
}

fn surface_point(eligibility: &Value) -> Result<(f64, f64)> {
    let point = eligibility
        .get("point")
        .ok_or_else(|| surface_input_error("surface_input", "eligible node has no point"))?;
    let x = point
        .get("x")
        .and_then(Value::as_f64)
        .filter(|value| value.is_finite())
        .ok_or_else(|| {
            surface_input_error("surface_input", "eligible node has no valid x point")
        })?;
    let y = point
        .get("y")
        .and_then(Value::as_f64)
        .filter(|value| value.is_finite())
        .ok_or_else(|| {
            surface_input_error("surface_input", "eligible node has no valid y point")
        })?;
    Ok((x, y))
}

fn surface_points_match(left: (f64, f64), right: (f64, f64)) -> bool {
    (left.0 - right.0).abs() <= SURFACE_POINT_TOLERANCE
        && (left.1 - right.1).abs() <= SURFACE_POINT_TOLERANCE
}

#[derive(Clone, Copy)]
struct SurfaceKey {
    key: &'static str,
    code: &'static str,
    virtual_code: i64,
    text: Option<&'static str>,
}

fn surface_key(key: &str) -> Result<SurfaceKey> {
    match key {
        "Enter" => Ok(SurfaceKey {
            key: "Enter",
            code: "Enter",
            virtual_code: 13,
            text: Some("\r"),
        }),
        "Tab" => Ok(SurfaceKey {
            key: "Tab",
            code: "Tab",
            virtual_code: 9,
            text: None,
        }),
        "Escape" => Ok(SurfaceKey {
            key: "Escape",
            code: "Escape",
            virtual_code: 27,
            text: None,
        }),
        "Backspace" => Ok(SurfaceKey {
            key: "Backspace",
            code: "Backspace",
            virtual_code: 8,
            text: None,
        }),
        _ => Err(surface_input_error(
            "surface_input",
            "key must be Enter, Tab, Escape, or Backspace",
        )),
    }
}

const fn surface_input_error(operation: &'static str, reason: &'static str) -> VoidCrawlError {
    VoidCrawlError::InvalidInput { operation, reason }
}
