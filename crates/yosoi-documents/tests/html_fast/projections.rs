#![allow(clippy::panic_in_result_fn)]
use super::support::*;

#[test]
fn css_root_attribute_and_node_projections_preserve_grid_order_and_coordinates()
-> Result<(), Box<dyn Error>> {
    let document = html("css-grid.html", repeated_grid())?;
    let attribute = Plan::new([output("ids", css("div.card")?.attribute("data-id")?)?])?;
    let node = Plan::new([output("cards", css("div.card")?.node())?])?;
    let paths = [vec![1, 2, 1, 2, 1], vec![1, 2, 1, 2, 3]];

    let attribute_outcome = equivalent(&document, &attribute)?;
    let attribute_findings = matched(&attribute_outcome)?;
    assert_eq!(
        attribute_findings
            .iter()
            .map(|finding| finding.value().clone())
            .collect::<Vec<_>>(),
        vec![
            ProjectedValue::Attribute {
                name: "data-id".to_owned(),
                value: "a".to_owned(),
            },
            ProjectedValue::Attribute {
                name: "data-id".to_owned(),
                value: "b".to_owned(),
            },
        ]
    );
    assert_coordinates(attribute_findings, &paths)?;

    let node_outcome = equivalent(&document, &node)?;
    let node_findings = matched(&node_outcome)?;
    assert_coordinates(node_findings, &paths)?;
    assert_node_references(node_findings)?;
    Ok(())
}

#[test]
fn xpath_root_projections_and_two_step_text_match_css_meaning_exactly() -> Result<(), Box<dyn Error>>
{
    let document = html("xpath-grid.html", repeated_grid())?;
    let attribute = Plan::new([output(
        "ids",
        xpath("//div[@class='card']")?.attribute("data-id")?,
    )?])?;
    let node = Plan::new([output("cards", xpath("//div[@class='card']")?.node())?])?;
    let text = Plan::new([output(
        "prices",
        xpath("//div[@class='card']//span[@class='price']")?.text(),
    )?])?;

    let root_paths = [vec![1, 2, 1, 2, 1], vec![1, 2, 1, 2, 3]];
    let value_paths = [vec![1, 2, 1, 2, 1, 1], vec![1, 2, 1, 2, 3, 1, 1]];
    let attribute_outcome = equivalent(&document, &attribute)?;
    assert_coordinates(matched(&attribute_outcome)?, &root_paths)?;
    let node_outcome = equivalent(&document, &node)?;
    assert_coordinates(matched(&node_outcome)?, &root_paths)?;
    assert_node_references(matched(&node_outcome)?)?;

    let text_outcome = equivalent(&document, &text)?;
    let text_findings = matched(&text_outcome)?;
    assert_eq!(
        text_findings
            .iter()
            .map(|finding| finding.value().clone())
            .collect::<Vec<_>>(),
        [
            ProjectedValue::Text("A".to_owned()),
            ProjectedValue::Text("B".to_owned()),
        ]
    );
    assert_coordinates(text_findings, &value_paths)?;
    Ok(())
}

#[test]
fn tree_text_text_and_node_projections_select_the_deepest_complete_element()
-> Result<(), Box<dyn Error>> {
    let document = html(
        "tree-text.html",
        concat!(
            "<section><div class='card'><p>prefix <em>needle</em> suffix</p></div></section>",
            "<aside><p>unrelated</p></aside>",
        ),
    )?;
    let text = Plan::new([output("text", tree_text_contains("needle")?.text())?])?;
    let node = Plan::new([output("node", tree_text_contains("needle")?.node())?])?;
    let expected = [vec![1, 2, 1, 1, 1, 1, 1]];

    let text_outcome = equivalent(&document, &text)?;
    let text_findings = matched(&text_outcome)?;
    assert_eq!(
        text_findings.first().map(yosoi_documents::Finding::value),
        Some(&ProjectedValue::Text("needle".to_owned()))
    );
    assert_coordinates(text_findings, &expected)?;

    let node_outcome = equivalent(&document, &node)?;
    let node_findings = matched(&node_outcome)?;
    assert_coordinates(node_findings, &expected)?;
    assert_node_references(node_findings)?;
    Ok(())
}

#[test]
fn generic_grids_preserve_multiple_late_and_no_match_terminal_results() -> Result<(), Box<dyn Error>>
{
    let mut body = String::from("<section>");
    for index in 0..24_usize {
        if matches!(index, 2 | 23) {
            write!(
                &mut body,
                "<div class='card' data-hit='yes'><span class='price'>hit-{index}</span></div>"
            )?;
        } else {
            write!(
                &mut body,
                "<div class='noise'><span class='price'>noise-{index}</span></div>"
            )?;
        }
    }
    body.push_str("</section>");
    let document = html("late-generic.html", &body)?;
    let plan = Plan::new([output(
        "hits",
        css("div.card[data-hit='yes'] span.price")?.text(),
    )?])?;
    let outcome = equivalent(&document, &plan)?;
    let findings = matched(&outcome)?;
    assert_eq!(
        findings
            .iter()
            .map(|finding| finding.value().clone())
            .collect::<Vec<_>>(),
        [
            ProjectedValue::Text("hit-2".to_owned()),
            ProjectedValue::Text("hit-23".to_owned()),
        ]
    );
    assert_coordinates(findings, &[vec![1, 2, 1, 1, 3, 1], vec![1, 2, 1, 1, 24, 1]])?;

    let absent = Plan::new([output("missing", css("div.absent span.price")?.text())?])?;
    assert!(matches!(
        equivalent(&document, &absent)?,
        LocateOutcome::NoMatch { .. }
    ));
    Ok(())
}
