use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use std::collections::{BTreeMap, HashSet};
use thiserror::Error;

use crate::internal::documents::{DocumentClass, DocumentId, OutputId, RegionId, ResourceLimit};

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
    /// Owned decoded text emitted by a text projection.
    Text(String),
    /// Text accompanied by named regular-expression capture values.
    TextWithCaptures {
        /// Full projected text, independent of the captured subexpressions.
        text: String,
        /// Capture names mapped to their owned matched text.
        captures: BTreeMap<String, String>,
    },
    /// One projected attribute name and its decoded value.
    Attribute {
        /// Name of the attribute selected by the projection.
        name: String,
        /// Owned decoded attribute value.
        value: String,
    },
    /// An owned JSON value, preserving its native JSON shape.
    Json(serde_json::Value),
    /// A document-bound native node reference rather than a copy of its contents.
    Node(NodeReference),
}

/// Evidence certainty inherited by a finding or indeterminate outcome.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum Completeness {
    /// The available evidence supports a complete result for the requested scope.
    Complete,
    /// Some evidence is known to be missing; absence claims require qualification.
    Partial {
        /// Structural explanation of the evidence loss, without document excerpts.
        reason_code: String,
        /// Number of omitted items when known; `None` means loss was not quantified.
        lost_items: Option<u64>,
    },
    /// Evidence completeness could not be established for the requested scope.
    Unknown {
        /// Structural explanation of why completeness cannot be determined.
        reason_code: String,
    },
}

/// Evidence states which cannot support a complete absence claim.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum IncompleteEvidence {
    /// Evidence is known to omit some items and cannot establish complete absence.
    Partial {
        /// Structural explanation of the evidence loss.
        reason_code: String,
        /// Number of omitted items if quantified; `None` does not mean zero loss.
        lost_items: Option<u64>,
    },
    /// Evidence coverage is unknown and cannot establish complete absence.
    Unknown {
        /// Structural explanation of the unresolved coverage.
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
    /// Creates owned lineage metadata for a repeated-region match.
    ///
    /// The caller supplies the region identity, ordinal, and native coordinate;
    /// this constructor does not verify them against a document or locate plan.
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

    /// Borrows the authored repeated-region identity associated with the finding.
    pub const fn region_id(&self) -> &RegionId {
        &self.region_id
    }
    /// Returns the stored repeated-region ordinal without renumbering it.
    pub const fn region_ordinal(&self) -> u64 {
        self.region_ordinal
    }
    /// Borrows the native location of the parent region in its document.
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

/// Inconsistency between a finding's native coordinate and its projected node reference.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum FindingError {
    /// A node projection identifies a document other than the finding's document.
    #[error("projected node reference belongs to a different document")]
    ProjectedNodeDocumentMismatch,
    /// A node projection identifies a native coordinate other than the finding's coordinate.
    #[error("projected node reference names a different native coordinate")]
    ProjectedNodeCoordinateMismatch,
}

impl Finding {
    /// Creates an owned finding after checking projected node-reference identity.
    ///
    /// `document_id`, `output_id`, and `order` label the finding; `coordinate`
    /// locates its evidence, and `parent_region` records optional repeated-region
    /// lineage. `completeness` is the supplied evidence claim, not independently
    /// verified by this constructor. For node projections, returns
    /// [`FindingError`] if the projected document or coordinate disagrees.
    /// Other projected values are accepted without document I/O.
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

