use std::{fmt, sync::OnceLock};

use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use thiserror::Error;

use crate::internal::documents::decoded_text::CompiledTextRegex;
use crate::internal::documents::html::{
    CompiledTreePlan, compile_tree_plan, validate_tree_plan_budget,
};
use crate::internal::documents::xml::{CompiledXmlPlan, XmlError};
use crate::internal::documents::{
    DocumentClass, JsonQuerySyntaxError, LocateFailure, Projection, QueryAtom, QueryError,
    QueryResultShape, QuerySpec, ResourceBudget, ResourceLimit,
};

use crate::internal::documents::plan::authoring::{
    NamedOutput, OutputId, OutputPlan, RegionId, RegionPlan,
};

/// One compiled, non-nested repeated region.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CompiledRegion {
    pub(super) id: RegionId,
    pub(super) query: QuerySpec,
}

impl CompiledRegion {
    /// Borrows the authored identity used for repeated-region lineage.
    pub const fn id(&self) -> &RegionId {
        &self.id
    }
    /// Borrows the root query used to select repeated-region evidence.
    pub const fn query(&self) -> &QuerySpec {
        &self.query
    }
}

/// One compiled named output.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CompiledOutput {
    pub(super) id: OutputId,
    pub(super) parent_region: Option<RegionId>,
    pub(super) query: QuerySpec,
    pub(super) projection: Projection,
}

impl CompiledOutput {
    /// Borrows the unique authored identity of this projected output.
    pub const fn id(&self) -> &OutputId {
        &self.id
    }
    /// Borrows the repeated parent-region identity, absent for unscoped output.
    pub const fn parent_region(&self) -> Option<&RegionId> {
        self.parent_region.as_ref()
    }
    /// Borrows the compiled query semantics before projection.
    pub const fn query(&self) -> &QuerySpec {
        &self.query
    }
    /// Borrows the supported projection determining finding value shape.
    pub const fn projection(&self) -> &Projection {
        &self.projection
    }
}

/// Capability set derived by compilation rather than declared by a document.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LocatorCapability {
    /// CSS source-tree node selection.
    Css,
    /// Supported XPath source-tree node selection.
    XPath,
    /// Literal substring selection over tree descendant text.
    TreeTextContains,
    /// JSON Pointer value selection.
    JsonPointer,
    /// Supported JSONPath value selection.
    JsonPath,
    /// Accessibility snapshot role selection.
    AccessibilityRole,
    /// Selection by accessible name rather than source-tree text.
    AccessibleNameQuery,
    /// Selection by accessibility-node text.
    AccessibilityTextQuery,
    /// Selection by supported boolean accessibility state.
    AccessibilityStateQuery,
    /// Literal decoded-text range selection.
    TextLiteral,
    /// Supported regular-expression range selection.
    TextRegex,
    /// Projection of tree descendant text from selected nodes.
    DescendantTextProjection,
    /// Projection of a named attribute from selected nodes.
    AttributeProjection,
    /// Projection preserving native JSON value shape.
    JsonValueProjection,
    /// Projection retaining a document-bound native node reference.
    NodeReferenceProjection,
    /// Projection of an accessibility node's reported name.
    AccessibleNameProjection,
    /// Projection of an accessibility node's reported text.
    AccessibilityTextProjection,
    /// Projection of selected decoded-text match content.
    MatchedTextProjection,
    /// Projection of decoded-text matches with named capture values.
    MatchedTextWithCapturesProjection,
}

/// The document classes and capabilities required by every plan operation.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DocumentRequirement {
    pub(super) accepted_documents: Vec<DocumentClass>,
    pub(super) capabilities: Vec<LocatorCapability>,
}

impl DocumentRequirement {
    /// Returns whether this compiled plan accepts the supplied document capability class.
    /// This checks class compatibility, not payload validity, resource availability, or completeness.
    pub fn accepts(&self, document: DocumentClass) -> bool {
        self.accepted_documents.contains(&document)
    }
}

/// Portable compiled semantics with no document identity or lifecycle handle.
#[derive(Clone, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Plan {
    pub(super) regions: Vec<CompiledRegion>,
    pub(super) outputs: Vec<CompiledOutput>,
    pub(super) requirement: DocumentRequirement,
    #[serde(skip)]
    pub(super) compiled_text_regexes: Vec<Option<CompiledTextRegex>>,
    #[serde(skip)]
    pub(super) compiled_tree: OnceLock<Result<CompiledTreePlan, LocateFailure>>,
    #[serde(skip)]
    pub(super) compiled_xml: OnceLock<Result<CompiledXmlPlan, XmlError>>,
}

impl PartialEq for Plan {
    fn eq(&self, other: &Self) -> bool {
        self.regions == other.regions
            && self.outputs == other.outputs
            && self.requirement == other.requirement
    }
}

