#![allow(clippy::panic_in_result_fn)]

use std::{any::TypeId, collections::HashSet, error::Error, io};

use yosoi::{PreparedAttempt, PreparedPageRequest, prelude as ys};

type TestResult = Result<(), Box<dyn Error>>;

fn target_error(target: &str) -> Result<ys::RequestPreparationError, Box<dyn Error>> {
    ys::request::new(target)
        .prepare()
        .err()
        .ok_or_else(|| io::Error::other("invalid target unexpectedly prepared").into())
}

fn ordered_policy() -> ys::Policy {
    let mut policy = ys::Policy::default();
    policy.page.acquisitions = vec![
        ys::policy::Acquisition::DirectHttp,
        ys::policy::Acquisition::Browser(ys::policy::BrowserMode::Headless),
        ys::policy::Acquisition::Browser(ys::policy::BrowserMode::Headful),
    ];
    policy
}

fn capture_ids(prepared: &PreparedPageRequest) -> HashSet<ys::CaptureId> {
    prepared
        .attempts()
        .iter()
        .map(PreparedAttempt::capture_id)
        .collect()
}

#[test]
fn request_construction_accepts_borrowed_and_owned_strings() -> TestResult {
    let authored_https = "https://EXAMPLE.test:443/a/../b?z=2&a=1#section";
    let borrowed_request = ys::request::new(authored_https);
    assert_eq!(borrowed_request.target().as_str(), authored_https);

    let borrowed_prepared = borrowed_request.prepare()?;
    assert_eq!(
        borrowed_prepared.target(),
        "https://example.test/b?z=2&a=1#section"
    );
    let borrowed_attempt = borrowed_prepared
        .attempts()
        .first()
        .ok_or_else(|| io::Error::other("default request has no prepared attempt"))?;
    assert_eq!(borrowed_attempt.target(), borrowed_prepared.target());

    let owned_http = String::from("http://EXAMPLE.test:80/owned");
    let owned_request = ys::request::new(owned_http);
    let owned_prepared = owned_request.prepare()?;
    assert_eq!(owned_prepared.target(), "http://example.test/owned");

    Ok(())
}

#[test]
fn request_target_validation_happens_during_prepare_with_typed_errors() -> TestResult {
    let malformed_request = ys::request::new("not a URL");
    assert_eq!(malformed_request.target().as_str(), "not a URL");
    let malformed_error = malformed_request
        .prepare()
        .err()
        .ok_or_else(|| io::Error::other("malformed target unexpectedly prepared"))?;
    assert!(matches!(
        &malformed_error,
        ys::RequestPreparationError::InvalidTarget(ys::WebUrlParseError::InvalidUrl(_))
    ));
    assert_eq!(malformed_request.target().as_str(), "not a URL");
    assert_eq!(malformed_request.prepare().err(), Some(malformed_error));

    assert!(matches!(
        target_error("ftp://example.test/file")?,
        ys::RequestPreparationError::InvalidTarget(ys::WebUrlParseError::UnsupportedScheme)
    ));

    assert!(matches!(
        target_error("https://")?,
        ys::RequestPreparationError::InvalidTarget(ys::WebUrlParseError::InvalidUrl(_))
    ));

    Ok(())
}

#[test]
fn credential_targets_are_typed_errors_without_secret_echo() -> TestResult {
    let error = target_error("https://andrew:top-secret@example.test/private")?;
    assert!(matches!(
        &error,
        ys::RequestPreparationError::InvalidTarget(ys::WebUrlParseError::CredentialsNotAllowed)
    ));

    let display = error.to_string();
    let debug = format!("{error:?}");
    assert!(
        !display.contains("andrew"),
        "error display must not echo a username"
    );
    assert!(
        !display.contains("top-secret"),
        "error display must not echo a password"
    );
    assert!(
        !debug.contains("andrew"),
        "error debug must not echo a username"
    );
    assert!(
        !debug.contains("top-secret"),
        "error debug must not echo a password"
    );

    Ok(())
}

#[test]
fn request_debug_output_redacts_valid_target_details() -> TestResult {
    let sentinel = "request-debug-secret-61a9";
    let target = format!("https://example.test/private?token={sentinel}#{sentinel}");
    let policy = ys::Policy::default();
    let page = ys::request::new(target);
    let bound = page.clone().bind(&policy);
    let prepared = bound.prepare()?;

    for debug in [
        format!("{page:?}"),
        format!("{bound:?}"),
        format!("{prepared:?}"),
    ] {
        assert!(!debug.contains(sentinel));
        assert!(!debug.contains("/private"));
    }
    for attempt in prepared.attempts() {
        let debug = format!("{attempt:?}");
        assert!(!debug.contains(sentinel));
        assert!(!debug.contains("/private"));
    }

    Ok(())
}

