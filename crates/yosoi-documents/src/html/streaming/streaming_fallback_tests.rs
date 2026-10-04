use std::{
    env,
    error::Error,
    fmt::{self, Write as _},
    fs,
};

use super::super::{
    HtmlAttemptFacts, HtmlAttemptFallbackReason, HtmlFallbackReason, HtmlLocateDispatch,
    HtmlPreflightFallbackReason,
};
use super::super::{ParsedHtmlDocument, parse_failure};
use super::routing::try_locate;
use super::test_support_tests::{admitted_equivalent, attempt, attempt_plan, completed_outcome};
use crate::{
    Document, LocateOutcome, Plan, ResourceBudget, ResourceBudgetValues, css, output, xpath,
};

#[test]
fn admits_generic_stable_containers() {
    let source = "<!doctype html><html><body><section><div class='row' data-id='x'><span class='value'>yes</span></div><div class='row' data-id='y'><span class='value'>no</span></div></section></body></html>".to_owned();
    assert!(matches!(
        attempt(source, "div.row[data-id='x'] span.value"),
        Some(LocateOutcome::Matched { .. })
    ));
}

#[test]
#[allow(
    clippy::panic_in_result_fn,
    reason = "private HTML5 differential uses an assertion while propagating plan errors"
)]
fn pre_body_text_forces_the_retained_html5_route() -> Result<(), Box<dyn Error>> {
    let plan = Plan::new([output("value", css("div.row span.value")?.text())?])?;
    let budget = ResourceBudget::conservative();
    for source in [
        "\u{00a0}<!doctype html><html><head></head><body><div class='row'><span class='value'>kept</span></div></body></html>",
        "<!doctype html>prefix<html><head></head><body><div class='row'><span class='value'>kept</span></div></body></html>",
    ] {
        let document = Document::html("pre-body-text", source.as_bytes().to_vec())?;
        assert!(matches!(
            try_locate(&document, &plan, budget),
            HtmlLocateDispatch::RetainedTree {
                reason: HtmlFallbackReason::Attempt(HtmlAttemptFallbackReason::Certificate),
                ..
            }
        ));
        let retained = document.parse_with_budget(budget)?.locate(&plan);
        assert!(matches!(retained, LocateOutcome::Matched { .. }));
        assert_eq!(document.locate_with_budget(&plan, budget), retained);
    }
    Ok(())
}

#[test]
fn certifies_bounded_noncandidate_foreign_subtree() -> Result<(), Box<dyn Error>> {
    let source = "<!doctype html><html><head></head><body><section><div class='row' data-id='other'><svg viewBox='0 0 1 1'><path d='M0 0'/></svg></div><div class='row' data-id='target'><span class='value'>yes</span></div></section></body></html>";
    admitted_equivalent(
        source,
        &Plan::new([output(
            "value",
            css("div.row[data-id='target'] span.value")?.text(),
        )?])?,
    )
}

#[test]
fn certifies_bounded_noncandidate_repair_island() -> Result<(), Box<dyn Error>> {
    let source = "<!doctype html><html><head></head><body><section><div class='row' data-id='other'><p><b>one<i>two</b>three</i></div><div class='row' data-id='target'><span class='value'>yes</span></div></section></body></html>";
    admitted_equivalent(
        source,
        &Plan::new([output(
            "value",
            css("div.row[data-id='target'] span.value")?.text(),
        )?])?,
    )
}

#[test]
#[allow(
    clippy::panic_in_result_fn,
    reason = "private island budget differential uses assertions"
)]
fn island_node_bounds_never_underestimate_retained_html() -> Result<(), Box<dyn Error>> {
    let source = concat!(
        "<!doctype html><html><head></head><body><main>",
        "<article class='row' data-id='other'>before<div>a<span>b</span>c</div>d",
        "<p><div>x</div></p><p><div>y</div></p>",
        "<table>\n<tr><td>0</td><td>1</td><td>2</td><td>3</td>",
        "<td>4</td><td>5</td><td>6</td><td>7</td></tr>\n</table></article>",
        "<article class='row' data-id='target'><span class='value'>ok</span></article>",
        "</main></body></html>",
    );
    let document = Document::html("island-node-budget", source.as_bytes().to_vec())?;
    let plan = Plan::new([output(
        "value",
        css("article.row[data-id='target'] span.value")?.text(),
    )?])?;
    let exact_nodes =
        ParsedHtmlDocument::parse(&document, ResourceBudget::conservative())?.node_count();
    for maximum in exact_nodes.saturating_sub(2)..=exact_nodes.saturating_add(1) {
        let limits = ResourceBudget::try_new(ResourceBudgetValues {
            max_input_bytes: u64::try_from(source.len())?.saturating_add(1),
            max_nodes: maximum,
            max_selector_visits: 1_000_000,
            max_query_bytes: 4_096,
            max_query_steps: 64,
            max_regions: 16,
            max_matches: 16,
            max_captures: 64,
            max_depth: 128,
            max_output_bytes: 4_096,
        })?;
        let retained = match ParsedHtmlDocument::parse(&document, limits) {
            Ok(parsed) => parsed.locate_with_budget(&plan, limits),
            Err(error) => LocateOutcome::Failed {
                failure: parse_failure(&error),
            },
        };
        if let Some(streamed) = completed_outcome(try_locate(&document, &plan, limits)) {
            assert_eq!(streamed, retained, "maximum={maximum}");
        }
    }
    Ok(())
}

