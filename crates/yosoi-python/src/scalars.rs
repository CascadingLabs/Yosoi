//! Rust-owned constructors and validation for public SDK scalar values.

use pyo3::{exceptions::PyValueError, prelude::*};
use serde::{Serialize, de::DeserializeOwned};
use yosoi::{
    contracts::{ContractId, FieldId},
    documents::{DocumentEpoch, DocumentId},
    locators::{
        AccessibilityCoordinate, ByteRange, DecodedTextCoordinate, DomCoordinate, DomNodeId,
        ExpandedNamePathSegment, Finding, JsonCoordinate, LocateResult, NativeCoordinate,
        NodeReference, OutputId, RegionId, RegionLineage, TextRange, TreeCoordinate,
    },
    policy::{
        AccessibilityNodeLimit, AddressableByteLimit, Budget, CountLimit, EventLimit,
        MaximumElapsed, ProviderDefaultsVersion, RedirectHopLimit, ResourceLimit, StepLimit,
    },
};

use crate::errors::{ContractError, DocumentError, LocatorError, PolicyError};

fn normalize<T>(value_json: &str, invalid: impl Fn(String) -> PyErr) -> PyResult<String>
where
    T: DeserializeOwned + Serialize,
{
    let value = serde_json::from_str::<T>(value_json)
        .map_err(|error| invalid(error.to_string()))?;
    serde_json::to_string(&value).map_err(|error| invalid(error.to_string()))
}

fn construct_locate_result_with_regions(
    value_json: &str,
    invalid: impl Fn(String) -> PyErr,
) -> PyResult<String> {
    #[derive(serde::Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Input {
        document_id: yosoi::documents::DocumentId,
        regions: Vec<yosoi::locators::RegionLineage>,
        findings: Vec<yosoi::locators::Finding>,
    }

    let input = serde_json::from_str::<Input>(value_json)
        .map_err(|error| invalid(error.to_string()))?;
    let result = yosoi::locators::LocateResult::try_new_with_regions(
        input.document_id,
        input.regions,
        input.findings,
    )
    .map_err(|error| invalid(error.to_string()))?;
    serde_json::to_string(&result).map_err(|error| invalid(error.to_string()))
}

#[pyfunction]
pub fn validate_domain_model(kind: &str, value_json: &str) -> PyResult<String> {
    match kind {
        "document_id" => normalize::<DocumentId>(value_json, |error| {
            DocumentError::new_err(error)
        }),
        "document_epoch" => normalize::<DocumentEpoch>(value_json, |error| {
            DocumentError::new_err(error)
        }),
        "contract_id" => normalize::<ContractId>(value_json, |error| {
            ContractError::new_err(error)
        }),
        "field_id" => normalize::<FieldId>(value_json, |error| ContractError::new_err(error)),
        "output_id" => normalize::<OutputId>(value_json, |error| LocatorError::new_err(error)),
        "region_id" => normalize::<RegionId>(value_json, |error| LocatorError::new_err(error)),
        "count_limit" => normalize::<CountLimit>(value_json, |error| PolicyError::new_err(error)),
        "step_limit" => normalize::<StepLimit>(value_json, |error| PolicyError::new_err(error)),
        "addressable_byte_limit" => {
            normalize::<AddressableByteLimit>(value_json, |error| PolicyError::new_err(error))
        }
        "event_limit" => normalize::<EventLimit>(value_json, |error| PolicyError::new_err(error)),
        "resource_limit" => {
            normalize::<ResourceLimit>(value_json, |error| PolicyError::new_err(error))
        }
        "accessibility_node_limit" => {
            normalize::<AccessibilityNodeLimit>(value_json, |error| PolicyError::new_err(error))
        }
        "maximum_elapsed" => {
            normalize::<MaximumElapsed>(value_json, |error| PolicyError::new_err(error))
        }
        "redirect_hop_limit" => {
            normalize::<RedirectHopLimit>(value_json, |error| PolicyError::new_err(error))
        }
        "budget" => normalize::<Budget>(value_json, |error| PolicyError::new_err(error)),
        "provider_defaults_version" => normalize::<ProviderDefaultsVersion>(value_json, |error| {
            PolicyError::new_err(error)
        }),
        "dom_node_id" => {
            normalize::<DomNodeId>(value_json, |error| LocatorError::new_err(error))
        }
        "byte_range" => normalize::<ByteRange>(value_json, |error| LocatorError::new_err(error)),
        "text_range" => normalize::<TextRange>(value_json, |error| LocatorError::new_err(error)),
        "expanded_name_path_segment" => normalize::<ExpandedNamePathSegment>(value_json, |error| {
            LocatorError::new_err(error)
        }),
        "tree_coordinate" => {
            normalize::<TreeCoordinate>(value_json, |error| LocatorError::new_err(error))
        }
        "json_coordinate" => {
            normalize::<JsonCoordinate>(value_json, |error| LocatorError::new_err(error))
        }
        "dom_coordinate" => {
            normalize::<DomCoordinate>(value_json, |error| LocatorError::new_err(error))
        }
        "accessibility_coordinate" => {
            normalize::<AccessibilityCoordinate>(value_json, |error| LocatorError::new_err(error))
        }
        "decoded_text_coordinate" => {
            normalize::<DecodedTextCoordinate>(value_json, |error| LocatorError::new_err(error))
        }
        "node_reference" => {
            normalize::<NodeReference>(value_json, |error| LocatorError::new_err(error))
        }
        "region_lineage" => {
            normalize::<RegionLineage>(value_json, |error| LocatorError::new_err(error))
        }
        "native_coordinate" => {
            normalize::<NativeCoordinate>(value_json, |error| LocatorError::new_err(error))
        }
        "finding" => normalize::<Finding>(value_json, |error| LocatorError::new_err(error)),
        "locate_result" => {
            normalize::<LocateResult>(value_json, |error| LocatorError::new_err(error))
        }
        "locate_result_explicit" => construct_locate_result_with_regions(value_json, |error| {
            LocatorError::new_err(error)
        }),
        _ => Err(PyValueError::new_err("unknown public SDK domain model")),
    }
}
