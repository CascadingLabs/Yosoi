#![allow(clippy::panic_in_result_fn)] // Conformance tests use direct assertions.

use std::{error::Error, io};

use yosoi_documents::{
    Document, LocateFailure, LocateOutcome, NativeCoordinate, Plan, ProjectedValue, ResourceBudget,
    ResourceBudgetValues, ResourceLimit, TreeCoordinate, css, output,
};

fn html(source: &str) -> Result<Document, Box<dyn Error>> {
    Ok(Document::html(
        "compact-html-semantics.html",
        source.as_bytes().to_vec(),
    )?)
}

fn matched(outcome: &LocateOutcome) -> Result<&[yosoi_documents::Finding], Box<dyn Error>> {
    match outcome {
        LocateOutcome::Matched { result } => Ok(result.findings()),
        other => Err(io::Error::other(format!("expected matched outcome, got {other:?}")).into()),
    }
}

fn values(outcome: &LocateOutcome) -> Result<Vec<ProjectedValue>, Box<dyn Error>> {
    Ok(matched(outcome)?
        .iter()
        .map(|finding| finding.value().clone())
        .collect())
}

fn match_limited_budget(max_matches: u64) -> Result<ResourceBudget, Box<dyn Error>> {
    Ok(ResourceBudget::try_new(ResourceBudgetValues {
        max_input_bytes: 16_384,
        max_nodes: 1_024,
        max_selector_visits: 100_000,
        max_query_bytes: 4_096,
        max_query_steps: 64,
        max_regions: 16,
        max_matches,
        max_captures: 64,
        max_depth: 128,
        max_output_bytes: 16_384,
    })?)
}

#[test]
fn html5_repair_preserves_implied_nodes_foster_parenting_order_and_coordinates()
-> Result<(), Box<dyn Error>> {
    let document = html(
        "<!doctype html><title>fixture</title><table><p id='foster'>before</p><tr><td>cell</td></tr></table>",
    )?;
    let plan = Plan::new([output("repaired", css("p#foster, td")?.text())?])?;
    let outcome = document.locate(&plan);
    let findings = matched(&outcome)?;

    assert_eq!(
        findings
            .iter()
            .map(|finding| finding.value().clone())
            .collect::<Vec<_>>(),
        vec![
            ProjectedValue::Text("before".to_owned()),
            ProjectedValue::Text("cell".to_owned()),
        ]
    );
    assert_eq!(
        findings.first().map(yosoi_documents::Finding::coordinate),
        Some(&NativeCoordinate::SourceTree(TreeCoordinate::try_new(
            vec![1, 2, 1],
            None,
        )?))
    );
    assert_eq!(
        findings.get(1).map(yosoi_documents::Finding::coordinate),
        Some(&NativeCoordinate::SourceTree(TreeCoordinate::try_new(
            vec![1, 2, 2, 1, 1, 1],
            None,
        )?))
    );
    Ok(())
}

#[test]
fn template_contents_remain_outside_the_document_selector_tree() -> Result<(), Box<dyn Error>> {
    let document = html(
        "<template id='draft'><span class='inside'>hidden</span></template><span class='outside'>visible</span>",
    )?;
    let plan = Plan::new([
        output("template", css("template#draft")?.text())?,
        output("spans", css("span.inside, span.outside")?.text())?,
    ])?;

    assert_eq!(
        values(&document.locate(&plan))?,
        vec![
            ProjectedValue::Text(String::new()),
            ProjectedValue::Text("visible".to_owned()),
        ]
    );
    Ok(())
}

#[test]
fn foreign_content_keeps_case_sensitive_names_attributes_order_and_coordinates()
-> Result<(), Box<dyn Error>> {
    let document = html(
        "<svg viewBox='0 0 10 10'><linearGradient id='paint'></linearGradient><circle id='dot'></circle></svg>",
    )?;
    let plan = Plan::new([
        output(
            "children",
            css("svg > linearGradient, svg > circle")?.node(),
        )?,
        output(
            "view_box",
            css("svg[viewBox='0 0 10 10']")?.attribute("viewBox")?,
        )?,
    ])?;
    let outcome = document.locate(&plan);
    let findings = matched(&outcome)?;

    assert_eq!(findings.len(), 3);
    assert_eq!(
        findings.first().map(yosoi_documents::Finding::coordinate),
        Some(&NativeCoordinate::SourceTree(TreeCoordinate::try_new(
            vec![1, 2, 1, 1],
            None,
        )?))
    );
    assert_eq!(
        findings.get(1).map(yosoi_documents::Finding::coordinate),
        Some(&NativeCoordinate::SourceTree(TreeCoordinate::try_new(
            vec![1, 2, 1, 2],
            None,
        )?))
    );
    assert_eq!(
        findings.get(2).map(yosoi_documents::Finding::value),
        Some(&ProjectedValue::Attribute {
            name: "viewBox".to_owned(),
            value: "0 0 10 10".to_owned(),
        })
    );

    let wrong_case = Plan::new([
        output("element", css("lineargradient")?.node())?,
        output(
            "attribute",
            css("svg[viewbox='0 0 10 10']")?.attribute("viewbox")?,
        )?,
    ])?;
    assert!(matches!(
        document.locate(&wrong_case),
        LocateOutcome::NoMatch { .. }
    ));
    Ok(())
}