    /// Borrows the document identity to which this finding's evidence belongs.
    pub const fn document_id(&self) -> &DocumentId {
        &self.document_id
    }
    /// Borrows the authored output identity that produced this finding.
    pub const fn output_id(&self) -> &OutputId {
        &self.output_id
    }
    /// Returns deterministic global finding order; a result requires strictly increasing values.
    pub const fn order(&self) -> u64 {
        self.order
    }
    /// Borrows the native evidence location, without copying document contents.
    pub const fn coordinate(&self) -> &NativeCoordinate {
        &self.coordinate
    }
    /// Borrows the owned projection value retained by this finding.
    pub const fn value(&self) -> &ProjectedValue {
        &self.value
    }
    /// Borrows the evidence coverage claim; matches can still have partial evidence.
    pub const fn completeness(&self) -> &Completeness {
        &self.completeness
    }
    /// Borrows repeated-region lineage, or `None` for a finding without a parent region.
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

/// Structural validation failure while assembling ordered findings and matched regions.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum LocateResultError {
    /// Neither a matched region nor a finding was supplied.
    #[error("matched outcome must contain at least one region or finding")]
    Empty,
    /// At least one finding belongs to a different document than the result.
    #[error("all findings must belong to the outcome document")]
    DocumentMismatch,
    /// Finding order values are repeated or decreasing rather than strictly increasing.
    #[error("finding order must be strictly increasing")]
    NonDeterministicOrder,
    /// The supplied matched-region set repeats the same lineage value.
    #[error("matched region lineage is duplicated")]
    DuplicateRegion,
    /// A finding refers to parent lineage missing from the supplied matched-region set.
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
    /// Creates a result and derives its unique region set from finding lineage.
    ///
    /// Owns the supplied findings and checks that they are nonempty, belong to
    /// `document_id`, and have strictly increasing order. Returns
    /// [`LocateResultError`] for invalid structure. Use
    /// [`Self::try_new_with_regions`] to retain matched regions with no findings.
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

    /// Creates a result with explicit owned matched regions and findings.
    ///
    /// At least one collection must be nonempty. Region lineage must be unique;
    /// findings must belong to `document_id`, have strictly increasing order,
    /// and refer only to parent lineage present in `regions`. Returns
    /// [`LocateResultError`] for violations. This validates structure, not the
    /// truth of completeness claims or coordinates against a live document.
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

    /// Borrows the shared identity checked against every retained finding.
    pub const fn document_id(&self) -> &DocumentId {
        &self.document_id
    }
    /// Borrows matched regions, including those that emitted no projected findings.
    pub fn regions(&self) -> &[RegionLineage] {
        &self.regions
    }
    /// Borrows retained findings in strictly increasing global order.
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
    /// The authored locate plan could not be accepted for execution.
    InvalidPlan {
        /// Bounded structural error identifier, without hostile document text.
        code: String,
    },
    /// Document parsing failed before usable locator evidence could be produced.
    ParseFailed {
        /// Bounded parser error identifier, without document excerpts.
        code: String,
    },
    /// The plan requires capabilities unavailable for the supplied document class.
    UnsupportedCombination {
        /// Class of the document for which the combination is unsupported.
        document: DocumentClass,
    },
    /// Execution exceeded a configured resource budget.
    LimitExhausted {
        /// Resource whose configured maximum was exhausted.
        limit: ResourceLimit,
        /// Configured maximum in the units of the named resource.
        maximum: u64,
        /// Recorded consumption or attempted consumption in those same units.
        observed: u64,
    },
    /// A configured budget cannot be used for locator execution.
    InvalidResourcePolicy {
        /// Resource whose configured policy was rejected.
        limit: ResourceLimit,
    },
}

/// Complete no-match, indeterminate absence, matches, and failures are never
/// collapsed into one empty collection.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum LocateOutcome {
    /// At least one region or finding matched; inspect individual evidence completeness.
    Matched {
        /// Owned nonempty matched-region or finding collection in deterministic order.
        result: LocateResult,
    },
    /// Complete execution found no matches within the requested scope.
    NoMatch {
        /// Identity of the document whose complete evidence supports this absence claim.
        document_id: DocumentId,
    },
    /// No matches were established, but incomplete evidence prevents a complete absence claim.
    Indeterminate {
        /// Identity of the document examined without establishing complete absence.
        document_id: DocumentId,
        /// Partial or unknown evidence coverage that limits the claim.
        completeness: IncompleteEvidence,
        /// Structural explanation of the indeterminate outcome.
        reason_code: String,
    },
    /// Execution ended with a typed terminal failure instead of a match or absence claim.
    Failed {
        /// Bounded structural failure details, without document excerpts.
        failure: LocateFailure,
    },
}
