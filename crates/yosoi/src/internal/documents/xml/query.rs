use crate::internal::documents::{Plan, Projection, QueryAtom, QuerySpec, ResourceBudget};

use super::text::{normalize_text, resolve_attribute_name};
use super::{XmlError, css, query_steps_exceeded, xpath};

#[derive(Clone, Debug)]
pub(super) enum CompiledXmlQuery {
    Css(css::SelectorList),
    XPath(xpath::XPath),
    TreeTextContains(String),
}

#[derive(Clone, Debug)]
pub(super) enum CompiledXmlProjection {
    DescendantText,
    Attribute {
        namespace_uri: Option<String>,
        local_name: String,
        canonical_name: String,
    },
    NodeReference,
}

#[derive(Clone, Debug)]
struct CompiledXmlSelection {
    query: CompiledXmlQuery,
    query_steps: usize,
}

#[derive(Clone, Debug)]
struct CompiledXmlOutput {
    query_index: usize,
    projection: CompiledXmlProjection,
}

#[derive(Clone, Debug, Default)]
pub struct CompiledXmlPlan {
    queries: Vec<CompiledXmlSelection>,
    region_queries: Vec<usize>,
    output_entries: Vec<usize>,
    outputs: Vec<CompiledXmlOutput>,
}

impl CompiledXmlPlan {
    pub(in crate::internal::documents) fn for_plan(plan: &Plan) -> Result<Self, XmlError> {
        let capacity = plan
            .regions()
            .len()
            .checked_add(plan.outputs().len())
            .ok_or(XmlError::InvalidResult)?;
        let mut compiled = Self {
            queries: Vec::with_capacity(capacity),
            region_queries: Vec::with_capacity(plan.regions().len()),
            output_entries: Vec::with_capacity(plan.outputs().len()),
            outputs: Vec::with_capacity(plan.outputs().len()),
        };
        let mut query_keys = Vec::<&QuerySpec>::with_capacity(capacity);
        let mut output_keys = Vec::<(usize, &Projection)>::with_capacity(plan.outputs().len());

        for region in plan.regions() {
            let query_index = compiled.query_index(region.query(), &mut query_keys)?;
            compiled.region_queries.push(query_index);
        }
        for output in plan.outputs() {
            let query_index = compiled.query_index(output.query(), &mut query_keys)?;
            let output_index = if let Some(index) =
                output_keys
                    .iter()
                    .position(|(candidate_query, candidate_projection)| {
                        *candidate_query == query_index
                            && *candidate_projection == output.projection()
                    }) {
                index
            } else {
                let projection = compile_projection(output.query(), output.projection())?;
                let index = compiled.outputs.len();
                compiled.outputs.push(CompiledXmlOutput {
                    query_index,
                    projection,
                });
                output_keys.push((query_index, output.projection()));
                index
            };
            compiled.output_entries.push(output_index);
        }
        Ok(compiled)
    }

    fn query_index<'plan>(
        &mut self,
        query: &'plan QuerySpec,
        keys: &mut Vec<&'plan QuerySpec>,
    ) -> Result<usize, XmlError> {
        if let Some(index) = keys.iter().position(|candidate| *candidate == query) {
            return Ok(index);
        }
        let selection = compile_query(query)?;
        let index = self.queries.len();
        self.queries.push(selection);
        keys.push(query);
        Ok(index)
    }

    pub(in crate::internal::documents) fn validate_budget(
        &self,
        budget: ResourceBudget,
    ) -> Result<(), XmlError> {
        for selection in &self.queries {
            let maximum = budget.max_query_steps();
            let maximum_usize = usize::try_from(maximum).unwrap_or(usize::MAX);
            if selection.query_steps > maximum_usize {
                return Err(query_steps_exceeded(
                    maximum,
                    maximum_usize.saturating_add(1),
                ));
            }
        }
        Ok(())
    }

    pub(super) fn region_query(&self, index: usize) -> Result<&CompiledXmlQuery, XmlError> {
        let query_index = self
            .region_queries
            .get(index)
            .copied()
            .ok_or(XmlError::IncompatiblePlan)?;
        self.queries
            .get(query_index)
            .map(|selection| &selection.query)
            .ok_or(XmlError::IncompatiblePlan)
    }

    pub(super) fn output(
        &self,
        index: usize,
    ) -> Result<(&CompiledXmlQuery, &CompiledXmlProjection), XmlError> {
        let output_index = self
            .output_entries
            .get(index)
            .copied()
            .ok_or(XmlError::IncompatiblePlan)?;
        let output = self
            .outputs
            .get(output_index)
            .ok_or(XmlError::IncompatiblePlan)?;
        let query = self
            .queries
            .get(output.query_index)
            .map(|selection| &selection.query)
            .ok_or(XmlError::IncompatiblePlan)?;
        Ok((query, &output.projection))
    }
}

fn compile_query(query: &QuerySpec) -> Result<CompiledXmlSelection, XmlError> {
    let (query, query_steps) = match query.atom() {
        QueryAtom::Css(expression) => {
            let selector = css::parse(expression, query.namespace_bindings(), u32::MAX)?;
            let steps = selector.step_count();
            (CompiledXmlQuery::Css(selector), steps)
        }
        QueryAtom::XPath(expression) => {
            let xpath = xpath::parse(expression, query.namespace_bindings(), u32::MAX)?;
            let steps = xpath.step_count();
            (CompiledXmlQuery::XPath(xpath), steps)
        }
        QueryAtom::TreeTextContains(needle) => {
            let normalized = normalize_text(needle);
            if normalized.is_empty() {
                return Err(XmlError::InvalidQuery);
            }
            (CompiledXmlQuery::TreeTextContains(normalized), 0)
        }
        _ => return Err(XmlError::IncompatiblePlan),
    };
    Ok(CompiledXmlSelection { query, query_steps })
}

fn compile_projection(
    query: &QuerySpec,
    projection: &Projection,
) -> Result<CompiledXmlProjection, XmlError> {
    match projection {
        Projection::DescendantText => Ok(CompiledXmlProjection::DescendantText),
        Projection::Attribute(name) => {
            let (namespace_uri, local_name) =
                resolve_attribute_name(name, query.namespace_bindings())?;
            let canonical_name = namespace_uri.as_ref().map_or_else(
                || local_name.to_owned(),
                |uri| format!("{{{uri}}}{local_name}"),
            );
            Ok(CompiledXmlProjection::Attribute {
                namespace_uri,
                local_name: local_name.to_owned(),
                canonical_name,
            })
        }
        Projection::NodeReference => Ok(CompiledXmlProjection::NodeReference),
        _ => Err(XmlError::IncompatiblePlan),
    }
}
