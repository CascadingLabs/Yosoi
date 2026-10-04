use super::Page;
use super::frame_geometry::BoxQuad;
use crate::error::Result;
use crate::error::VoidCrawlError;
use crate::selector;
use crate::selector::BrowserTarget;
use crate::selector::BrowserTargetKind;
use crate::selector::RawRect;
use crate::selector::TargetResolution;
use chromiumoxide::cdp::browser_protocol::dom::GetBoxModelParams;
use chromiumoxide::cdp::browser_protocol::dom::ResolveNodeParams;
use chromiumoxide::cdp::js_protocol::runtime::CallFunctionOnParams;
use serde_json::Value;

impl Page {
    /// Click an element addressed by its accessibility `role` and accessible
    /// `name` — the durable, markup-independent analogue of [`click_element`].
    ///
    /// Resolves via `Accessibility.queryAXTree`, picks the `nth` non-ignored
    /// match (0-based), bridges to the DOM through `backendDOMNodeId`, then
    /// scrolls it into view and clicks it. Errors if no such node exists.
    ///
    /// With `humanize = true`, the element is scrolled into view and then
    /// clicked at its box-model centre with a **trusted compositor** event
    /// along a human-like cursor path (see [`click_xy`]) — rather than the
    /// DOM `this.click()` used by default. Untrusted `.click()` is fine for
    /// ordinary forms but rejected by some challenge widgets.
    ///
    /// [`click_element`]: Self::click_element
    /// [`click_xy`]: Self::click_xy
    pub async fn click_by_role(
        &self,
        role: &str,
        name: &str,
        nth: usize,
        humanize: bool,
    ) -> Result<()> {
        self.ensure_active().await?;
        let nodes = self.query_ax_nodes(Some(role), Some(name)).await?;
        let backends: Vec<_> = nodes
            .iter()
            .filter(|n| !n.ignored)
            .filter_map(|n| n.backend_dom_node_id)
            .collect();
        let backend_id = backends.get(nth).copied().ok_or_else(|| {
            VoidCrawlError::ElementNotFound(format!(
                "no AX node with role={role:?} name={name:?} at index {nth} (found {} match(es))",
                backends.len()
            ))
        })?;

        // Bridge AX node → DOM → JS handle. Resolve once; both paths scroll it
        // into view first.
        let resolved = self
            .inner
            .execute(ResolveNodeParams {
                backend_node_id: Some(backend_id),
                ..Default::default()
            })
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        let object_id = resolved.result.object.object_id.ok_or_else(|| {
            VoidCrawlError::PageError("AX node could not be resolved to a DOM handle".into())
        })?;

        if humanize {
            // Scroll into view, then a trusted compositor click at the box
            // centre.
            let scroll = CallFunctionOnParams::builder()
                .object_id(object_id)
                .function_declaration(
                    "function(){ this.scrollIntoView({block:'center',inline:'center'}); }",
                )
                .await_promise(false)
                .build()
                .map_err(VoidCrawlError::PageError)?;
            self.inner
                .execute(scroll)
                .await
                .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
            let bm = self
                .inner
                .execute(GetBoxModelParams {
                    backend_node_id: Some(backend_id),
                    ..Default::default()
                })
                .await
                .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
            let quad = BoxQuad::from_cdp(bm.result.model.content.inner()).ok_or_else(|| {
                VoidCrawlError::PageError("element has no box-model content quad".into())
            })?;
            let (cx, cy) = quad.center();
            return self.click_xy(cx, cy, true).await;
        }

        // Default: the element's own click() — avoids box-model math and
        // survives elements that are off-screen until scrolled into
        // view.
        let call = CallFunctionOnParams::builder()
            .object_id(object_id)
            .function_declaration(
                "function(){ this.scrollIntoView({block:'center',inline:'center'}); this.click(); }",
            )
            .await_promise(false)
            .build()
            .map_err(VoidCrawlError::PageError)?;
        self.inner
            .execute(call)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(())
    }

    // ── Selector-backed bbox resolution ──────────────────────────────────

    /// Resolve a VoidCrawl [`BrowserTarget`] to a CSS-pixel rectangle.
    /// See the [`selector`](crate::selector) module docs for the full design:
    /// resolved, empty, and ambiguous are typed `Ok(...)` outcomes; `Err` is
    /// reserved for browser, JavaScript, or CDP failures.
    ///
    /// For a one-off crop, pass [`ScreenshotOptions::selector`] to
    /// [`Page::screenshot`] instead — that converts a non-`Resolved`
    /// outcome into an actionable `Err`, since a screenshot fundamentally
    /// needs a rectangle.
    pub async fn resolve_target(&self, entry: &BrowserTarget) -> Result<TargetResolution> {
        entry.validate()?;
        match entry.kind {
            BrowserTargetKind::Jsonld => Ok(TargetResolution::Empty {
                reason: "jsonld selectors address non-visual structured data (a <script> tag \
                         has no render box); not resolved to a rectangle"
                    .into(),
            }),
            BrowserTargetKind::Regex => Ok(TargetResolution::Empty {
                reason: "regex selectors match raw HTML text, which has no canonical DOM \
                         element; not resolved to a rectangle"
                    .into(),
            }),
            BrowserTargetKind::Visual => Ok(self.resolve_visual_selector(entry).await?),
            BrowserTargetKind::Role => self.resolve_role_selector(entry).await,
            BrowserTargetKind::Css
            | BrowserTargetKind::Xpath
            | BrowserTargetKind::Attr
            | BrowserTargetKind::GlobalId => self.resolve_dom_selector(entry).await,
        }
    }

