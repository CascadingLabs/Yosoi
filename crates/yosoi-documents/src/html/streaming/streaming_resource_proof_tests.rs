use std::error::Error;

use super::super::HtmlLocateDispatch;
use super::plan::CompiledStreamingPlan;
use super::routing::try_locate;
use super::scanner::{self, ScanAttempt};
use crate::{Document, LocateOutcome, Plan, ResourceBudget, ResourceBudgetValues, css, output};

fn selector_budget(max_selector_visits: u64) -> Result<ResourceBudget, Box<dyn Error>> {
    Ok(ResourceBudget::try_new(ResourceBudgetValues {
        max_input_bytes: 2_000_000,
        max_nodes: 1_024,
        max_selector_visits,
        max_query_bytes: 4_096,
        max_query_steps: 64,
        max_regions: 16,
        max_matches: 16,
        max_captures: 64,
        max_depth: 1_024,
        max_output_bytes: 4_096,
    })?)
}

#[allow(
    clippy::panic_in_result_fn,
    reason = "test helper asserts exact retained-path parity while propagating fixture errors"
)]
fn assert_budget_parity(source: &str, plan: &Plan) -> Result<(), Box<dyn Error>> {
    let document = Document::html("skipped-repair-budget", source.as_bytes().to_vec())?;
    for visits in 1..=512 {
        let budget = selector_budget(visits)?;
        let retained = document.parse_with_budget(budget)?.locate(plan);
        let direct = document.locate_with_budget(plan, budget);
        assert_eq!(direct, retained, "selector visits = {visits}");
    }
    Ok(())
}

#[allow(
    clippy::panic_in_result_fn,
    reason = "test helper asserts the exact candidate admission boundary"
)]
fn assert_candidate_threshold_parity(source: &str, plan: &Plan) -> Result<(), Box<dyn Error>> {
    let document = Document::html("skipped-repair-threshold", source.as_bytes().to_vec())?;
    let mut lower = 1_u64;
    let mut upper = 1_000_000_u64;
    assert!(matches!(
        try_locate(&document, plan, selector_budget(upper)?),
        HtmlLocateDispatch::Completed { .. }
    ));
    while lower < upper {
        let span = upper
            .checked_sub(lower)
            .ok_or("threshold bounds reversed")?;
        let middle = lower.checked_add(span / 2).ok_or("threshold overflow")?;
        if matches!(
            try_locate(&document, plan, selector_budget(middle)?),
            HtmlLocateDispatch::Completed { .. }
        ) {
            upper = middle;
        } else {
            lower = middle.checked_add(1).ok_or("threshold overflow")?;
        }
    }
    for visits in lower.saturating_sub(1)..=lower.saturating_add(1) {
        let budget = selector_budget(visits)?;
        let retained = document.parse_with_budget(budget)?.locate(plan);
        assert_eq!(
            document.locate_with_budget(plan, budget),
            retained,
            "candidate admission boundary at {visits} visits"
        );
    }
    Ok(())
}

#[test]
#[allow(
    clippy::panic_in_result_fn,
    reason = "resource-bound differential uses assertions while propagating authoring errors"
)]
fn implied_paragraph_repair_in_skipped_row_falls_back_for_exact_selector_work()
-> Result<(), Box<dyn Error>> {
    let source = concat!(
        "<!doctype html><html><head></head><body><main>",
        "<article class='row' data-id='other'><p><div>x</div></p></article>",
        "<article class='row' data-id='target'><span class='value'>ok</span></article>",
        "</main></body></html>",
    );
    let plan = Plan::new([output(
        "value",
        css("article.row[data-id='target'] span.value")?.text(),
    )?])?;
    let document = Document::html("skipped-paragraph", source.as_bytes().to_vec())?;
    assert_budget_parity(source, &plan)?;
    assert!(matches!(
        try_locate(&document, &plan, ResourceBudget::conservative()),
        HtmlLocateDispatch::RetainedTree { .. }
    ));
    Ok(())
}

