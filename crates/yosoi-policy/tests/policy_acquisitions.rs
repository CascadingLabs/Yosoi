// Test assertions fail the harness; Result is used for fixture setup errors.
#![allow(clippy::panic_in_result_fn)]

mod common;

use std::io;

use serde_json::Value;
use yosoi_policy::{
    Policy, PolicyError,
    policy::{Acquisition, AcquisitionKind, DocumentRequest, DocumentSelectionKind, Page},
};
use yosoi_types::BrowserMode;

use common::{TestResult, default_policy_json_value, set_json_value};

fn policy_with_acquisitions(acquisitions: Vec<Acquisition>) -> Policy {
    Policy {
        page: Page { acquisitions },
        ..Policy::default()
    }
}

const fn browser(mode: BrowserMode) -> Acquisition {
    Acquisition::Browser(mode)
}

#[test]
fn bare_acquisitions_resolve_to_response_document_and_keep_current_authorship() -> TestResult {
    let cases = [
        (
            Acquisition::DirectHttp,
            Acquisition::DirectHttp.documents([DocumentRequest::ResponseDocument]),
        ),
        (
            browser(BrowserMode::Headless),
            browser(BrowserMode::Headless).documents([DocumentRequest::ResponseDocument]),
        ),
        (
            browser(BrowserMode::Headful),
            browser(BrowserMode::Headful).documents([DocumentRequest::ResponseDocument]),
        ),
    ];

    for (current_acquisition, exact_acquisition) in cases {
        assert_eq!(
            current_acquisition.selection_kind(),
            DocumentSelectionKind::Current
        );
        assert_eq!(
            exact_acquisition.selection_kind(),
            DocumentSelectionKind::Exact
        );
        let current = policy_with_acquisitions(vec![current_acquisition]);
        let exact = policy_with_acquisitions(vec![exact_acquisition]);

        assert!(current.validate().is_ok());
        assert!(exact.validate().is_ok());
        assert_eq!(current.effective_identity()?, exact.effective_identity()?);
        assert_ne!(
            current, exact,
            "authored Current and Exact selections differ"
        );
        assert_ne!(
            current.to_canonical_json()?,
            exact.to_canonical_json()?,
            "the wire form retains whether documents were authored as Current or Exact"
        );
    }
    Ok(())
}

#[test]
fn exact_documents_replace_prior_documents_and_allow_empty_lists() {
    let exact = browser(BrowserMode::Headless)
        .documents([
            DocumentRequest::ResponseDocument,
            DocumentRequest::RenderedDom,
        ])
        .documents([DocumentRequest::NetworkTree]);
    assert_eq!(
        exact,
        Acquisition::Exact {
            acquisition: AcquisitionKind::Browser {
                mode: BrowserMode::Headless,
            },
            documents: vec![DocumentRequest::NetworkTree],
        }
    );

    let exact_empty = browser(BrowserMode::Headful).documents([]);
    assert_eq!(
        exact_empty,
        Acquisition::Exact {
            acquisition: AcquisitionKind::Browser {
                mode: BrowserMode::Headful,
            },
            documents: vec![],
        }
    );
    assert!(
        policy_with_acquisitions(vec![exact_empty])
            .validate()
            .is_ok()
    );

    let empty_page = policy_with_acquisitions(vec![]);
    assert!(empty_page.validate().is_ok());
    assert!(empty_page.to_canonical_json().is_ok());
    assert!(empty_page.effective_identity().is_ok());
}

#[test]
fn all_document_request_kinds_are_supported_for_browser_acquisitions() {
    let policy = policy_with_acquisitions(vec![browser(BrowserMode::Headless).documents([
        DocumentRequest::ResponseDocument,
        DocumentRequest::RenderedDom,
        DocumentRequest::AccessibilityTree,
        DocumentRequest::NetworkTree,
    ])]);

    assert!(policy.validate().is_ok());
}

