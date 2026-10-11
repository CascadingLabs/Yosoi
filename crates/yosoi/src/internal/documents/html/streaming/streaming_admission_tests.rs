use super::plan::CompiledStreamingPlan;
use super::record_metrics::fast_record_metrics;
use super::routing::try_locate;
use super::scanner::{ImpliedKind, RecordMeasure};
use std::error::Error;

use super::test_support_tests::{admitted_equivalent, attempt_plan, completed_outcome};
use crate::internal::documents::{
    Document, Plan, ResourceBudget, ResourceBudgetValues, css, output, tree_text_contains, xpath,
};

#[test]
#[allow(
    clippy::panic_in_result_fn,
    reason = "private metric regression uses assertions while propagating plan construction errors"
)]
fn skipped_record_metrics_count_only_matching_rightmost_elements() -> Result<(), Box<dyn Error>> {
    let plan = Plan::new([output(
        "value",
        css("article.product-card[data-selected='true'] span.price")?.text(),
    )?])?;
    let compiled = plan
        .compiled_tree_plan(ResourceBudget::conservative())
        .map_err(|_| "failed to compile selector streaming plan")?;
    let Some(CompiledStreamingPlan::Selector(selector)) = compiled.streaming.as_ref() else {
        return Err("expected selector streaming plan".into());
    };
    let record = br#"<div data-one="1" data-two="2"><span class="price">USD 12.34</span><span class="availability">in stock</span></div>"#;
    let RecordMeasure::Metrics(metrics) =
        fast_record_metrics(record, selector, true, ImpliedKind::Other)
    else {
        return Err("expected directly certified record metrics".into());
    };

    assert_eq!(metrics.rightmost_matches, 1);
    assert_eq!(metrics.max_attribute_count, 2);
    Ok(())
}

#[test]
#[allow(
    clippy::panic_in_result_fn,
    reason = "private conformance test uses assertions"
)]
fn admits_css_root_attribute_and_node_projections() -> Result<(), Box<dyn Error>> {
    let source = "<!doctype html><html><body><section><div class='row' data-id='a'></div><div class='row' data-id='b'></div></section></body></html>";
    let attribute = Plan::new([output("id", css("div.row")?.attribute("data-id")?)?])?;
    let node = Plan::new([output("node", css("div.row")?.node())?])?;
    assert!(attempt_plan(source, &attribute).is_some());
    assert!(attempt_plan(source, &node).is_some());
    Ok(())
}

#[test]
#[allow(
    clippy::panic_in_result_fn,
    reason = "private conformance test uses assertions"
)]
fn admits_equivalent_xpath_text_attribute_and_node() -> Result<(), Box<dyn Error>> {
    let source = "<!doctype html><html><body><ul><li data-selected='true'><span class='value' data-id='a'>yes</span></li><li data-selected='false'><span class='value' data-id='b'>no</span></li></ul></body></html>";
    let text = Plan::new([output(
        "text",
        xpath("//li[@data-selected='true']//span[@class='value']")?.text(),
    )?])?;
    let attribute = Plan::new([output(
        "id",
        xpath("//li[@data-selected='true']//span[@class='value']")?.attribute("data-id")?,
    )?])?;
    let node = Plan::new([output(
        "node",
        xpath("//li[@data-selected='true']//span[@class='value']")?.node(),
    )?])?;
    for plan in [text, attribute, node] {
        assert!(attempt_plan(source, &plan).is_some());
    }
    Ok(())
}

#[test]
#[allow(
    clippy::panic_in_result_fn,
    reason = "private conformance test uses assertions"
)]
fn admits_tree_text_text_node_lca_and_overlaps() -> Result<(), Box<dyn Error>> {
    let source = "<!doctype html><html><body><section><div><span>alpha <mark>beta</mark></span><p>aaaa</p></div></section></body></html>";
    let text = Plan::new([output("text", tree_text_contains("alpha beta")?.text())?])?;
    let node = Plan::new([output("node", tree_text_contains("alpha beta")?.node())?])?;
    let overlap = Plan::new([output("overlap", tree_text_contains("aaa")?.text())?])?;
    for plan in [text, node, overlap] {
        admitted_equivalent(source, &plan)?;
    }
    admitted_equivalent(
        "<!doctype html><html><body><div>needle<span>needle</span><p>needle</p></div></body></html>",
        &Plan::new([output("deepest", tree_text_contains("needle")?.text())?])?,
    )?;
    let fallback =
        "<!doctype html><html><body><table><tr><td>alpha beta</td></tr></table></body></html>";
    assert!(
        attempt_plan(
            fallback,
            &Plan::new([output("x", tree_text_contains("alpha")?.text())?])?
        )
        .is_none()
    );
    Ok(())
}

