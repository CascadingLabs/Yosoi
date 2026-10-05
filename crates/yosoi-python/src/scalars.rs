//! Rust-owned constructors and validation for public SDK scalar values.

use pyo3::{exceptions::PyValueError, prelude::*};
use serde::{Serialize, de::DeserializeOwned};
use yosoi::{
    contracts::{ContractId, FieldId},
    documents::{DocumentEpoch, DocumentId},
    locators::{
        AccessibilityCoordinate, ByteRange, CoordinateError, DecodedTextCoordinate, DomCoordinate,
        DomNodeId, ExpandedNamePathSegment, Finding, JsonCoordinate, LocateResult,
        NativeCoordinate, NodeReference, OutputId, RegionId, RegionLineage, TextRange,
        TreeCoordinate,
    },
    policy::{
        AccessibilityNodeLimit, AddressableByteLimit, Budget, CountLimit, DirectHttpRedirects,
        EventLimit, MaximumElapsed, PolicyError as RustPolicyError, ProviderDefaultsVersion,
        RedirectHopLimit, ResourceLimit, StepLimit,
    },
    request::WebTarget,
};

use crate::errors::{self, ContractError, DocumentError, LocatorError, PolicyError, RequestError};

fn normalize<T>(value_json: &str, invalid: impl Fn(String) -> PyErr) -> PyResult<String>
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

fn policy_value<T, U>(value_json: &str) -> PyResult<T>
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

fn policy_scalar<T, U>(value_json: &str) -> PyResult<String>
where
    T: TryFrom<U, Error = RustPolicyError> + Serialize,
    U: DeserializeOwned,
{
    let value = policy_value::<T, U>(value_json)?;
    converted_json(&value, PolicyError::new_err)
}

fn construct_locate_result_with_regions(
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

fn converted_json<T>(value: &T, invalid: impl Fn(String) -> PyErr) -> PyResult<String>
where
    T: Serialize,
{
    serde_json::to_string(value).map_err(|error| {
        Python::attach(|py| errors::serde_encode_error(py, invalid(error.to_string()), &error))
    })
}

#[derive(Clone, Copy, serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct RangeInput {
    start: u64,
    end: u64,
}

#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct ExpandedNamePathSegmentInput {
    namespace_uri: Option<String>,
    local_name: String,
    same_name_sibling_index: u32,
}

#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct TreeCoordinateInput {
    child_path: Vec<u32>,
    source_bytes: Option<RangeInput>,
    #[serde(default)]
    expanded_name_path: Option<Vec<ExpandedNamePathSegmentInput>>,
}

#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct DecodedTextCoordinateInput {
    byte_range: RangeInput,
    scalar_range: RangeInput,
}

#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct DomCoordinateInput {
    document_epoch: DocumentEpoch,
    node_id: u64,
}

#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct AccessibilityCoordinateInput {
    document_epoch: DocumentEpoch,
    node_id: String,
}

fn decode_input<T: DeserializeOwned>(
    value_json: &str,
    invalid: impl Fn(String) -> PyErr,
) -> PyResult<T> {
    serde_json::from_str(value_json).map_err(|error| {
        Python::attach(|py| errors::serde_decode_error(py, invalid(error.to_string()), &error))
    })
}

const fn byte_range(input: RangeInput) -> Result<ByteRange, CoordinateError> {
    ByteRange::try_new(input.start, input.end)
}

const fn text_range(input: RangeInput) -> Result<TextRange, CoordinateError> {
    TextRange::try_new(input.start, input.end)
}

fn coordinate_pyerr(error: CoordinateError) -> PyErr {
    Python::attach(|py| errors::coordinate_error(py, error))
}

