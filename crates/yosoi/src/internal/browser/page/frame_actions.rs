use crate::internal::types as yosoi_types;

use super::Page;
use super::input::runtime_seed;
use crate::internal::browser::ax::compact_outline;
use crate::internal::browser::environment::EnvironmentObservation;
use crate::internal::browser::error::Result;
use crate::internal::browser::error::VoidCrawlError;
use crate::internal::browser::input::HumanizeOptions;
use crate::internal::browser::input::Rng;
use crate::internal::browser::input::humanized_path;
use chromiumoxide::cdp::browser_protocol::accessibility::AxValue;
use chromiumoxide::cdp::browser_protocol::accessibility::GetFullAxTreeParams;
use chromiumoxide::cdp::browser_protocol::dom::BackendNodeId;
use chromiumoxide::cdp::browser_protocol::input::DispatchMouseEventParams;
use chromiumoxide::cdp::browser_protocol::input::DispatchMouseEventType;
use chromiumoxide::cdp::browser_protocol::input::MouseButton;
use chromiumoxide::cdp::browser_protocol::page::FrameId;
use chromiumoxide::cdp::browser_protocol::target::SessionId;
use serde_json::Value;
use std::time::Duration;
use tokio::time;

impl Page {
    /// Compact accessibility outline of a specific (possibly cross-origin)
    /// **frame** — the cross-frame analogue of [`ax_tree_outline`].
    ///
    /// Roots `Accessibility.getFullAXTree` at the frame matched by
    /// `frame_url_pattern` (resolved like [`evaluate_js_in_frame`]). The AX
    /// tree is browser-computed and ignores shadow-DOM mode, so this
    /// **pierces closed shadow roots** the page's own JavaScript cannot
    /// read — use it to discover the `role` / accessible-name to pass to
    /// [`click_ax_in_frame`].
    ///
    /// [`ax_tree_outline`]: Self::ax_tree_outline
    /// [`evaluate_js_in_frame`]: Self::evaluate_js_in_frame
    /// [`click_ax_in_frame`]: Self::click_ax_in_frame
    pub async fn ax_outline_in_frame(
        &self,
        frame_url_pattern: &str,
        depth: Option<i64>,
    ) -> Result<String> {
        let frame_id = self.resolve_frame(frame_url_pattern).await?;
        let session_id = self
            .inner
            .frame_session(frame_id.clone())
            .await
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?
            .ok_or_else(|| VoidCrawlError::FrameNotFound(frame_url_pattern.to_owned()))?;
        let resp = self
            .inner
            .execute_in_frame_session(
                frame_id.clone(),
                session_id,
                GetFullAxTreeParams {
                    depth,
                    frame_id: Some(frame_id),
                },
            )
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        let nodes = serde_json::to_value(&resp.result.nodes)
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(compact_outline(
            nodes.as_array().map_or(&[][..], Vec::as_slice),
        ))
    }

    /// Locate an element by accessibility `role` + accessible `name` **inside a
    /// specific (possibly cross-origin) frame** and click it with a real
    /// **compositor** mouse event. The cross-frame, shadow-piercing analogue of
    /// [`click_by_role`].
    ///
    /// `Accessibility.getFullAXTree` rooted at the resolved frame descends into
    /// that frame's tree **including closed shadow roots** (the AX tree is
    /// browser-computed and ignores shadow mode), so it reaches widgets that
    /// `contentDocument` / page-JS cannot — e.g. Cloudflare Turnstile's
    /// "Verify you are human" checkbox, which lives in a closed shadow root
    /// inside a cross-origin `challenges.cloudflare.com` iframe. The matched
    /// node is clicked at its box-model centre via `Input.dispatchMouseEvent`
    /// (a **trusted** event), *not* a DOM `.click()` — challenge widgets reject
    /// untrusted clicks, and crucially this does **no page-JS shadow
    /// tampering**, so it does not trip Turnstile's closed-shadow check
    /// (ERROR 600010).
    ///
    /// An empty `name` matches any node of that `role`. Picks the `nth`
    /// (0-based) non-ignored match; errors if there is none.
    ///
    /// Normal CDP mode routes AX and DOM geometry commands through the matched
    /// frame's owning session. Minimal mode leaves OOPIF routing disabled.
    ///
    /// [`click_by_role`]: Self::click_by_role
    /// [`evaluate_js_in_frame`]: Self::evaluate_js_in_frame
    pub async fn click_ax_in_frame(
        &self,
        frame_url_pattern: &str,
        role: &str,
        name: &str,
        nth: usize,
        humanize: bool,
    ) -> Result<()> {
        let (frame_id, session_id, quad) = self
            .ax_local_content_quad_in_frame(frame_url_pattern, role, name, nth)
            .await?;
        let (cx, cy) = quad.center();
        self.click_in_frame_session(frame_id, session_id, cx, cy, humanize)
            .await
    }

