use std::{fmt, sync::OnceLock};

use serde::{Deserialize, Deserializer, Serialize, de::Error as _};

use crate::decoded_text::{CompiledTextRegex, compile_regex};
use crate::html::compile_tree_plan;
use crate::xml::CompiledXmlPlan;
use crate::{DocumentClass, Projection, QueryAtom, QueryError, QuerySpec};

use crate::plan::compatibility::{
    output_compatibility, projection_capability, region_compatibility,
};
use crate::plan::model::{CompiledOutput, CompiledRegion, DocumentRequirement, Plan, PlanError};
use crate::plan::validation::{
    all_document_classes, intersect, push_unique, validate_authored_projection,
    validate_authored_query, validate_query_projection,
};

/// A validated output name stable within one plan.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct OutputId(String);

impl OutputId {
    pub fn try_new(value: impl Into<String>) -> Result<Self, PlanError> {
        let value = value.into();
        if value.trim().is_empty() {
            Err(PlanError::EmptyOutputId)
        } else {
            Ok(Self(value))
        }
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for OutputId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl<'de> Deserialize<'de> for OutputId {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        Self::try_new(String::deserialize(deserializer)?).map_err(D::Error::custom)
    }
}

/// A validated repeated-region name stable within one plan.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct RegionId(String);

impl RegionId {
    pub fn try_new(value: impl Into<String>) -> Result<Self, QueryError> {
        let value = value.into();
        if value.trim().is_empty() {
            Err(QueryError::EmptyRegionId)
        } else {
            Ok(Self(value))
        }
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl<'de> Deserialize<'de> for RegionId {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        Self::try_new(String::deserialize(deserializer)?).map_err(D::Error::custom)
    }
}

/// One non-nested repeated region used by one or more outputs.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RegionPlan {
    pub(super) id: RegionId,
    pub(super) query: QuerySpec,
}

impl RegionPlan {
    pub(crate) fn try_new(id: impl Into<String>, query: QuerySpec) -> Result<Self, QueryError> {
        Ok(Self {
            id: RegionId::try_new(id)?,
            query,
        })
    }

    pub const fn id(&self) -> &RegionId {
        &self.id
    }

    pub const fn query(&self) -> &QuerySpec {
        &self.query
    }

