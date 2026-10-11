use pyo3::prelude::{PyErr, PyResult, Python};
use serde::{Serialize, de::DeserializeOwned};
use yosoi::documents::{DocumentEpoch, DocumentId};
use yosoi::locators::{
    ByteRange, CoordinateError, Finding, LocateResult, RegionLineage, TextRange,
};
use yosoi::policy::PolicyError as RustPolicyError;

use super::PolicyError;
use crate::errors;

pub(super) fn normalize<T>(value_json: &str, invalid: impl Fn(String) -> PyErr) -> PyResult<String>
where
    T: DeserializeOwned + Serialize,
{
    let value = serde_json::from_str::<T>(value_json).map_err(|error| {
        Python::attach(|py| errors::serde_decode_error(py, invalid(error.to_string()), &error))
    })?;
    serde_json::to_string(&value).map_err(|error| {
        Python::attach(|py| errors::serde_encode_error(py, invalid(error.to_string()), &error))
    })
}

pub(super) fn policy_value<T, U>(value_json: &str) -> PyResult<T>
where
    T: TryFrom<U, Error = RustPolicyError>,
    U: DeserializeOwned,
{
    let value = serde_json::from_str::<U>(value_json).map_err(|error| {
        Python::attach(|py| {
            errors::serde_decode_error(py, PolicyError::new_err(error.to_string()), &error)
        })
    })?;
    T::try_from(value).map_err(|error| Python::attach(|py| errors::policy_error(py, &error)))
}

pub(super) fn policy_scalar<T, U>(value_json: &str) -> PyResult<String>
where
    T: TryFrom<U, Error = RustPolicyError> + Serialize,
    U: DeserializeOwned,
{
    let value = policy_value::<T, U>(value_json)?;
    converted_json(&value, PolicyError::new_err)
}

pub(super) fn construct_locate_result_with_regions(
    value_json: &str,
    invalid: impl Fn(String) -> PyErr,
) -> PyResult<String> {
    #[derive(serde::Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Input {
        document_id: DocumentId,
        regions: Vec<RegionLineage>,
        findings: Vec<Finding>,
    }

    let input = serde_json::from_str::<Input>(value_json).map_err(|error| {
        Python::attach(|py| errors::serde_decode_error(py, invalid(error.to_string()), &error))
    })?;
    let result =
        LocateResult::try_new_with_regions(input.document_id, input.regions, input.findings)
            .map_err(|error| invalid(error.to_string()))?;
    serde_json::to_string(&result).map_err(|error| {
        Python::attach(|py| errors::serde_encode_error(py, invalid(error.to_string()), &error))
    })
}

pub(super) fn converted_json<T>(value: &T, invalid: impl Fn(String) -> PyErr) -> PyResult<String>
where
    T: Serialize,
{
    serde_json::to_string(value).map_err(|error| {
        Python::attach(|py| errors::serde_encode_error(py, invalid(error.to_string()), &error))
    })
}

#[derive(Clone, Copy, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct RangeInput {
    pub(super) start: u64,
    pub(super) end: u64,
}

#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ExpandedNamePathSegmentInput {
    pub(super) namespace_uri: Option<String>,
    pub(super) local_name: String,
    pub(super) same_name_sibling_index: u32,
}

#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct TreeCoordinateInput {
    pub(super) child_path: Vec<u32>,
    pub(super) source_bytes: Option<RangeInput>,
    #[serde(default)]
    pub(super) expanded_name_path: Option<Vec<ExpandedNamePathSegmentInput>>,
}

#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct DecodedTextCoordinateInput {
    pub(super) byte_range: RangeInput,
    pub(super) scalar_range: RangeInput,
}

#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct DomCoordinateInput {
    pub(super) document_epoch: DocumentEpoch,
    pub(super) node_id: u64,
}

#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct AccessibilityCoordinateInput {
    pub(super) document_epoch: DocumentEpoch,
    pub(super) node_id: String,
}

pub(super) fn decode_input<T: DeserializeOwned>(
    value_json: &str,
    invalid: impl Fn(String) -> PyErr,
) -> PyResult<T> {
    serde_json::from_str(value_json).map_err(|error| {
        Python::attach(|py| errors::serde_decode_error(py, invalid(error.to_string()), &error))
    })
}

pub(super) const fn byte_range(input: RangeInput) -> Result<ByteRange, CoordinateError> {
    ByteRange::try_new(input.start, input.end)
}

pub(super) const fn text_range(input: RangeInput) -> Result<TextRange, CoordinateError> {
    TextRange::try_new(input.start, input.end)
}

pub(super) fn coordinate_pyerr(error: CoordinateError) -> PyErr {
    Python::attach(|py| errors::coordinate_error(py, error))
}