#[test]
fn unbound_request_uses_default_policy_and_resolves_current_direct_http() -> TestResult {
    let default_policy = ys::Policy::default();
    let prepared = ys::request::new("https://example.test/").prepare()?;

    assert_eq!(prepared.policy_snapshot().policy(), &default_policy);
    assert_eq!(
        prepared.policy_snapshot().effective_policy(),
        prepared.effective_policy()
    );
    assert_eq!(
        prepared.effective_policy_identity(),
        default_policy.effective_identity()?
    );

    let acquisition = prepared
        .effective_policy()
        .page
        .acquisitions
        .first()
        .ok_or_else(|| io::Error::other("default effective policy has no acquisition"))?;
    assert_eq!(
        acquisition.acquisition,
        ys::policy::AcquisitionKind::DirectHttp
    );
    assert_eq!(
        acquisition.authored_selection,
        ys::policy::DocumentSelectionKind::Current
    );
    assert_eq!(
        acquisition.documents,
        vec![ys::policy::DocumentRequest::ResponseDocument]
    );

    let attempt = prepared
        .attempts()
        .first()
        .ok_or_else(|| io::Error::other("default request has no prepared attempt"))?;
    assert_eq!(attempt.kind(), acquisition.acquisition);
    assert_eq!(attempt.authored_selection(), acquisition.authored_selection);
    assert_eq!(attempt.documents(), acquisition.documents);

    Ok(())
}

#[test]
fn bound_request_preserves_the_policy_snapshot_order_authorship_and_documents() -> TestResult {
    let mut policy = ys::Policy::default();
    policy.page.acquisitions = vec![
        ys::policy::Acquisition::DirectHttp,
        ys::policy::Acquisition::Browser(ys::policy::BrowserMode::Headless).documents([
            ys::policy::DocumentRequest::NetworkTree,
            ys::policy::DocumentRequest::RenderedDom,
        ]),
        ys::policy::Acquisition::Browser(ys::policy::BrowserMode::Headful),
    ];
    let declaration_before_prepare = policy.clone();
    let expected_snapshot = ys::PolicySnapshot::from_policy(&policy)?;

    let page_request = ys::request::new("https://example.test/catalog");
    let request_id = page_request.id();
    let bound = page_request.bind(&policy);
    assert_eq!(bound.id(), request_id);
    assert_eq!(bound.policy(), &policy);
    let prepared = bound.prepare()?;
    assert_eq!(prepared.id(), request_id);

    assert_eq!(policy, declaration_before_prepare);
    assert_eq!(prepared.policy_snapshot(), &expected_snapshot);
    assert_eq!(
        prepared.policy_snapshot().policy(),
        &declaration_before_prepare
    );

    let expected_kinds = vec![
        ys::policy::AcquisitionKind::DirectHttp,
        ys::policy::AcquisitionKind::Browser {
            mode: ys::policy::BrowserMode::Headless,
        },
        ys::policy::AcquisitionKind::Browser {
            mode: ys::policy::BrowserMode::Headful,
        },
    ];
    let expected_authorship = vec![
        ys::policy::DocumentSelectionKind::Current,
        ys::policy::DocumentSelectionKind::Exact,
        ys::policy::DocumentSelectionKind::Current,
    ];
    let expected_documents = vec![
        vec![ys::policy::DocumentRequest::ResponseDocument],
        vec![
            ys::policy::DocumentRequest::RenderedDom,
            ys::policy::DocumentRequest::NetworkTree,
        ],
        vec![ys::policy::DocumentRequest::ResponseDocument],
    ];

    assert_eq!(
        prepared
            .attempts()
            .iter()
            .map(PreparedAttempt::kind)
            .collect::<Vec<_>>(),
        expected_kinds
    );
    assert_eq!(
        prepared
            .attempts()
            .iter()
            .map(PreparedAttempt::authored_selection)
            .collect::<Vec<_>>(),
        expected_authorship
    );
    assert_eq!(
        prepared
            .attempts()
            .iter()
            .map(|attempt| attempt.documents().to_vec())
            .collect::<Vec<_>>(),
        expected_documents
    );

    let effective_acquisitions = &prepared
        .policy_snapshot()
        .effective_policy()
        .page
        .acquisitions;
    assert_eq!(prepared.attempts().len(), effective_acquisitions.len());
    for (attempt, effective) in prepared.attempts().iter().zip(effective_acquisitions) {
        assert_eq!(attempt.kind(), effective.acquisition);
        assert_eq!(attempt.authored_selection(), effective.authored_selection);
        assert_eq!(attempt.documents(), effective.documents);
    }

    Ok(())
}

#[test]
fn prepared_request_exposes_effective_identity_limits_and_redirects() -> TestResult {
    let mut policy = ys::Policy::default();
    policy.request.maximum_elapsed = ys::policy::MaximumElapsed::try_from(45_000_000_u64)?;
    policy.request.source.content_coded_bytes =
        ys::policy::AddressableByteLimit::try_from(2_000_000_u64)?;
    policy.request.direct_http_redirects = ys::policy::DirectHttpRedirects::Follow {
        max_hops: ys::policy::RedirectHopLimit::try_from(4_u32)?,
        targets: ys::policy::DirectHttpRedirectTargets::SameOrigin,
    };
    let expected_request_policy = policy.request;
    let expected_identity = policy.effective_identity()?;

    let prepared = ys::request::new("https://example.test/")
        .bind(&policy)
        .prepare()?;

    assert_eq!(prepared.effective_policy_identity(), expected_identity);
    assert_eq!(prepared.policy_snapshot().identity(), expected_identity);
    assert_eq!(prepared.effective_policy().request, expected_request_policy);
    assert_eq!(
        prepared.policy_snapshot().effective_policy(),
        prepared.effective_policy()
    );

    Ok(())
}

