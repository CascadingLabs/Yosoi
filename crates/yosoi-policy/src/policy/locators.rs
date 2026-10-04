use serde::{Deserialize, Serialize};

use super::{AddressableByteLimit, CountLimit, StepLimit};

/// Plan and evaluation bounds; query meaning remains document-owned.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Locators {
    pub max_selector_visits: CountLimit,
    pub max_query_bytes: AddressableByteLimit,
    pub max_query_steps: StepLimit,
    pub max_regions: StepLimit,
    pub max_matches: CountLimit,
    pub max_captures: CountLimit,
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
