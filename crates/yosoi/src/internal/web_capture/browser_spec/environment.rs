use crate::internal::web_capture::{
    BrowserMode, ColorScheme, DeviceScaleFactor, Locale, ReducedMotion, TimeZone, UserAgent,
    Viewport,
};
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FreshBrowserIsolation {
    FreshIsolatedContext,
}
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct BrowserEnvironmentOverrides {
    pub viewport: Option<Viewport>,
    pub device_scale_factor: Option<DeviceScaleFactor>,
    pub user_agent: Option<UserAgent>,
    pub locale: Option<Locale>,
    pub time_zone: Option<TimeZone>,
    pub color_scheme: Option<ColorScheme>,
    pub reduced_motion: Option<ReducedMotion>,
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BrowserAttemptEnvironment {
    mode: BrowserMode,
    isolation: FreshBrowserIsolation,
    overrides: BrowserEnvironmentOverrides,
}
impl BrowserAttemptEnvironment {
    pub fn new(mode: BrowserMode) -> Self {
        Self::with_overrides(mode, BrowserEnvironmentOverrides::default())
    }
    pub const fn with_overrides(mode: BrowserMode, overrides: BrowserEnvironmentOverrides) -> Self {
        Self {
            mode,
            isolation: FreshBrowserIsolation::FreshIsolatedContext,
            overrides,
        }
    }
    pub const fn mode(&self) -> BrowserMode {
        self.mode
    }
    pub const fn isolation(&self) -> FreshBrowserIsolation {
        self.isolation
    }
    pub const fn overrides(&self) -> &BrowserEnvironmentOverrides {
        &self.overrides
    }
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NavigationCompletionPolicy {
    DomContentLoaded,
    LoadEvent,
    NetworkIdle,
    ControllerCompleted,
}
/// Navigation has no independent deadline. Every phase uses the observation deadline.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BrowserNavigationPolicy {
    completion: NavigationCompletionPolicy,
}
impl BrowserNavigationPolicy {
    pub const fn new(completion: NavigationCompletionPolicy) -> Self {
        Self { completion }
    }
    pub const fn completion(self) -> NavigationCompletionPolicy {
        self.completion
    }
}