#[test]
#[allow(
    clippy::panic_in_result_fn,
    reason = "optional frozen-fixture regression uses assertions while propagating filesystem errors"
)]
fn admits_optional_frozen_caveman_fixture() -> Result<(), Box<dyn Error>> {
    let Ok(path) = env::var("YOSOI_BENCHMARK_FIXTURE") else {
        return Ok(());
    };
    let source = fs::read_to_string(path)?;
    let document = Document::html("caveman-budget", source.as_bytes().to_vec())?;
    let plan = Plan::new([output(
        "value",
        css("article.product-card[data-sku='sku-000073'] span.price")?.text(),
    )?])?;
    admitted_equivalent(&source, &plan)?;
    let selected_plan = Plan::new([output(
        "value",
        css("article.product-card[data-selected='true'] span.price")?.text(),
    )?])?;
    admitted_equivalent(&source, &selected_plan)?;
    let exact_nodes =
        ParsedHtmlDocument::parse(&document, ResourceBudget::conservative())?.node_count();
    let budget = |max_nodes,
                  max_depth,
                  max_selector_visits,
                  max_output_bytes|
     -> Result<ResourceBudget, Box<dyn Error>> {
        ResourceBudget::try_new(ResourceBudgetValues {
            max_input_bytes: u64::try_from(source.len())?.saturating_add(1),
            max_nodes,
            max_selector_visits,
            max_query_bytes: 4_096,
            max_query_steps: 64,
            max_regions: 16,
            max_matches: 128,
            max_captures: 64,
            max_depth,
            max_output_bytes,
        })
        .map_err(Into::into)
    };
    let forced = |limits| match ParsedHtmlDocument::parse(&document, limits) {
        Ok(parsed) => parsed.locate_with_budget(&plan, limits),
        Err(error) => LocateOutcome::Failed {
            failure: parse_failure(&error),
        },
    };
    for limits in [
        budget(exact_nodes.saturating_sub(1), 1_024, 10_000_000, 16_777_216)?,
        budget(exact_nodes, 1_024, 10_000_000, 16_777_216)?,
        budget(exact_nodes.saturating_add(1), 1_024, 10_000_000, 16_777_216)?,
        budget(1_000_000, 4, 10_000_000, 16_777_216)?,
        budget(1_000_000, 1_024, 1_000, 16_777_216)?,
        budget(1_000_000, 1_024, 10_000_000, 1)?,
    ] {
        if let Some(streamed) = completed_outcome(try_locate(&document, &plan, limits)) {
            assert_eq!(streamed, forced(limits));
        }
    }
    Ok(())
}

#[test]
#[allow(
    clippy::panic_in_result_fn,
    reason = "conformance unit test uses assertions while propagating fmt errors"
)]
fn admits_list_grid_and_hard_shaped_multi_match() -> Result<(), fmt::Error> {
    let mut rows = String::new();
    for index in 0..512 {
        let selected = index.to_string().ends_with('0');
        write!(
            rows,
            "<li class='row' data-selected='{selected}'><label>{index}</label><span class='value'>v{index}</span></li>"
        )?;
    }
    let source = format!("<!doctype html><html><head></head><body><ul>{rows}</ul></body></html>");
    assert!(matches!(
        attempt(source, "li.row[data-selected='true'] span.value"),
        Some(LocateOutcome::Matched { .. })
    ));
    Ok(())
}

#[test]
#[allow(
    clippy::panic_in_result_fn,
    reason = "private parallel conformance test uses assertions while propagating fmt errors"
)]
fn large_grid_parallel_admission_is_repeatable() -> Result<(), fmt::Error> {
    let mut rows = String::new();
    let padding = "x".repeat(1_024);
    for index in 0..2_048 {
        let selected = index.to_string().ends_with("00");
        write!(
            rows,
            "<li class='row' data-selected='{selected}'><span>{padding}</span><span class='value'>v{index}</span></li>"
        )?;
    }
    let source = format!("<!doctype html><html><head></head><body><ul>{rows}</ul></body></html>");
    let first = attempt(source.clone(), "li.row[data-selected='true'] span.value");
    let second = attempt(source, "li.row[data-selected='true'] span.value");
    assert!(first.is_some());
    assert_eq!(first, second);
    Ok(())
}