impl Eq for Plan {}

impl fmt::Debug for Plan {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("Plan")
            .field("regions", &self.regions)
            .field("outputs", &self.outputs)
            .field("requirement", &self.requirement)
            .finish_non_exhaustive()
    }
}

impl Plan {
    /// Compiles owned named outputs into portable query, projection, and region semantics.
    /// Returns [`PlanError`] for invalid identities, shape/projection combinations,
    /// nested or inconsistent regions, and supported syntax violations. No document
    /// is acquired or matched; document capability and resource checks occur at execution.
    pub fn new(outputs: impl IntoIterator<Item = NamedOutput>) -> Result<Self, PlanError> {
        super::authoring::compile_outputs(outputs.into_iter().collect())
    }

    pub(in crate::internal::documents) fn regions(&self) -> &[CompiledRegion] {
        &self.regions
    }
    pub(in crate::internal::documents) fn outputs(&self) -> &[CompiledOutput] {
        &self.outputs
    }
    pub(in crate::internal::documents) fn compiled_text_regex(
        &self,
        output_index: usize,
    ) -> Option<&CompiledTextRegex> {
        self.compiled_text_regexes
            .get(output_index)
            .and_then(Option::as_ref)
    }
    pub(in crate::internal::documents) fn compiled_tree_plan(
        &self,
        budget: ResourceBudget,
    ) -> Result<&CompiledTreePlan, LocateFailure> {
        let compiled = self.compiled_tree.get_or_init(|| compile_tree_plan(self));
        match compiled {
            Ok(compiled) => {
                validate_tree_plan_budget(compiled, budget)?;
                Ok(compiled)
            }
            Err(failure) => Err(failure.clone()),
        }
    }
    pub(in crate::internal::documents) fn compiled_xml_plan(
        &self,
        budget: ResourceBudget,
    ) -> Result<&CompiledXmlPlan, XmlError> {
        let compiled = self
            .compiled_xml
            .get_or_init(|| CompiledXmlPlan::for_plan(self));
        match compiled {
            Ok(compiled) => {
                compiled.validate_budget(budget)?;
                Ok(compiled)
            }
            Err(error) => Err(error.clone()),
        }
    }
    pub(in crate::internal::documents) const fn requirement(&self) -> &DocumentRequirement {
        &self.requirement
    }

    pub(in crate::internal::documents) fn validate_budget(
        &self,
        budget: ResourceBudget,
    ) -> Result<(), LocateFailure> {
        let region_count =
            u64::try_from(self.regions.len()).map_err(|_| invalid_plan("region_count_overflow"))?;
        check_budget(
            ResourceLimit::Regions,
            budget.max_regions().into(),
            region_count,
        )?;

        let mut query_bytes = 0_u64;
        let base_steps = self
            .regions
            .len()
            .checked_add(self.outputs.len())
            .and_then(|count| u64::try_from(count).ok())
            .ok_or_else(|| invalid_plan("query_step_count_overflow"))?;
        let mut query_steps = base_steps;

        for region in &self.regions {
            query_bytes = query_bytes
                .checked_add(
                    region
                        .query
                        .query_bytes()
                        .map_err(|_| invalid_plan("query_byte_count_overflow"))?,
                )
                .ok_or_else(|| invalid_plan("query_byte_count_overflow"))?;
            query_steps = query_steps
                .checked_add(
                    super::super::json::json_query_step_count(region.query.atom())
                        .map_err(|_| invalid_plan("json_query_step_count_invalid"))?,
                )
                .ok_or_else(|| invalid_plan("query_step_count_overflow"))?;
        }
        for output in &self.outputs {
            query_bytes = query_bytes
                .checked_add(
                    output
                        .query
                        .query_bytes()
                        .map_err(|_| invalid_plan("query_byte_count_overflow"))?,
                )
                .and_then(|count| {
                    output
                        .projection
                        .argument_bytes()
                        .ok()
                        .and_then(|argument| count.checked_add(argument))
                })
                .ok_or_else(|| invalid_plan("query_byte_count_overflow"))?;
            query_steps = query_steps
                .checked_add(
                    super::super::json::json_query_step_count(output.query.atom())
                        .map_err(|_| invalid_plan("json_query_step_count_invalid"))?,
                )
                .ok_or_else(|| invalid_plan("query_step_count_overflow"))?;
            if let Projection::MatchedTextWithCaptures { names } = &output.projection {
                let capture_count = u64::try_from(names.len())
                    .map_err(|_| invalid_plan("capture_count_overflow"))?;
                check_budget(
                    ResourceLimit::Captures,
                    budget.max_captures(),
                    capture_count,
                )?;
            }
        }
        check_budget(
            ResourceLimit::QueryBytes,
            budget.max_query_bytes(),
            query_bytes,
        )?;
        check_budget(
            ResourceLimit::QuerySteps,
            budget.max_query_steps().into(),
            query_steps,
        )
    }
}