#[test]
#[allow(
    clippy::panic_in_result_fn,
    reason = "resource-bound differential uses assertions while propagating authoring errors"
)]
fn formatting_repair_in_skipped_row_bounds_selector_work_without_losing_admission()
-> Result<(), Box<dyn Error>> {
    let source = concat!(
        "<!doctype html><html><head></head><body><main>",
        "<article class='row' data-id='other'><b><i>x</b>y</i></article>",
        "<article class='row' data-id='target'><span class='value'>ok</span></article>",
        "</main></body></html>",
    );
    let plan = Plan::new([output(
        "value",
        css("article.row[data-id='target'] span.value")?.text(),
    )?])?;
    let document = Document::html("skipped-formatting", source.as_bytes().to_vec())?;
    assert!(matches!(
        try_locate(&document, &plan, ResourceBudget::conservative()),
        HtmlLocateDispatch::Completed {
            outcome: LocateOutcome::Matched { .. },
            ..
        }
    ));
    assert_budget_parity(source, &plan)?;
    assert_candidate_threshold_parity(source, &plan)
}

#[test]
#[allow(
    clippy::panic_in_result_fn,
    reason = "resource-bound differential uses assertions while propagating authoring errors"
)]
fn implied_table_elements_in_skipped_row_bound_selector_work() -> Result<(), Box<dyn Error>> {
    let source = concat!(
        "<!doctype html><html><head></head><body><main>",
        "<article class='row' data-id='other'><table><tr><td>x</td></tr></table></article>",
        "<article class='row' data-id='target'><span class='value'>ok</span></article>",
        "</main></body></html>",
    );
    let plan = Plan::new([output(
        "value",
        css("article.row[data-id='target'] span.value")?.text(),
    )?])?;
    let document = Document::html("skipped-table", source.as_bytes().to_vec())?;
    assert!(matches!(
        try_locate(&document, &plan, ResourceBudget::conservative()),
        HtmlLocateDispatch::Completed {
            outcome: LocateOutcome::Matched { .. },
            ..
        }
    ));
    assert_budget_parity(source, &plan)?;
    assert_candidate_threshold_parity(source, &plan)
}

#[test]
#[allow(
    clippy::panic_in_result_fn,
    reason = "cross-context HTML5 differential uses assertions while propagating authoring errors"
)]
fn skipped_list_item_cannot_repair_an_outer_list_context() -> Result<(), Box<dyn Error>> {
    let source = concat!(
        "<!doctype html><html><head></head><body><ul><li>",
        "<article class='row' data-id='other'><li>x</li></article>",
        "<article class='row' data-id='target'><span class='value'>ok</span></article>",
        "</li></ul></body></html>",
    );
    let plan = Plan::new([output(
        "value",
        css("article.row[data-id='target'] span.value")?.text(),
    )?])?;
    let document = Document::html("outer-list-repair", source.as_bytes().to_vec())?;
    let budget = ResourceBudget::conservative();
    assert!(matches!(
        try_locate(&document, &plan, budget),
        HtmlLocateDispatch::RetainedTree { .. }
    ));
    assert_eq!(
        document.locate_with_budget(&plan, budget),
        document.parse_with_budget(budget)?.locate(&plan)
    );
    Ok(())
}

#[test]
#[allow(
    clippy::panic_in_result_fn,
    reason = "cross-context HTML5 differential uses assertions while propagating authoring errors"
)]
fn skipped_rows_cannot_change_outer_heading_button_or_form_state() -> Result<(), Box<dyn Error>> {
    let plan = Plan::new([output(
        "value",
        css("article.row[data-id='target'] span.value")?.text(),
    )?])?;
    let budget = ResourceBudget::conservative();
    for (label, source) in [
        (
            "heading",
            "<!doctype html><html><head></head><body><h2><article class='row' data-id='other'><h2>x</h2></article><article class='row' data-id='target'><span class='value'>ok</span></article></h2></body></html>",
        ),
        (
            "button",
            "<!doctype html><html><head></head><body><button><article class='row' data-id='other'><button>x</button></article><article class='row' data-id='target'><span class='value'>ok</span></article></button></body></html>",
        ),
        (
            "form",
            "<!doctype html><html><head></head><body><form><article class='row' data-id='other'><form>x</form></article><article class='row' data-id='target'><span class='value'>ok</span></article></form></body></html>",
        ),
    ] {
        let document = Document::html(label, source.as_bytes().to_vec())?;
        assert!(matches!(
            try_locate(&document, &plan, budget),
            HtmlLocateDispatch::RetainedTree { .. }
        ));
        assert_eq!(
            document.locate_with_budget(&plan, budget),
            document.parse_with_budget(budget)?.locate(&plan),
            "outer context: {label}"
        );
    }
    Ok(())
}

