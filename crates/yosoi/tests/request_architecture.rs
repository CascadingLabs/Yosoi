//! Source-contract checks for the normal Requests facade.
//!
//! These checks intentionally inspect only the request modules and their
//! request-specific facade exports. Capture and resolution APIs used by other
//! callers are outside this boundary.
//!
//! The small source parser uses bounded slicing and brace-depth arithmetic;
//! panics identify a malformed or moved declaration in this test fixture.
#![allow(
    clippy::arithmetic_side_effects,
    clippy::indexing_slicing,
    clippy::map_unwrap_or,
    clippy::panic,
    clippy::panic_in_result_fn,
    clippy::string_slice
)]

const LIB: &str = include_str!("../src/lib.rs");
const REQUEST: &str = include_str!("../src/request.rs");
const EXECUTION: &str = include_str!("../src/request/execution.rs");
const STANDARD: &str = include_str!("../src/request/execution/standard.rs");
const RESPONSE: &str = include_str!("../src/request/execution/outcome/response.rs");
const ATTEMPT: &str = include_str!("../src/request/execution/outcome/attempt.rs");
const FAILURE: &str = include_str!("../src/request/execution/outcome/failure.rs");

use yosoi::PolicyError;

#[test]
fn policy_prelude_supports_the_approved_concise_authoring_surface() -> Result<(), PolicyError> {
    use yosoi::policy::prelude::{Browser, DirectHttp, Headful, Headless, Page};

    let page = Page::new(vec![DirectHttp, Browser(Headless), Browser(Headful)])?;
    assert_eq!(page.acquisitions.len(), 3);
    Ok(())
}

fn braced_item<'source>(source: &'source str, declaration: &str) -> &'source str {
    let declaration_start = source
        .find(declaration)
        .unwrap_or_else(|| panic!("missing source declaration: {declaration}"));
    let open = source[declaration_start..]
        .find('{')
        .map(|offset| declaration_start + offset)
        .unwrap_or_else(|| panic!("missing opening brace for: {declaration}"));

    let mut depth = 0usize;
    for (offset, character) in source[open..].char_indices() {
        match character {
            '{' => depth += 1,
            '}' => {
                depth -= 1;
                if depth == 0 {
                    return &source[open + 1..open + offset];
                }
            }
            _ => {}
        }
    }

    panic!("missing closing brace for: {declaration}");
}

fn field_types<'source>(
    source: &'source str,
    declaration: &str,
) -> Vec<(&'source str, &'source str)> {
    braced_item(source, declaration)
        .lines()
        .filter_map(|line| {
            let line = line.trim();
            if line.is_empty() || line.starts_with("//") {
                return None;
            }
            let field = line.trim_end_matches(',');
            let (name, field_type) = field.split_once(':')?;
            Some((name.trim(), field_type.trim()))
        })
        .collect()
}

fn contains_identifier(source: &str, expected: &str) -> bool {
    source
        .split(|character: char| !character.is_ascii_alphanumeric() && character != '_')
        .any(|identifier| identifier == expected)
}

fn export_items<'source>(source: &'source str, declaration: &str) -> Vec<&'source str> {
    braced_item(source, declaration)
        .split(',')
        .map(str::trim)
        .filter(|item| !item.is_empty())
        .collect()
}

#[test]
fn response_and_attempt_outcomes_keep_only_projected_or_internal_bounded_source() {
    let carriers = [
        ("Response", field_types(RESPONSE, "pub struct Response {")),
        (
            "AttemptResult",
            field_types(ATTEMPT, "pub struct AttemptResult {"),
        ),
        (
            "AttemptDocumentOutcome",
            field_types(ATTEMPT, "pub struct AttemptDocumentOutcome {"),
        ),
        (
            "AttemptFailure",
            field_types(FAILURE, "pub struct AttemptFailure {"),
        ),
        (
            "NotStartedAttempt",
            field_types(FAILURE, "pub struct NotStartedAttempt {"),
        ),
    ];

    let forbidden_types = [
        "CaptureBundle",
        "PolicyCapture",
        "BrowserAdapterResult",
        "BrowserContextRef",
        "BrowserHandle",
        "PageHandle",
        "Client",
        "HashMap",
        "BTreeMap",
        "PayloadMap",
    ];

    for (carrier, fields) in carriers {
        for (field, field_type) in fields {
            if carrier == "AttemptResult" && field == "raw_response" {
                // Map can inspect a complete, policy-bounded source when no
                // public ResponseDocument could be projected. The payload is
                // moved from Capture and exposed only inside this crate.
                assert_eq!(field_type, "Option<Vec<u8>>");
                assert!(ATTEMPT.contains("pub(crate) fn raw_response(&self) -> Option<&[u8]>"));
                continue;
            }
            for forbidden in forbidden_types {
                assert!(
                    !contains_identifier(field_type, forbidden),
                    "{carrier}.{field} must not retain {forbidden}: {field_type}"
                );
            }
            let compact_type: String = field_type
                .chars()
                .filter(|character| !character.is_whitespace())
                .collect();
            assert!(
                !compact_type.contains("Vec<u8>"),
                "{carrier}.{field} must not retain raw payload bytes"
            );
        }
    }
}

