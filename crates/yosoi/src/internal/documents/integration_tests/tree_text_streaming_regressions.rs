#![allow(clippy::panic_in_result_fn)] // Differential conformance tests use direct assertions.

use std::{error::Error, fmt::Write as _, iter::repeat_n};

use crate::internal::documents::{
    Document, LocateFailure, LocateOutcome, NativeCoordinate, ParsedHtmlDocument, Plan,
    ProjectedValue, ResourceBudget, ResourceBudgetValues, ResourceLimit, TreeCoordinate, output,
    tree_text_contains,
};

fn document(id: &str, source: &str) -> Result<Document, Box<dyn Error>> {
    Ok(Document::html(id, source.as_bytes().to_vec())?)
}

fn plan(needle: &str) -> Result<Plan, Box<dyn Error>> {
    Ok(Plan::new([output(
        "match",
        tree_text_contains(needle)?.text(),
    )?])?)
}

fn node_plan(needle: &str) -> Result<Plan, Box<dyn Error>> {
    Ok(Plan::new([output(
        "match",
        tree_text_contains(needle)?.node(),
    )?])?)
}

fn budget(
    source_len: usize,
    max_nodes: u64,
    max_selector_visits: u64,
    max_depth: u32,
) -> Result<ResourceBudget, Box<dyn Error>> {
    let max_input_bytes = u64::try_from(source_len)?.saturating_add(1);
    Ok(ResourceBudget::try_new(ResourceBudgetValues {
        max_input_bytes,
        max_nodes,
        max_selector_visits,
        max_query_bytes: 4_096,
        max_query_steps: 64,
        max_regions: 16,
        max_matches: 128,
        max_captures: 64,
        max_depth,
        max_output_bytes: max_input_bytes.saturating_mul(2),
    })?)
}

fn assert_default_equivalent(
    document: &Document,
    plan: &Plan,
) -> Result<LocateOutcome, Box<dyn Error>> {
    let retained = document.parse()?.locate(plan);
    let direct = document.locate(plan);
    assert_eq!(direct, retained);
    Ok(direct)
}

fn assert_budget_equivalent(
    document: &Document,
    plan: &Plan,
    budget: ResourceBudget,
) -> Result<LocateOutcome, Box<dyn Error>> {
    let retained = document.parse_with_budget(budget)?.locate(plan);
    let direct = document.locate_with_budget(plan, budget);
    assert_eq!(direct, retained);
    Ok(direct)
}

#[test]
fn content_after_body_or_html_matches_the_repaired_retained_tree() -> Result<(), Box<dyn Error>> {
    let cases = [
        (
            "element-after-body.html",
            "<!doctype html><html><head></head><body><main>inside</main></body><section>after body needle</section></html>",
        ),
        (
            "text-after-body.html",
            "<!doctype html><html><head></head><body><main>inside</main></body>after body needle</html>",
        ),
        (
            "element-after-html.html",
            "<!doctype html><html><head></head><body><main>inside</main></body></html><section>after html needle</section>",
        ),
        (
            "text-after-html.html",
            "<!doctype html><html><head></head><body><main>inside</main></body></html>after html needle",
        ),
        (
            "extra-root-tokens.html",
            "<!doctype html><html><head></head><body><main>inside</main></body></html>\n<div>first root needle</div><aside>second root needle</aside>",
        ),
        (
            "implied-p-close.html",
            "<!doctype html><html><head></head><body><p>prefix<div>needle</div></p></body></html>",
        ),
    ];

    for (id, source) in cases {
        let document = document(id, source)?;
        for plan in [plan("needle")?, node_plan("needle")?] {
            let outcome = assert_default_equivalent(&document, &plan)?;
            assert!(matches!(outcome, LocateOutcome::Matched { .. }), "{id}");
        }
    }
    Ok(())
}