fn invalid_plan(code: &str) -> LocateFailure {
    LocateFailure::InvalidPlan {
        code: code.to_owned(),
    }
}

const fn check_budget(
    limit: ResourceLimit,
    maximum: u64,
    observed: u64,
) -> Result<(), LocateFailure> {
    if observed > maximum {
        Err(LocateFailure::LimitExhausted {
            limit,
            maximum,
            observed,
        })
    } else {
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, Error, PartialEq)]
/// Authored output, query, projection, or region declarations cannot form one supported portable plan.
pub enum PlanError {
    /// The authored plan contains no named output declarations.
    #[error("locator plan must contain at least one output")]
    NoOutputs,
    /// A named output lacks a nonblank authored identity.
    #[error("output identity cannot be empty")]
    EmptyOutputId,
    /// A query vocabulary requiring expression text received empty input.
    #[error("query expression cannot be empty")]
    EmptyQueryExpression,
    /// Explicit query-local namespace metadata fails supported XML binding rules.
    #[error("query namespace bindings are invalid: {0}")]
    InvalidQueryNamespaces(QueryError),
    /// No compatible document engine accepts the authored query syntax.
    #[error("query syntax is unsupported by every compatible document engine: {atom:?}")]
    InvalidQuerySyntax {
        /// Authored operation whose syntax could not be compiled.
        atom: QueryAtom,
    },
    /// JSON Pointer or supported JSONPath parsing rejected the query.
    #[error(transparent)]
    InvalidJsonQuery(#[from] JsonQuerySyntaxError),
    /// A projection requiring an attribute or capture argument received empty metadata.
    #[error("projection argument cannot be empty")]
    EmptyProjectionArgument,
    /// Named capture selection contains the same capture more than once.
    #[error("capture name {name} is requested more than once")]
    DuplicateCaptureName {
        /// Repeated authored capture name.
        name: String,
    },
    /// A requested capture name has no definition in the compiled pattern.
    #[error("capture name {name} does not exist in the regular expression")]
    UnknownCaptureName {
        /// Capture name absent from the regex definition.
        name: String,
    },
    /// Multiple output declarations use one authored identity.
    #[error("output {id} is defined more than once")]
    DuplicateOutput {
        /// Repeated identity that would make finding attribution ambiguous.
        id: OutputId,
    },
    /// One region identity names inconsistent root query declarations.
    #[error("region {id:?} has conflicting definitions")]
    ConflictingRegion {
        /// Region identity whose definitions disagree.
        id: RegionId,
    },
    /// A repeated-region root combines incompatible query operation and native result shape.
    #[error("region query has an unsupported atom/result-shape combination")]
    InvalidRegionQuery {
        /// Authored root query operation.
        atom: QueryAtom,
        /// Declared root-result capability incompatible with the query.
        result_shape: QueryResultShape,
    },
    /// Output query, native result shape, and projection cannot be evaluated together.
    #[error("query atom, result shape, and projection are incompatible")]
    InvalidCombination {
        /// Authored query operation involved in the mismatch.
        atom: QueryAtom,
        /// Declared native result capability.
        result_shape: QueryResultShape,
        /// Projection label incompatible with the query and shape.
        projection: String,
    },
    /// No single document capability class can satisfy every operation in the plan.
    #[error("plan operations cannot be satisfied by one document class")]
    NoCommonDocument,
}

impl<'de> Deserialize<'de> for Plan {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct WirePlan {
            regions: Vec<CompiledRegion>,
            outputs: Vec<CompiledOutput>,
            requirement: DocumentRequirement,
        }

        let wire = WirePlan::deserialize(deserializer)?;
        let mut outputs = Vec::with_capacity(wire.outputs.len());
        for output in &wire.outputs {
            let output_plan = match output.parent_region() {
                Some(parent_id) => {
                    let region = wire
                        .regions
                        .iter()
                        .find(|candidate| candidate.id() == parent_id)
                        .ok_or_else(|| D::Error::custom("output names an unknown parent region"))?;
                    RegionPlan {
                        id: region.id.clone(),
                        query: region.query.clone(),
                    }
                    .find(output.query.clone())
                    .project(output.projection.clone())
                }
                None => OutputPlan::new(None, output.query.clone(), output.projection.clone()),
            };
            outputs.push(
                super::authoring::output(output.id.as_str(), output_plan)
                    .map_err(D::Error::custom)?,
            );
        }
        let compiled = Self::new(outputs).map_err(D::Error::custom)?;
        if compiled.regions != wire.regions
            || compiled.outputs != wire.outputs
            || compiled.requirement != wire.requirement
        {
            return Err(D::Error::custom(
                "serialized locator plan does not match its compiled requirement",
            ));
        }
        Ok(compiled)
    }
}
