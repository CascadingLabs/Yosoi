use super::Page;
use crate::error::Result;
use crate::error::VoidCrawlError;
use crate::selector::RawRect;
use chromiumoxide::cdp::browser_protocol::dom::GetBoxModelParams;
use chromiumoxide::cdp::browser_protocol::dom::GetFrameOwnerParams;
use chromiumoxide::cdp::browser_protocol::page::FrameId;
use chromiumoxide::cdp::browser_protocol::page::GetLayoutMetricsParams;
use chromiumoxide::cdp::browser_protocol::target::SessionId;

#[derive(Debug, Clone, Copy)]
pub(super) struct BoxQuad {
    pub(super) x: [f64; 4],
    pub(super) y: [f64; 4],
}

impl BoxQuad {
    pub(super) const fn from_cdp(values: &[f64]) -> Option<Self> {
        let [x1, y1, x2, y2, x3, y3, x4, y4, ..] = values else {
            return None;
        };
        Some(Self {
            x: [*x1, *x2, *x3, *x4],
            y: [*y1, *y2, *y3, *y4],
        })
    }

    pub(super) fn center(self) -> (f64, f64) {
        (
            self.x.iter().sum::<f64>() / 4.0,
            self.y.iter().sum::<f64>() / 4.0,
        )
    }

    pub(super) fn map_into_parent(
        mut self,
        owner: Self,
        page_x: f64,
        page_y: f64,
        width: f64,
        height: f64,
    ) -> Option<Self> {
        if !width.is_finite() || !height.is_finite() || width <= 0.0 || height <= 0.0 {
            return None;
        }
        let [owner_x0, owner_x1, _, owner_x3] = owner.x;
        let [owner_y0, owner_y1, _, owner_y3] = owner.y;
        let x_axis = (owner_x1 - owner_x0, owner_y1 - owner_y0);
        let y_axis = (owner_x3 - owner_x0, owner_y3 - owner_y0);
        for (x, y) in self.x.iter_mut().zip(self.y.iter_mut()) {
            let horizontal = (*x - page_x) / width;
            let vertical = (*y - page_y) / height;
            *x = vertical.mul_add(y_axis.0, horizontal.mul_add(x_axis.0, owner_x0));
            *y = vertical.mul_add(y_axis.1, horizontal.mul_add(x_axis.1, owner_y0));
        }
        Some(self)
    }

    pub(super) fn bounding_rect(self) -> RawRect {
        let left = self.x.into_iter().fold(f64::INFINITY, f64::min);
        let top = self.y.into_iter().fold(f64::INFINITY, f64::min);
        let right = self.x.into_iter().fold(f64::NEG_INFINITY, f64::max);
        let bottom = self.y.into_iter().fold(f64::NEG_INFINITY, f64::max);
        RawRect {
            x: left,
            y: top,
            width: right - left,
            height: bottom - top,
        }
    }
}

impl Page {
    /// Locate an element by accessibility `role` + `name` **inside a specific
    /// frame** and return its on-page rectangle `[x, y, width, height]` in CSS
    /// pixels — the geometry needed to drive a **humanized** click yourself
    /// (e.g. move the cursor along a curved path with [`dispatch_mouse_event`]
    /// and press at a jittered point inside the box), rather than the single
    /// centre click of [`click_ax_in_frame`].
    ///
    /// Same cross-frame, closed-shadow-piercing resolution as
    /// [`click_ax_in_frame`]; an empty `name` matches any node of that `role`.
    ///
    /// [`dispatch_mouse_event`]: Self::dispatch_mouse_event
    /// [`click_ax_in_frame`]: Self::click_ax_in_frame
    pub async fn ax_box_in_frame(
        &self,
        frame_url_pattern: &str,
        role: &str,
        name: &str,
        nth: usize,
    ) -> Result<Vec<f64>> {
        let quad = self
            .ax_content_quad_in_frame(frame_url_pattern, role, name, nth)
            .await?;
        let rect = quad.bounding_rect();
        Ok(vec![rect.x, rect.y, rect.width, rect.height])
    }

