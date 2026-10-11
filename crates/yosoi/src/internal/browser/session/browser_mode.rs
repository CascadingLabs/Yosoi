use crate::internal::types as yosoi_types;

use crate::internal::browser::environment::{EnvironmentObservation, EnvironmentUnavailableReason};

use super::BrowserMode;

pub(super) const fn browser_mode_observation(
    mode: &BrowserMode,
) -> EnvironmentObservation<yosoi_types::BrowserMode> {
    match mode {
        BrowserMode::Headless => EnvironmentObservation::Known {
            value: yosoi_types::BrowserMode::Headless,
        },
        BrowserMode::Headful => EnvironmentObservation::Known {
            value: yosoi_types::BrowserMode::Headful,
        },
        BrowserMode::RemoteDebug { .. } => EnvironmentObservation::Unavailable {
            reason: EnvironmentUnavailableReason::AttachedBrowserNotControlled,
        },
    }
}
