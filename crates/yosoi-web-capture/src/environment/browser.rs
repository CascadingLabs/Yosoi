use serde::{Deserialize, Serialize};
use yosoi_types::Producer;
pub use yosoi_types::{BrowserMode, ColorScheme, ReducedMotion, Viewport};

use super::{DeviceScaleFactor, EnvironmentValue, Locale, TimeZone, UserAgent};

/// Effective environment for browser execution.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserCaptureEnvironment {
    controller: Producer,
    renderer: Producer,
    mode: EnvironmentValue<BrowserMode>,
    rendering: BrowserRenderingContext,
}

impl BrowserCaptureEnvironment {
    /// Creates a browser environment.
    pub const fn new(
        controller: Producer,
        renderer: Producer,
        mode: EnvironmentValue<BrowserMode>,
        rendering: BrowserRenderingContext,
    ) -> Self {
        Self {
            controller,
            renderer,
            mode,
            rendering,
        }
    }

    /// Returns the component that controlled browser execution.
    pub const fn controller(&self) -> &Producer {
        &self.controller
    }

    /// Returns the browser implementation that rendered content.
    pub const fn renderer(&self) -> &Producer {
        &self.renderer
    }

    /// Returns whether headless or headful mode was effective, if known.
    pub const fn mode(&self) -> &EnvironmentValue<BrowserMode> {
        &self.mode
    }

    /// Returns representation-affecting browser settings.
    pub const fn rendering(&self) -> &BrowserRenderingContext {
        &self.rendering
    }
}

/// Browser settings that can change layout, geometry, or representation.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserRenderingContext {
    viewport: EnvironmentValue<Viewport>,
    device_scale_factor: EnvironmentValue<DeviceScaleFactor>,
    user_agent: EnvironmentValue<UserAgent>,
    locale: EnvironmentValue<Locale>,
    time_zone: EnvironmentValue<TimeZone>,
    color_scheme: EnvironmentValue<ColorScheme>,
    reduced_motion: EnvironmentValue<ReducedMotion>,
}

impl BrowserRenderingContext {
    /// Creates a browser rendering context with explicit state for every fact.
    #[allow(clippy::too_many_arguments)]
    pub const fn new(
        viewport: EnvironmentValue<Viewport>,
        device_scale_factor: EnvironmentValue<DeviceScaleFactor>,
        user_agent: EnvironmentValue<UserAgent>,
        locale: EnvironmentValue<Locale>,
        time_zone: EnvironmentValue<TimeZone>,
        color_scheme: EnvironmentValue<ColorScheme>,
        reduced_motion: EnvironmentValue<ReducedMotion>,
    ) -> Self {
        Self {
            viewport,
            device_scale_factor,
            user_agent,
            locale,
            time_zone,
            color_scheme,
            reduced_motion,
        }
    }

    /// Returns viewport availability and value.
    pub const fn viewport(&self) -> &EnvironmentValue<Viewport> {
        &self.viewport
    }

    /// Returns device scale factor availability and value.
    pub const fn device_scale_factor(&self) -> &EnvironmentValue<DeviceScaleFactor> {
        &self.device_scale_factor
    }

    /// Returns effective browser user agent state.
    pub const fn user_agent(&self) -> &EnvironmentValue<UserAgent> {
        &self.user_agent
    }

    /// Returns effective browser locale state.
    pub const fn locale(&self) -> &EnvironmentValue<Locale> {
        &self.locale
    }

    /// Returns effective browser time zone state.
    pub const fn time_zone(&self) -> &EnvironmentValue<TimeZone> {
        &self.time_zone
    }

    /// Returns effective color-scheme preference state.
    pub const fn color_scheme(&self) -> &EnvironmentValue<ColorScheme> {
        &self.color_scheme
    }

    /// Returns effective reduced-motion preference state.
    pub const fn reduced_motion(&self) -> &EnvironmentValue<ReducedMotion> {
        &self.reduced_motion
    }
}