#[test]
fn request_facade_exports_outcomes_without_capture_or_provider_internals() {
    let forbidden_exports = [
        "CaptureBundle",
        "PolicyCapture",
        "BrowserAdapterResult",
        "BrowserContextRef",
        "BrowserResolutionInputs",
        "DirectHttpResolutionInputs",
        "LocatorPlan",
        "RawPayloadMap",
    ];

    for (source, declaration) in [
        (LIB, "pub use request::{"),
        (REQUEST, "pub use execution::{"),
    ] {
        for item in export_items(source, declaration) {
            for forbidden in forbidden_exports {
                assert!(
                    !contains_identifier(item, forbidden),
                    "request facade must not export {forbidden}: {item}"
                );
            }
        }
    }
}

#[test]
fn curated_prelude_omits_advanced_capture_and_provider_setup() {
    let exports = export_items(LIB, "pub use crate::{");
    for forbidden in [
        "PolicyCapture",
        "PolicyResolver",
        "ResolvedPolicySpec",
        "ProjectedAttempt",
        "project_attempt",
        "RequestExecutor",
        "PreparedPageRequest",
        "BrowserContextRef",
        "BrowserResolutionInputs",
        "DirectHttpResolutionInputs",
        "AcceptedSourceFormats",
    ] {
        assert!(
            exports
                .iter()
                .all(|item| !contains_identifier(item, forbidden)),
            "curated prelude must keep {forbidden} at the advanced crate-root boundary"
        );
    }
}

#[test]
fn request_execution_delegates_serially_without_a_client_or_scheduler() {
    let executor_fields = field_types(EXECUTION, "pub struct RequestExecutor {");
    assert_eq!(
        executor_fields,
        vec![
            ("direct_http", "Option<DirectHttpResolutionInputs>"),
            ("browser_headless", "Option<BrowserResolutionInputs>"),
            ("browser_headful", "Option<BrowserResolutionInputs>"),
        ]
    );

    assert!(EXECUTION.contains("PolicyResolver::resolve(prepared, attempt, context)"));
    assert!(EXECUTION.contains("resolved.execute(cancellation).await"));
    assert!(EXECUTION.contains("for attempt in prepared.attempts()"));

    assert!(EXECUTION.contains("standard::for_prepared(&prepared)"));

    for source in [EXECUTION, STANDARD] {
        for forbidden in [
            "wreq::Client::new",
            "reqwest::Client::new",
            "chromiumoxide::Browser::launch",
            "tokio::spawn(",
            "JoinSet::new(",
            "FuturesUnordered::new(",
            "Semaphore::new(",
            "std::sync::OnceLock",
            "std::sync::LazyLock",
            "thread_local!",
            "tokio_retry",
            "backoff::",
            "retry(",
        ] {
            assert!(
                !source.contains(forbidden),
                "request execution must reuse existing adapters without {forbidden}"
            );
        }
    }
}

#[test]
fn request_modules_do_not_execute_locator_plans() {
    for (module, source) in [
        ("request.rs", REQUEST),
        ("request/execution.rs", EXECUTION),
        ("request/execution/standard.rs", STANDARD),
        ("request/execution/outcome/response.rs", RESPONSE),
        ("request/execution/outcome/attempt.rs", ATTEMPT),
        ("request/execution/outcome/failure.rs", FAILURE),
    ] {
        for forbidden in [
            "LocatorPlan",
            "ParsedHtmlDocument",
            "EvaluationOutcome",
            ".locate(",
            ".evaluate(",
        ] {
            assert!(
                !source.contains(forbidden),
                "{module} must leave document evaluation to the locator API"
            );
        }
    }
}