#[test]
fn declaration_tokens_preserve_the_exact_retained_node_limit() -> Result<(), Box<dyn Error>> {
    let cases = [
        (
            "processing-instruction.html",
            "<!doctype html><?target data?><html><head></head><body><span>needle</span></body></html>",
        ),
        (
            "bogus-declaration.html",
            "<!doctype html><!target data><html><head></head><body><span>needle</span></body></html>",
        ),
        (
            "repeated-doctype.html",
            "<!doctype html><!doctype html><html><head></head><body><span>needle</span></body></html>",
        ),
        (
            "mixed-declarations.html",
            "<!doctype html><?first?><!bogus><!doctype html><html><head></head><body><span>needle</span></body></html>",
        ),
    ];

    for (id, source) in cases {
        let document = document(id, source)?;
        let exact_nodes =
            ParsedHtmlDocument::parse(&document, ResourceBudget::conservative())?.node_count();
        let below = exact_nodes
            .checked_sub(1)
            .ok_or("retained HTML tree must contain at least one node")?;
        let plan = plan("needle")?;
        let below_budget = budget(source.len(), below, 1_000_000, 128)?;
        assert_eq!(
            document.locate_with_budget(&plan, below_budget),
            LocateOutcome::Failed {
                failure: LocateFailure::LimitExhausted {
                    limit: ResourceLimit::Nodes,
                    maximum: below,
                    observed: exact_nodes,
                },
            },
            "{id} admitted a result below the retained tree's exact node count"
        );

        let exact_budget = budget(source.len(), exact_nodes, 1_000_000, 128)?;
        assert!(matches!(
            assert_budget_equivalent(&document, &plan, exact_budget)?,
            LocateOutcome::Matched { .. }
        ));
    }
    Ok(())
}

#[test]
fn tree_text_selector_visit_boundary_matches_the_retained_path() -> Result<(), Box<dyn Error>> {
    const MAX_VISITS_SEARCHED: u64 = 10_000;

    let source = concat!(
        "<!doctype html><html><head></head><body><section>",
        "<p>prefix <em>needle</em> suffix</p>",
        "</section></body></html>",
    );
    let document = document("selector-boundary.html", source)?;
    let node_count =
        ParsedHtmlDocument::parse(&document, ResourceBudget::conservative())?.node_count();

    for plan in [plan("needle")?, node_plan("needle")?] {
        let exact_retained_visits = (1..=MAX_VISITS_SEARCHED)
            .find_map(|selector_visits| {
                let limits = budget(source.len(), node_count, selector_visits, 128).ok()?;
                matches!(
                    document.parse_with_budget(limits).ok()?.locate(&plan),
                    LocateOutcome::Matched { .. }
                )
                .then_some(selector_visits)
            })
            .ok_or("tree-text selector cost exceeded the bounded test search")?;
        let below = exact_retained_visits
            .checked_sub(1)
            .ok_or("tree-text selector cost must be positive")?;

        assert_eq!(
            assert_budget_equivalent(
                &document,
                &plan,
                budget(source.len(), node_count, below, 128)?,
            )?,
            LocateOutcome::Failed {
                failure: LocateFailure::LimitExhausted {
                    limit: ResourceLimit::SelectorVisits,
                    maximum: below,
                    observed: exact_retained_visits,
                },
            }
        );
        assert!(matches!(
            assert_budget_equivalent(
                &document,
                &plan,
                budget(source.len(), node_count, exact_retained_visits, 128)?,
            )?,
            LocateOutcome::Matched { .. }
        ));
    }
    Ok(())
}

#[test]
fn bounded_deep_large_text_selects_the_deepest_complete_element() -> Result<(), Box<dyn Error>> {
    const DEPTH: usize = 64;
    const PREFIX_BYTES: usize = 32 * 1_024;

    let mut source = String::from("<!doctype html><html><head></head><body>");
    for _ in 0..DEPTH {
        source.push_str("<div>");
    }
    source.extend(repeat_n('x', PREFIX_BYTES));
    source.push_str(" needle ");
    for _ in 0..DEPTH {
        source.push_str("</div>");
    }
    source.push_str("</body></html>");

    let document = document("deep-large-text.html", &source)?;
    let plan = plan("needle")?;
    let outcome = assert_default_equivalent(&document, &plan)?;
    let LocateOutcome::Matched { result } = outcome else {
        return Err("deep large-text fixture did not match".into());
    };
    let finding = result
        .findings()
        .first()
        .ok_or("deep large-text fixture returned no finding")?;
    let ProjectedValue::Text(text) = finding.value() else {
        return Err("tree-text projection did not return text".into());
    };
    assert_eq!(text.len(), PREFIX_BYTES + " needle".len());

    let mut expected_path = vec![1_u32, 2];
    expected_path.extend(repeat_n(1, DEPTH));
    assert_eq!(
        finding.coordinate(),
        &NativeCoordinate::SourceTree(TreeCoordinate::try_new(expected_path, None)?)
    );
    Ok(())
}

#[test]
fn bounded_large_text_without_a_match_remains_a_no_match() -> Result<(), Box<dyn Error>> {
    let mut source = String::from("<!doctype html><html><head></head><body><main>");
    write!(&mut source, "{}", "ordinary catalog text ".repeat(2_048))?;
    source.push_str("</main></body></html>");

    let document = document("large-text-miss.html", &source)?;
    assert!(matches!(
        assert_default_equivalent(&document, &plan("missing needle")?)?,
        LocateOutcome::NoMatch { .. }
    ));
    Ok(())
}
