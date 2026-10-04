use super::{VoidCrawlAdapterError, conversions};
use crate as yosoi;
use void_crawl_core as provider;

pub async fn apply(
    page: &provider::Page,
    overrides: &yosoi::BrowserEnvironmentOverrides,
) -> Result<(), VoidCrawlAdapterError> {
    if overrides.viewport.is_some()
        || overrides.device_scale_factor.is_some()
        || overrides.user_agent.is_some()
    {
        let observed = page
            .environment_snapshot()
            .await
            .map_err(|error| conversions::map_provider_error(&error))?;
        let provider::EnvironmentObservation::Known {
            value: current_viewport,
        } = observed.rendering.viewport
        else {
            return Err(VoidCrawlAdapterError::InvalidEnvironment);
        };
        let provider::EnvironmentObservation::Known { value: current_dpr } =
            observed.rendering.device_scale_factor
        else {
            return Err(VoidCrawlAdapterError::InvalidEnvironment);
        };
        let provider::EnvironmentObservation::Known {
            value: current_user_agent,
        } = observed.rendering.user_agent
        else {
            return Err(VoidCrawlAdapterError::InvalidEnvironment);
        };
        let (width, height) = overrides.viewport.map_or_else(
            || {
                (
                    current_viewport.width_css_pixels().get(),
                    current_viewport.height_css_pixels().get(),
                )
            },
            |viewport| {
                (
                    viewport.width_css_pixels().get(),
                    viewport.height_css_pixels().get(),
                )
            },
        );
        let device_scale_factor = match &overrides.device_scale_factor {
            Some(value) => value
                .as_str()
                .parse::<f64>()
                .map_err(|_| VoidCrawlAdapterError::InvalidResolvedSpec)?,
            None => current_dpr,
        };
        if width == 0
            || height == 0
            || !device_scale_factor.is_finite()
            || device_scale_factor <= 0.0
        {
            return Err(VoidCrawlAdapterError::InvalidResolvedSpec);
        }
        let mut viewport = provider::Viewport::custom(width, height);
        viewport.device_scale_factor = device_scale_factor;
        viewport.mobile = false;
        viewport.has_touch = false;
        viewport.user_agent = Some(
            overrides
                .user_agent
                .as_ref()
                .map_or(current_user_agent, |value| value.as_str().to_owned()),
        );
        page.set_viewport(viewport)
            .await
            .map_err(|error| conversions::map_provider_error(&error))?;
    }
    if let Some(locale) = &overrides.locale {
        page.set_locale(locale.as_str())
            .await
            .map_err(|error| conversions::map_provider_error(&error))?;
    }
    if let Some(time_zone) = &overrides.time_zone {
        page.set_timezone(time_zone.as_str())
            .await
            .map_err(|error| conversions::map_provider_error(&error))?;
    }
    let color_scheme = overrides.color_scheme;
    let reduced_motion = overrides.reduced_motion;
    if color_scheme.is_some() || reduced_motion.is_some() {
        page.set_rendering_preferences(provider::RenderingPreferences::new(
            color_scheme,
            reduced_motion,
        ))
        .await
        .map_err(|error| conversions::map_provider_error(&error))?;
    }
    Ok(())
}
