//! Rust-backed helpers for public Policy component constructors and accessors.

use std::num::{NonZeroU16, NonZeroU32, NonZeroUsize};

use pyo3::prelude::*;
use serde::{Deserialize, Serialize, de::DeserializeOwned};
use yosoi::policy::{
    Acquisition, AddressableByteLimit, DocumentRequest, Filters, Map, MaximumElapsed, Page,
    PolicyError as SdkPolicyError, ProviderDefaultsVersion, Tuning,
    search::{EffectiveProviderRoute, Provider, ProviderRequestProfile, ProviderSelection, Search},
};

use crate::errors::{self, PolicyError};

fn decode<T: DeserializeOwned>(py: Python<'_>, value: &str) -> PyResult<T> {
    serde_json::from_str(value).map_err(|error| {
        errors::serde_decode_error(py, PolicyError::new_err(error.to_string()), &error)
    })
}

fn decode_args<T: DeserializeOwned>(py: Python<'_>, value: Option<&str>) -> PyResult<T> {
    let value = value.ok_or_else(|| PolicyError::new_err("missing Policy component arguments"))?;
    decode(py, value)
}

fn encode<T: Serialize>(py: Python<'_>, value: &T) -> PyResult<String> {
    serde_json::to_string(value).map_err(|error| {
        errors::serde_encode_error(py, PolicyError::new_err(error.to_string()), &error)
    })
}

fn sdk_error(py: Python<'_>, error: &SdkPolicyError) -> PyErr {
    errors::policy_error(py, error)
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ResultLimits {
    per_provider: NonZeroU16,
    total: NonZeroU32,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ProviderArgs {
    provider: Provider,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ExactProviderArgs {
    provider: Provider,
    profile: ProviderRequestProfile,
}

/// Calls public Rust Policy component methods and returns their Serde value.
#[pyfunction]
#[pyo3(signature = (kind, component_json, operation, args_json=None))]
pub fn policy_component(
    py: Python<'_>,
    kind: &str,
    component_json: Option<&str>,
    operation: &str,
    args_json: Option<&str>,
) -> PyResult<String> {
    match (kind, operation) {
        ("search", "disabled") => encode(py, &Search::disabled()),
        ("search", "is_enabled") => {
            let search = decode::<Search>(py, required(component_json)?)?;
            encode(py, &search.is_enabled())
        }
        ("search", "with_max_in_flight") => {
            let search = decode::<Search>(py, required(component_json)?)?;
            let value = decode_args::<NonZeroUsize>(py, args_json)?;
            encode(
                py,
                &search
                    .with_max_in_flight(value)
                    .map_err(|error| sdk_error(py, &error))?,
            )
        }
        ("search", "with_max_browser_in_flight") => {
            let search = decode::<Search>(py, required(component_json)?)?;
            let value = decode_args::<NonZeroUsize>(py, args_json)?;
            encode(
                py,
                &search
                    .with_max_browser_in_flight(value)
                    .map_err(|error| sdk_error(py, &error))?,
            )
        }
        ("search", "per_provider_limit") => {
            let search = decode::<Search>(py, required(component_json)?)?;
            let value = decode_args::<u16>(py, args_json)?;
            encode(
                py,
                &search
                    .per_provider_limit(value)
                    .map_err(|error| sdk_error(py, &error))?,
            )
        }
        ("search", "with_result_limits") => {
            let search = decode::<Search>(py, required(component_json)?)?;
            let values = decode_args::<ResultLimits>(py, args_json)?;
            encode(
                py,
                &search
                    .with_result_limits(values.per_provider, values.total)
                    .map_err(|error| sdk_error(py, &error))?,
            )
        }
        ("search", "with_max_total_results") => {
            let search = decode::<Search>(py, required(component_json)?)?;
            let value = decode_args::<NonZeroU32>(py, args_json)?;
            encode(
                py,
                &search
                    .with_max_total_results(value)
                    .map_err(|error| sdk_error(py, &error))?,
            )
        }
        ("search", "with_max_retained_content_bytes") => {
            let search = decode::<Search>(py, required(component_json)?)?;
            let value = decode_args::<AddressableByteLimit>(py, args_json)?;
            encode(
                py,
                &search
                    .with_max_retained_content_bytes(value)
                    .map_err(|error| sdk_error(py, &error))?,
            )
        }
        ("search", "with_maximum_elapsed") => {
            let search = decode::<Search>(py, required(component_json)?)?;
            let value = decode_args::<MaximumElapsed>(py, args_json)?;
            encode(
                py,
                &search
                    .with_maximum_elapsed(value)
                    .map_err(|error| sdk_error(py, &error))?,
            )
        }
        ("acquisition", "with_documents") => {
            let acquisition = decode::<Acquisition>(py, required(component_json)?)?;
            let documents = decode_args::<Vec<DocumentRequest>>(py, args_json)?;
            let updated = acquisition.documents(documents);
            Page::new(vec![updated.clone()]).map_err(|error| sdk_error(py, &error))?;
            encode(py, &updated)
        }
        ("acquisition", "exact_documents") => {
            let acquisition = decode::<Acquisition>(py, required(component_json)?)?;
            encode(py, &acquisition.exact_documents())
        }
        ("acquisition", "selection_kind") => {
            let acquisition = decode::<Acquisition>(py, required(component_json)?)?;
            encode(py, &acquisition.selection_kind())
        }
        ("provider_selection", "current") => {
            let values = decode_args::<ProviderArgs>(py, args_json)?;
            encode(py, &ProviderSelection::current(values.provider))
        }
        ("provider_selection", "exact") => {
            let values = decode_args::<ExactProviderArgs>(py, args_json)?;
            let profile = ProviderRequestProfile::new(
                values.profile.page,
                values.profile.request,
                values.profile.documents,
            )
            .map_err(|error| sdk_error(py, &error))?;
            encode(py, &ProviderSelection::exact(values.provider, profile))
        }
        ("provider", "defaults_status") => {
            let provider = decode::<Provider>(py, required(component_json)?)?;
            encode(py, &provider.defaults_status())
        }
        ("effective_provider_route", "page") => {
            let route = decode::<EffectiveProviderRoute>(py, required(component_json)?)?;
            encode(py, &route.page())
        }
        ("effective_provider_route", "request") => {
            let route = decode::<EffectiveProviderRoute>(py, required(component_json)?)?;
            encode(py, &route.request())
        }
        ("effective_provider_route", "documents") => {
            let route = decode::<EffectiveProviderRoute>(py, required(component_json)?)?;
            encode(py, &route.documents())
        }
        ("effective_provider_route", "defaults_version") => {
            let route = decode::<EffectiveProviderRoute>(py, required(component_json)?)?;
            let version: Option<ProviderDefaultsVersion> = route.defaults_version();
            encode(py, &version)
        }
        ("filters", "validate") => {
            let filters = decode::<Filters>(py, required(component_json)?)?;
            filters.validate().map_err(|error| sdk_error(py, &error))?;
            encode(py, &filters)
        }
        ("map", "validate") => {
            let map = decode::<Map>(py, required(component_json)?)?;
            map.validate().map_err(|error| sdk_error(py, &error))?;
            encode(py, &map)
        }
        ("tuning", "is_default") => {
            let tuning = decode::<Tuning>(py, required(component_json)?)?;
            encode(py, &tuning.is_default())
        }
        _ => Err(PolicyError::new_err(format!(
            "unsupported Policy component operation: {kind}.{operation}"
        ))),
    }
}

fn required(value: Option<&str>) -> PyResult<&str> {
    value.ok_or_else(|| PolicyError::new_err("missing Policy component JSON"))
}
