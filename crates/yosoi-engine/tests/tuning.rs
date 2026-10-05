// Assertions fail the harness; Result is used for setup errors.
#![allow(clippy::panic_in_result_fn)]

use std::error::Error;

use yosoi_engine::prelude as ys;

type TestResult = Result<(), Box<dyn Error>>;

#[test]
fn request_tuning_reaches_prepared_policy_without_mutating_the_borrowed_value() -> TestResult {
    let tuning = ys::policy::Tuning::default();
    let policy = ys::Policy {
        tuning,
        ..ys::Policy::default()
    };
    let before = policy.clone();

    let bound = ys::request::new("https://example.test/").bind(&policy);
    let prepared = bound.prepare()?;
    assert_eq!(prepared.policy_snapshot().policy().tuning, tuning);
    assert_eq!(prepared.effective_policy().tuning, tuning);
    assert_eq!(bound.policy(), &policy);
    assert_eq!(policy, before);
    Ok(())
}

#[test]
fn document_tuning_preserves_one_shot_and_reusable_results() -> TestResult {
    let document = ys::Document::html("page", b"<h1>Hello</h1>".to_vec())?;
    let plan = ys::Plan::new([ys::output("title", ys::css("h1")?.text())?])?;
    let tuning = ys::policy::Tuning::default();
    let policy = ys::Policy {
        tuning,
        ..ys::Policy::default()
    };
    let expected = document.locate(&plan);

    let bound = document.bind(&policy);
    assert_eq!(bound.locate(&plan), expected);
    let parsed = bound.parse()?;
    assert_eq!(parsed.locate(&plan), expected);
    assert_eq!(policy.tuning, tuning);
    Ok(())
}
