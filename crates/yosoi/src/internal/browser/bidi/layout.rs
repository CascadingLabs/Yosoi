//! CSSOM layout observations and native raster metadata bound to one realm.

use base64::{Engine as _, engine::general_purpose::STANDARD};
use serde_json::{Value, json};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

use super::{
    emulation::validate_viewport,
    session::{Page, SessionError},
};
use crate::{
    browser::{BrowserEngine, MoliProfile},
    internal::{
        browser::{
            DocumentScope, LayoutSnapshot, ScreenshotOptions, Viewport, VisualSnapshot,
            viewport::ScrollTarget,
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
        if options.path.is_some() {
            return Err(SessionError::InvalidArgument {
                operation: "visual_snapshot",
                reason: "filesystem output paths are not accepted",
            });
        }
        if options.selector.is_some() {
            return Err(SessionError::Unsupported("BiDi screenshot target"));
        }
        if options
            .bbox
            .is_some_and(|bbox| bbox.width == 0 || bbox.height == 0)
        {
            return Err(SessionError::InvalidArgument {
                operation: "visual_snapshot",
                reason: "crop dimensions must be positive",
            });
        }
        if let Some(viewport) = options.viewport.as_ref() {
            validate_viewport(viewport)?;
        }
        if matches!(options.scroll, Some(ScrollTarget::Viewports(n)) if !n.is_finite()) {
            return Err(SessionError::InvalidArgument {
                operation: "visual_snapshot",
                reason: "scroll offset must be finite",
            });
        }
        if self.session.config.engine == BrowserEngine::Moli
            && self.session.config.moli_profile != MoliProfile::Layout
        {
            return Err(SessionError::Unsupported(
                "visual capture requires the Moli layout profile",
            ));
        }
        let current = self.viewport.lock().await;
        let before = self.document_scope(token, deadline).await?;
        let (window, realm) = self
            .evaluate("({x:scrollX,y:scrollY})", token, deadline)
            .await?;
        let mut restore = RestoreVisual {
            page: self,
            scope: before.clone(),
            realm: realm.clone(),
            viewport: &current,
            scroll: (number(&window, "x")?, number(&window, "y")?),
            restore_viewport: options.viewport.is_some(),
            armed: false,
        };
        let result = self
            .capture_visual(options, before, &realm, &mut restore, token, deadline)
            .await;
        restore.restore().await?;
        drop(restore);
        drop(current);
        result
    }

    async fn capture_visual(
        &self,
        options: ScreenshotOptions,
        before: DocumentScope,
        realm: &str,
        restore: &mut RestoreVisual<'_>,
        token: &CancellationToken,
        deadline: Instant,
    ) -> Result<VisualSnapshot, SessionError> {
        if let Some(viewport) = options.viewport.as_ref() {
            restore.armed = true;
            self.apply_viewport(Some(viewport), token, deadline).await?;
        }
        let shift = if let Some(target) = options.scroll {
            let y = match target {
                ScrollTarget::Pixels(y) => serde_json::Number::from(y)
                    .as_f64()
                    .ok_or(SessionError::Serialization)?,
                ScrollTarget::Viewports(n) => {
                    let (height, _) = self
                        .evaluate_realm("innerHeight", realm, token, deadline)
                        .await?;
                    height.as_f64().ok_or(SessionError::Serialization)? * n
                }
            };
            if !y.is_finite() {
                return Err(SessionError::InvalidArgument {
                    operation: "visual_snapshot",
                    reason: "scroll offset exceeds finite coordinates",
                });
            }
            restore.armed = true;
            let (position, _) = self.evaluate_realm(&format!("window.scrollTo({{left:0,top:{y},behavior:'instant'}});({{x:scrollX,y:scrollY}})"), realm, token, deadline).await?;
            (number(&position, "x")?, number(&position, "y")?)
        } else {
            (0.0, 0.0)
        };
        // Screenshot coordinates cover the actual window viewport, including
        // native scrollbars. Layout metrics separately describe the scrollport.
        let (window, _) = self
            .evaluate_realm(
                "({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})",
                realm,
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
            let object = params.as_object_mut().ok_or(SessionError::Serialization)?;
            object.insert(
                "clip".to_owned(),
                json!({"type":"box","x":f64::from(bbox.x)+shift.0,"y":f64::from(bbox.y)+shift.1,"width":bbox.width,"height":bbox.height}),
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

struct RestoreVisual<'a> {
    page: &'a Page,
    scope: DocumentScope,
    realm: String,
    viewport: &'a Option<Viewport>,
    scroll: (f64, f64),
    restore_viewport: bool,
    armed: bool,
}

impl Drop for RestoreVisual<'_> {
    fn drop(&mut self) {
        if self.armed {
            // A cancelled capture cannot hand a modified page to another Work.
            // Logical teardown owns recovery; never replay a mutation on drop.
            self.page.session.connection.fence();
        }
    }
}

impl RestoreVisual<'_> {
    async fn restore(&mut self) -> Result<(), SessionError> {
        if !self.armed {
            return Ok(());
        }
        let token = CancellationToken::new();
        let deadline = Instant::now()
            .checked_add(Duration::from_secs(2))
            .ok_or(SessionError::Capacity)?;
        if self.page.document_scope(&token, deadline).await? != self.scope {
            return Err(SessionError::DocumentChanged);
        }
        if self.restore_viewport {
            self.page
                .apply_viewport(self.viewport.as_ref(), &token, deadline)
                .await?;
        }
        let (x, y) = self.scroll;
        let (position, _) = self.page.evaluate_realm(&format!("window.scrollTo({{left:{x},top:{y},behavior:'instant'}});({{x:scrollX,y:scrollY}})"), &self.realm, &token, deadline).await?;
        if (number(&position, "x")? - x).abs() > 0.5 || (number(&position, "y")? - y).abs() > 0.5 {
            return Err(SessionError::DocumentChanged);
        }
        self.armed = false;
        Ok(())
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