#[test]
#[allow(
    clippy::panic_in_result_fn,
    reason = "form-pointer differential uses assertions while propagating authoring errors"
)]
fn nested_form_tokens_use_the_authoritative_html5_tree() -> Result<(), Box<dyn Error>> {
    let source = concat!(
        "<!doctype html><html><head></head><body><form>",
        "<article class='row' data-id='target'><form><span class='value'>ok</span></form></article>",
        "</form></body></html>",
    );
    let plan = Plan::new([output(
        "value",
        css("article.row[data-id='target'] span.value")?.text(),
    )?])?;
    let document = Document::html("nested-form", source.as_bytes().to_vec())?;
    let budget = ResourceBudget::conservative();
    let first_form = source.find("<form>").ok_or("outer form missing")?;
    assert!(matches!(
        try_locate(&document, &plan, budget),
        HtmlLocateDispatch::RetainedTree { attempt, .. }
            if attempt.parser_offset == u64::try_from(first_form).ok()
    ));
    assert_eq!(
        document.locate_with_budget(&plan, budget),
        document.parse_with_budget(budget)?.locate(&plan)
    );
    Ok(())
}

#[test]
#[allow(
    clippy::panic_in_result_fn,
    reason = "paragraph-repair differential uses assertions while propagating authoring errors"
)]
fn skipped_list_and_definition_starts_cannot_close_the_outer_paragraph()
-> Result<(), Box<dyn Error>> {
    let plan = Plan::new([output(
        "value",
        css("p.row[data-id='target'] span.value")?.text(),
    )?])?;
    let budget = ResourceBudget::conservative();
    for inner in ["<li>x</li>", "<dt>x</dt>", "<dd>x</dd>"] {
        let source = format!(
            "<!doctype html><html><head></head><body><ul><p class='row' data-id='other'>{inner}</p><p class='row' data-id='target'><span class='value'>ok</span></p></ul></body></html>"
        );
        let document = Document::html("paragraph-list-repair", source.into_bytes())?;
        assert!(matches!(
            try_locate(&document, &plan, budget),
            HtmlLocateDispatch::RetainedTree { .. }
        ));
        assert_eq!(
            document.locate_with_budget(&plan, budget),
            document.parse_with_budget(budget)?.locate(&plan),
            "inner tag: {inner}"
        );
    }
    Ok(())
}

#[test]
#[allow(
    clippy::panic_in_result_fn,
    reason = "deferred-record differential asserts the exact outer-depth proof"
)]
fn deferred_record_uses_its_saved_outer_depth_for_selector_work() -> Result<(), Box<dyn Error>> {
    let mut source = String::from("<!doctype html><html><head></head><body>");
    source.push_str(&"x".repeat(1_100_000));
    for _ in 0..40 {
        source.push_str("<div>");
    }
    source.push_str(
        "<article class='row' data-id='other'><span class='value'>noise</span></article>",
    );
    source
        .push_str("<article class='row' data-id='target'><span class='value'>ok</span></article>");
    for _ in 0..40 {
        source.push_str("</div>");
    }
    source.push_str("</body></html>");

    let plan = Plan::new([output(
        "value",
        css("article.row[data-id='target'] span.value")?.text(),
    )?])?;
    let high_budget = selector_budget(1_000_000)?;
    let compiled = plan
        .compiled_tree_plan(high_budget)
        .map_err(|_| "compiled selector plan unavailable")?;
    let Some(CompiledStreamingPlan::Selector(selector)) = compiled.streaming.as_ref() else {
        return Err("expected a certified selector plan".into());
    };
    let ScanAttempt::Complete(scan) = scanner::scan(&source, selector, high_budget) else {
        return Err("expected deferred scanner certification".into());
    };
    assert_eq!(scan.rightmost_match_count, 2);
    assert!(scan.rightmost_depth_sum_upper >= 80);
    assert_candidate_threshold_parity(&source, &plan)
}
