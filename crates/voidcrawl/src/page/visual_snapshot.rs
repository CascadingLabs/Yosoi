use super::Page;
use super::ScreenshotOptions;
use super::ScreenshotOutput;
use super::shared::unix_millis_now;
use super::validation::positive_u32;
use crate::error::Result;
use crate::error::VoidCrawlError;
use crate::visual_snapshot::ContentSizeMetrics;
use crate::visual_snapshot::LayoutSnapshot;
use crate::visual_snapshot::LayoutViewportMetrics;
use crate::visual_snapshot::PairedLayoutVisualSnapshot;
use crate::visual_snapshot::VisualCaptureRegion;
use crate::visual_snapshot::VisualSnapshot;
use crate::visual_snapshot::VisualViewportMetrics;
use crate::visual_snapshot::visual_snapshot;

impl Page {
    // ── Screenshots & PDF ───────────────────────────────────────────────

    /// Capture point-in-time CSS layout metrics for the current document.
    pub async fn layout_snapshot(&self) -> Result<LayoutSnapshot> {
        let metrics = self
            .inner
            .layout_metrics()
            .await
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
        let dpr = self
            .evaluate_js("window.devicePixelRatio")
            .await
            .ok()
            .and_then(|value| value.as_f64())
            .filter(|value| value.is_finite() && *value > 0.0);
        let scope = self.top_level_document_scope().await?;
        Ok(LayoutSnapshot {
            scope,
            generated_at_unix_ms: unix_millis_now(),
            layout_viewport: LayoutViewportMetrics {
                page_x: metrics.css_layout_viewport.page_x,
                page_y: metrics.css_layout_viewport.page_y,
                client_width: metrics.css_layout_viewport.client_width,
                client_height: metrics.css_layout_viewport.client_height,
            },
            visual_viewport: VisualViewportMetrics {
                offset_x: metrics.css_visual_viewport.offset_x,
                offset_y: metrics.css_visual_viewport.offset_y,
                page_x: metrics.css_visual_viewport.page_x,
                page_y: metrics.css_visual_viewport.page_y,
                client_width: metrics.css_visual_viewport.client_width,
                client_height: metrics.css_visual_viewport.client_height,
                scale: metrics.css_visual_viewport.scale,
                zoom: metrics.css_visual_viewport.zoom,
            },
            content_size: ContentSizeMetrics {
                x: metrics.css_content_size.x,
                y: metrics.css_content_size.y,
                width: metrics.css_content_size.width,
                height: metrics.css_content_size.height,
            },
            device_scale_factor: dpr,
        })
    }

    /// Capture a screenshot with provider-native visual metadata.
    ///
    /// This method always returns owned bytes. Use [`Page::screenshot`] when a
    /// filesystem output path is desired.
    pub async fn visual_snapshot(&self, mut opts: ScreenshotOptions) -> Result<VisualSnapshot> {
        if opts.path.is_some() {
            return Err(VoidCrawlError::InvalidInput {
                operation: "visual_snapshot",
                reason: "filesystem output paths are not accepted",
            });
        }
        let region = if let Some(bbox) = opts.bbox {
            VisualCaptureRegion::BoundingBox { bbox }
        } else if let Some(target) = &opts.selector {
            VisualCaptureRegion::BrowserTarget {
                target_kind: target.kind,
            }
        } else if opts.full_page {
            VisualCaptureRegion::FullPage
        } else {
            VisualCaptureRegion::Viewport
        };
        let layout = self.layout_snapshot().await?;
        let (capture_viewport, device_scale_factor) = if let Some(viewport) = &opts.viewport {
            (
                yosoi_types::Viewport::try_from_pixels(viewport.width, viewport.height).map_err(
                    |_| VoidCrawlError::InvalidInput {
                        operation: "visual_snapshot",
                        reason: "viewport dimensions must be positive",
                    },
                )?,
                viewport.device_scale_factor,
            )
        } else {
            (
                yosoi_types::Viewport::try_from_pixels(
                    positive_u32(layout.visual_viewport.client_width),
                    positive_u32(layout.visual_viewport.client_height),
                )
                .map_err(|_| VoidCrawlError::InvalidInput {
                    operation: "visual_snapshot",
                    reason: "browser reported an invalid viewport",
                })?,
                layout.device_scale_factor.unwrap_or(1.0),
            )
        };
        opts.path = None;
        let bytes = match self.screenshot(opts).await? {
            ScreenshotOutput::Bytes(bytes) => bytes,
            ScreenshotOutput::Path(_) => {
                return Err(VoidCrawlError::ScreenshotError(
                    "visual snapshot unexpectedly wrote to disk".into(),
                ));
            }
        };
        visual_snapshot(
            bytes,
            layout.scope,
            region,
            capture_viewport,
            device_scale_factor,
        )
        .ok_or_else(|| {
            VoidCrawlError::ScreenshotError("PNG signature/IHDR/dimensions were invalid".into())
        })
    }

    /// Sequentially capture layout and visual evidence in one document epoch.
    /// The two factual observations are not simultaneous or atomically
    /// correlated. Chromium materializes the PNG before callers can enforce
    /// a retention bound; consumers must all-or-discard the returned PNG.
    pub async fn paired_layout_visual_snapshot(
        &self,
        opts: ScreenshotOptions,
    ) -> Result<PairedLayoutVisualSnapshot> {
        let layout = self.layout_snapshot().await?;
        let visual = self.visual_snapshot(opts).await?;
        if layout.scope != visual.scope {
            return Err(VoidCrawlError::PageError(
                "document epoch changed during paired visual capture".into(),
            ));
        }
        Ok(PairedLayoutVisualSnapshot { layout, visual })
    }
}