#[test]
fn retained_document_and_plan_reuse_are_deterministic_and_limits_still_fail_closed()
-> Result<(), Box<dyn Error>> {
    let document = html("<ol><li>one</li><li>two</li><li>three</li></ol>")?;
    let plan = Plan::new([output("items", css("li")?.text())?])?;
    let parsed = document.parse()?;

    let first = parsed.locate(&plan);
    let second = parsed.locate(&plan);
    assert_eq!(first, second);
    assert_eq!(
        values(&first)?,
        vec![
            ProjectedValue::Text("one".to_owned()),
            ProjectedValue::Text("two".to_owned()),
            ProjectedValue::Text("three".to_owned()),
        ]
    );

    assert_eq!(
        document.locate_with_budget(&plan, match_limited_budget(2)?),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::Matches,
                maximum: 2,
                observed: 3,
            },
        }
    );
    Ok(())
}

#[test]
fn customizable_select_clones_the_selected_option_into_selectedcontent_in_tree_order()
-> Result<(), Box<dyn Error>> {
    let document = html(
        "<select><button><selectedcontent></selectedcontent></button><option selected><span class='choice'>Alpha</span></option></select>",
    )?;
    let plan = Plan::new([output("choices", css("span.choice")?.text())?])?;
    let outcome = document.locate(&plan);
    let findings = matched(&outcome)?;

    assert_eq!(
        values(&outcome)?,
        vec![
            ProjectedValue::Text("Alpha".to_owned()),
            ProjectedValue::Text("Alpha".to_owned()),
        ]
    );
    assert_eq!(
        findings.first().map(yosoi_documents::Finding::coordinate),
        Some(&NativeCoordinate::SourceTree(TreeCoordinate::try_new(
            vec![1, 2, 1, 1, 1, 1],
            None,
        )?))
    );
    assert_eq!(
        findings.get(1).map(yosoi_documents::Finding::coordinate),
        Some(&NativeCoordinate::SourceTree(TreeCoordinate::try_new(
            vec![1, 2, 1, 2, 1],
            None,
        )?))
    );
    Ok(())
}

#[test]
fn adoption_agency_reconstructs_misnested_formatting_without_losing_order()
-> Result<(), Box<dyn Error>> {
    let document = html("<p><b>one<i>two</b>three</i>four")?;
    let plan = Plan::new([output("formatting", css("b, i")?.text())?])?;
    let outcome = document.locate(&plan);
    let findings = matched(&outcome)?;

    assert_eq!(
        values(&outcome)?,
        vec![
            ProjectedValue::Text("onetwo".to_owned()),
            ProjectedValue::Text("two".to_owned()),
            ProjectedValue::Text("three".to_owned()),
        ]
    );
    let coordinates = findings
        .iter()
        .map(|finding| finding.coordinate().clone())
        .collect::<Vec<_>>();
    assert_eq!(
        coordinates,
        vec![
            NativeCoordinate::SourceTree(TreeCoordinate::try_new(vec![1, 2, 1, 1], None)?),
            NativeCoordinate::SourceTree(TreeCoordinate::try_new(vec![1, 2, 1, 1, 1], None)?),
            NativeCoordinate::SourceTree(TreeCoordinate::try_new(vec![1, 2, 1, 2], None)?),
        ]
    );
    Ok(())
}

