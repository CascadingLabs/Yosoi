use serde::{Deserialize, Serialize};

use super::{AddressableByteLimit, CountLimit, StepLimit};

/// Plan and evaluation bounds; query meaning remains document-owned.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Locators {
    /// Positive maximum shared selector candidate, matcher-state, and tree-text visits.
    pub max_selector_visits: CountLimit,
    /// Positive addressable bytes for query and namespace metadata.
    pub max_query_bytes: AddressableByteLimit,
    /// Positive maximum query evaluation steps.
    pub max_query_steps: StepLimit,
    /// Positive maximum retained repeated-region matches.
    pub max_regions: StepLimit,
    /// Positive maximum retained finding matches.
    pub max_matches: CountLimit,
    /// Positive maximum materialized regex capture values.
    pub max_captures: CountLimit,
    /// Positive addressable bytes retained for projected values and output evidence.
    pub max_output_bytes: AddressableByteLimit,
}

impl Default for Locators {
    fn default() -> Self {
        Self {
            max_selector_visits: CountLimit::validated(10_000_000),
            max_query_bytes: AddressableByteLimit::default_locator_query(),
            max_query_steps: StepLimit::validated(256),
            max_regions: StepLimit::validated(64),
            max_matches: CountLimit::validated(100_000),
            max_captures: CountLimit::validated(16_384),
            max_output_bytes: AddressableByteLimit::default_locator_output(),
        }
    }
}
