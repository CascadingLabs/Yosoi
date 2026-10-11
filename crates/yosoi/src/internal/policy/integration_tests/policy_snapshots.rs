// Assertions fail the harness; Result is used for setup and worker errors.
#![allow(clippy::panic_in_result_fn)]

use std::{error::Error, io, sync::Arc, thread};

use crate::internal::policy::{
    Policy, PolicyError, PolicySnapshot,
    policy::{
        Acquisition, AcquisitionKind, DocumentRequest, DocumentSelectionKind, MaximumElapsed,
    },
};
use crate::internal::types::BrowserMode;

type TestResult = Result<(), Box<dyn Error>>;

fn join_snapshot_worker(
    result: thread::Result<Result<PolicySnapshot, PolicyError>>,
) -> Result<PolicySnapshot, io::Error> {
    match result {
        Ok(Ok(snapshot)) => Ok(snapshot),
        Ok(Err(error)) => Err(io::Error::other(error.to_string())),
        Err(_) => Err(io::Error::other("policy snapshot worker panicked")),
    }
}

#[test]
fn default_snapshot_matches_default_policy_identity() -> TestResult {
    let declaration = Policy::default();
    let snapshot = PolicySnapshot::from_policy(&declaration)?;

    assert_eq!(snapshot.policy(), &declaration);
    assert_eq!(snapshot.identity(), declaration.effective_identity()?);
    assert_eq!(snapshot, PolicySnapshot::from_policy(&declaration)?);
    Ok(())
}

#[test]
fn effective_identity_rejects_invalid_resolved_page() -> TestResult {
    let mut effective = Policy::default().effective_policy()?;
    let duplicate = effective
        .page
        .acquisitions
        .first()
        .cloned()
        .ok_or_else(|| io::Error::other("default acquisition is missing"))?;
    effective.page.acquisitions.push(duplicate);
    assert_eq!(
        effective.effective_identity(),
        Err(PolicyError::DuplicateAcquisition(
            AcquisitionKind::DirectHttp
        ))
    );
    Ok(())
}

#[test]
fn failed_borrowed_snapshot_preserves_the_callers_invalid_policy() {
    let mut invalid = Policy::default();
    invalid
        .page
        .acquisitions
        .push(Acquisition::DirectHttp.documents([DocumentRequest::ResponseDocument]));
    let before_validation = invalid.clone();

    assert!(PolicySnapshot::from_policy(&invalid).is_err());
    assert_eq!(invalid, before_validation);
    assert!(invalid.to_canonical_json().is_err());
}

#[test]
fn snapshot_policy_and_identity_survive_source_mutation_and_drop() -> TestResult {
    let mut declaration = Policy::default();
    let original_policy = declaration.clone();
    let snapshot = PolicySnapshot::from_policy(&declaration)?;
    let original_identity = snapshot.identity();

    declaration.page.acquisitions = vec![
        Acquisition::Browser(BrowserMode::Headless).documents([DocumentRequest::RenderedDom]),
        Acquisition::DirectHttp.documents([DocumentRequest::ResponseDocument]),
    ];
    assert_ne!(declaration.effective_identity()?, original_identity);
    assert_eq!(snapshot.policy(), &original_policy);
    assert_eq!(snapshot.identity(), original_identity);

    drop(declaration);
    assert_eq!(snapshot.policy(), &original_policy);
    assert_eq!(snapshot.identity(), original_identity);
    Ok(())
}

#[test]
fn independent_declarations_keep_independent_snapshot_identities() -> TestResult {
    let default_policy = Policy::default();
    let mut custom = Policy::default();
    custom.request.maximum_elapsed = MaximumElapsed::try_from(45_000_000_u64)?;

    let default_snapshot = PolicySnapshot::from_policy(&default_policy)?;
    let custom_snapshot = PolicySnapshot::from_policy(&custom)?;
    let default_identity = default_snapshot.identity();
    let custom_identity = custom_snapshot.identity();

    assert_ne!(default_identity, custom_identity);
    assert_eq!(default_snapshot.policy(), &default_policy);
    assert_eq!(custom_snapshot.policy(), &custom);

    custom.request.maximum_elapsed = MaximumElapsed::try_from(60_000_000_u64)?;
    assert_ne!(custom.effective_identity()?, custom_identity);
    assert_eq!(default_snapshot.identity(), default_identity);
    assert_eq!(custom_snapshot.identity(), custom_identity);
    Ok(())
}