#[test]
fn falls_back_for_candidate_repair_or_unstable_parent() {
    let repaired = "<!doctype html><html><head></head><body><section><div class='row'><b><i>x</b><span class='value'>y</span></i></div></section></body></html>".to_owned();
    assert!(attempt(repaired, "div.row span.value").is_none());
    let split = "<!doctype html><html><head></head><body><section><div class='row'><span class='value'>a</span></div></section><aside><div class='row'><span class='value'>b</span></div></aside></body></html>".to_owned();
    assert!(attempt(split, "div.row span.value").is_none());
    let mixed = "<!doctype html><html><head></head><body><section><div class='row'><span class='value'>a</span></div><aside></aside><div class='row'><span class='value'>b</span></div></section></body></html>".to_owned();
    assert!(attempt(mixed, "div.row span.value").is_none());
}

#[test]
#[allow(
    clippy::panic_in_result_fn,
    reason = "private certificate test uses direct assertions"
)]
fn falls_back_for_table_shift_and_entities() -> Result<(), Box<dyn Error>> {
    let table = "<!doctype html><html><head></head><body><section><div class='row'><table><tr><td>x</td></tr></table><span class='value'>y</span></div></section></body></html>".to_owned();
    assert!(attempt(table, "div.row span.value").is_none());
    let entity = "<!doctype html><html><head></head><body><div class='row'><span class='value'>&amp;</span></div></body></html>".to_owned();
    assert!(attempt(entity, "div.row span.value").is_none());
    let title =
        "<!doctype html><html><head><title>hello<br>world</title></head><body></body></html>"
            .to_owned();
    assert!(attempt(title, "title > br").is_none());
    let noframes =
        "<!doctype html><html><head><noframes><br></noframes></head><body></body></html>"
            .to_owned();
    assert!(attempt(noframes, "noframes > br").is_none());
    let fostered = "<!doctype html><html><head></head><body><table><br></table><article><span>ok</span></article></body></html>".to_owned();
    assert!(attempt(fostered, "article span").is_none());
    let implied_tbody = "<!doctype html><html><head></head><body><article><table><tr><td>ok</td></tr></table></article></body></html>";
    for plan in [
        Plan::new([output("tbody", css("article tbody")?.node())?])?,
        Plan::new([output("tbody", xpath("//article//tbody")?.node())?])?,
    ] {
        assert!(attempt_plan(implied_tbody, &plan).is_none());
    }
    let foreign_breakout = "<!doctype html><html><head></head><body><svg><br></svg><article><span>ok</span></article></body></html>".to_owned();
    assert!(attempt(foreign_breakout, "article span").is_none());
    let keygen = "<!doctype html><html><head></head><body><article><keygen><span>ok</span></keygen></article></body></html>".to_owned();
    admitted_equivalent(
        &keygen,
        &Plan::new([output("span", css("article span")?.text())?])?,
    )?;
    let prefixed_body =
        "<!doctype html><html><head></head><body:custom><span>ok</span></body:custom></html>"
            .to_owned();
    assert!(attempt(prefixed_body, "body span").is_none());
    let displaced_head = "<!doctype html><html><head><p>x</p></head><body><article><span>ok</span></article></body></html>".to_owned();
    assert!(attempt(displaced_head, "article span").is_none());
    let adoption_leak = format!(
        "<!doctype html><html><head></head><body><main><article class='row' data-id='other'><b>{}x</b>{}</article><article class='row' data-id='target'><span class='value'>ok</span></article></main></body></html>",
        "<div>".repeat(9),
        "</div>".repeat(9),
    );
    let adoption_plan = Plan::new([output(
        "value",
        css("article.row[data-id='target'] > span.value")?.node(),
    )?])?;
    assert!(attempt_plan(&adoption_leak, &adoption_plan).is_none());
    let table_text_reorder = "<!doctype html><html><head></head><body><article class='row' data-id='target'><span class='value'><table><tr><td>A</td></tr>B</table></span></article></body></html>";
    let table_text_plan = Plan::new([output(
        "value",
        css("article.row[data-id='target'] > span.value")?.text(),
    )?])?;
    assert!(attempt_plan(table_text_reorder, &table_text_plan).is_none());
    Ok(())
}

