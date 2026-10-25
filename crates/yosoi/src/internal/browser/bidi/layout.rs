//! CSSOM layout observations and native raster metadata bound to one realm.

use base64::{Engine as _, engine::general_purpose::STANDARD};
use serde_json::{Value, json};
use std::time::{SystemTime, UNIX_EPOCH};
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

use super::session::{Page, SessionError};
use crate::{
    browser::{BrowserEngine, MoliProfile},
    internal::{
        browser::{
            LayoutSnapshot, ScreenshotOptions, VisualSnapshot,
            visual_snapshot::{
                self, ContentSizeMetrics, LayoutViewportMetrics, VisualCaptureRegion,
                VisualViewportMetrics,
            },
        },
        types,
    },
};

const METRICS: &str = r#"(() => {
  const d=document.documentElement, b=document.body, v=window.visualViewport;
  return {url:location.href,x:scrollX,y:scrollY,width:innerWidth,height:innerHeight,
    clientWidth:v?v.width*v.scale:null,clientHeight:v?v.height*v.scale:null,dpr:devicePixelRatio,
    contentWidth:Math.max(d.scrollWidth,b?.scrollWidth??0,innerWidth),
    contentHeight:Math.max(d.scrollHeight,b?.scrollHeight??0,innerHeight),
    visual:v?{x:v.pageLeft,y:v.pageTop,offsetX:v.offsetLeft,offsetY:v.offsetTop,width:v.width,height:v.height,scale:v.scale}:null};
})()"#;

impl Page {
    pub async fn layout_snapshot(
        &self,
        token: &CancellationToken,
        deadline: Instant,
    ) -> Result<LayoutSnapshot, SessionError> {
        if self.session.config.engine == BrowserEngine::Moli {
            // Moli requires a raster refresh before geometry is current. A
            // layout-only request cannot silently spend Screenshot permission.
            return Err(SessionError::Unsupported("Moli layout-only refresh"));
        }
        self.observed_layout(token, deadline).await
    }

    async fn observed_layout(
        &self,
        token: &CancellationToken,
        deadline: Instant,
    ) -> Result<LayoutSnapshot, SessionError> {
        let (value, realm) = self.evaluate(METRICS, token, deadline).await?;
        let scope = self
            .scope_for(
                realm.clone(),
                value
                    .get("url")
                    .and_then(Value::as_str)
                    .ok_or(SessionError::Serialization)?
                    .to_owned(),
            )
            .await?;
        if self.evaluate("0", token, deadline).await?.1 != realm {
            return Err(SessionError::DocumentChanged);
        }
        let visual = value
            .get("visual")
            .filter(|value| !value.is_null())
            .ok_or(SessionError::Unsupported("visual viewport metrics"))?;
        Ok(LayoutSnapshot {
            scope,
            generated_at_unix_ms: unix_millis(),
            layout_viewport: LayoutViewportMetrics {
                page_x: integer(&value, "x")?,
                page_y: integer(&value, "y")?,
                client_width: integer(&value, "clientWidth")?,
                client_height: integer(&value, "clientHeight")?,
            },
            visual_viewport: VisualViewportMetrics {
                offset_x: number(visual, "offsetX")?,
                offset_y: number(visual, "offsetY")?,
                page_x: number(visual, "x")?,
                page_y: number(visual, "y")?,
                client_width: number(visual, "width")?,
                client_height: number(visual, "height")?,
                scale: number(visual, "scale")?,
                zoom: None,
            },
            content_size: ContentSizeMetrics {
                x: 0.0,
                y: 0.0,
                width: number(&value, "contentWidth")?,
                height: number(&value, "contentHeight")?,
            },
            device_scale_factor: Some(number(&value, "dpr")?),
        })
    }

    pub async fn visual_snapshot(
        &self,
        options: ScreenshotOptions,
        token: &CancellationToken,
        deadline: Instant,
    ) -> Result<VisualSnapshot, SessionError> {
        if options.path.is_some()
            || options.selector.is_some()
            || options.scroll.is_some()
            || options.viewport.is_some()
        {
            return Err(SessionError::Unsupported(
                "BiDi screenshot target, temporary viewport, scroll or file output",
            ));
        }
        if self.session.config.engine == BrowserEngine::Moli
            && self.session.config.moli_profile != MoliProfile::Layout
        {
            return Err(SessionError::Unsupported(
                "visual capture requires the Moli layout profile",
            ));
        }
        let before = self.document_scope(token, deadline).await?;
        // Screenshot coordinates cover the actual window viewport, including
        // native scrollbars. Layout metrics separately describe the scrollport.
        let (window, _) = self
            .evaluate(
                "({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})",
                token,
                deadline,
            )
            .await?;
        let viewport = types::Viewport::try_from_pixels(
            u32::try_from(integer(&window, "width")?).map_err(|_| SessionError::Serialization)?,
            u32::try_from(integer(&window, "height")?).map_err(|_| SessionError::Serialization)?,
        )
        .map_err(|_| SessionError::Serialization)?;
        let dpr = number(&window, "dpr")?;
        if dpr <= 0.0 {
            return Err(SessionError::Serialization);
        }
        let mut params = json!({"context":self.context,"origin":if options.full_page {"document"}else{"viewport"},"format":{"type":"image/png"}});
        let region = if let Some(bbox) = options.bbox {
            if bbox.width == 0 || bbox.height == 0 {
                return Err(SessionError::InvalidArgument {
                    operation: "visual_snapshot",
                    reason: "crop dimensions must be positive",
                });
            }
            let object = params.as_object_mut().ok_or(SessionError::Serialization)?;
            object.insert(
                "clip".to_owned(),
                json!({"type":"box","x":bbox.x,"y":bbox.y,"width":bbox.width,"height":bbox.height}),
            );
            // Crops use document coordinates, independent of full_page.
            object.insert("origin".to_owned(), json!("document"));
            VisualCaptureRegion::BoundingBox { bbox }
        } else if options.full_page {
            VisualCaptureRegion::FullPage
        } else {
            VisualCaptureRegion::Viewport
        };
        let result = self
            .command("browsingContext.captureScreenshot", params, token, deadline)
            .await?;
        let bytes = STANDARD
            .decode(
                result
                    .get("data")
                    .and_then(Value::as_str)
                    .ok_or(SessionError::Serialization)?,
            )
            .map_err(|_| SessionError::Serialization)?;
        let after = self.document_scope(token, deadline).await?;
        if before != after {
            return Err(SessionError::DocumentChanged);
        }
        visual_snapshot::visual_snapshot(bytes, before, region, viewport, dpr)
            .ok_or(SessionError::Serialization)
    }
}

fn number(value: &Value, field: &str) -> Result<f64, SessionError> {
    value
        .get(field)
        .and_then(Value::as_f64)
        .filter(|n| n.is_finite())
        .ok_or(SessionError::Serialization)
}

fn integer(value: &Value, field: &str) -> Result<i64, SessionError> {
    // Scrolling may report fractional CSS pixels. CDP's layout viewport uses
    // integers; retain visual-viewport precision separately.
    let number = number(value, field)?.round();
    format!("{number:.0}")
        .parse()
        .map_err(|_| SessionError::Serialization)
}

fn unix_millis() -> Option<u64> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .ok()
        .and_then(|duration| u64::try_from(duration.as_millis()).ok())
}
