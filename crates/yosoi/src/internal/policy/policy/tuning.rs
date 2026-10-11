use serde::{Deserialize, Serialize};

/// An operation's requested execution tuning.
///
/// The only current mode preserves the installed package's existing execution
/// behavior. Future modes may trade CPU time, latency, and retained memory
/// without changing result semantics or the existing resource limits.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Tuning {
    mode: TuningMode,
}

impl Tuning {
    /// Returns the selected execution mode.
    pub const fn mode(self) -> TuningMode {
        self.mode
    }

    /// Whether this value preserves the current package's default behavior.
    pub const fn is_default(&self) -> bool {
        matches!(self.mode, TuningMode::Default)
    }
}

/// Public tuning modes. More modes require measured execution behavior.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum TuningMode {
    /// Keep the installed package's current execution choices.
    #[default]
    Default,
}
