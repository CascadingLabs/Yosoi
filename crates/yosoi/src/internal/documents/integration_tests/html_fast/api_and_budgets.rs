#![allow(clippy::panic_in_result_fn)]
use super::support::*;
use std::thread;

#[test]
fn invalid_utf8_html_keeps_the_public_locate_parse_failure() -> Result<(), Box<dyn Error>> {
    let mut source = b"<!doctype html><html><head></head><body><main><article class='product-card' data-sku='sku-000073'><span class='price'>USD 19.73</span></article></main></body></html>".to_vec();
    source.push(0xff);
    let document = Document::html("invalid-utf8.html", source)?;
    let plan = Plan::new([output(
        "price",
        css("article.product-card[data-sku='sku-000073'] span.price")?.text(),
    )?])?;

    assert_eq!(
        document.locate(&plan),
        LocateOutcome::Failed {
            failure: LocateFailure::ParseFailed {
                code: "html_invalid_utf8".to_owned(),
            },
        }
    );
    Ok(())
}

#[test]
fn html_fast_path_warming_does_not_change_plan_serde_or_debug() -> Result<(), Box<dyn Error>> {
    let document = html(
        "stable-plan-shape.html",
        "<section><div class='card' data-id='a'>Ada</div></section>",
    )?;
    let plan = Plan::new([output("card", css("div.card")?.node())?])?;
    let serialized_before = serde_json::to_value(&plan)?;
    let debug_before = format!("{plan:?}");

    assert!(matches!(
        document.locate(&plan),
        LocateOutcome::Matched { .. }
    ));

    assert_eq!(serde_json::to_value(&plan)?, serialized_before);
    assert_eq!(format!("{plan:?}"), debug_before);
    Ok(())
}

#[test]
fn concurrent_locates_share_plan_without_budget_or_result_drift() -> Result<(), Box<dyn Error>> {
    const THREAD_COUNT: usize = 4;

    let document = Arc::new(html(
        "concurrent-plan.html",
        "<section><div class='card' data-id='a'>Ada</div></section>",
    )?);
    let plan = Arc::new(Plan::new([output(
        "card",
        css("section div.card")?.node(),
    )?])?);
    let generous = budget(1_000, 4, 8, 16_384)?;
    let low = budget(1_000, 3, 8, 16_384)?;
    let barrier = Arc::new(Barrier::new(THREAD_COUNT));

    let concurrent_outcomes = thread::scope(|scope| {
        let mut handles = Vec::with_capacity(THREAD_COUNT);
        for index in 0..THREAD_COUNT {
            let document = Arc::clone(&document);
            let plan = Arc::clone(&plan);
            let barrier = Arc::clone(&barrier);
            handles.push(scope.spawn(move || {
                barrier.wait();
                let (first_budget, second_budget) = if index % 2 == 0 {
                    (generous, low)
                } else {
                    (low, generous)
                };
                let first = document.locate_with_budget(&plan, first_budget);
                let second = document.locate_with_budget(&plan, second_budget);

                if index % 2 == 0 {
                    (first, second)
                } else {
                    (second, first)
                }
            }));
        }
        handles
            .into_iter()
            .map(|handle| {
                handle
                    .join()
                    .map_err(|_| io::Error::other("concurrent locator thread panicked"))
            })
            .collect::<Result<Vec<_>, _>>()
    })?;

    let retained_success = document.parse_with_budget(generous)?.locate(&plan);
    assert!(matches!(retained_success, LocateOutcome::Matched { .. }));
    let retained_low_budget = document.parse_with_budget(low)?.locate(&plan);
    assert_eq!(
        retained_low_budget,
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::QuerySteps,
                maximum: 3,
                observed: 4,
            },
        }
    );

    for (success, failure) in concurrent_outcomes {
        assert_eq!(success, retained_success);
        assert_eq!(failure, retained_low_budget);
    }
    Ok(())
}

#[test]
fn selector_query_match_and_output_boundaries_equal_the_retained_path() -> Result<(), Box<dyn Error>>
{
    let one = html(
        "budget.html",
        "<section><div class='card' data-id='a'></div></section>",
    )?;
    let node = Plan::new([output("node", css("div.card")?.node())?])?;
    assert_eq!(
        budget_equivalent(&one, &node, budget(15, 8, 8, 16_384)?)?,
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::SelectorVisits,
                maximum: 15,
                observed: 16,
            }
        }
    );
    assert!(matches!(
        budget_equivalent(&one, &node, budget(16, 8, 8, 16_384)?)?,
        LocateOutcome::Matched { .. }
    ));

    let stepped = Plan::new([output("node", css("section div.card")?.node())?])?;
    assert_eq!(
        budget_equivalent(&one, &stepped, budget(1_000, 3, 8, 16_384)?)?,
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::QuerySteps,
                maximum: 3,
                observed: 4,
            }
        }
    );
    assert!(matches!(
        budget_equivalent(&one, &stepped, budget(1_000, 4, 8, 16_384)?)?,
        LocateOutcome::Matched { .. }
    ));

    let two = html(
        "matches.html",
        "<section><div class='card'></div><div class='card'></div></section>",
    )?;
    assert_eq!(
        budget_equivalent(&two, &node, budget(1_000, 8, 1, 16_384)?)?,
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::Matches,
                maximum: 1,
                observed: 2,
            }
        }
    );
    assert!(matches!(
        budget_equivalent(&two, &node, budget(1_000, 8, 2, 16_384)?)?,
        LocateOutcome::Matched { .. }
    ));

    assert_eq!(
        budget_equivalent(&one, &node, budget(1_000, 8, 8, 65)?)?,
        LocateOutcome::Failed {
            failure: LocateFailure::LimitExhausted {
                limit: ResourceLimit::OutputBytes,
                maximum: 65,
                observed: 66,
            }
        }
    );
    assert!(matches!(
        budget_equivalent(&one, &node, budget(1_000, 8, 8, 66)?)?,
        LocateOutcome::Matched { .. }
    ));
    Ok(())
}

#[test]
fn ineligible_xpath_namespace_region_and_multi_output_plans_fall_back_exactly()
-> Result<(), Box<dyn Error>> {
    let document = html("fallback-grid.html", repeated_grid())?;
    let region = css("div.card")?.each_as_region("card")?;
    let plans = [
        Plan::new([output(
            "absolute_child_axis",
            xpath("/html/body/main/section/div")?.node(),
        )?])?,
        Plan::new([output("position", xpath("//div[1]")?.node())?])?,
        Plan::new([output(
            "namespace",
            xpath("//p:div")?.with_namespace("p", "urn:card")?.node(),
        )?])?,
        Plan::new([output("region", region.find(css("span.price")?).text())?])?,
        Plan::new([
            output("text", css("div.card span.price")?.text())?,
            output("node", css("div.card")?.node())?,
        ])?,
    ];

    for plan in plans {
        equivalent(&document, &plan)?;
    }
    Ok(())
}
