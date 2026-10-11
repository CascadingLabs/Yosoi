use super::Page;
use super::identity::{client_hints_for_ua, mobile_ua_platform_and_metadata};
use crate::internal::browser::error::Result;
use crate::internal::browser::error::VoidCrawlError;
use crate::internal::browser::viewport::Viewport;
use chromiumoxide::cdp::browser_protocol::emulation::ClearDeviceMetricsOverrideParams;
use chromiumoxide::cdp::browser_protocol::emulation::SetDeviceMetricsOverrideParams;
use chromiumoxide::cdp::browser_protocol::emulation::SetTouchEmulationEnabledParams;
use chromiumoxide::cdp::browser_protocol::emulation::SetUserAgentOverrideParams;

impl Page {
    // ── Viewport / device emulation ──────────────────────────────────────

    /// Persistently override this page's CDP viewport: dimensions, device
    /// pixel ratio, mobile/touch identity, and (if set) UA — the "set the
    /// viewport once, then click/navigate/screenshot as that device" flow.
    /// Stays in effect until [`Page::clear_viewport`] or another call to
    /// this method; does **not** auto-restore.
    ///
    /// `device_scale_factor` drives `window.devicePixelRatio` and CSS
    /// media-query matching (`min-resolution`, etc.) correctly, so layout
    /// and JS see a real Retina/mobile device. It does **not** change the
    /// pixel dimensions of a [`Page::screenshot`] PNG, though — CDP's
    /// `Page.captureScreenshot` renders at CSS-pixel size regardless of
    /// DPR in this configuration (tried both the device-metrics `scale`
    /// field and the per-clip `scale`; neither affected raster output).
    /// For pixel-perfect high-DPI captures, request `width`/`height`
    /// already multiplied by the density you want.
    ///
    /// For a one-off override scoped to a single capture, pass
    /// [`ScreenshotOptions::viewport`] to [`Page::screenshot`] instead —
    /// that snapshots and restores whatever was here before, so it can't
    /// leak a device identity into a later capture.
    pub async fn set_viewport(&self, viewport: Viewport) -> Result<()> {
        let metrics = SetDeviceMetricsOverrideParams::builder()
            .width(i64::from(viewport.width))
            .height(i64::from(viewport.height))
            .device_scale_factor(viewport.device_scale_factor)
            .mobile(viewport.mobile)
            .screen_width(i64::from(viewport.width))
            .screen_height(i64::from(viewport.height))
            .position_x(0_i64)
            .position_y(0_i64)
            .build()
            .map_err(VoidCrawlError::PageError)?;
        self.inner
            .execute(metrics)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        self.inner
            .execute(SetTouchEmulationEnabledParams::new(viewport.has_touch))
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        if let Some(ua) = viewport.user_agent.clone() {
            let (nav_platform, metadata) = if viewport.mobile {
                mobile_ua_platform_and_metadata(&ua)
            } else {
                client_hints_for_ua(&ua)
            };
            let mut builder = SetUserAgentOverrideParams::builder()
                .user_agent(ua)
                .platform(nav_platform);
            if let Some(metadata) = metadata {
                builder = builder.user_agent_metadata(metadata);
            }
            let params = builder.build().map_err(VoidCrawlError::PageError)?;
            self.inner
                .execute(params)
                .await
                .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        }
        *self
            .viewport_override
            .lock()
            .map_err(|_| VoidCrawlError::Other("viewport lock poisoned".into()))? = Some(viewport);
        // The device-metrics change doesn't always reflect in
        // `window.innerWidth`/media queries synchronously once the CDP
        // response returns — settle it before returning.
        self.wait_for_repaint().await
    }

    /// Clear a [`Page::set_viewport`] override, returning to the session's
    /// launch-time default viewport. Does not restore a prior UA override
    /// — call `set_viewport` again with the desired identity if you need
    /// one back.
    pub async fn clear_viewport(&self) -> Result<()> {
        self.inner
            .execute(ClearDeviceMetricsOverrideParams {})
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        self.inner
            .execute(SetTouchEmulationEnabledParams::new(false))
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        *self
            .viewport_override
            .lock()
            .map_err(|_| VoidCrawlError::Other("viewport lock poisoned".into()))? = None;
        self.wait_for_repaint().await
    }

    /// The viewport override currently in effect via [`Page::set_viewport`],
    /// or `None` if using the session's launch-time default.
    pub fn current_viewport(&self) -> Option<Viewport> {
        self.viewport_override
            .lock()
            .ok()
            .and_then(|guard| guard.clone())
    }
}