#[test]
fn empty_acquisition_policy_prepares_no_attempts() -> TestResult {
    let mut policy = ys::Policy::default();
    policy.page.acquisitions.clear();

    let prepared = ys::request::new("https://example.test/")
        .bind(&policy)
        .prepare()?;

    assert_eq!(prepared.attempts().len(), 0);
    assert_eq!(prepared.effective_policy().page.acquisitions.len(), 0);
    assert_eq!(prepared.policy_snapshot().policy(), &policy);

    Ok(())
}

#[test]
fn request_ids_belong_to_requests_while_capture_ids_are_fresh_per_preparation() -> TestResult {
    let policy = ordered_policy();

    let page_request = ys::request::new("https://example.test/page");
    let page_request_id = page_request.id();
    let page_request_clone = page_request.clone();
    assert_eq!(page_request_clone.id(), page_request_id);
    let page_first = page_request.prepare()?;
    let page_second = page_request.prepare()?;
    let page_clone_prepared = page_request_clone.prepare()?;
    assert_eq!(page_first.id(), page_request_id);
    assert_eq!(page_second.id(), page_request_id);
    assert_eq!(page_clone_prepared.id(), page_request_id);

    let bound_request = ys::request::new("https://example.test/bound").bind(&policy);
    let bound_request_id = bound_request.id();
    let bound_request_clone = bound_request.clone();
    assert_eq!(bound_request_clone.id(), bound_request_id);
    let bound_first = bound_request.prepare()?;
    let bound_second = bound_request.prepare()?;
    let bound_clone_prepared = bound_request_clone.prepare()?;
    assert_eq!(bound_first.id(), bound_request_id);
    assert_eq!(bound_second.id(), bound_request_id);
    assert_eq!(bound_clone_prepared.id(), bound_request_id);

    let independent_page_request = ys::request::new("https://example.test/page");
    assert_ne!(independent_page_request.id(), page_request_id);
    let independent_bound_request = ys::request::new("https://example.test/bound").bind(&policy);
    assert_ne!(independent_bound_request.id(), bound_request_id);

    assert_ne!(TypeId::of::<ys::RequestId>(), TypeId::of::<ys::CaptureId>());

    let page_first_capture_ids = capture_ids(&page_first);
    let page_second_capture_ids = capture_ids(&page_second);
    let page_clone_capture_ids = capture_ids(&page_clone_prepared);
    let bound_first_capture_ids = capture_ids(&bound_first);
    let bound_second_capture_ids = capture_ids(&bound_second);
    let bound_clone_capture_ids = capture_ids(&bound_clone_prepared);

    for (prepared, ids) in [
        (&page_first, &page_first_capture_ids),
        (&page_second, &page_second_capture_ids),
        (&page_clone_prepared, &page_clone_capture_ids),
        (&bound_first, &bound_first_capture_ids),
        (&bound_second, &bound_second_capture_ids),
        (&bound_clone_prepared, &bound_clone_capture_ids),
    ] {
        assert_eq!(ids.len(), prepared.attempts().len());
    }

    assert!(page_first_capture_ids.is_disjoint(&page_second_capture_ids));
    assert!(page_first_capture_ids.is_disjoint(&page_clone_capture_ids));
    assert!(page_second_capture_ids.is_disjoint(&page_clone_capture_ids));
    assert!(bound_first_capture_ids.is_disjoint(&bound_second_capture_ids));
    assert!(bound_first_capture_ids.is_disjoint(&bound_clone_capture_ids));
    assert!(bound_second_capture_ids.is_disjoint(&bound_clone_capture_ids));

    Ok(())
}

#[test]
fn invalid_bound_policy_is_reported_at_prepare_without_changing_declaration() -> TestResult {
    let mut policy = ys::Policy::default();
    policy.page.acquisitions = vec![
        ys::policy::Acquisition::DirectHttp,
        ys::policy::Acquisition::DirectHttp,
    ];
    let before_prepare = policy.clone();

    let bound = ys::request::new("https://example.test/").bind(&policy);
    let request_id = bound.id();
    assert_eq!(bound.policy(), &policy);
    let error = bound
        .prepare()
        .err()
        .ok_or_else(|| io::Error::other("invalid policy unexpectedly prepared"))?;

    assert!(matches!(
        &error,
        ys::RequestPreparationError::InvalidPolicy(_)
    ));
    assert_eq!(policy, before_prepare);
    assert_eq!(bound.id(), request_id);
    assert_eq!(bound.prepare().err(), Some(error));

    Ok(())
}
