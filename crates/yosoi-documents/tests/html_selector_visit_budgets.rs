#![allow(clippy::panic_in_result_fn)] // Conformance tests use direct assertions.

use std::{error::Error, io};

use yosoi_documents::{
    Document, LocateFailure, LocateOutcome, Plan, ResourceBudget, ResourceBudgetValues,
    ResourceLimit, css, output, xpath,
};

#[derive(Clone, Copy)]
enum ExpectedOutcome {
    Matched,
    NoMatch,
}

fn html(source: &str) -> Result<Document, Box<dyn Error>> {
    Ok(Document::html(
        "selector-budget.html",
        source.as_bytes().to_vec(),
    )?)
}

fn selector_budget(maximum: u64) -> Result<ResourceBudget, Box<dyn Error>> {
    Ok(ResourceBudget::try_new(ResourceBudgetValues {
        max_input_bytes: 16_384,
        max_nodes: 1_024,
        max_selector_visits: maximum,
        max_query_bytes: 4_096,
        max_query_steps: 64,
        max_regions: 16,
        max_matches: 128,
        max_captures: 64,
        max_depth: 128,
        max_output_bytes: 16_384,
    })?)
}

fn assert_exact_selector_cost(
    document: &Document,
    plan: &Plan,
    exact_visits: u64,
    expected: ExpectedOutcome,
) -> Result<(), Box<dyn Error>> {
    let below = exact_visits
        .checked_sub(1)
        .ok_or_else(|| io::Error::other("selector cost must be positive"))?;
    assert_eq!(
        document.locate_with_budget(plan, selector_budget(below)?),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::SelectorVisits,
                maximum: below,
                observed: exact_visits,
            },
        }
    );
    let exact = document.locate_with_budget(plan, selector_budget(exact_visits)?);
    match expected {
        ExpectedOutcome::Matched => assert!(
            matches!(exact, LocateOutcome::Matched { .. }),
            "expected a match at exactly {exact_visits} visits, got {exact:?}"
        ),
        ExpectedOutcome::NoMatch => assert!(
            matches!(exact, LocateOutcome::NoMatch { .. }),
            "expected no match at exactly {exact_visits} visits, got {exact:?}"
        ),
    }
    Ok(())
}

#[test]
fn one_step_css_and_xpath_hits_and_misses_have_stable_costs() -> Result<(), Box<dyn Error>> {
    let document = html("<div>target</div>")?;
    let cases = [
        (
            Plan::new([output("css_hit", css("div")?.text())?])?,
            ExpectedOutcome::Matched,
        ),
        (
            Plan::new([output("css_miss", css("aside")?.text())?])?,
            ExpectedOutcome::NoMatch,
        ),
        (
            Plan::new([output("xpath_hit", xpath("//div")?.text())?])?,
            ExpectedOutcome::Matched,
        ),
        (
            Plan::new([output("xpath_miss", xpath("//aside")?.text())?])?,
            ExpectedOutcome::NoMatch,
        ),
    ];
    for (plan, expected) in cases {
        assert_exact_selector_cost(&document, &plan, 8, expected)?;
    }
    Ok(())
}

#[test]
fn attribute_position_and_selector_groups_charge_each_observed_candidate()
-> Result<(), Box<dyn Error>> {
    let document = html("<div data-first='yes' middle='x' data-last='yes'>target</div>")?;
    let css_first = Plan::new([output("first", css("div[data-first]")?.text())?])?;
    let css_last = Plan::new([output("last", css("div[data-last]")?.text())?])?;
    let xpath_first = Plan::new([output("first", xpath("//div[@data-first]")?.text())?])?;
    let xpath_last = Plan::new([output("last", xpath("//div[@data-last]")?.text())?])?;
    let grouped = Plan::new([output("grouped", css("aside, div")?.text())?])?;

    assert_exact_selector_cost(&document, &css_first, 10, ExpectedOutcome::Matched)?;
    assert_exact_selector_cost(&document, &css_last, 12, ExpectedOutcome::Matched)?;
    assert_exact_selector_cost(&document, &xpath_first, 10, ExpectedOutcome::Matched)?;
    assert_exact_selector_cost(&document, &xpath_last, 12, ExpectedOutcome::Matched)?;
    assert_exact_selector_cost(&document, &grouped, 12, ExpectedOutcome::Matched)?;
    Ok(())
}

#[test]
fn child_and_descendant_backtracking_have_distinct_stable_costs() -> Result<(), Box<dyn Error>> {
    let document = html("<main><section><span>target</span></section></main>")?;
    let css_child = Plan::new([output("child", css("main > section > span")?.text())?])?;
    let css_descendant = Plan::new([output("descendant", css("main span")?.text())?])?;
    let xpath_child = Plan::new([output("child", xpath("//main/section/span")?.text())?])?;
    let xpath_descendant = Plan::new([output("descendant", xpath("//main//span")?.text())?])?;

    assert_exact_selector_cost(&document, &css_child, 14, ExpectedOutcome::Matched)?;
    assert_exact_selector_cost(&document, &css_descendant, 19, ExpectedOutcome::Matched)?;
    assert_exact_selector_cost(&document, &xpath_child, 14, ExpectedOutcome::Matched)?;
    assert_exact_selector_cost(&document, &xpath_descendant, 19, ExpectedOutcome::Matched)?;
    Ok(())
}

#[test]
fn scoped_region_selection_charges_region_and_descendant_checks_once() -> Result<(), Box<dyn Error>>
{
    let document = html("<main><span>target</span></main>")?;
    let regions = css("main")?.each_as_region("main")?;
    let plan = Plan::new([output("scoped", regions.find(css("span")?).text())?])?;

    assert_exact_selector_cost(&document, &plan, 21, ExpectedOutcome::Matched)?;
    Ok(())
}

#[test]
fn foreign_content_name_and_attribute_checks_remain_bounded() -> Result<(), Box<dyn Error>> {
    let document = html("<svg viewBox='0 0 1 1'><circle id='dot'>target</circle></svg>")?;
    let one_step = Plan::new([output("circle", css("circle#dot")?.text())?])?;
    let ancestry = Plan::new([output(
        "circle",
        css("svg[viewBox='0 0 1 1'] > circle#dot")?.text(),
    )?])?;

    assert_exact_selector_cost(&document, &one_step, 12, ExpectedOutcome::Matched)?;
    assert_exact_selector_cost(&document, &ancestry, 15, ExpectedOutcome::Matched)?;
    Ok(())
}
