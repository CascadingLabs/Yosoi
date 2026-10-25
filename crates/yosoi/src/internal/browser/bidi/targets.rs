//! Read-only geometry resolution shares CDP's DOM visibility and nth rules.

use super::session::{Page, SessionError};
use crate::browser::BrowserEngine;
use crate::internal::browser::{
    Bbox,
    selector::{self, BrowserTarget, BrowserTargetKind, RawRect, TargetResolution},
};
use serde_json::Value;
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

pub(super) fn validate_visual_target(target: &BrowserTarget) -> Result<(), SessionError> {
    target
        .validate()
        .map_err(|_| SessionError::InvalidArgument {
            operation: "visual_snapshot",
            reason: "invalid visual target declaration",
        })?;
    if !target.supports_geometry() {
        return Err(SessionError::UnsupportedVisualTarget);
    }
    if target.kind == BrowserTargetKind::Role {
        // A native accessibility locator does not prove AX-tree exposure.
        // CDP's role crop requires a non-ignored AX node, not just role/name.
        return Err(SessionError::Unsupported("BiDi AX-exposed role geometry"));
    }
    Ok(())
}

impl Page {
    pub(super) async fn visual_target(
        &self,
        target: &BrowserTarget,
        realm: &str,
        token: &CancellationToken,
        deadline: Instant,
    ) -> Result<Bbox, SessionError> {
        if self.session.config.engine == BrowserEngine::Moli {
            // This operation already owns Screenshot permission. Refresh Moli's
            // renderer before querying its otherwise possibly stale geometry.
            self.screenshot_png(token, deadline).await?;
        }
        let resolution = if target.kind == BrowserTargetKind::Visual {
            let x = target.x.ok_or(SessionError::Serialization)?;
            let y = target.y.ok_or(SessionError::Serialization)?;
            let (dims, _) = self
                .evaluate_realm(
                    "({width:innerWidth,height:innerHeight})",
                    realm,
                    token,
                    deadline,
                )
                .await?;
            let width = dims
                .get("width")
                .and_then(Value::as_f64)
                .ok_or(SessionError::Serialization)?;
            let height = dims
                .get("height")
                .and_then(Value::as_f64)
                .ok_or(SessionError::Serialization)?;
            if x >= width || y >= height {
                return Err(SessionError::TargetNotVisible);
            }
            TargetResolution::Resolved {
                bbox: RawRect {
                    x,
                    y,
                    width: 1.0,
                    height: 1.0,
                }
                .to_bbox(),
            }
        } else {
            let candidates =
                selector::candidates_js(target).ok_or(SessionError::UnsupportedVisualTarget)?;
            let visible = selector::visible_rects_js("nodes");
            let source = format!(
                "(()=>{{const nodes={candidates};if(nodes.length>4096)return {{overflow:true}};const rects={visible};return {{count:nodes.length,rects}};}})()"
            );
            let (value, _) = self.evaluate_realm(&source, realm, token, deadline).await?;
            if value.get("overflow").and_then(Value::as_bool) == Some(true) {
                return Err(SessionError::Capacity);
            }
            let count = value
                .get("count")
                .and_then(Value::as_u64)
                .and_then(|v| usize::try_from(v).ok())
                .ok_or(SessionError::Serialization)?;
            let rects: Vec<RawRect> = serde_json::from_value(
                value
                    .get("rects")
                    .cloned()
                    .ok_or(SessionError::Serialization)?,
            )
            .map_err(|_| SessionError::Serialization)?;
            if rects.iter().any(|r| {
                !r.x.is_finite()
                    || !r.y.is_finite()
                    || !r.width.is_finite()
                    || !r.height.is_finite()
            }) {
                return Err(SessionError::Serialization);
            }
            selector::pick_resolution(count, &rects, target.nth, || {
                "native visual target".to_owned()
            })
        };
        match resolution {
            TargetResolution::Resolved { bbox } => Ok(bbox),
            TargetResolution::Empty { .. } => Err(SessionError::TargetNotVisible),
            TargetResolution::Ambiguous { .. } => Err(SessionError::TargetAmbiguous),
        }
    }
}
