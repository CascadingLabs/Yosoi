use std::error::Error;

use super::super::HtmlLocateDispatch;
use super::routing::try_locate;
use crate::internal::documents::{Document, LocateOutcome, Plan, ResourceBudget, css, output};

pub(super) fn completed_outcome(dispatch: HtmlLocateDispatch) -> Option<LocateOutcome> {
    match dispatch {
        HtmlLocateDispatch::Completed { outcome, .. }
        | HtmlLocateDispatch::Terminal { outcome } => Some(outcome),
        HtmlLocateDispatch::RetainedTree { .. } => None,
    }
}

pub(super) fn attempt(source: String, selector: &str) -> Option<LocateOutcome> {
    let document = Document::html("streaming-test", source.into_bytes()).ok()?;
    let plan = Plan::new([output("value", css(selector).ok()?.text()).ok()?]).ok()?;
    completed_outcome(try_locate(&document, &plan, ResourceBudget::conservative()))
}

pub(super) fn attempt_plan(source: &str, plan: &Plan) -> Option<LocateOutcome> {
    let document = Document::html("streaming-plan-test", source.as_bytes().to_vec()).ok()?;
    completed_outcome(try_locate(&document, plan, ResourceBudget::conservative()))
}

#[allow(
    clippy::panic_in_result_fn,
    reason = "private differential helper uses an assertion"
)]
pub(super) fn admitted_equivalent(source: &str, plan: &Plan) -> Result<(), Box<dyn Error>> {
    let document = Document::html("streaming-equivalence", source.as_bytes().to_vec())?;
    let retained = document.parse()?.locate(plan);
    assert_eq!(
        completed_outcome(try_locate(&document, plan, ResourceBudget::conservative(),)),
        Some(retained)
    );
    Ok(())
}
