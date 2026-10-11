use pyo3::prelude::{PyErr, Python};
use serde_json::{Value, json};
use yosoi::map::MapError as SdkMapError;
use yosoi::policy::search::Provider;
use yosoi::policy::{AcquisitionKind, BrowserMode, DocumentRequest, PolicyError as SdkPolicyError};
use yosoi::request::{
    RequestPreparationError as SdkRequestPreparationError, RequestSendError as SdkRequestSendError,
};
use yosoi::search::{
    SearchQueryError as SdkSearchQueryError, SearchSendError as SdkSearchSendError,
};

use super::{MapError, PolicyError, RequestError, SearchError, source_chain, with_metadata};

pub fn policy_error(py: Python<'_>, error: &SdkPolicyError) -> PyErr {
    let (variant, details) = policy_error_details(error);
    with_metadata(
        py,
        PolicyError::new_err(error.to_string()),
        "yosoi_policy::PolicyError",
        Some(variant),
        details,
        &source_chain(error),
    )
}

fn policy_error_details(error: &SdkPolicyError) -> (&'static str, Value) {
    use SdkPolicyError as E;
    match error {
        E::ZeroCountLimit => ("ZeroCountLimit", json!({})),
        E::ZeroStepLimit => ("ZeroStepLimit", json!({})),
        E::ZeroByteLimit => ("ZeroByteLimit", json!({})),
        E::ByteLimitNotAddressable => ("ByteLimitNotAddressable", json!({})),
        E::ZeroEventLimit => ("ZeroEventLimit", json!({})),
        E::EventLimitNotAddressable => ("EventLimitNotAddressable", json!({})),
        E::ZeroResourceLimit => ("ZeroResourceLimit", json!({})),
        E::ResourceLimitNotAddressable => ("ResourceLimitNotAddressable", json!({})),
        E::ZeroAccessibilityNodeLimit => ("ZeroAccessibilityNodeLimit", json!({})),
        E::AccessibilityNodeLimitNotAddressable => {
            ("AccessibilityNodeLimitNotAddressable", json!({}))
        }
        E::ZeroMaximumElapsed => ("ZeroMaximumElapsed", json!({})),
        E::ZeroRedirectHopLimit => ("ZeroRedirectHopLimit", json!({})),
        E::ZeroMapBudget => ("ZeroMapBudget", json!({})),
        E::ZeroMapMaximumElapsed => ("ZeroMapMaximumElapsed", json!({})),
        E::InvalidMapDuration => ("InvalidMapDuration", json!({})),
        E::PassiveSubdomainsRequireRegistrableDomain => {
            ("PassiveSubdomainsRequireRegistrableDomain", json!({}))
        }
        E::TooManyMapFilters => ("TooManyMapFilters", json!({})),
        E::MapFilterStringTooLong => ("MapFilterStringTooLong", json!({})),
        E::EmptyMapPathPrefix => ("EmptyMapPathPrefix", json!({})),
        E::TooManyAcquisitions => ("TooManyAcquisitions", json!({})),
        E::DuplicateAcquisition(acquisition) => (
            "DuplicateAcquisition",
            json!({"acquisition": acquisition_kind_value(*acquisition)}),
        ),
        E::TooManyDocuments => ("TooManyDocuments", json!({})),
        E::DuplicateDocument(document) => (
            "DuplicateDocument",
            json!({"document": document_request_value(*document)}),
        ),
        E::NonCanonicalDocumentOrder => ("NonCanonicalDocumentOrder", json!({})),
        E::UnsupportedDirectHttpDocument => ("UnsupportedDirectHttpDocument", json!({})),
        E::DuplicateSearchProvider(provider) => (
            "DuplicateSearchProvider",
            json!({"provider": provider_name(*provider)}),
        ),
        E::SearchPlanArithmeticOverflow => ("SearchPlanArithmeticOverflow", json!({})),
        E::SearchPlanExceedsTotalResults { required, limit } => (
            "SearchPlanExceedsTotalResults",
            json!({"required": required, "limit": limit}),
        ),
        E::ZeroSearchPerProviderLimit => ("ZeroSearchPerProviderLimit", json!({})),
        E::ZeroProviderDefaultsVersion => ("ZeroProviderDefaultsVersion", json!({})),
        E::LegacyIdentityCannotIncludeSearch => ("LegacyIdentityCannotIncludeSearch", json!({})),
        E::LegacyIdentityCannotIncludeMap => ("LegacyIdentityCannotIncludeMap", json!({})),
        E::LegacyIdentityCannotIncludeRobots => ("LegacyIdentityCannotIncludeRobots", json!({})),
        E::InvalidEffectiveSearchRoute => ("InvalidEffectiveSearchRoute", json!({})),
        E::ArchivedIdentityMismatch => ("ArchivedIdentityMismatch", json!({})),
        E::ArchivedSnapshotMismatch => ("ArchivedSnapshotMismatch", json!({})),
        E::Serialization(message) => ("Serialization", json!({"message": message})),
    }
}