    pub fn find(&self, query: QuerySpec) -> OutputSelection {
        OutputSelection {
            region: self.clone(),
            query,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OutputSelection {
    region: RegionPlan,
    query: QuerySpec,
}

impl OutputSelection {
    pub(crate) fn project(self, projection: Projection) -> OutputPlan {
        OutputPlan::new(Some(self.region), self.query, projection)
    }

    pub fn text(self) -> OutputPlan {
        let Self { region, query } = self;
        let mut output = query.text();
        output.region = Some(region);
        output
    }

    pub fn attribute(self, name: impl Into<String>) -> Result<OutputPlan, QueryError> {
        let Self { region, query } = self;
        let mut output = query.attribute(name)?;
        output.region = Some(region);
        Ok(output)
    }

    pub fn value(self) -> OutputPlan {
        let Self { region, query } = self;
        let mut output = query.value();
        output.region = Some(region);
        output
    }

    pub fn node(self) -> OutputPlan {
        let Self { region, query } = self;
        let mut output = query.node();
        output.region = Some(region);
        output
    }

    pub fn name(self) -> OutputPlan {
        let Self { region, query } = self;
        let mut output = query.name();
        output.region = Some(region);
        output
    }

    pub fn captures(
        self,
        names: impl IntoIterator<Item = impl Into<String>>,
    ) -> Result<OutputPlan, QueryError> {
        let Self { region, query } = self;
        let mut output = query.captures(names)?;
        output.region = Some(region);
        Ok(output)
    }
}

/// An authored output before compatibility compilation.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct OutputPlan {
    pub(super) region: Option<RegionPlan>,
    pub(super) query: QuerySpec,
    pub(super) projection: Projection,
}

impl OutputPlan {
    pub(crate) const fn new(
        region: Option<RegionPlan>,
        query: QuerySpec,
        projection: Projection,
    ) -> Self {
        Self {
            region,
            query,
            projection,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NamedOutput {
    pub(super) id: OutputId,
    pub(super) output: OutputPlan,
}

/// Associates a stable output name with a query-local value selection.
pub fn output(id: impl Into<String>, value: OutputPlan) -> Result<NamedOutput, PlanError> {
    Ok(NamedOutput {
        id: OutputId::try_new(id)?,
        output: value,
    })
}

pub(super) fn compile_outputs(outputs: Vec<NamedOutput>) -> Result<Plan, PlanError> {
    if outputs.is_empty() {
        return Err(PlanError::NoOutputs);
    }

    let mut output_ids = Vec::with_capacity(outputs.len());
    for named in &outputs {
        if output_ids.iter().any(|id| id == &named.id) {
            return Err(PlanError::DuplicateOutput {
                id: named.id.clone(),
            });
        }
        output_ids.push(named.id.clone());
    }

    let mut regions = Vec::<CompiledRegion>::new();
    for named in &outputs {
        if let Some(region) = &named.output.region {
            validate_authored_query(&region.query, None)?;
            match regions.iter().find(|existing| existing.id == region.id) {
                Some(existing) if existing.query != region.query => {
                    return Err(PlanError::ConflictingRegion {
                        id: region.id.clone(),
                    });
                }
                Some(_) => {}
                None => regions.push(CompiledRegion {
                    id: region.id.clone(),
                    query: region.query.clone(),
                }),
            }
        }
    }

    let mut accepted = all_document_classes();
    let mut capabilities = Vec::new();

    for region in &regions {
        let compatibility =
            region_compatibility(&region.query).ok_or_else(|| PlanError::InvalidRegionQuery {
                atom: region.query.atom().clone(),
                result_shape: region.query.result_shape(),
            })?;
        if compatibility.documents.is_empty() {
            return Err(PlanError::InvalidQuerySyntax {
                atom: region.query.atom().clone(),
            });
        }
        intersect(&mut accepted, &compatibility.documents);
        push_unique(&mut capabilities, compatibility.capability);
    }

    let mut compiled_outputs = Vec::with_capacity(outputs.len());
    let mut compiled_text_regexes = Vec::with_capacity(outputs.len());
    for named in outputs {
        let mut compiled_text_regex = compile_text_regex(
            &named.output.query,
            &compiled_outputs,
            &compiled_text_regexes,
        )?;
        validate_authored_query(&named.output.query, compiled_text_regex.as_ref())?;
        validate_authored_projection(&named.output.projection)?;
        validate_query_projection(
            &named.output.query,
            &named.output.projection,
            compiled_text_regex.as_ref(),
        )?;
        lower_requested_capture_groups(
            compiled_text_regex.as_mut(),
            &named.output.query,
            &named.output.projection,
        )?;
        if let Projection::Attribute(name) = &named.output.projection {
            named
                .output
                .query
                .validate_attribute_projection(name)
                .map_err(PlanError::InvalidQueryNamespaces)?;
        }
        let compatibility = output_compatibility(&named.output.query, &named.output.projection)
            .ok_or_else(|| PlanError::InvalidCombination {
                atom: named.output.query.atom().clone(),
                result_shape: named.output.query.result_shape(),
                projection: format!("{:?}", named.output.projection.kind()),
            })?;
        if compatibility.documents.is_empty() {
            return Err(PlanError::InvalidQuerySyntax {
                atom: named.output.query.atom().clone(),
            });
        }
        intersect(&mut accepted, &compatibility.documents);
        push_unique(&mut capabilities, compatibility.capability);
        push_unique(
            &mut capabilities,
            projection_capability(named.output.projection.kind()),
        );
        compiled_outputs.push(CompiledOutput {
            id: named.id,
            parent_region: named.output.region.map(|region| region.id),
            query: named.output.query,
            projection: named.output.projection,
        });
        compiled_text_regexes.push(compiled_text_regex);
    }

    if accepted.is_empty() {
        return Err(PlanError::NoCommonDocument);
    }

    let plan = Plan {
        regions,
        outputs: compiled_outputs,
        requirement: DocumentRequirement {
            accepted_documents: accepted,
            capabilities,
        },
        compiled_text_regexes,
        compiled_tree: OnceLock::new(),
        compiled_xml: OnceLock::new(),
    };
    if plan.requirement.accepts(DocumentClass::SourceHtml)
        || plan.requirement.accepts(DocumentClass::RenderedDom)
    {
        // Compatibility compilation above has already established that this
        // plan has HTML tree semantics. Retain the executable query state so
        // every document evaluation can borrow it instead of lowering again.
        let _ = plan.compiled_tree.set(compile_tree_plan(&plan));
    }
    if plan.requirement.accepts(DocumentClass::SourceXml) {
        let _ = plan.compiled_xml.set(CompiledXmlPlan::for_plan(&plan));
    }
    Ok(plan)
}

fn compile_text_regex(
    query: &QuerySpec,
    prior_outputs: &[CompiledOutput],
    prior_regexes: &[Option<CompiledTextRegex>],
) -> Result<Option<CompiledTextRegex>, PlanError> {
    let QueryAtom::TextRegex(expression) = query.atom() else {
        return Ok(None);
    };
    if let Some(compiled) =
        prior_outputs
            .iter()
            .zip(prior_regexes)
            .find_map(|(output, compiled)| match output.query().atom() {
                QueryAtom::TextRegex(prior) if prior == expression => compiled.as_ref(),
                _ => None,
            })
    {
        let mut reused = compiled.clone();
        reused.set_requested_capture_groups(Vec::new());
        return Ok(Some(reused));
    }
    let regex = compile_regex(expression).map_err(|_| PlanError::InvalidQuerySyntax {
        atom: query.atom().clone(),
    })?;
    Ok(Some(CompiledTextRegex::new(regex, Vec::new())))
}

fn lower_requested_capture_groups(
    compiled: Option<&mut CompiledTextRegex>,
    query: &QuerySpec,
    projection: &Projection,
) -> Result<(), PlanError> {
    let Projection::MatchedTextWithCaptures { names } = projection else {
        return Ok(());
    };
    let compiled = compiled.ok_or_else(|| PlanError::InvalidCombination {
        atom: query.atom().clone(),
        result_shape: query.result_shape(),
        projection: format!("{:?}", projection.kind()),
    })?;

    let mut requested_capture_groups = Vec::with_capacity(names.len());
    for name in names {
        let group = compiled
            .regex()
            .capture_names()
            .enumerate()
            .find_map(|(group, candidate)| (candidate == Some(name.as_str())).then_some(group))
            .ok_or_else(|| PlanError::UnknownCaptureName { name: name.clone() })?;
        requested_capture_groups.push(group);
    }
    compiled.set_requested_capture_groups(requested_capture_groups);
    Ok(())
}