#[test]
#[allow(
    clippy::panic_in_result_fn,
    reason = "private certificate test uses assertions"
)]
fn tree_text_rejects_unstable_document_boundaries() -> Result<(), Box<dyn Error>> {
    let plan = Plan::new([output("x", tree_text_contains("needle")?.text())?])?;
    let sources = [
        "<!doctype html><html><head></head><body>x</body>needle</html>",
        "<!doctype html><html><head></head><body>x</body></html><div>needle</div>",
        "needle<!doctype html><html><head></head><body>x</body></html>",
        "<!doctype html><html><head></head><body>x</body></html><html><body>needle</body></html>",
        "<!doctype html><html><head></head>needle<body>x</body></html>",
        "<!doctype html><html><head></head><body><p>prefix<div>needle</div></p></body></html>",
        "<!doctype html><html><head></head><body><ul><li>one<li>needle</ul></body></html>",
        "<!doctype html><html><head></head><body><p>prefix<figure>needle</figure></p></body></html>",
        "<!doctype html><html><head></head><body><head><span>needle</span></head></body></html>",
        "<!doctype html><html><head></head><body><body><span>needle</span></body></body></html>",
        "<!doctype html><html><head><div></div></head><body><span>needle</span></body></html>",
        "<!doctype html><html><head></head><body:custom>needle</body:custom></html>",
        "<!doctype html><html><head></head><body><img:custom>needle</img:custom></body></html>",
    ];
    for source in sources {
        assert!(attempt_plan(source, &plan).is_none(), "admitted {source}");
    }
    Ok(())
}

#[test]
#[allow(
    clippy::panic_in_result_fn,
    reason = "private certificate test uses assertions"
)]
fn tree_text_rejects_unaccounted_declarations() -> Result<(), Box<dyn Error>> {
    let plan = Plan::new([output("x", tree_text_contains("needle")?.text())?])?;
    let sources = [
        "<!doctype html><?pi?><html><head></head><body>needle</body></html>",
        "<!doctype html><!bogus><html><head></head><body>needle</body></html>",
        "<!doctype html><!doctype html><html><head></head><body>needle</body></html>",
    ];
    for source in sources {
        assert!(attempt_plan(source, &plan).is_none(), "admitted {source}");
    }
    Ok(())
}

#[test]
#[allow(
    clippy::panic_in_result_fn,
    reason = "private limit-equivalence test uses assertions"
)]
fn tree_text_admission_preserves_every_selector_visit_boundary() -> Result<(), Box<dyn Error>> {
    let source = "<!doctype html><html><head></head><body><section><p>prefix <mark>needle</mark> suffix</p></section></body></html>";
    let document = Document::html("tree-text-budget", source.as_bytes().to_vec())?;
    let plan = Plan::new([output("x", tree_text_contains("needle")?.text())?])?;
    for maximum in 1..=160_u64 {
        let budget = ResourceBudget::try_new(ResourceBudgetValues {
            max_input_bytes: 4_096,
            max_nodes: 128,
            max_selector_visits: maximum,
            max_query_bytes: 4_096,
            max_query_steps: 64,
            max_regions: 16,
            max_matches: 128,
            max_captures: 64,
            max_depth: 128,
            max_output_bytes: 4_096,
        })?;
        let retained = document.parse_with_budget(budget)?.locate(&plan);
        assert_eq!(
            completed_outcome(try_locate(&document, &plan, budget)),
            Some(retained),
            "maximum={maximum}"
        );
    }
    Ok(())
}
