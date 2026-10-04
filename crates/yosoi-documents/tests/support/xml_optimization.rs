#![allow(clippy::panic_in_result_fn)]
#![allow(unused_imports)]
#![allow(dead_code)]
pub use std::{error::Error, io};
pub use yosoi_documents::{
    Document, ExpandedNamePathSegment, LocateFailure, LocateOutcome, NativeCoordinate, Plan,
    ProjectedValue, ResourceBudget, ResourceBudgetValues, ResourceLimit, css, output,
    tree_text_contains, xpath,
};

pub fn xml(id: &str, source: &str) -> Result<Document, Box<dyn Error>> {
    Ok(Document::xml(id, source.as_bytes().to_vec())?)
}

pub fn text_plan(expression: &str) -> Result<Plan, Box<dyn Error>> {
    Ok(Plan::new([output("values", xpath(expression)?.text())?])?)
}

pub fn matched(outcome: &LocateOutcome) -> Result<&[yosoi_documents::Finding], Box<dyn Error>> {
    match outcome {
        LocateOutcome::Matched { result } => Ok(result.findings()),
        other => Err(io::Error::other(format!("expected matched outcome, got {other:?}")).into()),
    }
}

pub fn text_values(outcome: &LocateOutcome) -> Result<Vec<String>, Box<dyn Error>> {
    matched(outcome)?
        .iter()
        .map(|finding| match finding.value() {
            ProjectedValue::Text(value) => Ok(value.clone()),
            other => {
                Err(io::Error::other(format!("expected text projection, got {other:?}")).into())
            }
        })
        .collect()
}

pub fn assert_equivalent(
    document: &Document,
    plan: &Plan,
) -> Result<LocateOutcome, Box<dyn Error>> {
    let parsed = document.parse()?;
    let retained = parsed.locate(plan);
    let direct = document.locate(plan);
    assert_eq!(direct, retained);
    Ok(direct)
}

pub fn budget(
    selector_visits: u64,
    query_steps: u32,
    matches: u64,
    output_bytes: u64,
) -> Result<ResourceBudget, Box<dyn Error>> {
    Ok(ResourceBudget::try_new(ResourceBudgetValues {
        max_input_bytes: 16_384,
        max_nodes: 1_024,
        max_selector_visits: selector_visits,
        max_query_bytes: 4_096,
        max_query_steps: query_steps,
        max_regions: 16,
        max_matches: matches,
        max_captures: 64,
        max_depth: 128,
        max_output_bytes: output_bytes,
    })?)
}

pub fn assert_budget_equivalent(
    document: &Document,
    plan: &Plan,
    limits: ResourceBudget,
) -> Result<LocateOutcome, Box<dyn Error>> {
    let retained = document.parse_with_budget(limits)?.locate(plan);
    let direct = document.locate_with_budget(plan, limits);
    assert_eq!(direct, retained);
    Ok(direct)
}