#[test]
fn repeated_adoption_agency_detach_and_reparent_keeps_every_reconstructed_subtree()
-> Result<(), Box<dyn Error>> {
    let document = html("<p><b><i><u>one</b>two</i>three</u>four")?;
    let plan = Plan::new([output("formatting", css("b, i, u")?.text())?])?;
    let outcome = document.locate(&plan);
    let findings = matched(&outcome)?;

    assert_eq!(
        values(&outcome)?,
        vec![
            ProjectedValue::Text("one".to_owned()),
            ProjectedValue::Text("one".to_owned()),
            ProjectedValue::Text("one".to_owned()),
            ProjectedValue::Text("two".to_owned()),
            ProjectedValue::Text("two".to_owned()),
            ProjectedValue::Text("three".to_owned()),
        ]
    );
    let coordinates = findings
        .iter()
        .map(|finding| finding.coordinate().clone())
        .collect::<Vec<_>>();
    assert_eq!(
        coordinates,
        vec![
            NativeCoordinate::SourceTree(TreeCoordinate::try_new(vec![1, 2, 1, 1], None)?),
            NativeCoordinate::SourceTree(TreeCoordinate::try_new(vec![1, 2, 1, 1, 1], None)?),
            NativeCoordinate::SourceTree(TreeCoordinate::try_new(vec![1, 2, 1, 1, 1, 1], None,)?),
            NativeCoordinate::SourceTree(TreeCoordinate::try_new(vec![1, 2, 1, 2], None)?),
            NativeCoordinate::SourceTree(TreeCoordinate::try_new(vec![1, 2, 1, 2, 1], None)?),
            NativeCoordinate::SourceTree(TreeCoordinate::try_new(vec![1, 2, 1, 3], None)?),
        ]
    );
    Ok(())
}

#[test]
fn table_foster_parenting_preserves_multiple_elements_before_the_repaired_table()
-> Result<(), Box<dyn Error>> {
    let document =
        html("<table><a id='first'>one</a><tr><td>cell</td></tr><a id='second'>two</a></table>")?;
    let plan = Plan::new([output("repaired", css("a, td")?.text())?])?;
    let outcome = document.locate(&plan);
    let findings = matched(&outcome)?;

    assert_eq!(
        values(&outcome)?,
        vec![
            ProjectedValue::Text("one".to_owned()),
            ProjectedValue::Text("two".to_owned()),
            ProjectedValue::Text("cell".to_owned()),
        ]
    );
    let coordinates = findings
        .iter()
        .map(|finding| finding.coordinate().clone())
        .collect::<Vec<_>>();
    assert_eq!(
        coordinates,
        vec![
            NativeCoordinate::SourceTree(TreeCoordinate::try_new(vec![1, 2, 1], None)?),
            NativeCoordinate::SourceTree(TreeCoordinate::try_new(vec![1, 2, 2], None)?),
            NativeCoordinate::SourceTree(TreeCoordinate::try_new(vec![1, 2, 3, 1, 1, 1], None,)?),
        ]
    );
    Ok(())
}

#[test]
fn mathml_text_integration_reenters_html_namespace_without_losing_ancestry()
-> Result<(), Box<dyn Error>> {
    let document = html("<math><mtext><b id='html-child'>bold</b></mtext></math>")?;
    let plan = Plan::new([output(
        "integrated",
        css("math > mtext > B#html-child")?.text(),
    )?])?;
    let outcome = document.locate(&plan);
    let findings = matched(&outcome)?;

    assert_eq!(
        values(&outcome)?,
        vec![ProjectedValue::Text("bold".to_owned())]
    );
    assert_eq!(
        findings.first().map(yosoi_documents::Finding::coordinate),
        Some(&NativeCoordinate::SourceTree(TreeCoordinate::try_new(
            vec![1, 2, 1, 1, 1],
            None,
        )?))
    );

    let wrong_foreign_case = Plan::new([output("wrong", css("math > MTEXT")?.node())?])?;
    assert!(matches!(
        document.locate(&wrong_foreign_case),
        LocateOutcome::NoMatch { .. }
    ));
    Ok(())
}

#[test]
fn malformed_input_terminates_with_deterministic_repair_order_and_coordinates()
-> Result<(), Box<dyn Error>> {
    let document = html(
        "<!doctype html><div id='a'><p id='b'>one<div id='c'>two</div>three</span></table><p id='d'>four",
    )?;
    let plan = Plan::new([output("repaired", css("#a, #b, #c, #d")?.text())?])?;
    let outcome = document.locate(&plan);
    let findings = matched(&outcome)?;

    assert_eq!(
        values(&outcome)?,
        vec![
            ProjectedValue::Text("onetwothreefour".to_owned()),
            ProjectedValue::Text("one".to_owned()),
            ProjectedValue::Text("two".to_owned()),
            ProjectedValue::Text("four".to_owned()),
        ]
    );
    let coordinates = findings
        .iter()
        .map(|finding| finding.coordinate().clone())
        .collect::<Vec<_>>();
    assert_eq!(
        coordinates,
        vec![
            NativeCoordinate::SourceTree(TreeCoordinate::try_new(vec![1, 2, 1], None)?),
            NativeCoordinate::SourceTree(TreeCoordinate::try_new(vec![1, 2, 1, 1], None)?),
            NativeCoordinate::SourceTree(TreeCoordinate::try_new(vec![1, 2, 1, 2], None)?),
            NativeCoordinate::SourceTree(TreeCoordinate::try_new(vec![1, 2, 1, 3], None)?),
        ]
    );
    Ok(())
}
