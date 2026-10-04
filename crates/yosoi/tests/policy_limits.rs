#![allow(clippy::panic_in_result_fn)] // Policy integration tests use assertions with fallible setup.

use std::error::Error;

use yosoi::prelude as ys;

type TestResult = Result<(), Box<dyn Error>>;

#[test]
fn ordinary_document_uses_implicit_default_policy_for_locate_and_parse() -> TestResult {
    let document = ys::Document::html("catalog.html", b"<main><h1>Catalog</h1></main>".to_vec())?;
    let plan = ys::Plan::new([ys::output("title", ys::css("h1")?.text())?])?;

    let direct = document.locate(&plan);
    assert!(matches!(direct, ys::LocateOutcome::Matched { .. }));

    let parsed = document.parse()?;
    let first = parsed.locate(&plan);
    let second = parsed.locate(&plan);
    assert_eq!(first, second);
    assert!(matches!(first, ys::LocateOutcome::Matched { .. }));
    Ok(())
}

#[test]
fn bound_document_and_parsed_document_enforce_custom_document_cap() -> TestResult {
    let bytes = b"<p>long</p>".to_vec();
    let document = ys::Document::html("bounded.html", bytes.clone())?;
    let plan = ys::Plan::new([ys::output("paragraph", ys::css("p")?.text())?])?;
    let mut policy = ys::Policy::default();
    policy.documents.max_input_bytes = ys::AddressableByteLimit::try_from(1)?;
    let bound = document.bind(&policy);

    assert!(
        bound.parse().is_err(),
        "bound parse ignored the document byte cap"
    );
    assert!(matches!(
        bound.locate(&plan),
        ys::LocateOutcome::Failed {
            failure: ys::LocateFailure::LimitExhausted {
                limit: ys::ResourceLimit::InputBytes,
                maximum: 1,
                observed,
            }
        } if observed == u64::try_from(bytes.len())?
    ));
    Ok(())
}

#[test]
fn bound_locator_cap_survives_parse_for_repeated_location() -> TestResult {
    let document = ys::Document::html(
        "products.html",
        b"<ul><li>one</li><li>two</li></ul>".to_vec(),
    )?;
    let plan = ys::Plan::new([ys::output("products", ys::css("li")?.text())?])?;
    let mut policy = ys::Policy::default();
    policy.locators.max_matches = ys::CountLimit::try_from(1)?;
    let bound = document.bind(&policy);

    let direct = bound.locate(&plan);
    assert!(matches!(
        direct,
        ys::LocateOutcome::Failed {
            failure: ys::LocateFailure::LimitExhausted {
                limit: ys::ResourceLimit::Matches,
                maximum: 1,
                observed: 2,
            }
        }
    ));

    let parsed = bound.parse()?;
    let repeated = parsed.locate(&plan);
    assert_eq!(repeated, direct);
    Ok(())
}

#[test]
fn parsed_document_retains_caps_without_borrowing_the_policy_declaration() -> TestResult {
    let document = ys::Document::html(
        "products.html",
        b"<ul><li>one</li><li>two</li></ul>".to_vec(),
    )?;
    let plan = ys::Plan::new([ys::output("products", ys::css("li")?.text())?])?;
    let parsed = {
        let mut policy = ys::Policy::default();
        policy.locators.max_matches = ys::CountLimit::try_from(1)?;
        document.bind(&policy).parse()?
    };

    assert!(matches!(
        parsed.locate(&plan),
        ys::LocateOutcome::Failed {
            failure: ys::LocateFailure::LimitExhausted {
                limit: ys::ResourceLimit::Matches,
                maximum: 1,
                observed: 2,
            }
        }
    ));
    Ok(())
}