    pub(super) async fn click_in_frame_session(
        &self,
        frame_id: FrameId,
        session_id: SessionId,
        x: f64,
        y: f64,
        humanize: bool,
    ) -> Result<()> {
        self.ensure_active().await?;
        let input_guard = self.capture_lock.lock().await;
        if !matches!(
            &self.browser_mode,
            EnvironmentObservation::Known {
                value: yosoi_types::BrowserMode::Headful
            }
        ) {
            self.inner
                .activate()
                .await
                .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
        }
        if humanize {
            let mut rng = Rng::seed(runtime_seed());
            for step in humanized_path((0.0, 0.0), (x, y), &HumanizeOptions::default(), &mut rng) {
                time::sleep(Duration::from_millis(step.delay_ms)).await;
                self.dispatch_mouse_event_in_frame(
                    frame_id.clone(),
                    session_id.clone(),
                    DispatchMouseEventType::MouseMoved,
                    step.x,
                    step.y,
                    None,
                    None,
                )
                .await?;
            }
        } else {
            self.dispatch_mouse_event_in_frame(
                frame_id.clone(),
                session_id.clone(),
                DispatchMouseEventType::MouseMoved,
                x,
                y,
                None,
                None,
            )
            .await?;
        }
        for event_type in [
            DispatchMouseEventType::MousePressed,
            DispatchMouseEventType::MouseReleased,
        ] {
            self.dispatch_mouse_event_in_frame(
                frame_id.clone(),
                session_id.clone(),
                event_type,
                x,
                y,
                Some(MouseButton::Left),
                Some(1),
            )
            .await?;
        }
        drop(input_guard);
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    pub(super) async fn dispatch_mouse_event_in_frame(
        &self,
        frame_id: FrameId,
        session_id: SessionId,
        event_type: DispatchMouseEventType,
        x: f64,
        y: f64,
        button: Option<MouseButton>,
        click_count: Option<i64>,
    ) -> Result<()> {
        let mut builder = DispatchMouseEventParams::builder()
            .r#type(event_type)
            .x(x)
            .y(y);
        if let Some(button) = button {
            builder = builder.button(button);
        }
        if let Some(click_count) = click_count {
            builder = builder.click_count(click_count);
        }
        let params = builder.build().map_err(VoidCrawlError::PageError)?;
        self.inner
            .execute_in_frame_session(frame_id, session_id, params)
            .await
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
        Ok(())
    }

    /// Resolve a frame-scoped AX `role`+`name` match to its `backendDOMNodeId`.
    pub(super) async fn ax_backend_in_frame(
        &self,
        frame_url_pattern: &str,
        role: &str,
        name: &str,
        nth: usize,
    ) -> Result<(FrameId, SessionId, BackendNodeId)> {
        fn ax_text(v: Option<&AxValue>) -> &str {
            v.and_then(|a| a.value.as_ref())
                .and_then(Value::as_str)
                .unwrap_or("")
        }
        let frame_id = self.resolve_frame(frame_url_pattern).await?;
        let session_id = self
            .inner
            .frame_session(frame_id.clone())
            .await
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?
            .ok_or_else(|| VoidCrawlError::FrameNotFound(frame_url_pattern.to_owned()))?;
        let resp = self
            .inner
            .execute_in_frame_session(
                frame_id.clone(),
                session_id.clone(),
                GetFullAxTreeParams {
                    depth: None,
                    frame_id: Some(frame_id.clone()),
                },
            )
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        let matched = resp
            .result
            .nodes
            .iter()
            .filter(|n| {
                !n.ignored
                    && ax_text(n.role.as_ref()) == role
                    && (name.is_empty() || ax_text(n.name.as_ref()) == name)
            })
            .filter_map(|n| n.backend_dom_node_id)
            .nth(nth);
        matched.map(|backend| (frame_id, session_id, backend)).ok_or_else(|| {
            VoidCrawlError::PageError(format!(
                "no AX node with role={role:?} name={name:?} at index {nth} in frame {frame_url_pattern:?}"
            ))
        })
    }
}