    /// Resolve a frame-scoped AX `role`+`name` match to its box-model content
    /// quad `[x1,y1, x2,y2, x3,y3, x4,y4]` in page coordinates.
    pub(super) async fn ax_content_quad_in_frame(
        &self,
        frame_url_pattern: &str,
        role: &str,
        name: &str,
        nth: usize,
    ) -> Result<BoxQuad> {
        let (frame_id, _, quad) = self
            .ax_local_content_quad_in_frame(frame_url_pattern, role, name, nth)
            .await?;
        self.map_frame_quad_to_top(frame_id, quad).await
    }

    pub(super) async fn ax_local_content_quad_in_frame(
        &self,
        frame_url_pattern: &str,
        role: &str,
        name: &str,
        nth: usize,
    ) -> Result<(FrameId, SessionId, BoxQuad)> {
        let (frame_id, session_id, backend_id) = self
            .ax_backend_in_frame(frame_url_pattern, role, name, nth)
            .await?;
        let bm = self
            .inner
            .execute_in_frame_session(
                frame_id.clone(),
                session_id.clone(),
                GetBoxModelParams {
                    backend_node_id: Some(backend_id),
                    ..Default::default()
                },
            )
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        let quad = BoxQuad::from_cdp(bm.result.model.content.inner()).ok_or_else(|| {
            VoidCrawlError::PageError("AX node has no box-model content quad".into())
        })?;
        Ok((frame_id, session_id, quad))
    }

    pub(super) async fn map_frame_quad_to_top(
        &self,
        mut frame_id: FrameId,
        mut quad: BoxQuad,
    ) -> Result<BoxQuad> {
        while let Some(parent_frame_id) = self
            .inner
            .frame_parent(frame_id.clone())
            .await
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?
        {
            let frame_session = self
                .inner
                .frame_session(frame_id.clone())
                .await
                .map_err(|error| VoidCrawlError::PageError(error.to_string()))?
                .ok_or_else(|| VoidCrawlError::FrameNotFound(format!("{frame_id:?}")))?;
            let metrics = self
                .inner
                .execute_in_frame_session(
                    frame_id.clone(),
                    frame_session,
                    GetLayoutMetricsParams::default(),
                )
                .await
                .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
            let viewport = metrics.result.css_layout_viewport;
            let page_x = f64::from(i32::try_from(viewport.page_x).map_err(|_| {
                VoidCrawlError::PageError("frame page_x exceeds supported geometry range".into())
            })?);
            let page_y = f64::from(i32::try_from(viewport.page_y).map_err(|_| {
                VoidCrawlError::PageError("frame page_y exceeds supported geometry range".into())
            })?);
            let parent_session = self
                .inner
                .frame_session(parent_frame_id.clone())
                .await
                .map_err(|error| VoidCrawlError::PageError(error.to_string()))?
                .ok_or_else(|| VoidCrawlError::FrameNotFound(format!("{parent_frame_id:?}")))?;
            let owner = self
                .inner
                .execute_in_frame_session(
                    parent_frame_id.clone(),
                    parent_session.clone(),
                    GetFrameOwnerParams::new(frame_id.clone()),
                )
                .await
                .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
            let model = self
                .inner
                .execute_in_frame_session(
                    parent_frame_id.clone(),
                    parent_session,
                    GetBoxModelParams {
                        backend_node_id: Some(owner.result.backend_node_id),
                        ..Default::default()
                    },
                )
                .await
                .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
            let owner_model = model.result.model;
            let width = f64::from(i32::try_from(owner_model.width).map_err(|_| {
                VoidCrawlError::PageError("frame width exceeds supported geometry range".into())
            })?);
            let height = f64::from(i32::try_from(owner_model.height).map_err(|_| {
                VoidCrawlError::PageError("frame height exceeds supported geometry range".into())
            })?);
            let owner_quad = BoxQuad::from_cdp(owner_model.content.inner()).ok_or_else(|| {
                VoidCrawlError::PageError("frame owner has no box-model content quad".into())
            })?;
            quad = quad
                .map_into_parent(owner_quad, page_x, page_y, width, height)
                .ok_or_else(|| {
                    VoidCrawlError::PageError("frame viewport cannot map geometry".into())
                })?;
            frame_id = parent_frame_id;
        }
        Ok(quad)
    }
}
