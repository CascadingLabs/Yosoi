// Assertions intentionally use the public prelude alias.
#![allow(
    clippy::absolute_paths,
    reason = "tests exercise the public ys namespace"
)]
#![allow(clippy::panic_in_result_fn)]

use std::{error::Error, io};

use yosoi::prelude as ys;

type TestResult = Result<(), Box<dyn Error>>;

#[test]
fn snapshot_owns_a_validated_copy_of_the_caller_policy() -> TestResult {
    let mut policy = ys::Policy::default();
    policy.page.acquisitions = vec![
        ys::policy::Acquisition::Browser(ys::policy::BrowserMode::Headless)
            .documents([ys::policy::DocumentRequest::RenderedDom]),
    ];
    let expected = policy.clone();
    let expected_identity = expected.effective_identity()?;

    let snapshot = ys::PolicySnapshot::from_policy(&policy)?;
    policy.page.acquisitions.clear();

    assert_eq!(snapshot.policy(), &expected);
    assert_eq!(snapshot.identity(), expected_identity);
    assert!(policy.page.acquisitions.is_empty());
    Ok(())
}

#[test]
fn invalid_snapshot_creation_returns_a_typed_error_without_consuming_policy() -> TestResult {
    let mut policy = ys::Policy::default();
    policy.page.acquisitions = vec![
        ys::policy::Acquisition::Browser(ys::policy::BrowserMode::Headless).documents([
            ys::policy::DocumentRequest::RenderedDom,
            ys::policy::DocumentRequest::RenderedDom,
        ]),
    ];

    let Err(error) = ys::PolicySnapshot::from_policy(&policy) else {
        return Err(io::Error::other("duplicate evidence unexpectedly validated").into());
    };

    assert_eq!(
        error,
        ys::PolicyError::DuplicateDocument(ys::policy::DocumentRequest::RenderedDom)
    );
    let expected_acquisition = ys::policy::Acquisition::Browser(ys::policy::BrowserMode::Headless)
        .documents([
            ys::policy::DocumentRequest::RenderedDom,
            ys::policy::DocumentRequest::RenderedDom,
        ]);
    assert_eq!(policy.page.acquisitions.len(), 1);
    assert_eq!(
        policy.page.acquisitions.first(),
        Some(&expected_acquisition)
    );
    Ok(())
}

#[test]
fn public_snapshot_is_send_and_sync() {
    fn assert_send_sync<T: Send + Sync>() {}

    assert_send_sync::<ys::PolicySnapshot>();
}