#[test]
fn snapshots_canonicalize_exact_documents_before_preserving_them() -> TestResult {
    let mut ascending = Policy::default();
    ascending.page.acquisitions = vec![Acquisition::Browser(BrowserMode::Headless).documents([
        DocumentRequest::NetworkTree,
        DocumentRequest::ResponseDocument,
        DocumentRequest::AccessibilityTree,
        DocumentRequest::RenderedDom,
    ])];
    let mut reverse = Policy::default();
    reverse.page.acquisitions = vec![Acquisition::Browser(BrowserMode::Headless).documents([
        DocumentRequest::RenderedDom,
        DocumentRequest::AccessibilityTree,
        DocumentRequest::ResponseDocument,
        DocumentRequest::NetworkTree,
    ])];

    let ascending_snapshot = PolicySnapshot::from_policy(&ascending)?;
    let reverse_snapshot = PolicySnapshot::from_policy(&reverse)?;
    assert_eq!(ascending_snapshot.policy(), reverse_snapshot.policy());
    assert_eq!(ascending_snapshot.identity(), reverse_snapshot.identity());
    assert_eq!(
        ascending_snapshot.effective_policy(),
        reverse_snapshot.effective_policy()
    );

    let authored = ascending_snapshot
        .policy()
        .page
        .acquisitions
        .first()
        .ok_or_else(|| io::Error::other("authored acquisition is missing"))?;
    assert_eq!(
        authored.exact_documents(),
        Some(
            &[
                DocumentRequest::ResponseDocument,
                DocumentRequest::RenderedDom,
                DocumentRequest::AccessibilityTree,
                DocumentRequest::NetworkTree,
            ][..]
        )
    );

    let effective = ascending_snapshot
        .effective_policy()
        .page
        .acquisitions
        .first()
        .ok_or_else(|| io::Error::other("effective acquisition is missing"))?;
    assert_eq!(
        effective.documents,
        vec![
            DocumentRequest::ResponseDocument,
            DocumentRequest::RenderedDom,
            DocumentRequest::AccessibilityTree,
            DocumentRequest::NetworkTree,
        ]
    );
    Ok(())
}

#[test]
fn effective_snapshot_keeps_current_and_exact_authorship_distinct() -> TestResult {
    let current = Policy::default();
    let mut exact = Policy::default();
    exact.page.acquisitions.clear();
    exact
        .page
        .acquisitions
        .push(Acquisition::DirectHttp.documents([DocumentRequest::ResponseDocument]));

    let current_snapshot = PolicySnapshot::from_policy(&current)?;
    let exact_snapshot = PolicySnapshot::from_policy(&exact)?;
    assert_eq!(current_snapshot.identity(), exact_snapshot.identity());
    assert_ne!(current_snapshot.policy(), exact_snapshot.policy());

    let current_effective = current_snapshot
        .effective_policy()
        .page
        .acquisitions
        .first()
        .ok_or_else(|| io::Error::other("current acquisition is missing"))?;
    let exact_effective = exact_snapshot
        .effective_policy()
        .page
        .acquisitions
        .first()
        .ok_or_else(|| io::Error::other("exact acquisition is missing"))?;
    assert_eq!(
        current_effective.authored_selection,
        DocumentSelectionKind::Current
    );
    assert_eq!(
        exact_effective.authored_selection,
        DocumentSelectionKind::Exact
    );
    assert_eq!(current_effective.documents, exact_effective.documents);
    assert_eq!(
        current_effective.documents,
        vec![DocumentRequest::ResponseDocument]
    );

    let exact_authored = exact_snapshot
        .policy()
        .page
        .acquisitions
        .first()
        .ok_or_else(|| io::Error::other("authored exact acquisition is missing"))?;
    assert_eq!(exact_authored.kind(), AcquisitionKind::DirectHttp);
    assert_eq!(
        exact_authored.exact_documents(),
        Some(&[DocumentRequest::ResponseDocument][..])
    );
    Ok(())
}

#[test]
fn shared_arc_policy_can_produce_equal_snapshots_on_two_threads() -> TestResult {
    fn assert_send_sync<T: Send + Sync>() {}

    assert_send_sync::<PolicySnapshot>();
    assert_send_sync::<Arc<Policy>>();

    let shared = Arc::new(Policy::default());
    let expected_identity = shared.effective_identity()?;
    let first_input = Arc::clone(&shared);
    let second_input = Arc::clone(&shared);
    let first_worker = thread::spawn(move || PolicySnapshot::from_policy(first_input.as_ref()));
    let second_worker = thread::spawn(move || PolicySnapshot::from_policy(second_input.as_ref()));

    let first = join_snapshot_worker(first_worker.join())?;
    let second = join_snapshot_worker(second_worker.join())?;
    assert_eq!(first.identity(), expected_identity);
    assert_eq!(second.identity(), expected_identity);
    assert_eq!(first.policy(), second.policy());
    assert_eq!(first, second);
    assert_eq!(shared.effective_identity()?, expected_identity);
    Ok(())
}
