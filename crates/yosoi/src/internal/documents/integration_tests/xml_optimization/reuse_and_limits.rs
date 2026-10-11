#![allow(clippy::panic_in_result_fn)]
use super::support::*;
use crate::internal::documents as internal_documents;

#[test]
fn query_traversal_match_and_output_limits_have_exact_boundaries() -> Result<(), Box<dyn Error>> {
    let one = xml("one.xml", "<root><item id='x'>A</item></root>")?;
    let node_plan = Plan::new([output("item", xpath("/root/item")?.node())?])?;

    assert_eq!(
        assert_budget_equivalent(&one, &node_plan, budget(3, 8, 8, 16_384)?)?,
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::SelectorVisits,
                maximum: 3,
                observed: 4,
            }
        }
    );
    assert!(matches!(
        assert_budget_equivalent(&one, &node_plan, budget(4, 8, 8, 16_384)?)?,
        LocateOutcome::Matched { .. }
    ));
    assert_eq!(
        assert_budget_equivalent(&one, &node_plan, budget(100, 1, 8, 16_384)?)?,
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::QuerySteps,
                maximum: 1,
                observed: 2,
            }
        }
    );
    assert!(matches!(
        assert_budget_equivalent(&one, &node_plan, budget(100, 2, 8, 16_384)?)?,
        LocateOutcome::Matched { .. }
    ));

    let two = xml("two.xml", "<root><item>A</item><item>B</item></root>")?;
    let text_items = text_plan("//item")?;
    assert_eq!(
        assert_budget_equivalent(&two, &text_items, budget(1_000, 8, 1, 16_384)?)?,
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::Matches,
                maximum: 1,
                observed: 2,
            }
        }
    );
    assert!(matches!(
        assert_budget_equivalent(&two, &text_items, budget(1_000, 8, 2, 16_384)?)?,
        LocateOutcome::Matched { .. }
    ));

    let full = assert_budget_equivalent(&one, &node_plan, budget(100, 8, 8, 16_384)?)?;
    let exact_output_bytes = u64::try_from(serde_json::to_vec(&full)?.len())?;
    let below_output = exact_output_bytes
        .checked_sub(1)
        .ok_or_else(|| io::Error::other("serialized outcome cannot be empty"))?;
    assert_eq!(
        assert_budget_equivalent(&one, &node_plan, budget(100, 8, 8, below_output)?,)?,
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::OutputBytes,
                maximum: below_output,
                observed: exact_output_bytes,
            }
        }
    );
    assert_eq!(
        assert_budget_equivalent(&one, &node_plan, budget(100, 8, 8, exact_output_bytes)?,)?,
        full
    );
    Ok(())
}

#[test]
fn parsed_xml_and_one_reusable_plan_are_repeatable_and_match_direct_location()
-> Result<(), Box<dyn Error>> {
    let document = xml(
        "reuse.xml",
        "<root><group><item>A</item><item>B</item></group><group><item>C</item></group></root>",
    )?;
    let plan = text_plan("//group//item")?;
    let parsed = document.parse()?;

    let first = parsed.locate(&plan);
    let second = parsed.locate(&plan);
    assert_eq!(first, second);
    assert_eq!(document.locate(&plan), first);

    let round_trip: Plan = serde_json::from_value(serde_json::to_value(&plan)?)?;
    assert_eq!(parsed.locate(&round_trip), first);
    Ok(())
}

#[test]
fn one_parsed_xml_document_reuses_css_xpath_and_tree_text_plans_for_1_10_and_100_locates()
-> Result<(), Box<dyn Error>> {
    let document = xml(
        "cache-matrix.xml",
        concat!(
            "<root><group>",
            "<item data-id='a'><name>A</name></item>",
            "<item data-id='b'><name>B <em>needle</em></name></item>",
            "<item data-id='c'><name>C</name></item>",
            "</group></root>",
        ),
    )?;
    let parsed = document.parse()?;
    let plans = [
        Plan::new([output("css_attribute", css("item")?.attribute("data-id")?)?])?,
        Plan::new([output("css_text", css("item")?.text())?])?,
        Plan::new([output("css_node", css("item")?.node())?])?,
        Plan::new([output(
            "xpath_attribute",
            xpath("//item")?.attribute("data-id")?,
        )?])?,
        Plan::new([output("xpath_text", xpath("//item")?.text())?])?,
        Plan::new([output("xpath_node", xpath("//item")?.node())?])?,
        Plan::new([output(
            "tree_text_text",
            tree_text_contains("needle")?.text(),
        )?])?,
        Plan::new([output(
            "tree_text_node",
            tree_text_contains("needle")?.node(),
        )?])?,
    ];

    for plan in plans {
        let expected = parsed.locate(&plan);
        assert_eq!(document.locate(&plan), expected);
        for repetitions in [1_usize, 10, 100] {
            for _ in 0..repetitions {
                assert_eq!(parsed.locate(&plan), expected);
            }
        }
    }
    Ok(())
}

