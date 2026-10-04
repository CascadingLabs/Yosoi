#![allow(clippy::panic_in_result_fn)]
#![allow(unused_imports)]
#![allow(dead_code)]
#![allow(
    clippy::too_many_arguments,
    reason = "the test budget helper names each independently varied public limit"
)]
pub use std::{error::Error, io};
pub use yosoi_documents::{
    Document, DocumentParseError, HtmlParseError, LocateFailure, LocateOutcome, NativeCoordinate,
    Plan, ProjectedValue, ResourceBudget, ResourceBudgetValues, ResourceLimit, TreeCoordinate, css,
    output, tree_text_contains, xpath,
};

pub const CAVEMAN_SELECTOR: &str = "article.product-card[data-sku='sku-000073'] span.price";

pub fn html(id: &str, source: &str) -> Result<Document, Box<dyn Error>> {
    Ok(Document::html(id, source.as_bytes().to_vec())?)
}

pub fn caveman_plan() -> Result<Plan, Box<dyn Error>> {
    Ok(Plan::new([output(
        "price",
        css(CAVEMAN_SELECTOR)?.text(),
    )?])?)
}

pub fn assert_default_equivalent(
    document: &Document,
    plan: &Plan,
) -> Result<LocateOutcome, Box<dyn Error>> {
    let retained = document.parse()?.locate(plan);
    let candidate = document.locate(plan);
    assert_eq!(candidate, retained);
    Ok(candidate)
}

pub fn assert_budget_equivalent(
    document: &Document,
    plan: &Plan,
    budget: ResourceBudget,
) -> Result<LocateOutcome, Box<dyn Error>> {
    let retained = document.parse_with_budget(budget)?.locate(plan);
    let candidate = document.locate_with_budget(plan, budget);
    assert_eq!(candidate, retained);
    Ok(candidate)
}

pub fn matched(outcome: &LocateOutcome) -> Result<&[yosoi_documents::Finding], Box<dyn Error>> {
    match outcome {
        LocateOutcome::Matched { result } => Ok(result.findings()),
        other => Err(io::Error::other(format!("expected matched outcome, got {other:?}")).into()),
    }
}

pub fn budget(
    max_input_bytes: u64,
    max_nodes: u64,
    max_selector_visits: u64,
    max_query_bytes: u64,
    max_query_steps: u32,
    max_regions: u32,
    max_matches: u64,
    max_depth: u32,
    max_output_bytes: u64,
) -> Result<ResourceBudget, Box<dyn Error>> {
    Ok(ResourceBudget::try_new(ResourceBudgetValues {
        max_input_bytes,
        max_nodes,
        max_selector_visits,
        max_query_bytes,
        max_query_steps,
        max_regions,
        max_matches,
        max_captures: 64,
        max_depth,
        max_output_bytes,
    })?)
}
