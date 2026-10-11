use pyo3::prelude::{PyErr, Python};
use serde_json::{Value, json};
use yosoi::locators::{CoordinateError, JsonQuerySyntaxError, PlanError, QueryError};

use super::{LocatorError, serde_value, source_chain, with_metadata};

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
