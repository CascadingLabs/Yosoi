use std::num::{NonZeroU32, NonZeroU64};

use serde::{Deserialize, Serialize};
use thiserror::Error;

/// Values used to construct a checked document and locator resource budget.
///
/// Fixed-width integers keep this public contract independent of process
/// address width and suitable for a future Python boundary.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ResourceBudgetValues {
    pub max_input_bytes: u64,
    pub max_nodes: u64,
    /// Shared candidate, matcher-state, and tree-text visit budget per evaluation.
    pub max_selector_visits: u64,
    pub max_query_bytes: u64,
    pub max_query_steps: u32,
    pub max_regions: u32,
    pub max_matches: u64,
    pub max_captures: u64,
    pub max_depth: u32,
    pub max_output_bytes: u64,
}

/// Which checked resource budget stopped parsing or locating.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ResourceLimit {
    InputBytes,
    Nodes,
    SelectorVisits,
    QueryBytes,
    QuerySteps,
    Regions,
    Matches,
    Captures,
    Depth,
    OutputBytes,
}

/// A resource budget value must be positive.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
#[error("{limit:?} limit must be greater than zero")]
pub struct ResourceBudgetError {
    pub limit: ResourceLimit,
}

/// Mandatory positive budgets for one parse or locate operation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[allow(clippy::struct_field_names)] // The max_ prefix is the public budget vocabulary.
pub struct ResourceBudget {
    max_input_bytes: NonZeroU64,
    max_nodes: NonZeroU64,
    max_selector_visits: NonZeroU64,
    max_query_bytes: NonZeroU64,
    max_query_steps: NonZeroU32,
    max_regions: NonZeroU32,
    max_matches: NonZeroU64,
    max_captures: NonZeroU64,
    max_depth: NonZeroU32,
    max_output_bytes: NonZeroU64,
}

impl ResourceBudget {
    /// Conservative defaults, including a bound on materialized regex captures.
    pub const fn conservative() -> Self {
        Self {
            max_input_bytes: nonzero_u64(67_108_864),
            max_nodes: nonzero_u64(1_000_000),
            max_selector_visits: nonzero_u64(10_000_000),
            max_query_bytes: nonzero_u64(65_536),
            max_query_steps: nonzero_u32(256),
            max_regions: nonzero_u32(64),
            max_matches: nonzero_u64(100_000),
            max_captures: nonzero_u64(16_384),
            max_depth: nonzero_u32(1_024),
            max_output_bytes: nonzero_u64(16_777_216),
        }
    }

    pub const fn max_input_bytes(self) -> u64 {
        self.max_input_bytes.get()
    }
    pub const fn max_nodes(self) -> u64 {
        self.max_nodes.get()
    }
    pub const fn max_selector_visits(self) -> u64 {
        self.max_selector_visits.get()
    }
    pub const fn max_query_bytes(self) -> u64 {
        self.max_query_bytes.get()
    }
    pub const fn max_query_steps(self) -> u32 {
        self.max_query_steps.get()
    }
    pub const fn max_regions(self) -> u32 {
        self.max_regions.get()
    }
    pub const fn max_matches(self) -> u64 {
        self.max_matches.get()
    }
    pub const fn max_captures(self) -> u64 {
        self.max_captures.get()
    }
    pub const fn max_depth(self) -> u32 {
        self.max_depth.get()
    }
    pub const fn max_output_bytes(self) -> u64 {
        self.max_output_bytes.get()
    }
}

impl Default for ResourceBudget {
    fn default() -> Self {
        Self::conservative()
    }
}

impl TryFrom<ResourceBudgetValues> for ResourceBudget {
    type Error = ResourceBudgetError;

    fn try_from(values: ResourceBudgetValues) -> Result<Self, Self::Error> {
        Ok(Self {
            max_input_bytes: positive_u64(values.max_input_bytes, ResourceLimit::InputBytes)?,
            max_nodes: positive_u64(values.max_nodes, ResourceLimit::Nodes)?,
            max_selector_visits: positive_u64(
                values.max_selector_visits,
                ResourceLimit::SelectorVisits,
            )?,
            max_query_bytes: positive_u64(values.max_query_bytes, ResourceLimit::QueryBytes)?,
            max_query_steps: positive_u32(values.max_query_steps, ResourceLimit::QuerySteps)?,
            max_regions: positive_u32(values.max_regions, ResourceLimit::Regions)?,
            max_matches: positive_u64(values.max_matches, ResourceLimit::Matches)?,
            max_captures: positive_u64(values.max_captures, ResourceLimit::Captures)?,
            max_depth: positive_u32(values.max_depth, ResourceLimit::Depth)?,
            max_output_bytes: positive_u64(values.max_output_bytes, ResourceLimit::OutputBytes)?,
        })
    }
}

impl ResourceBudget {
    pub fn try_new(values: ResourceBudgetValues) -> Result<Self, ResourceBudgetError> {
        Self::try_from(values)
    }
}

fn positive_u64(value: u64, limit: ResourceLimit) -> Result<NonZeroU64, ResourceBudgetError> {
    NonZeroU64::new(value).ok_or(ResourceBudgetError { limit })
}

fn positive_u32(value: u32, limit: ResourceLimit) -> Result<NonZeroU32, ResourceBudgetError> {
    NonZeroU32::new(value).ok_or(ResourceBudgetError { limit })
}

const fn nonzero_u64(value: u64) -> NonZeroU64 {
    match NonZeroU64::new(value) {
        Some(value) => value,
        None => NonZeroU64::MIN,
    }
}

const fn nonzero_u32(value: u32) -> NonZeroU32 {
    match NonZeroU32::new(value) {
        Some(value) => value,
        None => NonZeroU32::MIN,
    }
}
