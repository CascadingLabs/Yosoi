//! Python exceptions correspond to public SDK input and operation failures.

use pyo3::{
    create_exception,
    exceptions::PyException,
    prelude::*,
    types::{PyBool, PyDict, PyFloat, PyInt, PyList, PyString},
};
use serde::Serialize;
use serde_json::{Value, error::Category, json};
use std::{convert::TryFrom, error::Error as StdError};
use yosoi::contracts::{ContractSchemaError, RuntimeContractArchiveError, RuntimeContractError};
use yosoi::documents::{
    DocumentEpoch, DocumentError as SdkDocumentError, ParseError as SdkParseError,
};
use yosoi::locators::{CoordinateError, JsonQuerySyntaxError, PlanError, QueryError};
use yosoi::map::MapError as SdkMapError;
use yosoi::policy::search::Provider;
use yosoi::policy::{AcquisitionKind, BrowserMode, DocumentRequest, PolicyError as SdkPolicyError};
use yosoi::{
    request::RequestPreparationError as SdkRequestPreparationError,
    request::RequestSendError as SdkRequestSendError,
    search::{SearchQueryError as SdkSearchQueryError, SearchSendError as SdkSearchSendError},
};

type DocumentProfileError = <DocumentEpoch as TryFrom<u64>>::Error;

create_exception!(_native, YosoiError, PyException);
create_exception!(_native, DocumentError, YosoiError);
create_exception!(_native, ParseError, YosoiError);
create_exception!(_native, LocatorError, YosoiError);
create_exception!(_native, PolicyError, YosoiError);
create_exception!(_native, ClosedResourceError, YosoiError);
create_exception!(_native, RequestError, YosoiError);
create_exception!(_native, MapError, YosoiError);
create_exception!(_native, SearchError, YosoiError);
create_exception!(_native, ContractError, YosoiError);

/// Attaches Rust error identity and payload to the existing exception category
/// without changing its Display message or Python inheritance. Opaque public
/// wrappers carry no variant because their inner discriminants are not exposed.
pub fn with_metadata(
    py: Python<'_>,
    error: PyErr,
    rust_type: &str,
    variant: Option<&str>,
    details: Value,
    source_chain: &[String],
) -> PyErr {
    let value = error.value(py);
    let _ = value.setattr("rust_type", rust_type);
    match variant {
        Some(variant) => {
            let _ = value.setattr("variant", variant);
        }
        None => {
            let _ = value.setattr("variant", py.None());
        }
    }
    if let Ok(details) = json_to_python(py, details) {
        let _ = value.setattr("details", details);
    }
    let sources = PyList::empty(py);
    for source in source_chain {
        let _ = sources.append(source);
    }
    let _ = value.setattr("source_chain", sources);
    error
}

