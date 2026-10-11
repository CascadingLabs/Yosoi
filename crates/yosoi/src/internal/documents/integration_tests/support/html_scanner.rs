#![allow(clippy::panic_in_result_fn)]
#![allow(unused_imports)]
#![allow(dead_code)]
pub use crate::internal::documents::{
    Document, DocumentParseError, HtmlParseError, LocateFailure, LocateOutcome, NativeCoordinate,
    Plan, ProjectedValue, ResourceBudget, ResourceBudgetValues, ResourceLimit, TreeCoordinate, css,
    output,
};
use std::fmt::{self, Write as _};
pub use std::{error::Error, fmt::Write, io, num::TryFromIntError};

pub const SELECTOR: &str = "article.product-card[data-sku='sku-000073'] span.price";

pub fn plan() -> Result<Plan, Box<dyn Error>> {
    Ok(Plan::new([output("price", css(SELECTOR)?.text())?])?)
}

pub fn document(id: &str, body: &str) -> Result<Document, Box<dyn Error>> {
    let source = format!(
        "<!doctype html><html><head><title>fixture</title></head><body><main>{body}</main></body></html>"
    );
    Ok(Document::html(id, source.into_bytes())?)
}

pub fn exact_outcome(document: &Document, plan: &Plan) -> Result<LocateOutcome, Box<dyn Error>> {
    let retained = document.parse()?.locate(plan);
    let candidate = document.locate(plan);
    assert_eq!(candidate, retained);
    Ok(candidate)
}

pub fn assert_matches(
    outcome: &LocateOutcome,
    expected: &[(String, Vec<u32>)],
) -> Result<(), Box<dyn Error>> {
    let LocateOutcome::Matched { result } = outcome else {
        return Err(io::Error::other(format!("expected matched outcome, got {outcome:?}")).into());
    };
    assert_eq!(result.findings().len(), expected.len());
    for (finding, (value, child_path)) in result.findings().iter().zip(expected) {
        assert_eq!(finding.value(), &ProjectedValue::Text(value.clone()));
        assert_eq!(
            finding.coordinate(),
            &NativeCoordinate::SourceTree(TreeCoordinate::try_new(child_path.clone(), None)?)
        );
    }
    Ok(())
}

pub fn generated_catalog(records: usize, targets: &[usize]) -> Result<String, fmt::Error> {
    let mut source = String::new();
    for index in 0..records {
        let sku = if targets.contains(&index) {
            "sku-000073".to_owned()
        } else {
            format!("sku-{index:06}")
        };
        write!(
            &mut source,
            "<article class='product-card card-{index}' data-sku='{sku}'><span class='price'>value-{index}</span></article>"
        )?;
    }
    Ok(source)
}

pub fn input_budget(max_input_bytes: u64) -> Result<ResourceBudget, Box<dyn Error>> {
    Ok(ResourceBudget::try_new(ResourceBudgetValues {
        max_input_bytes,
        max_nodes: 1_000_000,
        max_selector_visits: 10_000_000,
        max_query_bytes: 65_536,
        max_query_steps: 256,
        max_regions: 64,
        max_matches: 100_000,
        max_captures: 16_384,
        max_depth: 1_024,
        max_output_bytes: 16_777_216,
    })?)
}
