use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use std::collections::{BTreeMap, HashSet};
use thiserror::Error;

use crate::{DocumentClass, DocumentId, OutputId, RegionId, ResourceLimit};

#[path = "outcome_coordinates.rs"]
mod coordinates;
#[path = "outcome_native_coordinates.rs"]
mod native_coordinates;
#[path = "outcome_tree_coordinates.rs"]
mod tree_coordinates;

pub use coordinates::{ByteRange, CoordinateError, DecodedTextCoordinate, TextRange};
pub use native_coordinates::{
    AccessibilityCoordinate, DomCoordinate, DomNodeId, JsonCoordinate, NativeCoordinate,
    NodeReference,
};
pub use tree_coordinates::{ExpandedNamePathSegment, TreeCoordinate};

/// Owned value emitted by one projection.
#[derive(Clone, Debug, Deserialize, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum ProjectedValue {
    Text(String),
    TextWithCaptures {
        text: String,
        captures: BTreeMap<String, String>,
    },
    Attribute {
        name: String,
        value: String,
    },
    Json(serde_json::Value),
    Node(NodeReference),
}

/// Evidence certainty inherited by a finding or indeterminate outcome.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum Completeness {
    Complete,
    Partial {
        reason_code: String,
        lost_items: Option<u64>,
    },
    Unknown {
        reason_code: String,
    },
}

/// Evidence states which cannot support a complete absence claim.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum IncompleteEvidence {
    Partial {
        reason_code: String,
        lost_items: Option<u64>,
    },
    Unknown {
        reason_code: String,
    },
}

/// Parent repeated-region identity and coordinate for one finding.
#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RegionLineage {
    region_id: RegionId,
    region_ordinal: u64,
    coordinate: NativeCoordinate,
}

impl RegionLineage {
    pub const fn new(
        region_id: RegionId,
        region_ordinal: u64,
        coordinate: NativeCoordinate,
    ) -> Self {
        Self {
            region_id,
            region_ordinal,
            coordinate,
        }
    }

    pub const fn region_id(&self) -> &RegionId {
        &self.region_id
    }
    pub const fn region_ordinal(&self) -> u64 {
        self.region_ordinal
    }
    pub const fn coordinate(&self) -> &NativeCoordinate {
        &self.coordinate
    }
}

/// One deterministic, ordered locator finding.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Finding {
    document_id: DocumentId,
    output_id: OutputId,
    order: u64,
    coordinate: NativeCoordinate,
    value: ProjectedValue,
    completeness: Completeness,
    parent_region: Option<RegionLineage>,
}

#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum FindingError {
    #[error("projected node reference belongs to a different document")]
    ProjectedNodeDocumentMismatch,
    #[error("projected node reference names a different native coordinate")]
    ProjectedNodeCoordinateMismatch,
}

impl Finding {
    pub fn try_new(
        document_id: DocumentId,
        output_id: OutputId,
        order: u64,
        coordinate: NativeCoordinate,
        value: ProjectedValue,
        completeness: Completeness,
        parent_region: Option<RegionLineage>,
    ) -> Result<Self, FindingError> {
        if let ProjectedValue::Node(reference) = &value {
            if reference.document_id() != &document_id {
                return Err(FindingError::ProjectedNodeDocumentMismatch);
            }
            if reference.coordinate() != &coordinate {
                return Err(FindingError::ProjectedNodeCoordinateMismatch);
            }
        }
        Ok(Self {
            document_id,
            output_id,
            order,
            coordinate,
            value,
            completeness,
            parent_region,
        })
    }

    pub const fn document_id(&self) -> &DocumentId {
        &self.document_id
    }
    pub const fn output_id(&self) -> &OutputId {
        &self.output_id
    }
    pub const fn order(&self) -> u64 {
        self.order
    }
    pub const fn coordinate(&self) -> &NativeCoordinate {
        &self.coordinate
    }
    pub const fn value(&self) -> &ProjectedValue {
        &self.value
    }
    pub const fn completeness(&self) -> &Completeness {
        &self.completeness
    }
    pub const fn parent_region(&self) -> Option<&RegionLineage> {
        self.parent_region.as_ref()
    }
}