fn json_to_python(py: Python<'_>, value: Value) -> PyResult<Bound<'_, PyAny>> {
    match value {
        Value::Null => Ok(py.None().into_bound(py)),
        Value::Bool(value) => Ok(PyBool::new(py, value).to_owned().into_any()),
        Value::Number(value) => value.as_i64().map_or_else(
            || {
                value.as_u64().map_or_else(
                    || {
                        value.as_f64().map_or_else(
                            || Ok(py.None().into_bound(py)),
                            |value| Ok(PyFloat::new(py, value).into_any()),
                        )
                    },
                    |value| Ok(PyInt::new(py, value).into_any()),
                )
            },
            |value| Ok(PyInt::new(py, value).into_any()),
        ),
        Value::String(value) => Ok(PyString::new(py, &value).into_any()),
        Value::Array(values) => {
            let result = PyList::empty(py);
            for value in values {
                result.append(json_to_python(py, value)?)?;
            }
            Ok(result.into_any())
        }
        Value::Object(values) => {
            let result = PyDict::new(py);
            for (key, value) in values {
                result.set_item(key, json_to_python(py, value)?)?;
            }
            Ok(result.into_any())
        }
    }
}

fn source_chain(error: &(dyn StdError + 'static)) -> Vec<String> {
    let mut result = Vec::new();
    let mut source = error.source();
    while let Some(error) = source {
        result.push(error.to_string());
        source = error.source();
    }
    result
}

fn serde_value<T: Serialize>(value: &T) -> Value {
    match serde_json::to_value(value) {
        Ok(value) => value,
        Err(error) => json!({"serialization_error": error.to_string()}),
    }
}

pub fn serde_decode_error(py: Python<'_>, error: PyErr, source: &serde_json::Error) -> PyErr {
    let (variant, category) = match source.classify() {
        Category::Io => ("Io", "io"),
        Category::Syntax => ("Syntax", "syntax"),
        Category::Data => ("Data", "data"),
        Category::Eof => ("Eof", "eof"),
    };
    with_metadata(
        py,
        error,
        "serde_json::Error",
        Some(variant),
        json!({"category": category, "line": source.line(), "column": source.column()}),
        &[],
    )
}

pub fn serde_encode_error(py: Python<'_>, error: PyErr, source: &serde_json::Error) -> PyErr {
    with_metadata(
        py,
        error,
        "serde_json::Error",
        Some("Serialize"),
        json!({"message": source.to_string()}),
        &[],
    )
}

fn document_profile_error_details(error: DocumentProfileError) -> (&'static str, Value) {
    use DocumentProfileError as E;
    match error {
        E::IncompatibleAxes => ("IncompatibleAxes", json!({})),
        E::UnexpectedEpoch => ("UnexpectedEpoch", json!({})),
        E::MissingEpoch => ("MissingEpoch", json!({})),
        E::ZeroEpoch => ("ZeroEpoch", json!({})),
    }
}

pub fn document_profile_error(py: Python<'_>, error: DocumentProfileError) -> PyErr {
    let (variant, details) = document_profile_error_details(error);
    with_metadata(
        py,
        DocumentError::new_err(error.to_string()),
        "yosoi_documents::DocumentProfileError",
        Some(variant),
        details,
        &source_chain(&error),
    )
}

fn document_error_details(error: &SdkDocumentError) -> (&'static str, Value) {
    use SdkDocumentError as E;
    match error {
        E::EmptyId => ("EmptyId", json!({})),
        E::EmptyPayload => ("EmptyPayload", json!({})),
        E::PayloadLengthOverflow => ("PayloadLengthOverflow", json!({})),
        E::InvalidProfile(source) => {
            let (variant, details) = document_profile_error_details(*source);
            (
                "InvalidProfile",
                json!({
                    "source": {
                        "rust_type": "yosoi_documents::DocumentProfileError",
                        "variant": variant,
                        "details": details
                    }
                }),
            )
        }
    }
}

pub fn document_error(py: Python<'_>, error: &SdkDocumentError) -> PyErr {
    let (variant, details) = document_error_details(error);
    with_metadata(
        py,
        DocumentError::new_err(error.to_string()),
        "yosoi_documents::DocumentError",
        Some(variant),
        details,
        &source_chain(error),
    )
}

fn parse_error_details(error: &SdkParseError) -> (&'static str, Value) {
    use SdkParseError as E;
    match error {
        E::InvalidResourcePolicy { limit } => (
            "InvalidResourcePolicy",
            json!({"limit": serde_value(limit)}),
        ),
        // The SDK facade exposes this type only as the `ParseError::Document`
        // payload. Preserve that public source family and its Error chain;
        // do not infer unexported parser variants from Debug or Display text.
        E::Document(source) => (
            "Document",
            json!({
                "source": {
                    "rust_type": "yosoi_documents::DocumentParseError",
                    "message": source.to_string()
                }
            }),
        ),
    }
}

pub fn parse_error(py: Python<'_>, error: &SdkParseError) -> PyErr {
    let (variant, details) = parse_error_details(error);
    with_metadata(
        py,
        ParseError::new_err(error.to_string()),
        "yosoi_engine::ParseError",
        Some(variant),
        details,
        &source_chain(error),
    )
}

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

fn json_query_syntax_error(error: JsonQuerySyntaxError) -> Value {
    use JsonQuerySyntaxError as E;
    let variant = match error {
        E::InvalidPointerSyntax => "InvalidPointerSyntax",
        E::InvalidPointerEscape => "InvalidPointerEscape",
        E::InvalidPathSyntax => "InvalidPathSyntax",
        E::UnsupportedPathFeature => "UnsupportedPathFeature",
    };
    json!({"rust_type": "yosoi_documents::JsonQuerySyntaxError", "variant": variant, "details": {}})
}

fn query_error_details(error: &QueryError) -> (&'static str, Value) {
    use QueryError as E;
    match error {
        E::EmptyExpression => ("EmptyExpression", json!({})),
        E::InvalidRegexSyntax => ("InvalidRegexSyntax", json!({})),
        E::EmptyAttributeName => ("EmptyAttributeName", json!({})),
        E::EmptyRegionId => ("EmptyRegionId", json!({})),
        E::EmptyCaptureList => ("EmptyCaptureList", json!({})),
        E::EmptyCaptureName => ("EmptyCaptureName", json!({})),
        E::DuplicateCaptureName { name } => ("DuplicateCaptureName", json!({"name": name})),
        E::UnknownCaptureName { name } => ("UnknownCaptureName", json!({"name": name})),
        E::LengthOverflow => ("LengthOverflow", json!({})),
        E::InvalidNamespacePrefix => ("InvalidNamespacePrefix", json!({})),
        E::EmptyNamespaceUri => ("EmptyNamespaceUri", json!({})),
        E::DuplicateNamespacePrefix => ("DuplicateNamespacePrefix", json!({})),
        E::ReservedNamespacePrefix => ("ReservedNamespacePrefix", json!({})),
        E::UnboundNamespacePrefix => ("UnboundNamespacePrefix", json!({})),
        E::NamespacesRequireXmlLocator => ("NamespacesRequireXmlLocator", json!({})),
        E::NonCanonicalNamespaceBindingOrder => ("NonCanonicalNamespaceBindingOrder", json!({})),
        E::DefaultNamespaceOnlyForCss => ("DefaultNamespaceOnlyForCss", json!({})),
        E::InvalidAttributeNamespaceName => ("InvalidAttributeNamespaceName", json!({})),
        E::InvalidJsonQuery(source) => (
            "InvalidJsonQuery",
            json!({"source": json_query_syntax_error(*source)}),
        ),
    }
}

pub fn query_error(py: Python<'_>, error: &QueryError) -> PyErr {
    let (variant, details) = query_error_details(error);
    with_metadata(
        py,
        LocatorError::new_err(error.to_string()),
        "yosoi_documents::QueryError",
        Some(variant),
        details,
        &source_chain(error),
    )
}

pub fn plan_error(py: Python<'_>, error: &PlanError) -> PyErr {
    use PlanError as E;
    let (variant, details) = match error {
        E::NoOutputs => ("NoOutputs", json!({})),
        E::EmptyOutputId => ("EmptyOutputId", json!({})),
        E::EmptyQueryExpression => ("EmptyQueryExpression", json!({})),
        E::InvalidQueryNamespaces(source) => {
            let (variant, details) = query_error_details(source);
            (
                "InvalidQueryNamespaces",
                json!({
                    "source": {
                        "rust_type": "yosoi_documents::QueryError",
                        "variant": variant,
                        "details": details
                    }
                }),
            )
        }
        E::InvalidQuerySyntax { atom } => {
            ("InvalidQuerySyntax", json!({"atom": serde_value(atom)}))
        }
        E::InvalidJsonQuery(source) => (
            "InvalidJsonQuery",
            json!({"source": json_query_syntax_error(*source)}),
        ),
        E::EmptyProjectionArgument => ("EmptyProjectionArgument", json!({})),
        E::DuplicateCaptureName { name } => ("DuplicateCaptureName", json!({"name": name})),
        E::UnknownCaptureName { name } => ("UnknownCaptureName", json!({"name": name})),
        E::DuplicateOutput { id } => ("DuplicateOutput", json!({"id": id.as_str()})),
        E::ConflictingRegion { id } => ("ConflictingRegion", json!({"id": id.as_str()})),
        E::InvalidRegionQuery { atom, result_shape } => (
            "InvalidRegionQuery",
            json!({"atom": serde_value(atom), "result_shape": serde_value(result_shape)}),
        ),
        E::InvalidCombination {
            atom,
            result_shape,
            projection,
        } => (
            "InvalidCombination",
            json!({
                "atom": serde_value(atom),
                "result_shape": serde_value(result_shape),
                "projection": projection
            }),
        ),
        E::NoCommonDocument => ("NoCommonDocument", json!({})),
    };
    with_metadata(
        py,
        LocatorError::new_err(error.to_string()),
        "yosoi_documents::PlanError",
        Some(variant),
        details,
        &source_chain(error),
    )
}

pub fn coordinate_error(py: Python<'_>, error: CoordinateError) -> PyErr {
    use CoordinateError as E;
    let variant = match error {
        E::ReversedRange => "ReversedRange",
        E::EmptyIdentity => "EmptyIdentity",
        E::ZeroDomNodeId => "ZeroDomNodeId",
        E::InvalidJsonPointerSyntax => "InvalidJsonPointerSyntax",
        E::InvalidJsonPointerEscape => "InvalidJsonPointerEscape",
        E::EmptyExpandedLocalName => "EmptyExpandedLocalName",
        E::ZeroExpandedSiblingIndex => "ZeroExpandedSiblingIndex",
        E::EmptyExpandedNamePath => "EmptyExpandedNamePath",
        E::InvalidTreeChildPath => "InvalidTreeChildPath",
    };
    with_metadata(
        py,
        LocatorError::new_err(error.to_string()),
        "yosoi_documents::CoordinateError",
        Some(variant),
        json!({}),
        &source_chain(&error),
    )
}

pub fn contract_schema_error(py: Python<'_>, error: &ContractSchemaError) -> PyErr {
    use ContractSchemaError as E;
    let (variant, details) = match error {
        E::ZeroVersion => ("ZeroVersion", json!({})),
        E::UnsupportedVersion { observed } => ("UnsupportedVersion", json!({"observed": observed})),
        E::EmptyContractId => ("EmptyContractId", json!({})),
        E::EmptyFieldId => ("EmptyFieldId", json!({})),
        E::EmptyContractDescription => ("EmptyContractDescription", json!({})),
        E::EmptyFieldDescription { field } => {
            ("EmptyFieldDescription", json!({"field": field.as_str()}))
        }
        E::EmptyValueType { field } => ("EmptyValueType", json!({"field": field.as_str()})),
        E::NoFields => ("NoFields", json!({})),
        E::DuplicateField { field } => ("DuplicateField", json!({"field": field.as_str()})),
        E::LengthOverflow => ("LengthOverflow", json!({})),
    };
    with_metadata(
        py,
        ContractError::new_err(error.to_string()),
        "yosoi_contracts::ContractSchemaError",
        Some(variant),
        details,
        &source_chain(error),
    )
}

pub fn runtime_contract_error(py: Python<'_>, error: &RuntimeContractError) -> PyErr {
    let RuntimeContractError::UnsupportedValueType { field, value_type } = error;
    with_metadata(
        py,
        ContractError::new_err(error.to_string()),
        "yosoi_contract_validation::RuntimeContractError",
        Some("UnsupportedValueType"),
        json!({"field": field.as_str(), "value_type": value_type}),
        &source_chain(error),
    )
}

pub fn runtime_archive_error(py: Python<'_>, error: &RuntimeContractArchiveError) -> PyErr {
    use RuntimeContractArchiveError as E;
    let (variant, details) = match error {
        E::InvalidSchema => ("InvalidSchema", json!({})),
        E::UnsupportedValueType { field, value_type } => (
            "UnsupportedValueType",
            json!({"field": field.as_str(), "value_type": value_type}),
        ),
        E::RecordSchemaMismatch => ("RecordSchemaMismatch", json!({})),
        E::UnexpectedCandidateField { field } => {
            ("UnexpectedCandidateField", json!({"field": field.as_str()}))
        }
        E::FieldValueMismatch { field } => ("FieldValueMismatch", json!({"field": field.as_str()})),
    };
    with_metadata(
        py,
        ContractError::new_err(error.to_string()),
        "yosoi_contract_validation::RuntimeContractArchiveError",
        Some(variant),
        details,
        &source_chain(error),
    )
}

pub fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    let py = module.py();
    module.add("YosoiError", py.get_type::<YosoiError>())?;
    module.add("DocumentError", py.get_type::<DocumentError>())?;
    module.add("ParseError", py.get_type::<ParseError>())?;
    module.add("LocatorError", py.get_type::<LocatorError>())?;
    module.add("PolicyError", py.get_type::<PolicyError>())?;
    module.add("ClosedResourceError", py.get_type::<ClosedResourceError>())?;
    module.add("RequestError", py.get_type::<RequestError>())?;
    module.add("MapError", py.get_type::<MapError>())?;
    module.add("SearchError", py.get_type::<SearchError>())?;
    module.add("ContractError", py.get_type::<ContractError>())
}