#[test]
fn duplicate_outputs_with_identical_xml_query_and_projection_preserve_multiplicity_and_order()
-> Result<(), Box<dyn Error>> {
    let document = xml(
        "duplicate-outputs.xml",
        "<root><item>A</item><item>B</item><item>C</item></root>",
    )?;
    let query = xpath("//item")?;
    let plan = Plan::new([
        output("first", query.clone().text())?,
        output("second", query.text())?,
    ])?;
    let outcome = assert_equivalent(&document, &plan)?;
    let findings = matched(&outcome)?;

    assert_eq!(findings.len(), 6);
    assert_eq!(
        findings
            .iter()
            .map(internal_documents::Finding::order)
            .collect::<Vec<_>>(),
        [0, 1, 2, 3, 4, 5]
    );
    assert_eq!(
        findings
            .iter()
            .map(|finding| finding.output_id().as_str())
            .collect::<Vec<_>>(),
        ["first", "first", "first", "second", "second", "second"]
    );
    assert_eq!(
        findings
            .iter()
            .map(|finding| finding.value().clone())
            .collect::<Vec<_>>(),
        [
            ProjectedValue::Text("A".to_owned()),
            ProjectedValue::Text("B".to_owned()),
            ProjectedValue::Text("C".to_owned()),
            ProjectedValue::Text("A".to_owned()),
            ProjectedValue::Text("B".to_owned()),
            ProjectedValue::Text("C".to_owned()),
        ]
    );
    Ok(())
}

#[test]
fn cloned_and_deserialized_mixed_xml_plans_rebuild_to_identical_outcomes()
-> Result<(), Box<dyn Error>> {
    let document = xml(
        "cache-rebuild.xml",
        "<root><item data-id='a'>A</item><item data-id='b'><em>needle</em></item></root>",
    )?;
    let plan = Plan::new([
        output("css_attribute", css("item")?.attribute("data-id")?)?,
        output("xpath_text", xpath("//item")?.text())?,
        output("tree_node", tree_text_contains("needle")?.node())?,
    ])?;
    let parsed = document.parse()?;
    let expected = parsed.locate(&plan);

    let cloned = plan.clone();
    assert_eq!(parsed.locate(&cloned), expected);
    assert_eq!(document.locate(&cloned), expected);

    let serialized = serde_json::to_vec(&plan)?;
    let rebuilt: Plan = serde_json::from_slice(&serialized)?;
    assert_eq!(rebuilt, plan);
    assert_eq!(parsed.locate(&rebuilt), expected);
    assert_eq!(document.locate(&rebuilt), expected);
    Ok(())
}

#[test]
fn warmed_xml_plan_still_enforces_low_query_step_budget_exactly() -> Result<(), Box<dyn Error>> {
    let document = xml(
        "cached-budget.xml",
        "<root><group><item kind='x'>A</item><item kind='y'>B</item></group></root>",
    )?;
    let plan = text_plan("//group/item[@kind='x']")?;

    assert!(matches!(
        document.locate(&plan),
        LocateOutcome::Matched { .. }
    ));

    let below = budget(1_000, 2, 8, 16_384)?;
    let parsed_below = document.parse_with_budget(below)?;
    let expected_failure = LocateOutcome::Failed {
        failure: LocateFailure::LimitExhausted {
            limit: ResourceLimit::QuerySteps,
            maximum: 2,
            observed: 3,
        },
    };
    assert_eq!(parsed_below.locate(&plan), expected_failure);
    assert_eq!(document.locate_with_budget(&plan, below), expected_failure);

    let exact = budget(1_000, 3, 8, 16_384)?;
    let parsed_exact = document.parse_with_budget(exact)?;
    assert!(matches!(
        parsed_exact.locate(&plan),
        LocateOutcome::Matched { .. }
    ));
    assert_eq!(
        document.locate_with_budget(&plan, exact),
        parsed_exact.locate(&plan)
    );
    Ok(())
}