#[pyfunction]
pub fn validate_domain_model(kind: &str, value_json: &str) -> PyResult<String> {
    match kind {
        "event_limit_default" => converted_json(&EventLimit::default(), PolicyError::new_err),
        "maximum_elapsed_default" => {
            converted_json(&MaximumElapsed::default(), PolicyError::new_err)
        }
        "redirect_hop_limit_default" => {
            converted_json(&RedirectHopLimit::default(), PolicyError::new_err)
        }
        "direct_http_redirects_default" => {
            converted_json(&DirectHttpRedirects::default(), PolicyError::new_err)
        }
        "document_id" => {
            let value = serde_json::from_str::<String>(value_json).map_err(|error| {
                Python::attach(|py| {
                    errors::serde_decode_error(
                        py,
                        DocumentError::new_err(error.to_string()),
                        &error,
                    )
                })
            })?;
            let value = DocumentId::try_new(value)
                .map_err(|error| Python::attach(|py| errors::document_error(py, &error)))?;
            converted_json(&value, DocumentError::new_err)
        }
        "document_epoch" => {
            let value = serde_json::from_str::<u64>(value_json).map_err(|error| {
                Python::attach(|py| {
                    errors::serde_decode_error(
                        py,
                        DocumentError::new_err(error.to_string()),
                        &error,
                    )
                })
            })?;
            let value = DocumentEpoch::try_from(value)
                .map_err(|error| Python::attach(|py| errors::document_profile_error(py, error)))?;
            converted_json(&value, DocumentError::new_err)
        }
        "contract_id" => {
            let value = serde_json::from_str::<String>(value_json).map_err(|error| {
                Python::attach(|py| {
                    errors::serde_decode_error(
                        py,
                        ContractError::new_err(error.to_string()),
                        &error,
                    )
                })
            })?;
            let value = ContractId::try_new(value)
                .map_err(|error| Python::attach(|py| errors::contract_schema_error(py, &error)))?;
            converted_json(&value, ContractError::new_err)
        }
        "field_id" => {
            let value = serde_json::from_str::<String>(value_json).map_err(|error| {
                Python::attach(|py| {
                    errors::serde_decode_error(
                        py,
                        ContractError::new_err(error.to_string()),
                        &error,
                    )
                })
            })?;
            let value = FieldId::try_new(value)
                .map_err(|error| Python::attach(|py| errors::contract_schema_error(py, &error)))?;
            converted_json(&value, ContractError::new_err)
        }
        "output_id" => {
            let value = serde_json::from_str::<String>(value_json).map_err(|error| {
                Python::attach(|py| {
                    errors::serde_decode_error(py, LocatorError::new_err(error.to_string()), &error)
                })
            })?;
            let value = OutputId::try_new(value)
                .map_err(|error| Python::attach(|py| errors::plan_error(py, &error)))?;
            converted_json(&value, LocatorError::new_err)
        }
        "region_id" => {
            let value = serde_json::from_str::<String>(value_json).map_err(|error| {
                Python::attach(|py| {
                    errors::serde_decode_error(py, LocatorError::new_err(error.to_string()), &error)
                })
            })?;
            let value = RegionId::try_new(value)
                .map_err(|error| Python::attach(|py| errors::query_error(py, &error)))?;
            converted_json(&value, LocatorError::new_err)
        }
        "count_limit" => policy_scalar::<CountLimit, u64>(value_json),
        "step_limit" => policy_scalar::<StepLimit, u32>(value_json),
        "addressable_byte_limit" => policy_scalar::<AddressableByteLimit, u64>(value_json),
        "addressable_byte_limit_to_byte_limit" => {
            let limit = policy_value::<AddressableByteLimit, u64>(value_json)?;
            let converted = limit
                .to_byte_limit()
                .map_err(|error| PyValueError::new_err(error.to_string()))?;
            converted_json(&converted, PyValueError::new_err)
        }
        "event_limit" => policy_scalar::<EventLimit, u64>(value_json),
        "resource_limit" => policy_scalar::<ResourceLimit, u32>(value_json),
        "resource_limit_to_nonzero" => {
            let limit = policy_value::<ResourceLimit, u32>(value_json)?;
            let converted = limit
                .to_nonzero()
                .map_err(|error| Python::attach(|py| errors::policy_error(py, &error)))?;
            converted_json(&converted, PolicyError::new_err)
        }
        "accessibility_node_limit" => policy_scalar::<AccessibilityNodeLimit, u32>(value_json),
        "accessibility_node_limit_to_nonzero" => {
            let limit = policy_value::<AccessibilityNodeLimit, u32>(value_json)?;
            let converted = limit
                .to_nonzero()
                .map_err(|error| Python::attach(|py| errors::policy_error(py, &error)))?;
            converted_json(&converted, PolicyError::new_err)
        }
        "maximum_elapsed" => policy_scalar::<MaximumElapsed, u64>(value_json),
        "maximum_elapsed_to_capture_deadline" => {
            let maximum = policy_value::<MaximumElapsed, u64>(value_json)?;
            let converted = maximum
                .to_capture_deadline()
                .map_err(|error| PyValueError::new_err(error.to_string()))?;
            converted_json(&converted, PyValueError::new_err)
        }
        "maximum_elapsed_capture_duration" => {
            let maximum = policy_value::<MaximumElapsed, u64>(value_json)?;
            let converted = maximum
                .to_capture_deadline()
                .map_err(|error| PyValueError::new_err(error.to_string()))?
                .duration();
            converted_json(&converted, PyValueError::new_err)
        }
        "redirect_hop_limit" => policy_scalar::<RedirectHopLimit, u32>(value_json),
        "budget" => {
            let value = serde_json::from_str::<u32>(value_json).map_err(|error| {
                Python::attach(|py| {
                    errors::serde_decode_error(py, PolicyError::new_err(error.to_string()), &error)
                })
            })?;
            let value = Budget::new(value)
                .map_err(|error| Python::attach(|py| errors::policy_error(py, &error)))?;
            converted_json(&value, PolicyError::new_err)
        }
        "provider_defaults_version" => {
            let value = serde_json::from_str::<u16>(value_json).map_err(|error| {
                Python::attach(|py| {
                    errors::serde_decode_error(py, PolicyError::new_err(error.to_string()), &error)
                })
            })?;
            let value = ProviderDefaultsVersion::try_new(value)
                .map_err(|error| Python::attach(|py| errors::policy_error(py, &error)))?;
            converted_json(&value, PolicyError::new_err)
        }
        "dom_node_id" => {
            let value = serde_json::from_str::<u64>(value_json).map_err(|error| {
                Python::attach(|py| {
                    errors::serde_decode_error(py, LocatorError::new_err(error.to_string()), &error)
                })
            })?;
            let value = DomNodeId::try_new(value)
                .map_err(|error| Python::attach(|py| errors::coordinate_error(py, error)))?;
            converted_json(&value, LocatorError::new_err)
        }
        "byte_range" => {
            let input = decode_input::<RangeInput>(value_json, LocatorError::new_err)?;
            let value = byte_range(input).map_err(coordinate_pyerr)?;
            converted_json(&value, LocatorError::new_err)
        }
        "text_range" => {
            let input = decode_input::<RangeInput>(value_json, LocatorError::new_err)?;
            let value = text_range(input).map_err(coordinate_pyerr)?;
            converted_json(&value, LocatorError::new_err)
        }
        "expanded_name_path_segment" => {
            let input =
                decode_input::<ExpandedNamePathSegmentInput>(value_json, LocatorError::new_err)?;
            let value = ExpandedNamePathSegment::try_new(
                input.namespace_uri,
                input.local_name,
                input.same_name_sibling_index,
            )
            .map_err(coordinate_pyerr)?;
            converted_json(&value, LocatorError::new_err)
        }
        "tree_coordinate" => {
            let input = decode_input::<TreeCoordinateInput>(value_json, LocatorError::new_err)?;
            let source_bytes = input
                .source_bytes
                .map(byte_range)
                .transpose()
                .map_err(coordinate_pyerr)?;
            let value = match input.expanded_name_path {
                Some(segments) => {
                    let segments = segments
                        .into_iter()
                        .map(|segment| {
                            ExpandedNamePathSegment::try_new(
                                segment.namespace_uri,
                                segment.local_name,
                                segment.same_name_sibling_index,
                            )
                        })
                        .collect::<Result<Vec<_>, _>>()
                        .map_err(coordinate_pyerr)?;
                    TreeCoordinate::with_expanded_name_path(
                        input.child_path,
                        source_bytes,
                        segments,
                    )
                    .map_err(coordinate_pyerr)?
                }
                None => TreeCoordinate::try_new(input.child_path, source_bytes)
                    .map_err(coordinate_pyerr)?,
            };
            converted_json(&value, LocatorError::new_err)
        }
        "json_coordinate" => {
            let input = decode_input::<String>(value_json, LocatorError::new_err)?;
            let value = JsonCoordinate::try_new(input).map_err(coordinate_pyerr)?;
            converted_json(&value, LocatorError::new_err)
        }
        "dom_coordinate" => {
            let input = decode_input::<DomCoordinateInput>(value_json, LocatorError::new_err)?;
            let node_id = DomNodeId::try_new(input.node_id).map_err(coordinate_pyerr)?;
            let value = DomCoordinate::new(input.document_epoch, node_id);
            converted_json(&value, LocatorError::new_err)
        }
        "accessibility_coordinate" => {
            let input =
                decode_input::<AccessibilityCoordinateInput>(value_json, LocatorError::new_err)?;
            let value = AccessibilityCoordinate::try_new(input.document_epoch, input.node_id)
                .map_err(coordinate_pyerr)?;
            converted_json(&value, LocatorError::new_err)
        }
        "decoded_text_coordinate" => {
            let input =
                decode_input::<DecodedTextCoordinateInput>(value_json, LocatorError::new_err)?;
            let byte_range = byte_range(input.byte_range).map_err(coordinate_pyerr)?;
            let scalar_range = text_range(input.scalar_range).map_err(coordinate_pyerr)?;
            let value = DecodedTextCoordinate::new(byte_range, scalar_range);
            converted_json(&value, LocatorError::new_err)
        }
        "node_reference" => normalize::<NodeReference>(value_json, LocatorError::new_err),
        "region_lineage" => normalize::<RegionLineage>(value_json, LocatorError::new_err),
        "native_coordinate" => normalize::<NativeCoordinate>(value_json, LocatorError::new_err),
        "finding" => normalize::<Finding>(value_json, LocatorError::new_err),
        "locate_result" => normalize::<LocateResult>(value_json, LocatorError::new_err),
        "locate_result_explicit" => {
            construct_locate_result_with_regions(value_json, LocatorError::new_err)
        }
        "web_target" => {
            let value = serde_json::from_str::<String>(value_json)
                .map_err(|error| RequestError::new_err(error.to_string()))?;
            let target = WebTarget::new(value);
            serde_json::to_string(target.as_str())
                .map_err(|error| RequestError::new_err(error.to_string()))
        }
        _ => Err(PyValueError::new_err("unknown public SDK domain model")),
    }
}
