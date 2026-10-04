#![allow(clippy::panic_in_result_fn)]
#![allow(unused_imports)]
#![allow(dead_code)]
pub use std::{
    error::Error,
    fmt::Write,
    io,
    sync::{Arc, Barrier},
};
pub use yosoi_documents::{
    Document, LocateFailure, LocateOutcome, NativeCoordinate, Plan, ProjectedValue, ResourceBudget,
    ResourceBudgetValues, ResourceLimit, TreeCoordinate, css, output, tree_text_contains, xpath,
};

pub fn html(id: &str, body: &str) -> Result<Document, Box<dyn Error>> {
    let source = format!(
        "<!doctype html><html><head><title>grid</title></head><body><main>{body}</main></body></html>"
    );
    Ok(Document::html(id, source.into_bytes())?)
}

pub fn matched(outcome: &LocateOutcome) -> Result<&[yosoi_documents::Finding], Box<dyn Error>> {
    match outcome {
        LocateOutcome::Matched { result } => Ok(result.findings()),
        other => Err(io::Error::other(format!("expected matched outcome, got {other:?}")).into()),
    }
}

pub fn equivalent(document: &Document, plan: &Plan) -> Result<LocateOutcome, Box<dyn Error>> {
    let retained = document.parse()?.locate(plan);
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

pub fn budget_equivalent(
    document: &Document,
    plan: &Plan,
    limits: ResourceBudget,
) -> Result<LocateOutcome, Box<dyn Error>> {
    let retained = document.parse_with_budget(limits)?.locate(plan);
    let direct = document.locate_with_budget(plan, limits);
    assert_eq!(direct, retained);
    Ok(direct)
}

pub fn assert_coordinates(
    findings: &[yosoi_documents::Finding],
    paths: &[Vec<u32>],
) -> Result<(), Box<dyn Error>> {
    assert_eq!(findings.len(), paths.len());
    for (finding, path) in findings.iter().zip(paths) {
        assert_eq!(
            finding.coordinate(),
            &NativeCoordinate::SourceTree(TreeCoordinate::try_new(path.clone(), None)?)
        );
    }
    Ok(())
}

pub fn assert_node_references(findings: &[yosoi_documents::Finding]) -> Result<(), Box<dyn Error>> {
    for finding in findings {
        let ProjectedValue::Node(reference) = finding.value() else {
            return Err(io::Error::other("expected node-reference projection").into());
        };
        assert_eq!(reference.document_id(), finding.document_id());
        assert_eq!(reference.coordinate(), finding.coordinate());
    }
    Ok(())
}

pub const fn repeated_grid() -> &'static str {
    concat!(
        "<nav>before</nav><section>",
        "text<!--comment--><div class='card' data-id='a'><span class='price'>A</span></div>",
        "<p>unrelated</p>",
        "<div class='card' data-id='b'><div><span class='price'>B</span></div></div>",
        "</section><aside>after</aside>",
    )
}