impl<'de> Deserialize<'de> for Finding {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct WireFinding {
            document_id: DocumentId,
            output_id: OutputId,
            order: u64,
            coordinate: NativeCoordinate,
            value: ProjectedValue,
            completeness: Completeness,
            parent_region: Option<RegionLineage>,
        }

        let wire = WireFinding::deserialize(deserializer)?;
        Self::try_new(
            wire.document_id,
            wire.output_id,
            wire.order,
            wire.coordinate,
            wire.value,
            wire.completeness,
            wire.parent_region,
        )
        .map_err(D::Error::custom)
    }
}

#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum LocateResultError {
    #[error("matched outcome must contain at least one region or finding")]
    Empty,
    #[error("all findings must belong to the outcome document")]
    DocumentMismatch,
    #[error("finding order must be strictly increasing")]
    NonDeterministicOrder,
    #[error("matched region lineage is duplicated")]
    DuplicateRegion,
    #[error("finding names a parent region absent from the matched region set")]
    UnknownParentRegion,
}

/// Non-empty matched regions or findings in deterministic global order.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LocateResult {
    document_id: DocumentId,
    regions: Vec<RegionLineage>,
    findings: Vec<Finding>,
}

impl LocateResult {
    pub fn try_new(
        document_id: DocumentId,
        findings: Vec<Finding>,
    ) -> Result<Self, LocateResultError> {
        let mut seen = HashSet::new();
        let mut regions = Vec::new();
        for region in findings.iter().filter_map(Finding::parent_region) {
            if seen.insert(region.clone()) {
                regions.push(region.clone());
            }
        }
        Self::try_new_with_regions(document_id, regions, findings)
    }

    pub fn try_new_with_regions(
        document_id: DocumentId,
        regions: Vec<RegionLineage>,
        findings: Vec<Finding>,
    ) -> Result<Self, LocateResultError> {
        if regions.is_empty() && findings.is_empty() {
            return Err(LocateResultError::Empty);
        }
        let mut known_regions = HashSet::new();
        for region in &regions {
            if !known_regions.insert(region.clone()) {
                return Err(LocateResultError::DuplicateRegion);
            }
        }
        let mut previous = None;
        for finding in &findings {
            if finding.document_id() != &document_id {
                return Err(LocateResultError::DocumentMismatch);
            }
            if previous.is_some_and(|order| finding.order() <= order) {
                return Err(LocateResultError::NonDeterministicOrder);
            }
            if finding
                .parent_region()
                .is_some_and(|region| !known_regions.contains(region))
            {
                return Err(LocateResultError::UnknownParentRegion);
            }
            previous = Some(finding.order());
        }
        Ok(Self {
            document_id,
            regions,
            findings,
        })
    }

    pub const fn document_id(&self) -> &DocumentId {
        &self.document_id
    }
    pub fn regions(&self) -> &[RegionLineage] {
        &self.regions
    }
    pub fn findings(&self) -> &[Finding] {
        &self.findings
    }
}

impl<'de> Deserialize<'de> for LocateResult {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct WireResult {
            document_id: DocumentId,
            #[serde(default)]
            regions: Vec<RegionLineage>,
            findings: Vec<Finding>,
        }

        let wire = WireResult::deserialize(deserializer)?;
        if wire.regions.is_empty() {
            Self::try_new(wire.document_id, wire.findings).map_err(D::Error::custom)
        } else {
            Self::try_new_with_regions(wire.document_id, wire.regions, wire.findings)
                .map_err(D::Error::custom)
        }
    }
}

/// Typed terminal failures. Error codes are bounded structural identifiers,
/// never excerpts from hostile document payloads.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum LocateFailure {
    InvalidPlan {
        code: String,
    },
    ParseFailed {
        code: String,
    },
    UnsupportedCombination {
        document: DocumentClass,
    },
    LimitExhausted {
        limit: ResourceLimit,
        maximum: u64,
        observed: u64,
    },
    InvalidResourcePolicy {
        limit: ResourceLimit,
    },
}

/// Complete no-match, indeterminate absence, matches, and failures are never
/// collapsed into one empty collection.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum LocateOutcome {
    Matched {
        result: LocateResult,
    },
    NoMatch {
        document_id: DocumentId,
    },
    Indeterminate {
        document_id: DocumentId,
        completeness: IncompleteEvidence,
        reason_code: String,
    },
    Failed {
        failure: LocateFailure,
    },
}