pub fn request_preparation_error(py: Python<'_>, error: &SdkRequestPreparationError) -> PyErr {
    with_metadata(
        py,
        RequestError::new_err(error.to_string()),
        "yosoi::request::RequestPreparationError",
        None,
        json!({"opaque": true}),
        &source_chain(error),
    )
}

pub fn request_send_error(py: Python<'_>, error: &SdkRequestSendError) -> PyErr {
    with_metadata(
        py,
        RequestError::new_err(error.to_string()),
        "yosoi::request::RequestSendError",
        None,
        json!({"opaque": true}),
        &source_chain(error),
    )
}

pub fn map_error(py: Python<'_>, error: &SdkMapError) -> PyErr {
    with_metadata(
        py,
        MapError::new_err(error.to_string()),
        "yosoi::map::MapError",
        None,
        json!({"opaque": true}),
        &source_chain(error),
    )
}

pub fn search_query_error(py: Python<'_>, error: &SdkSearchQueryError) -> PyErr {
    use SdkSearchQueryError as E;
    let (variant, details) = match error {
        E::Empty => ("Empty", json!({})),
        E::TooLong { maximum, observed } => {
            ("TooLong", json!({"maximum": maximum, "observed": observed}))
        }
    };
    with_metadata(
        py,
        SearchError::new_err(error.to_string()),
        "yosoi::search::SearchQueryError",
        Some(variant),
        details,
        &source_chain(error),
    )
}

pub fn search_send_error(py: Python<'_>, error: &SdkSearchSendError) -> PyErr {
    use SdkSearchSendError as E;
    let (variant, details) = match error {
        E::NoProviderConfigured => ("NoProviderConfigured", json!({})),
        E::Policy(source) => {
            let (variant, details) = policy_error_details(source);
            (
                "Policy",
                json!({"source": {
                    "rust_type": "yosoi_policy::PolicyError",
                    "variant": variant,
                    "details": details
                }}),
            )
        }
        E::Execution(_) => ("Execution", json!({})),
    };
    with_metadata(
        py,
        SearchError::new_err(error.to_string()),
        "yosoi::search::SearchSendError",
        Some(variant),
        details,
        &source_chain(error),
    )
}

fn acquisition_kind_value(value: AcquisitionKind) -> Value {
    match value {
        AcquisitionKind::DirectHttp => json!({"kind": "direct_http"}),
        AcquisitionKind::Browser { mode } => json!({
            "kind": "browser",
            "mode": match mode {
                BrowserMode::Headless => "headless",
                BrowserMode::Headful => "headful",
            }
        }),
    }
}

const fn document_request_value(value: DocumentRequest) -> &'static str {
    match value {
        DocumentRequest::ResponseDocument => "response_document",
        DocumentRequest::RenderedDom => "rendered_dom",
        DocumentRequest::AccessibilityTree => "accessibility_tree",
        DocumentRequest::NetworkTree => "network_tree",
    }
}

const fn provider_name(value: Provider) -> &'static str {
    match value {
        Provider::Brave => "brave",
        Provider::Bing => "bing",
        Provider::DuckDuckGo => "duck_duck_go",
    }
}
