use crate::internal::types as yosoi_types;

use super::Page;
use crate::internal::browser::environment::RenderingPreferences;
use crate::internal::browser::error::Result;
use crate::internal::browser::error::VoidCrawlError;
use crate::internal::browser::vendor::chromiumoxide::cdp::browser_protocol::browser::PermissionDescriptor;
use crate::internal::browser::vendor::chromiumoxide::cdp::browser_protocol::browser::PermissionSetting;
use crate::internal::browser::vendor::chromiumoxide::cdp::browser_protocol::browser::SetPermissionParams;
use crate::internal::browser::vendor::chromiumoxide::cdp::browser_protocol::emulation::MediaFeature;
use crate::internal::browser::vendor::chromiumoxide::cdp::browser_protocol::emulation::SetEmulatedMediaParams;
use crate::internal::browser::vendor::chromiumoxide::cdp::browser_protocol::emulation::SetGeolocationOverrideParams;
use crate::internal::browser::vendor::chromiumoxide::cdp::browser_protocol::emulation::SetLocaleOverrideParams;
use crate::internal::browser::vendor::chromiumoxide::cdp::browser_protocol::emulation::SetTimezoneOverrideParams;

impl Page {
    // ── Emulation ───────────────────────────────────────────────────────

    /// Override the page's geolocation. Geo-aware sites (maps, "near me"
    /// search, store locators) will behave as if the browser is at these
    /// coordinates. `accuracy` defaults to 50 metres.
    ///
    /// Note: sites that read `navigator.geolocation` still gate on the
    /// geolocation *permission* (granted here) and require a secure context
    /// (https / localhost), not `data:` URLs. Header/IP-driven geo (e.g.
    /// Google Maps) keys off [`set_locale`] and the request URL more than this.
    ///
    /// [`set_locale`]: Self::set_locale
    pub async fn set_geolocation(
        &self,
        latitude: f64,
        longitude: f64,
        accuracy: Option<f64>,
    ) -> Result<()> {
        self.ensure_active().await?;
        // Grant the geolocation permission first, otherwise headless Chrome
        // auto-denies `navigator.geolocation` and the override is never read.
        // Origin omitted applies to every origin, while an isolated page's
        // retained provider identity confines the grant to its browser context.
        // Ordinary/shared pages keep the existing default-context behavior.
        let grant = SetPermissionParams {
            permission: PermissionDescriptor::new("geolocation"),
            setting: PermissionSetting::Granted,
            origin: None,
            embedded_origin: None,
            browser_context_id: self
                .provider_context
                .as_ref()
                .map(|context| context.0.clone()),
        };
        self.inner
            .execute(grant)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;

        let params = SetGeolocationOverrideParams {
            latitude: Some(latitude),
            longitude: Some(longitude),
            accuracy: Some(accuracy.unwrap_or(50.0)),
            ..Default::default()
        };
        self.inner
            .execute(params)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(())
    }

    /// Apply independently optional rendering preferences in one CDP command.
    pub async fn set_rendering_preferences(&self, preferences: RenderingPreferences) -> Result<()> {
        self.ensure_active().await?;
        if preferences.color_scheme.is_none() && preferences.reduced_motion.is_none() {
            return Ok(());
        }
        let mut tracked = self.rendering_preferences.lock().await;
        let mut candidate = *tracked;
        if preferences.color_scheme.is_some() {
            candidate.color_scheme = preferences.color_scheme;
        }
        if preferences.reduced_motion.is_some() {
            candidate.reduced_motion = preferences.reduced_motion;
        }
        let mut features = Vec::with_capacity(2);
        if let Some(preference) = candidate.color_scheme {
            let value = match preference {
                yosoi_types::ColorScheme::Light => "light",
                yosoi_types::ColorScheme::Dark => "dark",
                yosoi_types::ColorScheme::NoPreference => "no-preference",
            };
            features.push(MediaFeature::new("prefers-color-scheme", value));
        }
        if let Some(preference) = candidate.reduced_motion {
            let value = match preference {
                yosoi_types::ReducedMotion::Reduce => "reduce",
                yosoi_types::ReducedMotion::NoPreference => "no-preference",
            };
            features.push(MediaFeature::new("prefers-reduced-motion", value));
        }
        let params = SetEmulatedMediaParams::builder().features(features).build();
        self.inner
            .execute(params)
            .await
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
        *tracked = candidate;
        drop(tracked);
        Ok(())
    }

    /// Override the JS locale and `Accept-Language` (e.g. `"en-US"`,
    /// `"fr-FR"`). This is the lever that shifts region-aware content like
    /// Google Maps results or localized pricing.
    pub async fn set_locale(&self, locale: &str) -> Result<()> {
        self.ensure_active().await?;
        let params = SetLocaleOverrideParams {
            locale: Some(locale.to_string()),
        };
        self.inner
            .execute(params)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(())
    }

    /// Override the timezone by IANA id (e.g. `"America/New_York"`). Affects
    /// `Date`, `Intl`, and any server probes that read the rendered clock.
    pub async fn set_timezone(&self, timezone_id: &str) -> Result<()> {
        self.ensure_active().await?;
        let params = SetTimezoneOverrideParams::new(timezone_id.to_string());
        self.inner
            .execute(params)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        Ok(())
    }
}