#[test]
fn duplicate_acquisition_kinds_and_duplicate_document_requests_are_rejected() -> TestResult {
    let duplicate_direct_http = policy_with_acquisitions(vec![
        Acquisition::DirectHttp,
        Acquisition::DirectHttp.documents([DocumentRequest::ResponseDocument]),
    ]);
    assert!(duplicate_direct_http.validate().is_err());
    assert!(duplicate_direct_http.to_canonical_json().is_err());
    assert!(duplicate_direct_http.effective_identity().is_err());

    let mut duplicate_acquisitions_json = default_policy_json_value()?;
    set_json_value(
        &mut duplicate_acquisitions_json,
        "/page/acquisitions",
        Value::Array(vec![
            serde_json::to_value(Acquisition::DirectHttp)?,
            serde_json::to_value(
                Acquisition::DirectHttp.documents([DocumentRequest::ResponseDocument]),
            )?,
        ]),
    )?;
    assert!(serde_json::from_value::<Policy>(duplicate_acquisitions_json).is_err());

    let duplicate_browser = policy_with_acquisitions(vec![
        browser(BrowserMode::Headless),
        browser(BrowserMode::Headless).documents([DocumentRequest::RenderedDom]),
    ]);
    assert!(duplicate_browser.validate().is_err());

    let duplicate_document = policy_with_acquisitions(vec![
        browser(BrowserMode::Headless)
            .documents([DocumentRequest::RenderedDom, DocumentRequest::RenderedDom]),
    ]);
    assert!(duplicate_document.validate().is_err());
    assert!(duplicate_document.to_canonical_json().is_err());
    assert!(duplicate_document.effective_identity().is_err());

    let mut duplicate_documents_json = default_policy_json_value()?;
    set_json_value(
        &mut duplicate_documents_json,
        "/page/acquisitions/0",
        serde_json::to_value(browser(BrowserMode::Headless))?,
    )?;
    set_json_value(
        &mut duplicate_documents_json,
        "/page/acquisitions/0/documents/kind",
        Value::from("exact"),
    )?;
    let selection = duplicate_documents_json
        .pointer_mut("/page/acquisitions/0/documents")
        .and_then(Value::as_object_mut)
        .ok_or_else(|| {
            io::Error::new(
                io::ErrorKind::InvalidData,
                "default policy has no acquisition document selection",
            )
        })?;
    selection.insert(
        "documents".to_owned(),
        Value::Array(vec![
            serde_json::to_value(DocumentRequest::RenderedDom)?,
            serde_json::to_value(DocumentRequest::RenderedDom)?,
        ]),
    );
    assert!(serde_json::from_value::<Policy>(duplicate_documents_json).is_err());

    let mut unknown_document_json = default_policy_json_value()?;
    set_json_value(
        &mut unknown_document_json,
        "/page/acquisitions/0",
        serde_json::to_value(browser(BrowserMode::Headless))?,
    )?;
    set_json_value(
        &mut unknown_document_json,
        "/page/acquisitions/0/documents/kind",
        Value::from("exact"),
    )?;
    let selection = unknown_document_json
        .pointer_mut("/page/acquisitions/0/documents")
        .and_then(Value::as_object_mut)
        .ok_or_else(|| {
            io::Error::new(
                io::ErrorKind::InvalidData,
                "default policy has no acquisition document selection",
            )
        })?;
    selection.insert(
        "documents".to_owned(),
        Value::Array(vec![Value::from("future_document")]),
    );
    assert!(serde_json::from_value::<Policy>(unknown_document_json).is_err());
    Ok(())
}

#[test]
fn direct_http_exact_selection_rejects_browser_only_document_requests() {
    for document in [
        DocumentRequest::RenderedDom,
        DocumentRequest::AccessibilityTree,
        DocumentRequest::NetworkTree,
    ] {
        let policy = policy_with_acquisitions(vec![Acquisition::DirectHttp.documents([document])]);
        assert!(
            policy.validate().is_err(),
            "{document:?} is not available over DirectHttp"
        );
        assert!(policy.to_canonical_json().is_err());
        assert!(policy.effective_identity().is_err());
    }

    let direct_http_exact_empty =
        policy_with_acquisitions(vec![Acquisition::DirectHttp.documents([])]);
    assert!(direct_http_exact_empty.validate().is_ok());
}