    /// `visual`: an exact 1x1 CSS-pixel box at `(x, y)` — no invented
    /// hit-radius. Coordinates have already passed [`BrowserTarget::validate`];
    /// `Empty` means the point is outside the current viewport.
    async fn resolve_visual_selector(&self, entry: &BrowserTarget) -> Result<TargetResolution> {
        let (Some(x), Some(y)) = (entry.x, entry.y) else {
            return Err(VoidCrawlError::InvalidInput {
                operation: "browser_target",
                reason: "visual target requires both x and y coordinates",
            });
        };
        let dims = self
            .evaluate_js("[window.innerWidth, window.innerHeight]")
            .await?
            .as_array()
            .cloned()
            .unwrap_or_default();
        let (vw, vh) = (
            dims.first()
                .and_then(Value::as_f64)
                .unwrap_or(f64::INFINITY),
            dims.get(1).and_then(Value::as_f64).unwrap_or(f64::INFINITY),
        );
        if x >= vw || y >= vh {
            return Ok(TargetResolution::Empty {
                reason: format!(
                    "visual point ({x}, {y}) is outside the current viewport ({vw}x{vh})"
                ),
            });
        }
        Ok(TargetResolution::Resolved {
            bbox: RawRect {
                x,
                y,
                width: 1.0,
                height: 1.0,
            }
            .to_bbox(),
        })
    }

    /// `role`: `Accessibility.queryAXTree` role + exact accessible-name
    /// match — the same resolution [`Page::click_by_role`] uses, so a
    /// selector that could click an element can also crop it.
    pub(super) async fn resolve_role_selector(
        &self,
        entry: &BrowserTarget,
    ) -> Result<TargetResolution> {
        let name = entry.name.as_deref();
        let nodes = self.query_ax_nodes(Some(&entry.value), name).await?;
        let backends: Vec<_> = nodes
            .iter()
            .filter(|n| !n.ignored)
            .filter_map(|n| n.backend_dom_node_id)
            .collect();
        let describe = || format!("role={:?} name={:?}", entry.value, name.unwrap_or(""));

        if backends.is_empty() {
            return Ok(TargetResolution::Empty {
                reason: format!("{} matched no AX nodes", describe()),
            });
        }
        // AX-tree matches are already "exists in the accessibility tree",
        // which excludes `display:none`/`aria-hidden` — but the box model
        // can still be a zero-area detached node, so resolve+filter each
        // candidate the same way `pick_resolution` treats DOM rects.
        let mut visible = Vec::with_capacity(backends.len());
        for backend_id in &backends {
            let bm = self
                .inner
                .execute(GetBoxModelParams {
                    backend_node_id: Some(*backend_id),
                    ..Default::default()
                })
                .await;
            let Ok(bm) = bm else { continue };
            // The *border* box, not the content box: it's what
            // `getBoundingClientRect()` returns for a typical element, and
            // every other selector kind here resolves via that same JS
            // call — using the content box would exclude an element's own
            // padding/border and disagree with them for no reason.
            let Some(quad) = BoxQuad::from_cdp(bm.result.model.border.inner()) else {
                continue;
            };
            let rect = quad.bounding_rect();
            if rect.width > 0.0 && rect.height > 0.0 {
                visible.push(rect);
            }
        }
        Ok(selector::pick_resolution(
            backends.len(),
            &visible,
            entry.nth,
            describe,
        ))
    }

    /// `css` / `xpath` / `attr` / `global_id`: gather DOM candidates (see
    /// [`selector::candidates_js`]), filter to visible ones, then resolve
    /// via [`selector::pick_resolution`].
    pub(super) async fn resolve_dom_selector(
        &self,
        entry: &BrowserTarget,
    ) -> Result<TargetResolution> {
        let candidates = selector::candidates_js(entry).ok_or_else(|| {
            VoidCrawlError::PageError(format!("{:?} has no DOM candidate step", entry.kind))
        })?;
        let count_js = format!("({candidates}).length");
        let count = self.evaluate_js(&count_js).await?.as_u64().ok_or_else(|| {
            VoidCrawlError::JsEvalError("candidate count was not a number".into())
        })?;
        let total_matches = usize::try_from(count).map_err(|_| {
            VoidCrawlError::JsEvalError(format!("implausible candidate count: {count}"))
        })?;

        let rects_js = selector::visible_rects_js(&candidates);
        let raw: Value = self.evaluate_js(&rects_js).await?;
        let visible: Vec<RawRect> = serde_json::from_value(raw)
            .map_err(|e| VoidCrawlError::JsEvalError(format!("rect decode failed: {e}")))?;

        let describe = || format!("{:?} {:?}", entry.kind, entry.value);
        Ok(selector::pick_resolution(
            total_matches,
            &visible,
            entry.nth,
            describe,
        ))
    }
}
