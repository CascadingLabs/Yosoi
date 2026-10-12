use serde::{Deserialize, Serialize};

use super::{AddressableByteLimit, CountLimit, StepLimit};

/// Parser-owned bounds shared by immutable document representations.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Documents {
    /// Positive addressable byte limit for retained document parsing input.
    pub max_input_bytes: AddressableByteLimit,
    /// Positive maximum parsed document nodes.
    pub max_nodes: CountLimit,
    /// Positive maximum document parse or traversal depth.
    pub max_depth: StepLimit,
}

impl Default for Documents {
    fn default() -> Self {
        Self {
            max_input_bytes: AddressableByteLimit::default_document_input(),
            max_nodes: CountLimit::validated(1_000_000),
            max_depth: StepLimit::validated(1_024),
        }
    }
}
