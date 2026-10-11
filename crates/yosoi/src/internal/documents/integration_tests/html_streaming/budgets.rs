#![allow(clippy::panic_in_result_fn)]
use super::support::*;
use crate::internal::documents as internal_documents;

#[test]
fn locate_limits_match_the_retained_oracle_exactly() -> Result<(), Box<dyn Error>> {
    let document = html(
        "limits.html",
        concat!(
            "<main>",
            "<article class='product-card' data-sku='sku-000073'><span class='price'>one</span></article>",
            "<article class='product-card' data-sku='sku-000073'><span class='price'>two</span></article>",
            "</main>",
        ),
    )?;
    let plan = caveman_plan()?;
    let budgets = [
        budget(16_384, 1_024, 1, 4_096, 64, 16, 128, 128, 16_384)?,
        budget(16_384, 1_024, 100_000, 1, 64, 16, 128, 128, 16_384)?,
        budget(16_384, 1_024, 100_000, 4_096, 1, 16, 128, 128, 16_384)?,
        budget(16_384, 1_024, 100_000, 4_096, 64, 16, 1, 128, 16_384)?,
        budget(16_384, 1_024, 100_000, 4_096, 64, 16, 128, 128, 1)?,
    ];

    for limit in budgets {
        assert!(matches!(
            assert_budget_equivalent(&document, &plan, limit)?,
            LocateOutcome::Failed {
                failure: LocateFailure::LimitExhausted { .. }
            }
        ));
    }
    Ok(())
}

#[test]
fn parse_limits_map_to_the_same_public_failure_without_candidate_execution()
-> Result<(), Box<dyn Error>> {
    let document = html("parse-limits.html", "<div><span>value</span></div>")?;
    let plan = Plan::new([output("value", css("span")?.text())?])?;

    let input_limited = budget(1, 1_024, 100_000, 4_096, 64, 16, 128, 128, 16_384)?;
    assert!(matches!(
        document.parse_with_budget(input_limited),
        Err(DocumentParseError::Html(HtmlParseError::InputLimitExceeded {
            maximum: 1,
            observed,
        })) if observed == document.byte_len()
    ));
    assert_eq!(
        document.locate_with_budget(&plan, input_limited),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::InputBytes,
                maximum: 1,
                observed: document.byte_len(),
            }
        }
    );

    let node_limited = budget(16_384, 1, 100_000, 4_096, 64, 16, 128, 128, 16_384)?;
    let observed_nodes = match document.parse_with_budget(node_limited) {
        Err(DocumentParseError::Html(HtmlParseError::NodeLimitExceeded {
            maximum: 1,
            observed,
        })) => observed,
        other => panic!("expected the parser node limit to fail, got {other:?}"),
    };
    assert!(observed_nodes > 1);
    assert_eq!(
        document.locate_with_budget(&plan, node_limited),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::Nodes,
                maximum: 1,
                observed: observed_nodes,
            }
        }
    );

    let depth_limited = budget(16_384, 1_024, 100_000, 4_096, 64, 16, 128, 1, 16_384)?;
    assert!(matches!(
        document.parse_with_budget(depth_limited),
        Err(DocumentParseError::Html(
            HtmlParseError::DepthLimitExceeded {
                maximum: 1,
                observed: 2,
            }
        ))
    ));
    assert_eq!(
        document.locate_with_budget(&plan, depth_limited),
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::Depth,
                maximum: 1,
                observed: 2,
            }
        }
    );
    Ok(())
}

#[test]
fn plans_outside_the_initial_streaming_subset_remain_exactly_equivalent()
-> Result<(), Box<dyn Error>> {
    let document = html(
        "ineligible-plans.html",
        concat!(
            "<main>",
            "<article class='product-card' data-sku='sku-000073'>",
            "<span class='price' data-currency='USD'>USD 19.73</span>",
            "</article>",
            "</main>",
        ),
    )?;
    let products = css("article.product-card")?.each_as_region("product")?;
    let plans = [
        Plan::new([output(
            "xpath",
            xpath("//article[@data-sku='sku-000073']//span")?.text(),
        )?])?,
        Plan::new([output(
            "tree_text",
            tree_text_contains("USD 19.73")?.text(),
        )?])?,
        Plan::new([output("node", css("span.price")?.node())?])?,
        Plan::new([output(
            "attribute",
            css("span.price")?.attribute("data-currency")?,
        )?])?,
        Plan::new([output("region", products.find(css("span.price")?).text())?])?,
        Plan::new([
            output("price", css("span.price")?.text())?,
            output("currency", css("span.price")?.attribute("data-currency")?)?,
        ])?,
    ];

    for plan in plans {
        assert_default_equivalent(&document, &plan)?;
    }
    Ok(())
}

#[test]
fn one_multi_output_plan_is_repeatable_for_late_matches_and_complete_absence()
-> Result<(), Box<dyn Error>> {
    let document = html(
        "multi-output-reuse.html",
        concat!(
            "<main>",
            "<article class='product-card' data-sku='sku-000001'><span class='price'>early distractor</span></article>",
            "<article class='product-card' data-sku='sku-000002'><span class='price'>middle distractor</span></article>",
            "<article class='product-card' data-sku='sku-000073'><span class='price' data-currency='USD'>late target</span></article>",
            "</main>",
        ),
    )?;
    let plan = Plan::new([
        output("price", css(CAVEMAN_SELECTOR)?.text())?,
        output(
            "currency",
            css(CAVEMAN_SELECTOR)?.attribute("data-currency")?,
        )?,
    ])?;
    let parsed = document.parse()?;
    let first = parsed.locate(&plan);
    let second = parsed.locate(&plan);

    assert_eq!(first, second);
    assert_eq!(document.locate(&plan), first);
    let findings = matched(&first)?;
    assert_eq!(findings.len(), 2);
    assert_eq!(
        findings.first().map(internal_documents::Finding::order),
        Some(0)
    );
    assert_eq!(
        findings.get(1).map(internal_documents::Finding::order),
        Some(1)
    );
    assert_eq!(
        findings.first().map(internal_documents::Finding::value),
        Some(&ProjectedValue::Text("late target".to_owned()))
    );
    assert_eq!(
        findings.get(1).map(internal_documents::Finding::value),
        Some(&ProjectedValue::Attribute {
            name: "data-currency".to_owned(),
            value: "USD".to_owned(),
        })
    );
    assert_eq!(
        findings
            .first()
            .map(internal_documents::Finding::coordinate),
        findings.get(1).map(internal_documents::Finding::coordinate)
    );

    let absent = html(
        "multi-output-absent.html",
        "<main><article class='product-card' data-sku='sku-000001'><span class='price' data-currency='USD'>only distractor</span></article></main>",
    )?;
    let parsed_absent = absent.parse()?;
    let first_absent = parsed_absent.locate(&plan);
    assert_eq!(parsed_absent.locate(&plan), first_absent);
    assert_eq!(absent.locate(&plan), first_absent);
    assert!(matches!(first_absent, LocateOutcome::NoMatch { .. }));
    Ok(())
}
