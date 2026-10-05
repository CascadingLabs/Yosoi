//! Convert Python authoring values into the existing public Rust plan builders.

use std::collections::BTreeMap;

use pyo3::prelude::*;
use serde::Deserialize;
use yosoi::locators as ys;

use crate::errors::{self, LocatorError};

#[pyfunction]
pub fn projected_value_equal(py: Python<'_>, left: &str, right: &str) -> PyResult<bool> {
    let decode = |value: &str| -> PyResult<ys::ProjectedValue> {
        serde_json::from_str(value).map_err(|error| {
            errors::serde_decode_error(py, LocatorError::new_err(error.to_string()), &error)
        })
    };
    Ok(decode(left)? == decode(right)?)
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct QueryDeclaration {
    kind: String,
    expression: String,
    #[serde(default)]
    namespaces: BTreeMap<String, String>,
    #[serde(default)]
    state: Option<bool>,
    #[serde(default)]
    shape: Option<ys::QueryResultShape>,
    #[serde(default)]
    within: Option<Box<RegionDeclaration>>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RegionDeclaration {
    id: String,
    query: QueryDeclaration,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct LocatorDeclaration {
    query: QueryDeclaration,
    projection: String,
    #[serde(default)]
    attribute: Option<String>,
    #[serde(default)]
    captures: Vec<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct OutputDeclaration {
    id: String,
    locator: LocatorDeclaration,
}

fn query(py: Python<'_>, declaration: &QueryDeclaration) -> PyResult<ys::QuerySpec> {
    let expression = &declaration.expression;
    if declaration.kind != "accessibility_state" && declaration.state.is_some() {
        return Err(LocatorError::new_err(
            "state is only valid for accessibility_state",
        ));
    }
    let compiled = match declaration.kind.as_str() {
        "css" => ys::css(expression),
        "xpath" => ys::xpath(expression),
        "tree_text_contains" => ys::tree_text_contains(expression),
        "json_pointer" => ys::json_pointer(expression),
        "json_path" => ys::json_path(expression),
        "role" => ys::role(expression),
        "accessible_name" => ys::accessible_name(expression),
        "accessibility_text" => ys::accessibility_text(expression),
        "text_literal" => ys::text_literal(expression),
        "regex" => ys::regex(expression),
        "accessibility_state" => {
            let name = match expression.as_str() {
                "expanded" => ys::AccessibilityStateName::Expanded,
                "focused" => ys::AccessibilityStateName::Focused,
                _ => return Err(LocatorError::new_err("unknown accessibility state")),
            };
            let value = declaration.state.ok_or_else(|| {
                LocatorError::new_err("accessibility_state requires a boolean value")
            })?;
            Ok(ys::accessibility_state(name, value))
        }
        _ => return Err(LocatorError::new_err("unknown locator family")),
    };
    let mut compiled = compiled.map_err(|error| errors::query_error(py, &error))?;
    if let Some(shape) = declaration.shape {
        compiled = ys::QuerySpec::new(compiled.atom().clone(), shape);
    }
    for (prefix, uri) in &declaration.namespaces {
        compiled = if prefix.is_empty() && declaration.kind == "css" {
            compiled.with_default_namespace(uri)
        } else {
            compiled.with_namespace(prefix, uri)
        }
        .map_err(|error| errors::query_error(py, &error))?;
    }
    Ok(compiled)
}

fn projected(py: Python<'_>, declaration: &LocatorDeclaration) -> PyResult<ys::OutputPlan> {
    if declaration.projection != "attribute" && declaration.attribute.is_some() {
        return Err(LocatorError::new_err(
            "attribute name requires attribute projection",
        ));
    }
    if declaration.projection != "captures" && !declaration.captures.is_empty() {
        return Err(LocatorError::new_err(
            "capture names require captures projection",
        ));
    }
    let compiled = query(py, &declaration.query)?;
    let output = match declaration.projection.as_str() {
        "text" => compiled.text(),
        "value" => compiled.value(),
        "node" => compiled.node(),
        "name" => compiled.name(),
        "attribute" => compiled
            .attribute(
                declaration
                    .attribute
                    .as_deref()
                    .ok_or_else(|| LocatorError::new_err("attribute projection requires a name"))?,
            )
            .map_err(|error| errors::query_error(py, &error))?,
        "captures" => compiled
            .captures(declaration.captures.clone())
            .map_err(|error| errors::query_error(py, &error))?,
        _ => return Err(LocatorError::new_err("unknown projection")),
    };
    let Some(region) = &declaration.query.within else {
        return Ok(output);
    };
    if region.query.within.is_some() {
        return Err(LocatorError::new_err("nested regions are not supported"));
    }
    let region = query(py, &region.query)?
        .each_as_region(&region.id)
        .map_err(|error| errors::query_error(py, &error))?;
    let selection = region.find(query(py, &declaration.query)?);
    Ok(match declaration.projection.as_str() {
        "text" => selection.text(),
        "value" => selection.value(),
        "node" => selection.node(),
        "name" => selection.name(),
        "attribute" => selection
            .attribute(
                declaration
                    .attribute
                    .as_deref()
                    .ok_or_else(|| LocatorError::new_err("attribute projection requires a name"))?,
            )
            .map_err(|error| errors::query_error(py, &error))?,
        "captures" => selection
            .captures(declaration.captures.clone())
            .map_err(|error| errors::query_error(py, &error))?,
        _ => return Err(LocatorError::new_err("unknown projection")),
    })
}

#[pyclass(frozen, skip_from_py_object, module = "yosoi._native", name = "Plan")]
#[derive(Clone, Debug)]
pub struct NativePlan {
    pub inner: ys::Plan,
}

#[pymethods]
impl NativePlan {
    #[new]
    fn new(py: Python<'_>, outputs_json: &str) -> PyResult<Self> {
        let declarations: Vec<OutputDeclaration> =
            serde_json::from_str(outputs_json).map_err(|error| {
                errors::serde_decode_error(py, LocatorError::new_err(error.to_string()), &error)
            })?;
        let mut outputs = Vec::with_capacity(declarations.len());
        for declaration in declarations {
            outputs.push(
                ys::output(declaration.id, projected(py, &declaration.locator)?)
                    .map_err(|error| errors::plan_error(py, &error))?,
            );
        }
        let inner = ys::Plan::new(outputs).map_err(|error| errors::plan_error(py, &error))?;
        Ok(Self { inner })
    }

    #[staticmethod]
    fn from_json(py: Python<'_>, value: &str) -> PyResult<Self> {
        serde_json::from_str::<ys::Plan>(value)
            .map(|inner| Self { inner })
            .map_err(|error| {
                errors::serde_decode_error(py, LocatorError::new_err(error.to_string()), &error)
            })
    }

    fn to_json(&self, py: Python<'_>) -> PyResult<String> {
        serde_json::to_string(&self.inner).map_err(|error| {
            errors::serde_encode_error(py, LocatorError::new_err(error.to_string()), &error)
        })
    }
}

#[pyfunction]
pub fn validate_query(py: Python<'_>, declaration_json: &str) -> PyResult<()> {
    let declaration: QueryDeclaration =
        serde_json::from_str(declaration_json).map_err(|error| {
            errors::serde_decode_error(py, LocatorError::new_err(error.to_string()), &error)
        })?;
    query(py, &declaration).map(|_| ())
}

#[pyfunction]
pub fn validate_namespace(
    py: Python<'_>,
    declaration_json: &str,
    prefix: Option<&str>,
    uri: &str,
) -> PyResult<()> {
    let declaration: QueryDeclaration =
        serde_json::from_str(declaration_json).map_err(|error| {
            errors::serde_decode_error(py, LocatorError::new_err(error.to_string()), &error)
        })?;
    let compiled = query(py, &declaration)?;
    match prefix {
        Some(prefix) => compiled.with_namespace(prefix, uri),
        None => compiled.with_default_namespace(uri),
    }
    .map(|_| ())
    .map_err(|error| errors::query_error(py, &error))
}
#[pyfunction]
pub fn validate_region_id(py: Python<'_>, value: &str) -> PyResult<()> {
    ys::RegionId::try_new(value)
        .map(|_| ())
        .map_err(|error| errors::query_error(py, &error))
}
#[pyfunction]
pub fn validate_output_id(py: Python<'_>, value: &str) -> PyResult<()> {
    ys::OutputId::try_new(value)
        .map(|_| ())
        .map_err(|error| errors::plan_error(py, &error))
}

#[pyfunction]
pub fn validate_locator(py: Python<'_>, declaration_json: &str) -> PyResult<()> {
    let declaration: LocatorDeclaration =
        serde_json::from_str(declaration_json).map_err(|error| {
            errors::serde_decode_error(py, LocatorError::new_err(error.to_string()), &error)
        })?;
    projected(py, &declaration).map(|_| ())
}

fn query_info(py: Python<'_>, compiled: &ys::QuerySpec) -> PyResult<String> {
    let bytes = compiled
        .query_bytes()
        .map_err(|error| errors::query_error(py, &error))?;
    serde_json::to_string(&serde_json::json!({"query": compiled, "query_bytes": bytes})).map_err(
        |error| errors::serde_encode_error(py, LocatorError::new_err(error.to_string()), &error),
    )
}
#[pyfunction]
pub fn authored_query_info(py: Python<'_>, value: &str) -> PyResult<String> {
    let declaration: QueryDeclaration = serde_json::from_str(value).map_err(|error| {
        errors::serde_decode_error(py, LocatorError::new_err(error.to_string()), &error)
    })?;
    query_info(py, &query(py, &declaration)?)
}
#[pyfunction]
pub fn compiled_query_info(py: Python<'_>, value: &str) -> PyResult<String> {
    let compiled: ys::QuerySpec = serde_json::from_str(value).map_err(|error| {
        errors::serde_decode_error(py, LocatorError::new_err(error.to_string()), &error)
    })?;
    query_info(py, &compiled)
}
#[pyfunction]
pub fn compiled_query_namespace(
    py: Python<'_>,
    value: &str,
    prefix: Option<&str>,
    uri: &str,
) -> PyResult<String> {
    let compiled: ys::QuerySpec = serde_json::from_str(value).map_err(|error| {
        errors::serde_decode_error(py, LocatorError::new_err(error.to_string()), &error)
    })?;
    let compiled = match prefix {
        Some(prefix) => compiled.with_namespace(prefix, uri),
        None => compiled.with_default_namespace(uri),
    }
    .map_err(|error| errors::query_error(py, &error))?;
    serde_json::to_string(&compiled).map_err(|error| {
        errors::serde_encode_error(py, LocatorError::new_err(error.to_string()), &error)
    })
}
