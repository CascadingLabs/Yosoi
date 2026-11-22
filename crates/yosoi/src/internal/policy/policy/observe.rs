use serde::{Deserialize, Serialize};
use std::time::{Duration, Instant};

use crate::internal::policy::{PolicyError, policy::AddressableByteLimit};

/// Maximum recording output duration in milliseconds (24 hours).
pub const MAX_RECORDING_DURATION_MS: u64 = 86_400_000;

/// How an observation failure affects later operations in the same session.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceFailurePolicy {
    /// Continue after the current action settles and retain an explicit evidence gap.
    #[default]
    Continue,
    /// Settle the current action, then prevent later effectful operations from starting.
    Require,
}

/// The browser surface captured by an automatic screenshot rule.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ScreenshotScope {
    /// Capture the action's resolved target when it has one.
    Target,
    /// Capture the browser viewport instead of resolving a target.
    Viewport,
}

/// Automatic screenshot events configured for a Session's actions.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ScreenshotPolicy {
    /// Scope to capture before dispatch; `None` disables this phase.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub before: Option<ScreenshotScope>,
    /// Scope to capture after the action settles; `None` disables this phase.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub after: Option<ScreenshotScope>,
    /// Scope to capture when the action settles with a failure; `None` disables this phase.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub failure: Option<ScreenshotScope>,
}

/// Which native browser surface supplies a recording rule.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RecordingMode {
    /// Record the visible browser surface as one output.
    #[default]
    BrowserVisible,
    /// Record each selected tab as an independent output.
    EachTab,
}

/// One independently bounded recording output rule.
///
/// Rules are additive. Multiple rules may select the same mode with different
/// byte, duration, or audio settings; `ObserveLimits::max_recordings` bounds
/// the total number of outputs that the consumer may open.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RecordingRule {
    /// Native browser surface used to create outputs for this rule.
    #[serde(default)]
    pub mode: RecordingMode,
    /// Maximum bytes retained for each output produced by this rule.
    #[serde(default = "default_recording_bytes")]
    pub max_bytes: AddressableByteLimit,
    /// Maximum output duration for this rule, in milliseconds.
    #[serde(default = "default_recording_duration_ms")]
    pub max_duration_ms: u64,
    /// Include tab audio when the mode supports an explicit audio track.
    ///
    /// Audio is available only for `EachTab` rules and defaults to disabled.
    #[serde(default)]
    pub include_audio: bool,
}

impl Default for RecordingRule {
    fn default() -> Self {
        Self {
            mode: RecordingMode::default(),
            max_bytes: default_recording_bytes(),
            max_duration_ms: default_recording_duration_ms(),
            include_audio: false,
        }
    }
}

impl RecordingRule {
    fn validate(&self) -> Result<(), PolicyError> {
        self.max_bytes.as_usize()?;
        validate_recording_duration(self.max_duration_ms)?;
        if self.mode == RecordingMode::BrowserVisible && self.include_audio {
            return Err(PolicyError::BrowserVisibleAudioUnsupported);
        }
        Ok(())
    }
}

/// Aggregate limits for native observation sources, outputs, and buffering.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ObserveLimits {
    /// Maximum number of native capture feeds active at once.
    #[serde(default = "default_max_sources")]
    pub max_sources: u32,
    /// Maximum number of independently stoppable recording outputs.
    #[serde(default = "default_max_recordings")]
    pub max_recordings: u32,
    /// Maximum bytes held in flight across native capture buffers.
    #[serde(default = "default_buffer_bytes")]
    pub max_buffer_bytes: AddressableByteLimit,
    /// Maximum image and other evidence bytes retained for the Session lifetime.
    #[serde(default = "default_retained_bytes")]
    pub max_retained_bytes: AddressableByteLimit,
}

impl Default for ObserveLimits {
    fn default() -> Self {
        Self {
            max_sources: default_max_sources(),
            max_recordings: default_max_recordings(),
            max_buffer_bytes: default_buffer_bytes(),
            max_retained_bytes: default_retained_bytes(),
        }
    }
}

impl ObserveLimits {
    fn validate(&self, configured_recordings: usize) -> Result<(), PolicyError> {
        if self.max_sources == 0 {
            return Err(PolicyError::ZeroObservationSourceLimit);
        }
        if self.max_recordings == 0 {
            return Err(PolicyError::ZeroObservationRecordingLimit);
        }
        self.max_buffer_bytes.as_usize()?;
        self.max_retained_bytes.as_usize()?;
        let configured_recordings = u32::try_from(configured_recordings)
            .map_err(|_| PolicyError::TooManyObservationRecordingRules)?;
        if configured_recordings > self.max_recordings {
            return Err(PolicyError::ObservationRulesExceedRecordingLimit {
                configured: configured_recordings,
                maximum: self.max_recordings,
            });
        }
        Ok(())
    }
}

/// Policy for optional automatic evidence and explicit recording capability.
///
/// The default disables automatic observation, recording rules, and tab-audio
/// capture. Existing explicit Work screenshot actions remain independent of
/// this switch. `native_tab_capture` is a separate opt-in consumed during
/// Session acquisition; setting it alone does not enable automatic capture.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize, Default)]
#[serde(deny_unknown_fields)]
pub struct ObservePolicy {
    /// Enable configured automatic screenshots and recording rules.
    #[serde(default)]
    pub enabled: bool,
    /// Explicitly allow the browser to capture its own tabs for recordings.
    #[serde(default)]
    pub native_tab_capture: bool,
    /// Automatic screenshot events and their target/viewport scope.
    #[serde(default)]
    pub screenshots: ScreenshotPolicy,
    /// Additive recording output rules; each rule has its own byte and duration bounds.
    #[serde(default)]
    pub recordings: Vec<RecordingRule>,
    /// Whether evidence failures leave a gap or gate later effectful operations.
    #[serde(default)]
    pub failure: EvidenceFailurePolicy,
    /// Aggregate native source, output, and in-flight buffer limits.
    #[serde(default)]
    pub limits: ObserveLimits,
}

impl ObservePolicy {
    /// Returns whether this policy uses the default disabled observation settings.
    pub(in crate::internal::policy) fn is_default(&self) -> bool {
        self == &Self::default()
    }

    pub(in crate::internal::policy) fn validate(&self) -> Result<(), PolicyError> {
        self.limits.validate(self.recordings.len())?;
        for rule in &self.recordings {
            rule.validate()?;
            if rule.mode == RecordingMode::EachTab && !self.native_tab_capture {
                return Err(PolicyError::NativeTabCaptureNotPermitted);
            }
        }
        Ok(())
    }
}

const fn default_max_sources() -> u32 {
    33
}

const fn default_max_recordings() -> u32 {
    5
}

const fn default_buffer_bytes() -> AddressableByteLimit {
    AddressableByteLimit::default_browser_bytes()
}

const fn default_retained_bytes() -> AddressableByteLimit {
    AddressableByteLimit::default_observation_recording_bytes()
}

const fn default_recording_bytes() -> AddressableByteLimit {
    AddressableByteLimit::default_observation_recording_bytes()
}

const fn default_recording_duration_ms() -> u64 {
    60_000
}

fn validate_recording_duration(value: u64) -> Result<(), PolicyError> {
    if value == 0
        || value > MAX_RECORDING_DURATION_MS
        || Instant::now()
            .checked_add(Duration::from_millis(value))
            .is_none()
    {
        return Err(PolicyError::InvalidObservationRecordingDuration);
    }
    Ok(())
}
