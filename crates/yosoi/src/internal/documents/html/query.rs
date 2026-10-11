use crate::internal::documents::{
    LocateFailure, OutputId, Plan, Projection, QueryAtom, QueryResultShape, QuerySpec, RegionId,
    ResourceBudget, ResourceLimit,
};

use super::streaming::CompiledStreamingPlan;
use super::{
    CssSelectorList, XPathPath, append_normalized_text, invalid_failure, limit_failure, parse_css,
    parse_xpath,
};

#[derive(Clone)]
pub struct CompiledTreePlan {
    pub(in crate::internal::documents) regions: Vec<CompiledTreeRegion>,
    pub(in crate::internal::documents) outputs: Vec<CompiledTreeOutput>,
    pub(super) streaming: Option<CompiledStreamingPlan>,
}

#[derive(Clone)]
pub struct CompiledTreeRegion {
    pub(in crate::internal::documents) id: RegionId,
    pub(in crate::internal::documents) query: TreeQuery,
}

#[derive(Clone)]
pub struct CompiledTreeOutput {
    pub(in crate::internal::documents) id: OutputId,
    pub(in crate::internal::documents) parent_region: Option<RegionId>,
    pub(in crate::internal::documents) query: TreeQuery,
    pub(in crate::internal::documents) projection: Projection,
}

#[derive(Clone)]
pub enum TreeQuery {
    Css(CssSelectorList),
    XPath(XPathPath),
    TreeTextContains(String),
}

impl TreeQuery {
    pub(in crate::internal::documents) const fn step_count(&self) -> u64 {
        match self {
            Self::Css(selector) => selector.step_count,
            Self::XPath(path) => path.step_count,
            Self::TreeTextContains(_) => 1,
        }
    }
}

pub fn compile_tree_plan(plan: &Plan) -> Result<CompiledTreePlan, LocateFailure> {
    let mut regions = Vec::with_capacity(plan.regions().len());
    for region in plan.regions() {
        let query = compile_query(region.query())?;
        regions.push(CompiledTreeRegion {
            id: region.id().clone(),
            query,
        });
    }

    let mut outputs = Vec::with_capacity(plan.outputs().len());
    for output in plan.outputs() {
        if matches!(output.projection(), Projection::Attribute(name) if name.trim().is_empty()) {
            return Err(invalid_failure("html_empty_attribute_name"));
        }
        if !matches!(
            output.projection(),
            Projection::DescendantText | Projection::Attribute(_) | Projection::NodeReference
        ) {
            return Err(invalid_failure("html_projection_unsupported"));
        }
        let query = compile_query(output.query())?;
        outputs.push(CompiledTreeOutput {
            id: output.id().clone(),
            parent_region: output.parent_region().cloned(),
            query,
            projection: output.projection().clone(),
        });
    }
    let mut compiled = CompiledTreePlan {
        regions,
        outputs,
        streaming: None,
    };
    compiled.streaming = super::streaming::compile_plan(&compiled);
    Ok(compiled)
}

pub(super) fn validate_tree_plan_budget(
    plan: &CompiledTreePlan,
    budget: ResourceBudget,
) -> Result<(), LocateFailure> {
    let mut query_steps = 0_u64;
    for region in &plan.regions {
        query_steps = add_query_steps(
            query_steps,
            region.query.step_count(),
            budget.max_query_steps(),
        )?;
    }
    for output in &plan.outputs {
        query_steps = add_query_steps(
            query_steps,
            output.query.step_count(),
            budget.max_query_steps(),
        )?;
    }
    Ok(())
}

fn add_query_steps(current: u64, additional: u64, maximum: u32) -> Result<u64, LocateFailure> {
    let observed = current.saturating_add(additional);
    if observed > u64::from(maximum) {
        return Err(limit_failure(
            ResourceLimit::QuerySteps,
            u64::from(maximum),
            observed,
        ));
    }
    Ok(observed)
}

fn compile_query(query: &QuerySpec) -> Result<TreeQuery, LocateFailure> {
    match (query.atom(), query.result_shape()) {
        (QueryAtom::Css(expression), QueryResultShape::TreeNodes) => parse_css(expression)
            .map(TreeQuery::Css)
            .map_err(|()| invalid_failure("html_css_syntax_unsupported")),
        (QueryAtom::XPath(expression), QueryResultShape::TreeNodes) => parse_xpath(expression)
            .map(TreeQuery::XPath)
            .map_err(|()| invalid_failure("html_xpath_syntax_unsupported")),
        (QueryAtom::TreeTextContains(expression), QueryResultShape::TreeNodes) => {
            let normalized = normalize_text_query(expression);
            if normalized.is_empty() {
                Err(invalid_failure("html_text_query_empty"))
            } else {
                Ok(TreeQuery::TreeTextContains(normalized))
            }
        }
        _ => Err(invalid_failure("html_query_shape_unsupported")),
    }
}

fn normalize_text_query(source: &str) -> String {
    let mut normalized = String::new();
    let mut previous_was_space = false;
    append_normalized_text(source, &mut normalized, &mut previous_was_space);
    normalized.trim_matches(' ').to_owned()
}