#[test]
fn document_sets_are_canonicalized_while_acquisition_order_is_preserved() -> TestResult {
    let documents = [
        DocumentRequest::ResponseDocument,
        DocumentRequest::RenderedDom,
        DocumentRequest::AccessibilityTree,
        DocumentRequest::NetworkTree,
    ];
    let reverse_documents = [
        DocumentRequest::NetworkTree,
        DocumentRequest::AccessibilityTree,
        DocumentRequest::RenderedDom,
        DocumentRequest::ResponseDocument,
    ];

    let document_order =
        policy_with_acquisitions(vec![browser(BrowserMode::Headless).documents(documents)]);
    let reverse_document_order = policy_with_acquisitions(vec![
        browser(BrowserMode::Headless).documents(reverse_documents),
    ]);
    assert_eq!(
        document_order.effective_identity()?,
        reverse_document_order.effective_identity()?
    );
    assert_eq!(document_order, reverse_document_order);
    assert_eq!(
        document_order.to_canonical_json()?,
        reverse_document_order.to_canonical_json()?
    );
    let roundtrip: Policy = serde_json::from_str(&document_order.to_canonical_json()?)?;
    assert_eq!(roundtrip, document_order);

    let noncanonical = policy_with_acquisitions(vec![Acquisition::Exact {
        acquisition: AcquisitionKind::Browser {
            mode: BrowserMode::Headless,
        },
        documents: reverse_documents.to_vec(),
    }]);
    assert!(matches!(
        noncanonical.validate(),
        Err(PolicyError::NonCanonicalDocumentOrder)
    ));

    let first_acquisition_order = policy_with_acquisitions(vec![
        Acquisition::DirectHttp,
        browser(BrowserMode::Headless),
    ]);
    let reverse_acquisition_order = policy_with_acquisitions(vec![
        browser(BrowserMode::Headless),
        Acquisition::DirectHttp,
    ]);
    assert!(first_acquisition_order.validate().is_ok());
    assert!(reverse_acquisition_order.validate().is_ok());
    assert_ne!(
        first_acquisition_order.effective_identity()?,
        reverse_acquisition_order.effective_identity()?
    );
    assert_ne!(
        first_acquisition_order.to_canonical_json()?,
        reverse_acquisition_order.to_canonical_json()?
    );
    Ok(())
}

#[test]
fn deserialization_rejects_overlong_acquisition_and_document_lists() -> TestResult {
    let mut policy_json = default_policy_json_value()?;
    let acquisitions = vec![
        serde_json::to_value(Acquisition::DirectHttp)?,
        serde_json::to_value(browser(BrowserMode::Headless))?,
        serde_json::to_value(browser(BrowserMode::Headful))?,
        serde_json::to_value(browser(BrowserMode::Headful).documents([]))?,
    ];
    set_json_value(
        &mut policy_json,
        "/page/acquisitions",
        Value::Array(acquisitions),
    )?;
    assert!(serde_json::from_value::<Policy>(policy_json).is_err());

    let mut policy_json = default_policy_json_value()?;
    set_json_value(
        &mut policy_json,
        "/page/acquisitions/0/documents/kind",
        Value::from("exact"),
    )?;
    let documents = vec![
        serde_json::to_value(DocumentRequest::ResponseDocument)?,
        serde_json::to_value(DocumentRequest::RenderedDom)?,
        serde_json::to_value(DocumentRequest::AccessibilityTree)?,
        serde_json::to_value(DocumentRequest::NetworkTree)?,
        serde_json::to_value(DocumentRequest::ResponseDocument)?,
    ];
    let selection = policy_json
        .pointer_mut("/page/acquisitions/0/documents")
        .and_then(Value::as_object_mut)
        .ok_or_else(|| {
            io::Error::new(
                io::ErrorKind::InvalidData,
                "default policy has no acquisition document selection",
            )
        })?;
    selection.insert("documents".to_owned(), Value::Array(documents));
    assert!(serde_json::from_value::<Policy>(policy_json).is_err());
    Ok(())
}

#[test]
fn direct_policy_json_roundtrips_exact_order() -> TestResult {
    let policy = policy_with_acquisitions(vec![
        Acquisition::DirectHttp.documents([DocumentRequest::ResponseDocument]),
        browser(BrowserMode::Headless).documents([
            DocumentRequest::ResponseDocument,
            DocumentRequest::RenderedDom,
            DocumentRequest::AccessibilityTree,
            DocumentRequest::NetworkTree,
        ]),
    ]);
    let expected_canonical = include_str!("fixtures/exact-policy.json").trim();
    let canonical = policy.to_canonical_json()?;
    assert_eq!(canonical, expected_canonical);
    let parsed: Policy = serde_json::from_str(&canonical)?;

    assert_eq!(parsed, policy);
    assert_eq!(parsed.to_canonical_json()?, canonical);
    assert_eq!(parsed.effective_identity()?, policy.effective_identity()?);
    Ok(())
}