#[test]
#[allow(
    clippy::panic_in_result_fn,
    reason = "private fallback differential uses assertions while propagating parse errors"
)]
fn unsupported_plan_is_classified_before_streaming_and_uses_retained_semantics()
-> Result<(), Box<dyn Error>> {
    let source = "<!doctype html><html><head></head><body><div class='row'><span class='value'>kept</span></div></body></html>";
    let document = Document::html("streaming-early-fallback", source.as_bytes().to_vec())?;
    let plan = Plan::new([
        output("value", css("div.row span.value")?.text())?,
        output("row", css("div.row")?.node())?,
    ])?;
    let budget = ResourceBudget::conservative();

    let dispatch = try_locate(&document, &plan, budget);
    assert!(matches!(
        dispatch,
        HtmlLocateDispatch::RetainedTree {
            reason: HtmlFallbackReason::Preflight(
                HtmlPreflightFallbackReason::PlanOutsideCertifiedSubset
            ),
            attempt: HtmlAttemptFacts {
                parser_offset: None,
                candidate_work: None,
                ..
            },
        }
    ));

    let forced = document.parse_with_budget(budget)?.locate(&plan);
    assert_eq!(document.locate_with_budget(&plan, budget), forced);
    Ok(())
}

#[test]
#[allow(
    clippy::panic_in_result_fn,
    reason = "private late-fallback differential uses assertions while propagating parse errors"
)]
fn late_hazard_discards_partial_matches_and_uses_retained_semantics() -> Result<(), Box<dyn Error>>
{
    let source = concat!(
        "<!doctype html><html><head></head><body><section>",
        "<div class='row'><span class='value'>kept</span></div>",
        "</section><table><tbody><tr><td>later</td></tr></tbody></table>",
        "</body></html>",
    );
    let document = Document::html("streaming-late-fallback", source.as_bytes().to_vec())?;
    let plan = Plan::new([output("value", css("div.row span.value")?.text())?])?;
    let budget = ResourceBudget::conservative();

    let dispatch = try_locate(&document, &plan, budget);
    let HtmlLocateDispatch::RetainedTree { reason, attempt } = dispatch else {
        return Err(
            "late table hazard must reject the candidate and select the retained tree".into(),
        );
    };
    assert_eq!(
        reason,
        HtmlFallbackReason::Attempt(HtmlAttemptFallbackReason::Certificate)
    );
    let value_offset = source
        .find("<span class='value'>")
        .ok_or("matching span must be present")?;
    assert!(attempt.parser_offset.is_some_and(|offset| {
        usize::try_from(offset).is_ok_and(|offset| offset > value_offset)
    }));
    assert!(attempt.candidate_work.is_some_and(|work| work > 0));

    // The rejected attempt carries no LocateOutcome, so its earlier match
    // cannot leak. The public operation rereads immutable bytes through HTML5.
    let forced = document.parse_with_budget(budget)?.locate(&plan);
    assert_eq!(document.locate_with_budget(&plan, budget), forced);
    assert!(matches!(forced, LocateOutcome::Matched { .. }));
    Ok(())
}

#[test]
#[allow(
    clippy::panic_in_result_fn,
    reason = "private budget differential uses assertions while propagating parse errors"
)]
fn selector_budget_rejection_matches_the_retained_evaluator() -> Result<(), Box<dyn Error>> {
    let source = "<!doctype html><html><head></head><body><div class='row'><span class='value'>kept</span></div></body></html>";
    let document = Document::html("streaming-budget-fallback", source.as_bytes().to_vec())?;
    let plan = Plan::new([output("value", css("div.row span.value")?.text())?])?;
    let budget = ResourceBudget::try_new(ResourceBudgetValues {
        max_input_bytes: u64::try_from(source.len())?.saturating_add(1),
        max_nodes: 1_000_000,
        max_selector_visits: 1,
        max_query_bytes: 65_536,
        max_query_steps: 256,
        max_regions: 64,
        max_matches: 100_000,
        max_captures: 16_384,
        max_depth: 1_024,
        max_output_bytes: 16_777_216,
    })?;

    let dispatch = try_locate(&document, &plan, budget);
    assert!(matches!(
        dispatch,
        HtmlLocateDispatch::RetainedTree {
            reason: HtmlFallbackReason::Attempt(
                HtmlAttemptFallbackReason::ResourceProof
            ),
            attempt: HtmlAttemptFacts {
                candidate_work: Some(work),
                ..
            },
        } if work > 1
    ));

    let forced = document.parse_with_budget(budget)?.locate(&plan);
    assert_eq!(document.locate_with_budget(&plan, budget), forced);
    Ok(())
}
